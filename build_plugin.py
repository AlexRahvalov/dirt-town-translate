"""Build runtime language plugin data (locales/<locale>/exe_patch.dtloc and pack_patches.dtpk) from translations/<locale>.json."""

import argparse
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

from common import (
    CATALOG_PATH,
    IMAGE_BASE,
    ROOT_DIR,
    add_game_dir_arg,
    parse_pe_sections,
    resolve_game_dir,
    va_to_raw as _va_to_raw,
)
from loc_strings import (
    EXTRA_UI_PTR_TABLES,
    MACHINE_DISPLAY_ROWS,
    STRING_PATCHES,
)
from validate_translations import validate_doc


def build_plugin_data(game_dir: Path, locale: str = "ru") -> None:
    trans_dir = ROOT_DIR / "translations"
    template_path = trans_dir / "template.json"
    locale_path = trans_dir / f"{locale}.json"
    if not locale_path.exists():
        raise FileNotFoundError(f"Translation file not found: {locale_path}")

    template = json.loads(template_path.read_text("utf-8"))
    doc = json.loads(locale_path.read_text("utf-8"))
    errs = validate_doc(doc, template, locale_path.name)
    if errs:
        raise ValueError("Translation validation failed:\n  " + "\n  ".join(errs))

    backup_exe = game_dir / "backup_en" / "dirttown.exe"
    if not backup_exe.exists():
        backup_exe = game_dir / "dirttown.exe"
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"{CATALOG_PATH} not found. Run build_loc_catalog.py first.")

    orig = backup_exe.read_bytes()
    _, _, _, _, _, _, _, _, sections = parse_pe_sections(orig)
    catalog = json.loads(CATALOG_PATH.read_text("utf-8"))

    def va_to_raw(va: int) -> int:
        raw = _va_to_raw(sections, va)
        assert raw is not None, f"Invalid VA 0x{va:x}"
        return raw

    def read_cstr(va: int) -> str:
        raw = va_to_raw(va)
        end = orig.find(b"\x00", raw, raw + 1024)
        assert end != -1, f"Unterminated string at 0x{va:x}"
        return orig[raw:end].decode("utf-8")

    loc_buf = bytearray()
    str_cache: dict[bytes, int] = {}

    def add_str(s: str) -> int:
        b = s.encode("utf-8") + b"\x00"
        if b in str_cache:
            return str_cache[b]
        off = len(loc_buf)
        loc_buf.extend(b)
        str_cache[b] = off
        return off

    def add_bytes(b: bytes, align: int = 16) -> int:
        while len(loc_buf) % align != 0:
            loc_buf.append(0)
        off = len(loc_buf)
        loc_buf.extend(b)
        return off

    # SIMD/literal blocks inside loc_buf (NUL-padded if shorter than engine constant)
    simd = doc["simd_strings"]
    clear_pad_txt = simd["clear_pad_26b"]["text"]
    clear_pad_b = clear_pad_txt.encode("utf-8").ljust(26, b"\x00")
    clear_pad_str_off = add_str(clear_pad_txt)
    clear_pad_xmm0_off = add_bytes(clear_pad_b[:16], align=16)
    clear_pad_xmm1_off = add_bytes(clear_pad_b[10:26], align=16)

    seat_b = simd["seat_37b"]["text"].encode("utf-8").ljust(37, b"\x00")
    seat_ymm_off = add_bytes(seat_b[:32], align=32)
    seat_tail_bytes = seat_b[29:37]

    flat_b = simd["flat_51b"]["text"].encode("utf-8").ljust(51, b"\x00")
    flat_ymm0_off = add_bytes(flat_b[:32], align=32)
    flat_ymm1_off = add_bytes(flat_b[19:51], align=32)

    dealer_b = simd["dealer_46b"]["text"].encode("utf-8").ljust(46, b"\x00")
    dealer_ymm0_off = add_bytes(dealer_b[:32], align=32)
    dealer_xmm1_off = add_bytes(dealer_b[30:46], align=16)

    item_b = simd["item_31b"]["text"].encode("utf-8").ljust(31, b"\x00")
    item_xmm0_off = add_bytes(item_b[:16], align=16)
    item_xmm1_off = add_bytes(item_b[15:31], align=16)

    gfx_ptr_offs = [add_str(s) for s in doc["graphics_presets"]]
    gfx_table_off = add_bytes(b"\x00" * 32, align=8)
    loc_ptrs = [(gfx_table_off + k * 8, gfx_ptr_offs[k]) for k in range(4)]

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    rip32_patches: list[tuple[int, int, int, int]] = []
    ptr64_patches: list[tuple[int, int, int]] = []
    raw_patches: list[tuple[int, bytes, bytes]] = []

    def add_rip32(insn_va: int, new_loc_off: int, expected_orig_target: int | None = None) -> None:
        raw = va_to_raw(insn_va)
        insns = list(md.disasm(orig[raw:raw + 16], insn_va, count=1))
        assert insns, f"Cannot disasm 0x{insn_va:x}"
        insn = insns[0]
        rip_op = [op for op in insn.operands if op.type == 3 and op.mem.base == 41]
        assert len(rip_op) == 1, f"Not single RIP op at 0x{insn_va:x}"
        orig_t = insn.address + insn.size + rip_op[0].mem.disp
        if expected_orig_target is not None:
            assert orig_t == expected_orig_target, f"At 0x{insn_va:x}: 0x{orig_t:x} != 0x{expected_orig_target:x}"
        expected_disp = struct.unpack_from("<i", orig, raw + insn.size - 4)[0]
        rip32_patches.append((insn_va - IMAGE_BASE, insn.size, expected_disp, new_loc_off))

    def add_ptr64(ptr_va: int, new_loc_off: int, expected_orig_target: int | None = None) -> None:
        raw = va_to_raw(ptr_va)
        orig_val = struct.unpack_from("<Q", orig, raw)[0]
        if expected_orig_target is not None:
            assert orig_val == expected_orig_target, f"PTR at 0x{ptr_va:x}"
        assert orig_val >= IMAGE_BASE
        ptr64_patches.append((ptr_va - IMAGE_BASE, orig_val - IMAGE_BASE, new_loc_off))

    def add_raw(target_va: int, new_bytes: bytes, expected_orig: bytes | None = None) -> None:
        raw = va_to_raw(target_va)
        orig_bytes = orig[raw:raw + len(new_bytes)]
        if expected_orig is not None:
            assert orig_bytes == expected_orig, f"Raw mismatch at 0x{target_va:x}"
        raw_patches.append((target_va - IMAGE_BASE, orig_bytes, new_bytes))

    def add_imm(insn_va: int, expected_imm: int, new_imm: int, imm_size: int) -> None:
        raw = va_to_raw(insn_va)
        insn = next(md.disasm(orig[raw:raw + 16], insn_va, count=1))
        off_va = insn_va + insn.size - imm_size
        fmt = "<i" if imm_size == 4 else "<B"
        cur = struct.unpack_from(fmt, orig, va_to_raw(off_va))[0]
        assert cur == expected_imm, f"At 0x{insn_va:x}: {cur} != {expected_imm}"
        add_raw(off_va, struct.pack(fmt, new_imm), struct.pack(fmt, cur))

    exe_strs = doc["exe_strings"]

    def ttext(va: int) -> str:
        return exe_strs[hex(va)]["text"]

    def slen(va: int) -> int:
        return len(ttext(va).encode("utf-8"))

    # 1. STRING_PATCHES
    for orig_va, (exp_en, _, allowed_groups) in STRING_PATCHES.items():
        actual_en = read_cstr(orig_va)
        assert actual_en == exp_en
        cat_entry = catalog[hex(orig_va)]
        leas = [int(x["va"], 16) for x in cat_entry["leas"] if x["group"] in allowed_groups]
        assert leas
        loc_off = add_str(ttext(orig_va))
        for lva in leas:
            add_rip32(lva, loc_off, orig_va)

    # 2. Special SIMD / movabs / length immediates
    add_rip32(0x140c5365b, clear_pad_str_off, 0x141561798)
    add_rip32(0x140c5366b, clear_pad_xmm0_off, 0x141561840)
    add_rip32(0x140c5367f, clear_pad_xmm1_off, 0x141561850)
    add_rip32(0x140c53f5b, clear_pad_xmm0_off, 0x141561840)
    add_rip32(0x140c53f6a, clear_pad_xmm1_off, 0x141561850)

    add_rip32(0x14095155e, seat_ymm_off)
    add_raw(0x140951566 + 2, seat_tail_bytes, struct.pack("<Q", 0x79726576696c6564))
    for off_va in range(0x14095172c, 0x140951785):
        r = va_to_raw(off_va)
        if orig[r:r + 2] == b"\x48\xb8" and struct.unpack_from("<Q", orig, r + 2)[0] == 0x79726576696c6564:
            add_raw(off_va + 2, seat_tail_bytes, struct.pack("<Q", 0x79726576696c6564))
    for insn in md.disasm(orig[va_to_raw(0x14095172c):va_to_raw(0x140951785)], 0x14095172c):
        if insn.mnemonic == "vmovdqu" and any(op.type == 3 and op.mem.base == 41 for op in insn.operands):
            add_rip32(insn.address, seat_ymm_off)

    for va in (0x1409515fc, 0x14095179f):
        add_rip32(va, flat_ymm0_off)
    for va in (0x140951608, 0x1409517ae):
        add_rip32(va, flat_ymm1_off)

    for va in (0x14095169d, 0x14095180e):
        add_rip32(va, dealer_ymm0_off)
    for va in (0x1409516a9, 0x14095181d):
        add_rip32(va, dealer_xmm1_off)

    add_rip32(0x140275095, item_xmm0_off)
    add_rip32(0x1402750a1, item_xmm1_off)

    l_short = slen(0x14149b5ba)
    add_imm(0x1402545d9, 0x14, l_short, 4)
    add_imm(0x140254603, 0x14, l_short, 4)
    add_raw(0x14025460f + 2, bytes([l_short]), b"\x14")
    add_imm(0x140254f29, 0x1B, slen(0x14149b5fc), 4)
    add_imm(0x14026dd2e, 0x14, slen(0x14149beeb), 4)
    add_imm(0x14026ea17, 4, slen(0x14149c1d3), 4)

    l_agr = slen(0x14149c350)
    add_imm(0x1402750f5, 0x35, l_agr - 1, 1)
    add_imm(0x140275104, 0x36, l_agr, 4)
    add_imm(0x140275123, 0x36, l_agr, 4)
    add_imm(0x140276407, 0x36, l_agr, 4)

    add_imm(0x14094e86d, 4, slen(0x141548c2b), 4)
    add_imm(0x14094e82a, 8, slen(0x141548c30), 4)

    add_imm(0x1409a92d9, 0x14, slen(0x14154a31a), 4)
    l_pick = slen(0x14154a376)
    add_imm(0x1409a9a9f, 0x19, l_pick, 4)
    add_imm(0x1409aa1a8, 0x19, l_pick, 4)
    l_unhook = slen(0x14154a390)
    add_imm(0x1409a9ed8, 0x12, l_unhook, 4)
    add_imm(0x1409aa9ac, 0x12, l_unhook, 4)
    l_set = slen(0x14154a330)
    add_imm(0x1409a9ff5, 0x45, l_set, 4)
    add_imm(0x1409aa004, 0x45, l_set, 4)
    add_imm(0x1409aa00a, 0x46, l_set + 1, 4)

    l_lim = slen(0x14156063a)
    add_imm(0x140c47f24, 0x0E, l_lim, 4)
    add_imm(0x140c47f29, 0x1E, l_lim + 16, 4)
    add_imm(0x140c47f3f, 0x1F, l_lim + 17, 4)

    l_priv = slen(0x141560650)
    add_imm(0x140c4867f, 0x38, l_priv, 4)
    add_imm(0x140c48684, 0x3A, l_priv + 2, 4)
    add_imm(0x140c48699, 0x3B, l_priv + 3, 4)

    add_imm(0x140c5973b, 5, slen(0x141561c2a), 4)
    for va_s, imm_va, old_l in [
        (0x141561fe0, 0x140c5e084, 8),
        (0x141561e07, 0x140c5e184, 5),
        (0x141561fd6, 0x140c5e62d, 9),
        (0x141561fe9, 0x140c5e678, 11),
    ]:
        add_imm(imm_va, old_l, slen(va_s), 4)
    add_imm(0x140c5e1a7, 0x0A, slen(0x141561fb3), 4)
    add_imm(0x140c5e640, 0x17, slen(0x141561fbe), 4)

    add_imm(0x140c6283d, 0x14, slen(0x141562253), 4)
    add_imm(0x140c630f6, 0x11, slen(0x14156226f), 4)
    add_imm(0x140c69d95, 0x15, slen(0x1415622f2), 4)

    l_bind = slen(0x141562968)
    add_imm(0x140c6b575, 0x24, l_bind - 1, 1)
    add_imm(0x140c6b57f, 0x25, l_bind, 4)

    add_imm(0x140c7e3cf, 0x0F, slen(0x141564aa4), 4)

    yes_b = doc["inline_literals"]["yes"]["text"].encode("utf-8")
    no_b = doc["inline_literals"]["no"]["text"].encode("utf-8")
    add_raw(
        0x140c7e6d9,
        b"\x48\xb8" + yes_b.ljust(8, b"\x00")
        + b"\x48\x89\x84\x24\xc0\x01\x00\x00" + struct.pack("<BI", 0xB8, len(yes_b)) + b"\x90" * 11,
        bytes.fromhex("ba79650000c68424c201000073b80300000066899424c0010000c68424c301000000"),
    )
    add_raw(
        0x140c7ed58,
        b"\x48\xb8" + no_b.ljust(8, b"\x00")
        + b"\x48\x89\x84\x24\xc0\x01\x00\x00" + struct.pack("<BI", 0xB8, len(no_b))
        + b"\xe9" + struct.pack("<i", 0x140c7e6fb - (0x140c7ed58 + 23 + 5)) + b"\x90" * 3,
        bytes.fromhex("b86e6f0000c68424c20100000066898424c0010000b802000000e984f9ffff"),
    )
    add_rip32(0x140c66e53, add_str(""), 0x141562102)

    add_imm(0x140c7eaf9, 0x0E, slen(0x141564b11), 4)
    add_imm(0x140c7edf6, 0x10, slen(0x141564aef), 4)
    add_imm(0x140c7ef50, 0x10, slen(0x141564b00), 4)
    add_imm(0x140c877c3, 8, slen(0x141565e81), 4)
    add_imm(0x140c88c86, 9, slen(0x141565e8a), 4)
    add_imm(0x140c897b7, 3, slen(0x141565ee7), 4)
    add_imm(0x140c8c9f6, 7, slen(0x141565fb9), 4)
    add_imm(0x140c8d1a2, 6, slen(0x141565fab), 4)

    l_over = slen(0x141565fb2)
    add_imm(0x140c8ea50, 6, l_over, 4)
    add_raw(0x140c8d1f1 + 3, bytes([l_over]), b"\x06")
    add_raw(0x140c8d209, b"\xe9\x32\x18\x00\x00\x90", b"\x0f\x82\x31\x18\x00\x00")
    add_raw(0x140c8d230 + 4, bytes([l_over]), b"\x06")

    add_imm(0x140c90cf3, 3, slen(0x1415660ad), 4)
    add_imm(0x140c90d18, 0x0A, slen(0x1415660b1), 4)
    add_imm(0x140c96e40, 0x41, slen(0x1415670d0), 4)
    add_imm(0x140ca18cd, 6, slen(0x1415679c7), 4)

    # Fix HUD machine title bar byte-by-byte loop (0x140cb329b..0x140cb33de):
    # draw full UTF-8 title centered in one ImDrawList::AddText call instead of splitting multi-byte UTF-8 into 1-byte chunks
    add_raw(0x140cb329b, b"\x31\xd2\x90\x90", b"\x48\x83\xea\x01")
    add_raw(0x140cb33be, b"\x48\x89\x5c\x24\x28", b"\x48\x89\x74\x24\x28")
    add_raw(0x140cb33d9, b"\x90\x90\x90\x90\x90", b"\xe9\xe2\xfe\xff\xff")

    for va_s, imm_r13, imm_ecx, old_l in [
        (0x14156ae4c, 0x140cc923b, 0x140cc9236, 0x14),
        (0x14156ae61, 0x140cc9bb5, 0x140cc9bb0, 0x17),
        (0x14156ae90, 0x140cc9c4d, 0x140cc9c48, 0x13),
        (0x14156ae79, 0x140cc9c75, 0x140cc9c70, 0x16),
    ]:
        nl = slen(va_s)
        add_imm(imm_r13, old_l, nl, 4)
        add_imm(imm_ecx, old_l + 1, nl + 1, 4)

    add_imm(0x140cc9f31, 6, slen(0x14156af98), 4)
    add_imm(0x140cc9f80, 4, slen(0x14156af9f), 4)

    add_rip32(0x140cb85d7, gfx_table_off, 0x141634c00)
    add_rip32(0x140cb8716, gfx_ptr_offs[0], 0x141569211)

    shop_sections = doc["shop_sections"]
    for idx, (orig_s_va, loc_sec) in enumerate(
        zip([0x14156ac3d, 0x14156acb0, 0x14156acbc, 0x14156b014, 0x14156acc4], shop_sections)
    ):
        add_ptr64(0x14156b020 + idx * 8, add_str(loc_sec), orig_s_va)
    add_rip32(0x140cc4431, add_str(shop_sections[0]), 0x14156ac3d)

    tables = doc["table_strings"]
    ctrl_map = tables["controls"]
    for idx in range(89):
        row_va = 0x1414a1c20 + idx * 0x38
        for col_off in (0x08, 0x10, 0x18):
            pva = row_va + col_off
            tgt = struct.unpack_from("<Q", orig, va_to_raw(pva))[0]
            k = hex(tgt)
            if k in ctrl_map:
                assert read_cstr(tgt) == ctrl_map[k]["en"]
                add_ptr64(pva, add_str(ctrl_map[k]["text"]), tgt)

    fc_map = tables["free_cam"]
    for idx in range(4):
        row_va = 0x141562de8 + idx * 0x48
        for col_off in (0x00, 0x08, 0x10, 0x18):
            pva = row_va + col_off
            tgt = struct.unpack_from("<Q", orig, va_to_raw(pva))[0]
            k = hex(tgt)
            if k in fc_map:
                assert read_cstr(tgt) == fc_map[k]["en"]
                add_ptr64(pva, add_str(fc_map[k]["text"]), tgt)

    la_map = tables["look_around"]
    for idx in range(5):
        row_va = 0x141562ce8 + idx * 0x18
        for col_off in (0x00, 0x08):
            pva = row_va + col_off
            tgt = struct.unpack_from("<Q", orig, va_to_raw(pva))[0]
            k = hex(tgt)
            if k in la_map:
                assert read_cstr(tgt) == la_map[k]["en"]
                add_ptr64(pva, add_str(la_map[k]["text"]), tgt)

    vt_map = tables["vehicle_tabs"]
    for idx in range(13):
        pva = 0x1414a09c0 + idx * 8
        tgt = struct.unpack_from("<Q", orig, va_to_raw(pva))[0]
        k = hex(tgt)
        assert read_cstr(tgt) == vt_map[k]["en"]
        add_ptr64(pva, add_str(vt_map[k]["text"]), tgt)

    md_map = tables["machine_display"]
    for row_va, full_en, _, short_en, _ in MACHINE_DISPLAY_ROWS:
        p_full, p_short = row_va + 8, row_va + 16
        t_full = struct.unpack_from("<Q", orig, va_to_raw(p_full))[0]
        t_short = struct.unpack_from("<Q", orig, va_to_raw(p_short))[0]
        assert read_cstr(t_full) == full_en and read_cstr(t_short) == short_en
        entry = md_map[hex(row_va)]
        add_ptr64(p_full, add_str(entry["full"]), t_full)
        add_ptr64(p_short, add_str(entry["short"]), t_short)

    ed_map = tables["editor"]
    for tbl_va, count, stride in [(0x1414d0080, 6, 0x30), (0x1414d0628, 11, 8), (0x1414d1280, 32, 8), (0x1414d14a0, 32, 8)]:
        for idx in range(count):
            pva = tbl_va + idx * stride
            tgt = struct.unpack_from("<Q", orig, va_to_raw(pva))[0]
            s = read_cstr(tgt)
            if s in ed_map:
                add_ptr64(pva, add_str(ed_map[s]), tgt)

    ex_map = tables["extra_ui"]
    for pva, orig_s_va, exp_en, _ in EXTRA_UI_PTR_TABLES:
        assert read_cstr(orig_s_va) == exp_en
        add_ptr64(pva, add_str(ex_map[hex(pva)]["text"]), orig_s_va)

    # Write DTLP v1
    loc_dir = ROOT_DIR / "locales" / locale
    loc_dir.mkdir(parents=True, exist_ok=True)
    dtlp = bytearray()
    dtlp.extend(
        struct.pack(
            "<4s10I",
            b"DTLP",
            1,
            len(loc_buf),
            len(rip32_patches),
            len(ptr64_patches),
            len(loc_ptrs),
            len(raw_patches),
            0x0D1B087,
            0x0D16D30,
            0x145E400,
            0x145E3B0,
        )
    )
    dtlp.extend(loc_buf)
    for rva, insn_sz, exp_disp, off in rip32_patches:
        dtlp.extend(struct.pack("<IIiI", rva, insn_sz, exp_disp, off))
    for pva, exp_tgt, off in ptr64_patches:
        dtlp.extend(struct.pack("<III", pva, exp_tgt, off))
    for dst_off, tgt_off in loc_ptrs:
        dtlp.extend(struct.pack("<II", dst_off, tgt_off))
    for rva, exp_b, new_b in raw_patches:
        dtlp.extend(struct.pack("<IH", rva, len(new_b)))
        dtlp.extend(exp_b)
        dtlp.extend(new_b)

    (loc_dir / "exe_patch.dtloc").write_bytes(bytes(dtlp))

    # Write DTPK v1
    kind_map = {"pack": 0, "winfont": 1}
    fonts = doc["font_redirects"]
    toml_dict = doc["pack_toml"]
    total_rules = sum(len(rules) for rules in toml_dict.values())
    dtpk = bytearray()
    dtpk.extend(struct.pack("<4sIII", b"DTPK", 1, len(fonts), total_rules))
    for f in fonts:
        kb, vb = f["pack_key"].encode("utf-8"), f["target"].encode("utf-8")
        dtpk.extend(struct.pack("<H", len(kb)))
        dtpk.extend(kb)
        dtpk.extend(struct.pack("<BH", kind_map[f["kind"]], len(vb)))
        dtpk.extend(vb)
    for file_key, rules in toml_dict.items():
        fk = file_key.encode("utf-8")
        for r in rules:
            ob, nb = r["old"].encode("utf-8"), r["new"].encode("utf-8")
            dtpk.extend(struct.pack("<H", len(fk)))
            dtpk.extend(fk)
            dtpk.extend(struct.pack("<I", len(ob)))
            dtpk.extend(ob)
            dtpk.extend(struct.pack("<I", len(nb)))
            dtpk.extend(nb)

    (loc_dir / "pack_patches.dtpk").write_bytes(bytes(dtpk))
    display_name = doc.get("meta", {}).get("name", locale.upper())
    (loc_dir / "meta.ini").write_text(f"name={display_name}\n", encoding="utf-8")
    ini = ROOT_DIR / "locales" / "lang.ini"
    if not ini.exists():
        ini.write_text(f"active={locale}\n", encoding="utf-8")

    print(
        f"Built plugin locale '{locale}' from {locale_path.name}: "
        f"exe_patch.dtloc={len(dtlp)} B (loc={len(loc_buf)} B, rip32={len(rip32_patches)}, ptr64={len(ptr64_patches)}, raw={len(raw_patches)}), "
        f"pack_patches.dtpk={len(dtpk)} B (fonts={len(fonts)}, rules={total_rules})"
    )


def main() -> None:
    p = add_game_dir_arg(argparse.ArgumentParser())
    p.add_argument("--locale", default="ru")
    args = p.parse_args()
    build_plugin_data(resolve_game_dir(args.game_dir), args.locale)


if __name__ == "__main__":
    main()
