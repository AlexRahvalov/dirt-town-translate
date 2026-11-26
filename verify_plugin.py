"""Verify generated runtime plugin blobs (exe_patch.dtloc & pack_patches.dtpk) against original game files."""

import argparse
import struct
import tomllib
import zlib

from common import ROOT_DIR, add_game_dir_arg, parse_pe_sections, read_pack_key, resolve_game_dir, va_to_raw, xor_at


def main() -> None:
    p = add_game_dir_arg(argparse.ArgumentParser())
    p.add_argument("--locale", default="ru")
    args = p.parse_args()

    game_dir = resolve_game_dir(args.game_dir)
    orig_exe = (game_dir / "backup_en" / "dirttown.exe")
    if not orig_exe.exists():
        orig_exe = game_dir / "dirttown.exe"
    orig_pack = (game_dir / "backup_en" / "data.pack")
    if not orig_pack.exists():
        orig_pack = game_dir / "data.pack"

    exe_bytes = orig_exe.read_bytes()
    _, _, _, _, _, _, _, _, sections = parse_pe_sections(exe_bytes)
    IMAGE_BASE = 0x140000000

    loc_dir = ROOT_DIR / "locales" / args.locale
    dtlp = (loc_dir / "exe_patch.dtloc").read_bytes()
    magic, ver, loc_sz, n_rip, n_ptr, n_loc_ptr, n_raw, hook_call, hook_orig, op_new, op_del = struct.unpack_from(
        "<4s10I", dtlp, 0
    )
    assert magic == b"DTLP" and ver == 1
    pos = 44
    loc_blob = bytearray(dtlp[pos : pos + loc_sz])
    pos += loc_sz

    # Simulate ASLR base + virtual loc_mem placed cleanly after SizeOfImage
    ASLR_BASE = 0x7FF612340000
    LOC_MEM = ASLR_BASE + 0x1E60000

    rip_recs = [struct.unpack_from("<IIiI", dtlp, pos + i * 16) for i in range(n_rip)]
    pos += n_rip * 16
    ptr_recs = [struct.unpack_from("<III", dtlp, pos + i * 12) for i in range(n_ptr)]
    pos += n_ptr * 12
    loc_ptr_recs = [struct.unpack_from("<II", dtlp, pos + i * 8) for i in range(n_loc_ptr)]
    pos += n_loc_ptr * 8

    raw_recs = []
    for _ in range(n_raw):
        rva, sz = struct.unpack_from("<IH", dtlp, pos)
        pos += 6
        exp_b = dtlp[pos : pos + sz]
        pos += sz
        new_b = dtlp[pos : pos + sz]
        pos += sz
        raw_recs.append((rva, exp_b, new_b))
    assert pos == len(dtlp), f"Trailing bytes in exe_patch.dtloc: {len(dtlp) - pos}"

    # Verify loc_ptrs
    for dst_off, tgt_off in loc_ptr_recs:
        assert dst_off + 8 <= loc_sz and tgt_off < loc_sz
        struct.pack_into("<Q", loc_blob, dst_off, LOC_MEM + tgt_off)

    NON_CSTR_RIPS = {
        0xCB85D7,  # gfx_table_va pointer array
        0xC5366B, 0xC5367F, 0xC53F5B, 0xC53F6A,  # clear_pad XMM chunks
        0x95155E, 0x951748, 0x951754,            # seat YMM chunks (scan range)
        0x9515FC, 0x951608, 0x95179F, 0x9517AE,  # flat YMM chunks
        0x95169D, 0x9516A9, 0x95180E, 0x95181D,  # dealer YMM/XMM chunks
        0x275095, 0x2750A1,                      # item XMM chunks
    }
    # Verify rip32 records against original exe + ASLR range
    for rva, insn_sz, exp_disp, tgt_off in rip_recs:
        raw = va_to_raw(sections, IMAGE_BASE + rva)
        assert raw is not None
        cur_disp = struct.unpack_from("<i", exe_bytes, raw + insn_sz - 4)[0]
        assert cur_disp == exp_disp, f"RIP32 mismatch at RVA 0x{rva:x}"
        new_disp = (LOC_MEM + tgt_off) - (ASLR_BASE + rva + insn_sz)
        assert -0x80000000 <= new_disp <= 0x7FFFFFFF
        if rva not in NON_CSTR_RIPS and not (0x95172C <= rva <= 0x951785):
            s_end = loc_blob.find(b"\x00", tgt_off)
            assert s_end != -1
            loc_blob[tgt_off:s_end].decode("utf-8")

    # Verify ptr64 records
    for pva, exp_tgt, tgt_off in ptr_recs:
        raw = va_to_raw(sections, IMAGE_BASE + pva)
        assert raw is not None
        cur_val = struct.unpack_from("<Q", exe_bytes, raw)[0]
        assert cur_val == IMAGE_BASE + exp_tgt, f"PTR64 mismatch at RVA 0x{pva:x}"
        s_end = loc_blob.find(b"\x00", tgt_off)
        assert s_end != -1
        loc_blob[tgt_off:s_end].decode("utf-8")

    # Verify raw records
    for rva, exp_b, new_b in raw_recs:
        raw = va_to_raw(sections, IMAGE_BASE + rva)
        assert raw is not None and exe_bytes[raw : raw + len(exp_b)] == exp_b

    # Verify pack hook call site
    r_hc = va_to_raw(sections, IMAGE_BASE + hook_call)
    assert exe_bytes[r_hc] == 0xE8
    disp = struct.unpack_from("<i", exe_bytes, r_hc + 1)[0]
    assert hook_call + 5 + disp == hook_orig

    # Verify pack_patches.dtpk against original data.pack
    dtpk = (loc_dir / "pack_patches.dtpk").read_bytes()
    pmagic, pver, n_fonts, n_rules = struct.unpack_from("<4sIII", dtpk, 0)
    assert pmagic == b"DTPK" and pver == 1
    ppos = 16
    fonts = []
    for _ in range(n_fonts):
        kl = struct.unpack_from("<H", dtpk, ppos)[0]
        ppos += 2
        k = dtpk[ppos : ppos + kl].decode("utf-8")
        ppos += kl
        kind, vl = struct.unpack_from("<BH", dtpk, ppos)
        ppos += 3
        v = dtpk[ppos : ppos + vl].decode("utf-8")
        ppos += vl
        fonts.append((k, kind, v))

    rules_by_file: dict[str, list[tuple[str, str]]] = {}
    for _ in range(n_rules):
        fkl = struct.unpack_from("<H", dtpk, ppos)[0]
        ppos += 2
        fk = dtpk[ppos : ppos + fkl].decode("utf-8")
        ppos += fkl
        ol = struct.unpack_from("<I", dtpk, ppos)[0]
        ppos += 4
        old_s = dtpk[ppos : ppos + ol].decode("utf-8")
        ppos += ol
        nl = struct.unpack_from("<I", dtpk, ppos)[0]
        ppos += 4
        new_s = dtpk[ppos : ppos + nl].decode("utf-8")
        ppos += nl
        rules_by_file.setdefault(fk, []).append((old_s, new_s))
    assert ppos == len(dtpk)

    key32 = read_pack_key(exe_bytes)
    pbytes = orig_pack.read_bytes()
    _, ioff, isz = struct.unpack("<IQQ", xor_at(pbytes[4:24], 4, key32))
    idx = xor_at(pbytes[ioff : ioff + isz], ioff, key32)
    cnt = struct.unpack_from("<I", idx, 0)[0]
    ipos = 4
    pack_map = {}
    for _ in range(cnt):
        nl = struct.unpack_from("<H", idx, ipos)[0]
        ipos += 2
        nm = idx[ipos : ipos + nl].decode("utf-8")
        ipos += nl
        fl, off, us, cs = struct.unpack_from("<BQQQ", idx, ipos)
        ipos += 25
        if nm in rules_by_file or any(v == nm for _, k, v in fonts if k == 0):
            pl = xor_at(pbytes[off : off + cs], off, key32)
            pack_map[nm] = zlib.decompress(pl, -15) if fl == 1 else pl

    for fk, rlist in rules_by_file.items():
        text = pack_map[fk].decode("utf-8")
        for old_s, new_s in rlist:
            assert old_s in text, f"{fk}: missing {old_s!r}"
            text = text.replace(old_s, new_s)
        doc = tomllib.loads(text)
        if fk == "sites/demo2/demo2.toml":
            assert isinstance(doc.get("name"), str) and doc["name"]
            assert "811034dce06dee68" in doc["site"]["accepts"]

    print(
        f"Plugin offline verification PASSED: {n_rip} rip32, {n_ptr} ptr64, "
        f"{n_loc_ptr} loc_ptrs, {n_raw} raw patches, {len(rules_by_file)} TOMLs, {len(fonts)} font redirects!"
    )


if __name__ == "__main__":
    main()
