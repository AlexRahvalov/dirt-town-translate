import argparse
import hashlib
import struct
import tomllib
import zlib

from common import (
    OVERRIDES_DIR,
    add_game_dir_arg,
    read_pack_key,
    resolve_game_dir,
    xor_at,
)


def main() -> None:
    parser = add_game_dir_arg(argparse.ArgumentParser())
    args = parser.parse_args()
    game_dir = resolve_game_dir(args.game_dir)

    backup_exe = game_dir / "backup_en" / "dirttown.exe"
    backup_pack = game_dir / "backup_en" / "data.pack"
    target_pack = game_dir / "data.pack"
    key32 = read_pack_key(backup_exe.read_bytes())

    orig = backup_pack.read_bytes()
    assert orig[:4] == b"DIGP"
    ver, idx_off, idx_sz = struct.unpack("<IQQ", xor_at(orig[4:24], 4, key32))
    assert ver == 1

    idx_raw = xor_at(orig[idx_off:idx_off + idx_sz], idx_off, key32)
    count = struct.unpack_from("<I", idx_raw, 0)[0]
    pos = 4
    entries = []
    for _ in range(count):
        nlen = struct.unpack_from("<H", idx_raw, pos)[0]
        pos += 2
        name = idx_raw[pos:pos + nlen].decode("utf-8")
        pos += nlen
        flags, off, usize, csize = struct.unpack_from("<BQQQ", idx_raw, pos)
        pos += 25
        entries.append((name, flags, off, usize, csize))
    assert pos == idx_sz, f"{pos} != {idx_sz}"

    overrides = {}
    for p in OVERRIDES_DIR.rglob("*"):
        if p.is_file():
            overrides[p.relative_to(OVERRIDES_DIR).as_posix()] = p.read_bytes()
    print(f"Repacking {count} entries with {len(overrides)} overrides...")

    out = bytearray(32)
    new_entries = []
    orig_hashes = {}
    for name, flags, off, usize, csize in entries:
        while len(out) % 32 != 0:
            out.append(0)
        cur_off = len(out)

        orig_payload_plain = xor_at(orig[off:off + csize], off, key32)
        if name in overrides:
            raw_bytes = overrides[name]
            if flags == 1:
                co = zlib.compressobj(9, zlib.DEFLATED, -15)
                payload_plain = co.compress(raw_bytes) + co.flush()
                new_flags = 1
            else:
                payload_plain = raw_bytes
                new_flags = 0
            new_usize = len(raw_bytes)
            new_csize = len(payload_plain)
            print(f"  [OVERRIDE] {name}: usize {usize}->{new_usize}, csize {csize}->{new_csize}")
        else:
            new_flags, new_usize, new_csize = flags, usize, csize
            payload_plain = orig_payload_plain
            orig_hashes[name] = hashlib.sha256(orig_payload_plain).hexdigest()

        out.extend(xor_at(payload_plain, cur_off, key32))
        new_entries.append((name, new_flags, cur_off, new_usize, new_csize))

    while len(out) % 32 != 0:
        out.append(0)
    new_idx_off = len(out)

    idx_buf = bytearray(struct.pack("<I", len(new_entries)))
    for name, flags, off, usize, csize in new_entries:
        nb = name.encode("utf-8")
        idx_buf.extend(struct.pack("<H", len(nb)))
        idx_buf.extend(nb)
        idx_buf.extend(struct.pack("<BQQQ", flags, off, usize, csize))
    new_idx_sz = len(idx_buf)

    out.extend(xor_at(bytes(idx_buf), new_idx_off, key32))
    out[0:4] = b"DIGP"
    out[4:24] = xor_at(struct.pack("<IQQ", 1, new_idx_off, new_idx_sz), 4, key32)

    target_pack.write_bytes(bytes(out))
    print(f"Wrote {target_pack} ({len(out)} bytes)")

    chk = target_pack.read_bytes()
    c_ver, c_ioff, c_isz = struct.unpack("<IQQ", xor_at(chk[4:24], 4, key32))
    assert (c_ver, c_ioff, c_isz) == (1, new_idx_off, new_idx_sz)
    c_idx = xor_at(chk[c_ioff:c_ioff + c_isz], c_ioff, key32)
    c_cnt = struct.unpack_from("<I", c_idx, 0)[0]
    assert c_cnt == count
    p = 4
    for _ in range(c_cnt):
        nl = struct.unpack_from("<H", c_idx, p)[0]
        p += 2
        nm = c_idx[p:p + nl].decode("utf-8")
        p += nl
        fl, o, us, cs = struct.unpack_from("<BQQQ", c_idx, p)
        p += 25
        plain = xor_at(chk[o:o + cs], o, key32)
        raw_u = zlib.decompress(plain, -15) if fl == 1 else plain
        assert len(raw_u) == us
        if nm in overrides:
            assert raw_u == overrides[nm], f"Mismatch in override {nm}"
            if nm.endswith(".toml"):
                tomllib.loads(raw_u.decode("utf-8"))
        else:
            assert hashlib.sha256(plain).hexdigest() == orig_hashes[nm], f"Hash mismatch {nm}"
    assert p == c_isz
    print(f"Roundtrip verification PASSED for all {c_cnt} entries!")


if __name__ == "__main__":
    main()
