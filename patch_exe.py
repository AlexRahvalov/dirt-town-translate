import json
import re
import struct
import sys
from pathlib import Path
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

from loc_strings import (
    STRING_PATCHES,
    CONTROLS_PTR_TRANSLATIONS,
    FREE_CAM_PTR_TRANSLATIONS,
    LOOK_AROUND_PTR_TRANSLATIONS,
    VEHICLE_TAB_PTR_TRANSLATIONS,
    MACHINE_DISPLAY_ROWS,
    GRAPHICS_PRESET_UI,
    SHOP_SECTIONS_UI,
    EXTRA_UI_PTR_TABLES,
    EDITOR_STR_PTR_MAP,
)

import argparse
from common import CATALOG_PATH, add_game_dir_arg, resolve_game_dir

_p = add_game_dir_arg(argparse.ArgumentParser())
_p.add_argument("output", nargs="?", help="Optional output exe path")
_args = _p.parse_args()
_game_dir = resolve_game_dir(_args.game_dir)
BACKUP_EXE = _game_dir / "backup_en" / "dirttown.exe"
TARGET_EXE = Path(_args.output) if _args.output else _game_dir / "dirttown.exe"

data = bytearray(BACKUP_EXE.read_bytes())
catalog = json.loads(CATALOG_PATH.read_text("utf-8"))

pe_off = struct.unpack_from("<I", data, 0x3C)[0]
num_sec = struct.unpack_from("<H", data, pe_off + 6)[0]
opt_sz = struct.unpack_from("<H", data, pe_off + 20)[0]
sec_off = pe_off + 24 + opt_sz
sec_align = struct.unpack_from("<I", data, pe_off + 24 + 32)[0]
file_align = struct.unpack_from("<I", data, pe_off + 24 + 36)[0]
size_of_image_off = pe_off + 24 + 56
size_of_headers = struct.unpack_from("<I", data, pe_off + 24 + 60)[0]
IMAGE_BASE = 0x140000000

def align_up(v, a):
    return (v + a - 1) & ~(a - 1)

sections = []
for i in range(num_sec):
    s = sec_off + i * 40
    name = data[s:s+8].rstrip(b"\x00").decode("ascii", "replace")
    vsz, va, rsz, rptr = struct.unpack_from("<IIII", data, s + 8)
    sections.append((name, va, vsz, rptr, rsz))

def va_to_raw(va):
    rva = va - IMAGE_BASE
    for name, s_va, s_vsz, s_rptr, s_rsz in sections:
        if s_va <= rva < s_va + max(s_vsz, s_rsz):
            return s_rptr + (rva - s_va)
    return None

def read_cstr(va):
    raw = va_to_raw(va)
    assert raw is not None, f"Invalid VA 0x{va:x}"
    end = data.find(b"\x00", raw, raw + 1024)
    assert end != -1, f"Unterminated string at 0x{va:x}"
    return data[raw:end].decode("utf-8")

# Collect .reloc entries so we guarantee NO modified code/ptr overlaps a relocation slot unexpectedly
reloc_sec = [x for x in sections if x[0] == ".reloc"][0]
reloc_set = set()
r_pos = reloc_sec[3]
r_end = r_pos + reloc_sec[2]
while r_pos + 8 <= r_end:
    page_rva, blk_sz = struct.unpack_from("<II", data, r_pos)
    if blk_sz < 8:
        break
    cnt = (blk_sz - 8) // 2
    for j in range(cnt):
        ent = struct.unpack_from("<H", data, r_pos + 8 + j * 2)[0]
        typ = ent >> 12
        off = ent & 0xFFF
        if typ == 10:  # IMAGE_REL_BASED_DIR64
            va = IMAGE_BASE + page_rva + off
            for k in range(8):
                reloc_set.add(va + k)
        elif typ != 0:
            va = IMAGE_BASE + page_rva + off
            for k in range(4):
                reloc_set.add(va + k)
    r_pos += blk_sz

# Format specifier parity check
FMT_RE = re.compile(r"(?:%(?:[0-9#+\- .*]*)(?:ll|l|z)?[dfsuxXocp%])|\{\}")
def fmt_tokens(s):
    return [t for t in FMT_RE.findall(s) if t != "%%"]

def imgui_suffix(s):
    idx = s.find("###")
    if idx != -1:
        return s[idx:]
    idx = s.find("##")
    if idx != -1:
        return s[idx:]
    return ""

# Build .loc buffer
loc_buf = bytearray()
str_cache = {}
def add_str(s: str) -> int:
    b = s.encode("utf-8") + b"\x00"
    if b in str_cache:
        return str_cache[b]
    off = len(loc_buf)
    loc_buf.extend(b)
    str_cache[b] = off
    return off

def add_bytes(b: bytes, align=16) -> int:
    while len(loc_buf) % align != 0:
        loc_buf.append(0)
    off = len(loc_buf)
    loc_buf.extend(b)
    return off

# Compute .loc section RVA & file offset
last_name, last_va, last_vsz, last_rptr, last_rsz = sections[-1]
loc_rva = align_up(last_va + last_vsz, sec_align)
loc_va_base = IMAGE_BASE + loc_rva
# Ensure file is padded to FileAlignment before appending .loc
while len(data) % file_align != 0:
    data.append(0)
loc_raw_off = len(data)

# Reserve special data blocks in .loc first
# 1) "очистить зону." (26B exact) + overlapping 16B XMM chunks
clear_pad_ru = "очистить зону."
clear_pad_b = clear_pad_ru.encode("utf-8")
assert len(clear_pad_b) == 26, len(clear_pad_b)
clear_pad_str_va = loc_va_base + add_str(clear_pad_ru)
clear_pad_xmm0_va = loc_va_base + add_bytes(clear_pad_b[:16], align=16)
clear_pad_xmm1_va = loc_va_base + add_bytes(clear_pad_b[10:26], align=16)

# 2) step out of the seat (37B), there is no flat (51B), dealer has none (46B), item no longer installed (31B)
seat_ru = "сначала нужно выйти!"
seat_b = seat_ru.encode("utf-8")
assert len(seat_b) == 37, len(seat_b)
seat_ymm_va = loc_va_base + add_bytes(seat_b[:32], align=32)
seat_tail_qword = struct.unpack("<Q", seat_b[29:37])[0]

flat_ru = "тут нет ровного места рядом."
flat_b = flat_ru.encode("utf-8")
assert len(flat_b) == 51, len(flat_b)
flat_ymm0_va = loc_va_base + add_bytes(flat_b[:32], align=32)
flat_ymm1_va = loc_va_base + add_bytes(flat_b[19:51], align=32)

dealer_ru = "этой техники нет у дилера"
dealer_b = dealer_ru.encode("utf-8")
assert len(dealer_b) == 46, len(dealer_b)
dealer_ymm0_va = loc_va_base + add_bytes(dealer_b[:32], align=32)
dealer_xmm1_va = loc_va_base + add_bytes(dealer_b[30:46], align=16)

item_ru = "объект не найден."
item_b = item_ru.encode("utf-8")
assert len(item_b) == 31, len(item_b)
item_xmm0_va = loc_va_base + add_bytes(item_b[:16], align=16)
item_xmm1_va = loc_va_base + add_bytes(item_b[15:31], align=16)

# 3) Graphics presets 4-pointer table (needs DIR64 .reloc block appended to .reloc)
gfx_ptr_offs = [add_str(s) for s in GRAPHICS_PRESET_UI]
gfx_table_va = loc_va_base + add_bytes(struct.pack("<4Q", *[loc_va_base + o for o in gfx_ptr_offs]), align=8)
assert (gfx_table_va & 0xFFF) + 24 < 0x1000, "gfx_table_va crosses 4KB page!"

# Helpers to patch instructions cleanly
md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True

patched_leas = []
patched_ptrs = []
patched_imms = []

def patch_rip_target(insn_va: int, new_target_va: int, expected_orig_target: int | None = None):
    raw = va_to_raw(insn_va)
    insns = list(md.disasm(bytes(data[raw:raw+16]), insn_va, count=1))
    assert insns, f"Cannot disasm 0x{insn_va:x}"
    insn = insns[0]
    # Find RIP-relative displacement offset (always last 4 bytes for LEA/VMOVDQU [rip+disp32] without imm)
    rip_op = [op for op in insn.operands if op.type == 3 and op.mem.base == 41]
    assert len(rip_op) == 1, f"Not single RIP op at 0x{insn_va:x}: {insn.mnemonic} {insn.op_str}"
    orig_t = insn.address + insn.size + rip_op[0].mem.disp
    if expected_orig_target is not None:
        assert orig_t == expected_orig_target, f"At 0x{insn_va:x}: target 0x{orig_t:x} != expected 0x{expected_orig_target:x}"
    disp_off = insn.size - 4
    # Verify reloc doesn't overlap disp32
    for b_va in range(insn_va + disp_off, insn_va + disp_off + 4):
        assert b_va not in reloc_set, f"Reloc overlap at 0x{b_va:x}"
    new_disp = new_target_va - (insn.address + insn.size)
    assert -0x80000000 <= new_disp <= 0x7FFFFFFF, f"disp32 out of range at 0x{insn_va:x}"
    struct.pack_into("<i", data, raw + disp_off, new_disp)
    patched_leas.append((insn_va, orig_t, new_target_va))

def patch_ptr64(ptr_va: int, new_target_va: int, expected_orig_target: int | None = None):
    raw = va_to_raw(ptr_va)
    assert raw is not None
    orig_val = struct.unpack_from("<Q", data, raw)[0]
    if expected_orig_target is not None:
        assert orig_val == expected_orig_target, f"PTR at 0x{ptr_va:x}: 0x{orig_val:x} != 0x{expected_orig_target:x}"
    # Verify .reloc aligns on ptr_va (all 8 bytes or none)
    in_r = [ (ptr_va + k) in reloc_set for k in range(8) ]
    assert all(in_r) or not any(in_r), f"Partial reloc on ptr 0x{ptr_va:x}: {in_r}"
    struct.pack_into("<Q", data, raw, new_target_va)
    patched_ptrs.append((ptr_va, orig_val, new_target_va))

def patch_imm_at(insn_va: int, expected_imm: int, new_imm: int, imm_size: int | None = None):
    raw = va_to_raw(insn_va)
    insns = list(md.disasm(bytes(data[raw:raw+16]), insn_va, count=1))
    assert insns, f"Cannot disasm imm insn 0x{insn_va:x}"
    insn = insns[0]
    # Encode immediate at tail of instruction
    if imm_size is None:
        # Try 4-byte tail first, then 1-byte tail
        if insn.size >= 4 and struct.unpack_from("<i", data, raw + insn.size - 4)[0] == expected_imm:
            imm_size = 4
        elif insn.size >= 2 and data[raw + insn.size - 1] == expected_imm:
            imm_size = 1
        else:
            raise AssertionError(f"Could not locate imm {expected_imm} in {insn.mnemonic} {insn.op_str} at 0x{insn_va:x} ({insn.bytes.hex()})")
    off = raw + insn.size - imm_size
    if imm_size == 4:
        cur = struct.unpack_from("<i", data, off)[0]
        assert cur == expected_imm, f"At 0x{insn_va:x}: {cur} != {expected_imm}"
        struct.pack_into("<i", data, off, new_imm)
    elif imm_size == 1:
        cur = data[off]
        assert cur == expected_imm, f"At 0x{insn_va:x}: {cur} != {expected_imm}"
        assert 0 <= new_imm <= 0x7F, f"imm8 overflow at 0x{insn_va:x}: {new_imm}"
        data[off] = new_imm
    patched_imms.append((insn_va, expected_imm, new_imm))

# Apply STRING_PATCHES
for orig_va, (exp_en, ru_text, allowed_groups) in STRING_PATCHES.items():
    actual_en = read_cstr(orig_va)
    assert actual_en == exp_en, f"0x{orig_va:x}: actual {actual_en!r} != expected {exp_en!r}"
    assert fmt_tokens(actual_en) == fmt_tokens(ru_text), f"Format mismatch at 0x{orig_va:x}: {fmt_tokens(actual_en)} vs {fmt_tokens(ru_text)}"
    assert imgui_suffix(actual_en) == imgui_suffix(ru_text), f"ImGui ## suffix mismatch at 0x{orig_va:x}"

    cat_entry = catalog.get(hex(orig_va))
    assert cat_entry is not None, f"0x{orig_va:x} missing from ui_catalog.json"
    leas = [int(x["va"], 16) for x in cat_entry["leas"] if x["group"] in allowed_groups]
    assert leas, f"No LEAs in allowed_groups {allowed_groups} for 0x{orig_va:x} ({actual_en!r})"

    new_va = loc_va_base + add_str(ru_text)
    for lva in leas:
        patch_rip_target(lva, new_va, expected_orig_target=orig_va)

# Apply special SIMD / movabs / length-immediate sites
# 1) clear the pad for the crew (26B exact)
patch_rip_target(0x140c5365b, clear_pad_str_va, 0x141561798)
patch_rip_target(0x140c5366b, clear_pad_xmm0_va, 0x141561840)
patch_rip_target(0x140c5367f, clear_pad_xmm1_va, 0x141561850)
patch_rip_target(0x140c53f5b, clear_pad_xmm0_va, 0x141561840)
patch_rip_target(0x140c53f6a, clear_pad_xmm1_va, 0x141561850)

# 2) step out of the seat (37B exact) - 0x140951545 already patched by STRING_PATCHES
patch_rip_target(0x14095155e, seat_ymm_va, None)
assert struct.unpack_from("<Q", data, va_to_raw(0x140951566) + 2)[0] == 0x79726576696c6564
struct.pack_into("<Q", data, va_to_raw(0x140951566) + 2, seat_tail_qword)
# check 0x14095172c realloc branch too if it has ymm0/movabs!
for off_va in range(0x14095172c, 0x140951785):
    if data[va_to_raw(off_va):va_to_raw(off_va)+2] == b"\x48\xb8" and struct.unpack_from("<Q", data, va_to_raw(off_va)+2)[0] == 0x79726576696c6564:
        struct.pack_into("<Q", data, va_to_raw(off_va)+2, seat_tail_qword)
for insn in md.disasm(bytes(data[va_to_raw(0x14095172c):va_to_raw(0x140951785)]), 0x14095172c):
    if insn.mnemonic == "vmovdqu" and any(op.type == 3 and op.mem.base == 41 for op in insn.operands):
        patch_rip_target(insn.address, seat_ymm_va)

# 3) there is no flat... (51B exact) - 0x1409515df already patched by STRING_PATCHES
patch_rip_target(0x1409515fc, flat_ymm0_va)
patch_rip_target(0x140951608, flat_ymm1_va)
patch_rip_target(0x14095179f, flat_ymm0_va)
patch_rip_target(0x1409517ae, flat_ymm1_va)

# 4) the dealer has none... (46B exact) - 0x140951680 already patched by STRING_PATCHES
patch_rip_target(0x14095169d, dealer_ymm0_va)
patch_rip_target(0x1409516a9, dealer_xmm1_va)
patch_rip_target(0x14095180e, dealer_ymm0_va)
patch_rip_target(0x14095181d, dealer_xmm1_va)

# 5) the item is no longer installed (31B exact)
patch_rip_target(0x140275095, item_xmm0_va)
patch_rip_target(0x1402750a1, item_xmm1_va)

# Length immediates for variable-length translated strings
def slen(orig_va):
    return len(STRING_PATCHES[orig_va][1].encode("utf-8"))

# account is short
l_short = slen(0x14149b5ba)
patch_imm_at(0x1402545d9, 0x14, l_short, 4)
patch_imm_at(0x140254603, 0x14, l_short, 4)
r_null = va_to_raw(0x14025460f)
assert data[r_null:r_null+4] == b"\xc6\x40\x14\x00"
data[r_null + 2] = l_short
patched_imms.append((0x14025460f, 0x14, l_short))

# delivered in front of you
patch_imm_at(0x140254f29, 0x1b, slen(0x14149b5fc), 4)

# receiving the site, 
patch_imm_at(0x14026dd2e, 0x14, slen(0x14149beeb), 4)

# All 
patch_imm_at(0x14026ea17, 4, slen(0x14149c1d3), 4)

# accept Workshop agreement (<= 54B -> 53B)
l_agr = slen(0x14149c350)
patch_imm_at(0x1402750f5, 0x35, l_agr - 1, 1)
patch_imm_at(0x140275104, 0x36, l_agr, 4)
patch_imm_at(0x140275123, 0x36, l_agr, 4)
patch_imm_at(0x140276407, 0x36, l_agr, 4)

# Use / to push
patch_imm_at(0x14094e86d, 4, slen(0x141548c2b), 4)
patch_imm_at(0x14094e82a, 8, slen(0x141548c30), 4)

# Chains
l_put = slen(0x14154a31a)  # <= 20B ("  убр. цепь" = 19B)
assert l_put <= 20
patch_imm_at(0x1409a92d9, 0x14, l_put, 4)

l_pick = slen(0x14154a376)  # 30B <= 0x1e
assert l_pick <= 30
patch_imm_at(0x1409a9a9f, 0x19, l_pick, 4)
patch_imm_at(0x1409aa1a8, 0x19, l_pick, 4)

l_unhook = slen(0x14154a390)  # 27B <= 30
assert l_unhook <= 30
patch_imm_at(0x1409a9ed8, 0x12, l_unhook, 4)
patch_imm_at(0x1409aa9ac, 0x12, l_unhook, 4)

l_set = slen(0x14154a330)
patch_imm_at(0x1409a9ff5, 0x45, l_set, 4)
patch_imm_at(0x1409aa004, 0x45, l_set, 4)
patch_imm_at(0x1409aa00a, 0x46, l_set + 1, 4)

# limit exceeded & insufficient privilege
l_lim = slen(0x14156063a)
assert 16 <= l_lim < 128
patch_imm_at(0x140c47f24, 0x0e, l_lim, 4)
patch_imm_at(0x140c47f29, 0x1e, l_lim + 16, 4)
patch_imm_at(0x140c47f3f, 0x1f, l_lim + 17, 4)

l_priv = slen(0x141560650)
assert 16 <= l_priv < 128
patch_imm_at(0x140c4867f, 0x38, l_priv, 4)
patch_imm_at(0x140c48684, 0x3a, l_priv + 2, 4)
patch_imm_at(0x140c48699, 0x3b, l_priv + 3, 4)

# ' and ' in Controls devices (" и " = 4B)
patch_imm_at(0x140c5973b, 5, slen(0x141561c2a), 4)

# Capture prompts (SSO <= 15B for esi ones, full string for push up / sideways)
for va_s, imm_va, old_l in [
    (0x141561fe0, 0x140c5e084, 8),
    (0x141561e07, 0x140c5e184, 5),
    (0x141561fd6, 0x140c5e62d, 9),
    (0x141561fe9, 0x140c5e678, 11),
]:
    nl = slen(va_s)
    assert nl <= 15, f"Capture SSO > 15: {nl}"
    patch_imm_at(imm_va, old_l, nl, 4)

patch_imm_at(0x140c5e1a7, 0x0a, slen(0x141561fb3), 4)
patch_imm_at(0x140c5e640, 0x17, slen(0x141561fbe), 4)

# Controls header / subtitle appends
patch_imm_at(0x140c6283d, 0x14, slen(0x141562253), 4)
patch_imm_at(0x140c630f6, 0x11, slen(0x14156226f), 4)
patch_imm_at(0x140c69d95, 0x15, slen(0x1415622f2), 4)

# Replace layout popup (" bindings..." -> 26B <= 37B)
l_bind = slen(0x141562968)
assert l_bind <= 37
patch_imm_at(0x140c6b575, 0x24, l_bind - 1, 1)
patch_imm_at(0x140c6b57f, 0x25, l_bind, 4)

# Test drive & Start screen
patch_imm_at(0x140c7e3cf, 0x0f, slen(0x141564aa4), 4)
# Inline "yes" / "no" in site card (EDITABLE -> РЕДАКТ.)
r_yes = va_to_raw(0x140c7e6d9)
orig_yes = bytes.fromhex("ba79650000c68424c201000073b80300000066899424c0010000c68424c301000000")
assert data[r_yes:r_yes + len(orig_yes)] == orig_yes
data[r_yes:r_yes + len(orig_yes)] = (
    b"\x48\xb8" + "да".encode("utf-8").ljust(8, b"\x00")
    + b"\x48\x89\x84\x24\xc0\x01\x00\x00\xb8\x04\x00\x00\x00" + b"\x90" * 11
)
r_no = va_to_raw(0x140c7ed58)
orig_no = bytes.fromhex("b86e6f0000c68424c20100000066898424c0010000b802000000e984f9ffff")
assert data[r_no:r_no + len(orig_no)] == orig_no
data[r_no:r_no + len(orig_no)] = (
    b"\x48\xb8" + "нет".encode("utf-8").ljust(8, b"\x00")
    + b"\x48\x89\x84\x24\xc0\x01\x00\x00\xb8\x06\x00\x00\x00"
    + b"\xe9" + struct.pack("<i", 0x140c7e6fb - (0x140c7ed58 + 23 + 5)) + b"\x90" * 3
)
# Silence plural "s" in Controls "%d control%s"
patch_rip_target(0x140c66e53, loc_va_base + add_str(""), 0x141562102)
patch_imm_at(0x140c7eaf9, 0x0e, slen(0x141564b11), 4)
patch_imm_at(0x140c7edf6, 0x10, slen(0x141564aef), 4)
patch_imm_at(0x140c7ef50, 0x10, slen(0x141564b00), 4)
patch_imm_at(0x140c877c3, 8, slen(0x141565e81), 4)
patch_imm_at(0x140c88c86, 9, slen(0x141565e8a), 4)
patch_imm_at(0x140c897b7, 3, slen(0x141565ee7), 4)
patch_imm_at(0x140c8c9f6, 7, slen(0x141565fb9), 4)
patch_imm_at(0x140c8d1a2, 6, slen(0x141565fab), 4)
l_over = slen(0x141565fb2)  # " ЗАНОВО?" = 14B
assert l_over < 128
patch_imm_at(0x140c8ea50, 6, l_over, 4)
r_lea_r15 = va_to_raw(0x140c8d1f1)
assert data[r_lea_r15:r_lea_r15+4] == b"\x4d\x8d\x7e\x06"
data[r_lea_r15 + 3] = l_over
r_jb_over = va_to_raw(0x140c8d209)
assert data[r_jb_over:r_jb_over+6] == b"\x0f\x82\x31\x18\x00\x00"
data[r_jb_over:r_jb_over+6] = b"\xe9\x32\x18\x00\x00\x90"
r_nul_over = va_to_raw(0x140c8d230)
assert data[r_nul_over:r_nul_over+6] == b"\x42\xc6\x44\x30\x06\x00"
data[r_nul_over + 4] = l_over
patch_imm_at(0x140c90cf3, 3, slen(0x1415660ad), 4)
patch_imm_at(0x140c90d18, 0x0a, slen(0x1415660b1), 4)
patch_imm_at(0x140c96e40, 0x41, slen(0x1415670d0), 4)
patch_imm_at(0x140ca18cd, 6, slen(0x1415679c7), 4)

# Fix HUD machine title bar byte-by-byte UTF-8 splitting (0x140cb329b..0x140cb33de)
for patch_va, orig_b, new_b in [
    (0x140cb329b, b"\x48\x83\xea\x01", b"\x31\xd2\x90\x90"),
    (0x140cb33be, b"\x48\x89\x74\x24\x28", b"\x48\x89\x5c\x24\x28"),
    (0x140cb33d9, b"\xe9\xe2\xfe\xff\xff", b"\x90\x90\x90\x90\x90"),
]:
    r_p = va_to_raw(patch_va)
    assert data[r_p:r_p + len(orig_b)] == orig_b
    data[r_p:r_p + len(orig_b)] = new_b

# Shop availability strings (all >= 16B!)
for va_s, imm_r13, imm_ecx, old_l in [
    (0x14156ae4c, 0x140cc923b, 0x140cc9236, 0x14),
    (0x14156ae61, 0x140cc9bb5, 0x140cc9bb0, 0x17),
    (0x14156ae90, 0x140cc9c4d, 0x140cc9c48, 0x13),
    (0x14156ae79, 0x140cc9c75, 0x140cc9c70, 0x16),
]:
    nl = slen(va_s)
    assert nl >= 16
    patch_imm_at(imm_r13, old_l, nl, 4)
    patch_imm_at(imm_ecx, old_l + 1, nl + 1, 4)

patch_imm_at(0x140cc9f31, 6, slen(0x14156af98), 4)
patch_imm_at(0x140cc9f80, 4, slen(0x14156af9f), 4)

# Custom Graphics preset UI table
patch_rip_target(0x140cb85d7, gfx_table_va, 0x141634c00)
patch_rip_target(0x140cb8716, loc_va_base + gfx_ptr_offs[0], 0x141569211)

# Shop sections UI table in .rdata (5 ptrs at 0x14156b020..0x14156b040; preserves existing .reloc)
SHOP_SECTION_ORIG_PTRS = [0x14156ac3d, 0x14156acb0, 0x14156acbc, 0x14156b014, 0x14156acc4]
for idx, (orig_s_va, ru_sec) in enumerate(zip(SHOP_SECTION_ORIG_PTRS, SHOP_SECTIONS_UI)):
    patch_ptr64(0x14156b020 + idx * 8, loc_va_base + add_str(ru_sec), orig_s_va)
patch_rip_target(0x140cc4431, loc_va_base + add_str(SHOP_SECTIONS_UI[0]), 0x14156ac3d)

# Controls table 0x1414a1c20 (89 rows * 0x38, cols +0x08/+0x10/+0x18 ONLY)
for idx in range(89):
    row_va = 0x1414a1c20 + idx * 0x38
    for col_off in (0x08, 0x10, 0x18):
        pva = row_va + col_off
        tgt = struct.unpack_from("<Q", data, va_to_raw(pva))[0]
        if tgt in CONTROLS_PTR_TRANSLATIONS:
            exp_en, ru = CONTROLS_PTR_TRANSLATIONS[tgt]
            assert read_cstr(tgt) == exp_en, f"Controls ptr 0x{pva:x} -> {read_cstr(tgt)!r} != {exp_en!r}"
            patch_ptr64(pva, loc_va_base + add_str(ru), tgt)

# Free cam / Menus table 0x141562de8 (4 rows * 0x48, first 4 ptrs each)
for idx in range(4):
    row_va = 0x141562de8 + idx * 0x48
    for col_off in (0x00, 0x08, 0x10, 0x18):
        pva = row_va + col_off
        tgt = struct.unpack_from("<Q", data, va_to_raw(pva))[0]
        if tgt in FREE_CAM_PTR_TRANSLATIONS:
            exp_en, ru = FREE_CAM_PTR_TRANSLATIONS[tgt]
            assert read_cstr(tgt) == exp_en
            patch_ptr64(pva, loc_va_base + add_str(ru), tgt)

# Look around table 0x141562ce8 (5 rows * 0x18, cols 0 and 8)
for idx in range(5):
    row_va = 0x141562ce8 + idx * 0x18
    for col_off in (0x00, 0x08):
        pva = row_va + col_off
        tgt = struct.unpack_from("<Q", data, va_to_raw(pva))[0]
        if tgt in LOOK_AROUND_PTR_TRANSLATIONS:
            exp_en, ru = LOOK_AROUND_PTR_TRANSLATIONS[tgt]
            assert read_cstr(tgt) == exp_en
            patch_ptr64(pva, loc_va_base + add_str(ru), tgt)

# Vehicle tabs table 0x1414a09c0 (13 ptrs)
for idx in range(13):
    pva = 0x1414a09c0 + idx * 8
    tgt = struct.unpack_from("<Q", data, va_to_raw(pva))[0]
    exp_en, ru = VEHICLE_TAB_PTR_TRANSLATIONS[tgt]
    assert read_cstr(tgt) == exp_en
    patch_ptr64(pva, loc_va_base + add_str(ru), tgt)

# Machine display names table 0x141648820 (cols +0x08 and +0x10 ONLY)
for row_va, full_en, full_ru, short_en, short_ru in MACHINE_DISPLAY_ROWS:
    p_full = row_va + 8
    p_short = row_va + 16
    t_full = struct.unpack_from("<Q", data, va_to_raw(p_full))[0]
    t_short = struct.unpack_from("<Q", data, va_to_raw(p_short))[0]
    assert read_cstr(t_full) == full_en, f"0x{row_va:x} full: {read_cstr(t_full)!r}"
    assert read_cstr(t_short) == short_en, f"0x{row_va:x} short: {read_cstr(t_short)!r}"
    patch_ptr64(p_full, loc_va_base + add_str(full_ru), t_full)
    patch_ptr64(p_short, loc_va_base + add_str(short_ru), t_short)

# Site Editor tables (safe UI-only pointer slots)
for tbl_va, count, stride in [
    (0x1414d0080, 6, 0x30),
    (0x1414d0628, 11, 8),
    (0x1414d1280, 32, 8),
    (0x1414d14a0, 32, 8),
]:
    for idx in range(count):
        pva = tbl_va + idx * stride
        tgt = struct.unpack_from("<Q", data, va_to_raw(pva))[0]
        s = read_cstr(tgt)
        if s in EDITOR_STR_PTR_MAP:
            patch_ptr64(pva, loc_va_base + add_str(EDITOR_STR_PTR_MAP[s]), tgt)

# Controls categories, loading stages, and start screen card PTR64s
for pva, orig_s_va, exp_en, ru_s in EXTRA_UI_PTR_TABLES:
    assert read_cstr(orig_s_va) == exp_en, f"EXTRA_UI mismatch at 0x{pva:x}"
    patch_ptr64(pva, loc_va_base + add_str(ru_s), orig_s_va)

# Append DIR64 relocation block for gfx_table_va into free padding at end of .reloc
reloc_idx = [i for i, x in enumerate(sections) if x[0] == ".reloc"][0]
_, reloc_s_va, reloc_s_vsz, reloc_s_rptr, reloc_s_rsz = reloc_sec
reloc_dir_off = pe_off + 24 + 112 + 5 * 8
dd_reloc_rva, dd_reloc_sz = struct.unpack_from("<II", data, reloc_dir_off)
assert dd_reloc_rva == reloc_s_va and dd_reloc_sz == reloc_s_vsz
gfx_reloc_blk = struct.pack(
    "<II4H",
    (gfx_table_va - IMAGE_BASE) & ~0xFFF,
    16,
    *[((10 << 12) | ((gfx_table_va - IMAGE_BASE + k * 8) & 0xFFF)) for k in range(4)],
)
assert dd_reloc_sz + len(gfx_reloc_blk) <= reloc_s_rsz, "Not enough free bytes in .reloc!"
assert all(b == 0 for b in data[reloc_s_rptr + dd_reloc_sz : reloc_s_rptr + dd_reloc_sz + len(gfx_reloc_blk)])
data[reloc_s_rptr + dd_reloc_sz : reloc_s_rptr + dd_reloc_sz + len(gfx_reloc_blk)] = gfx_reloc_blk
new_reloc_sz = dd_reloc_sz + len(gfx_reloc_blk)
struct.pack_into("<I", data, reloc_dir_off + 4, new_reloc_sz)
struct.pack_into("<I", data, sec_off + reloc_idx * 40 + 8, new_reloc_sz)

# Finalize .loc section & PE header
loc_vsz = len(loc_buf)
loc_rsz = align_up(loc_vsz, file_align)
while len(loc_buf) < loc_rsz:
    loc_buf.append(0)
data.extend(loc_buf)

# Write new section header at sec_off + num_sec * 40
new_sec_hdr = sec_off + num_sec * 40
assert new_sec_hdr + 40 <= size_of_headers, "Not enough free header space!"
assert all(b == 0 for b in data[new_sec_hdr:new_sec_hdr+40]), "Header slot not empty!"
struct.pack_into("<8sIIIIIIHHI", data, new_sec_hdr,
    b".loc\x00\x00\x00\x00",
    loc_vsz, loc_rva, loc_rsz, loc_raw_off,
    0, 0, 0, 0,
    0x40000040  # IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ
)
# Update NumberOfSections & SizeOfImage
struct.pack_into("<H", data, pe_off + 6, num_sec + 1)
new_size_of_image = align_up(loc_rva + loc_vsz, sec_align)
struct.pack_into("<I", data, size_of_image_off, new_size_of_image)

TARGET_EXE.write_bytes(bytes(data))
print(f"Patched dirttown.exe successfully!")
print(f"  .loc VA=0x{loc_va_base:x}, VSize={loc_vsz}, Raw=0x{loc_raw_off:x}, RSize={loc_rsz}")
print(f"  SizeOfImage: 0x{new_size_of_image:x}, NumberOfSections: {num_sec + 1}")
print(f"  Patched LEAs/XMMs: {len(patched_leas)}, PTR64s: {len(patched_ptrs)}, IMMS: {len(patched_imms)}")
print(f"  Unique strings written to .loc: {len(str_cache)}")
