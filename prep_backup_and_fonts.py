import argparse
import os
import shutil
import struct
import zlib
from pathlib import Path

from common import (
    OVERRIDES_DIR,
    UNPACKED_DIR,
    add_game_dir_arg,
    read_pack_key,
    resolve_game_dir,
    xor_at,
)


def check_cyrillic_cmap(ttf_path: Path) -> tuple[int, bool]:
    b = ttf_path.read_bytes()
    num_tables = struct.unpack_from(">H", b, 4)[0]
    cmap_off = None
    for i in range(num_tables):
        t = 12 + i * 16
        if b[t:t + 4] == b"cmap":
            cmap_off = struct.unpack_from(">I", b, t + 8)[0]
            break
    assert cmap_off is not None, f"Missing cmap table in {ttf_path}"
    nsub = struct.unpack_from(">H", b, cmap_off + 2)[0]
    cov: set[int] = set()
    for i in range(nsub):
        rec = cmap_off + 4 + i * 8
        _, _, sub_off = struct.unpack_from(">HHI", b, rec)
        off = cmap_off + sub_off
        fmt = struct.unpack_from(">H", b, off)[0]
        if fmt == 4:
            seg_count = struct.unpack_from(">H", b, off + 6)[0] // 2
            ends = struct.unpack_from(f">{seg_count}H", b, off + 14)
            starts = struct.unpack_from(f">{seg_count}H", b, off + 16 + 2 * seg_count)
            for s, e in zip(starts, ends):
                if s <= 0x04FF and e >= 0x0400:
                    cov.update(range(max(s, 0x0400), min(e, 0x04FF) + 1))
        elif fmt == 12:
            ngrp = struct.unpack_from(">I", b, off + 12)[0]
            for g in range(ngrp):
                s, e, _ = struct.unpack_from(">III", b, off + 16 + g * 12)
                if s <= 0x04FF and e >= 0x0400:
                    cov.update(range(max(s, 0x0400), min(e, 0x04FF) + 1))
    req = set(range(0x0410, 0x0450)) | {0x0401, 0x0451}
    return len(cov), not (req - cov)


def unpack_tomls_and_fonts(exe_path: Path, pack_path: Path) -> None:
    key32 = read_pack_key(exe_path.read_bytes())
    data = pack_path.read_bytes()
    assert data[:4] == b"DIGP"
    _, idx_off, idx_sz = struct.unpack_from("<IQQ", xor_at(data[4:24], 4, key32), 0)
    idx = xor_at(data[idx_off:idx_off + idx_sz], idx_off, key32)
    count = struct.unpack_from("<I", idx, 0)[0]
    pos = 4
    UNPACKED_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(count):
        nlen = struct.unpack_from("<H", idx, pos)[0]
        pos += 2
        name = idx[pos:pos + nlen].decode("utf-8")
        pos += nlen
        flags, off, usize, csize = struct.unpack_from("<BQQQ", idx, pos)
        pos += 25
        if not name.startswith("brushes/") and name.endswith((".toml", ".ttf")):
            plain = xor_at(data[off:off + csize], off, key32)
            dec = zlib.decompress(plain, -15) if flags == 1 else plain
            assert len(dec) == usize, f"Size mismatch for {name}"
            dst = UNPACKED_DIR / Path(name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(dec)


def main() -> None:
    parser = add_game_dir_arg(argparse.ArgumentParser())
    args = parser.parse_args()
    game_dir = resolve_game_dir(args.game_dir)

    backup_dir = game_dir / "backup_en"
    backup_dir.mkdir(exist_ok=True)
    for fname in ("dirttown.exe", "data.pack"):
        src = game_dir / fname
        dst = backup_dir / fname
        if not dst.exists():
            shutil.copy2(src, dst)
            print(f"Backed up {fname} -> {dst} ({dst.stat().st_size} bytes)")
        else:
            print(f"Backup already exists: {dst} ({dst.stat().st_size} bytes)")

    unpack_tomls_and_fonts(backup_dir / "dirttown.exe", backup_dir / "data.pack")

    unpacked_fonts = UNPACKED_DIR / "fonts"
    overrides_fonts = OVERRIDES_DIR / "fonts"
    overrides_fonts.mkdir(parents=True, exist_ok=True)

    win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    shutil.copy2(unpacked_fonts / "Roboto-Regular.ttf", overrides_fonts / "Roboto-Medium.ttf")
    shutil.copy2(unpacked_fonts / "Roboto-Bold.ttf", overrides_fonts / "Roboto-Black.ttf")
    shutil.copy2(win_fonts / "cour.ttf", overrides_fonts / "CourierPrime-Regular.ttf")
    shutil.copy2(win_fonts / "courbd.ttf", overrides_fonts / "CourierPrime-Bold.ttf")

    for p in [
        unpacked_fonts / "Roboto-Regular.ttf",
        unpacked_fonts / "Roboto-Bold.ttf",
        overrides_fonts / "Roboto-Medium.ttf",
        overrides_fonts / "Roboto-Black.ttf",
        overrides_fonts / "CourierPrime-Regular.ttf",
        overrides_fonts / "CourierPrime-Bold.ttf",
    ]:
        cnt, ok = check_cyrillic_cmap(p)
        assert ok, f"{p.name} missing Russian Cyrillic glyphs!"
        print(f"  {p.name}: cyrillic_cps={cnt}, full_ru={ok}, size={p.stat().st_size}")


if __name__ == "__main__":
    main()
