import argparse
import json
import struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

from common import CATALOG_PATH, add_game_dir_arg, resolve_game_dir

_args = add_game_dir_arg(argparse.ArgumentParser()).parse_args()
_game_dir = resolve_game_dir(_args.game_dir)
EXE = _game_dir / "backup_en" / "dirttown.exe"
if not EXE.exists():
    EXE = _game_dir / "dirttown.exe"
data = EXE.read_bytes()
pe_off = struct.unpack_from("<I", data, 0x3C)[0]
num_sec = struct.unpack_from("<H", data, pe_off + 6)[0]
opt_sz = struct.unpack_from("<H", data, pe_off + 20)[0]
sec_off = pe_off + 24 + opt_sz
IMAGE_BASE = 0x140000000

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
    if va < IMAGE_BASE:
        return None
    raw = va_to_raw(va)
    if raw is None or raw >= len(data):
        return None
    end = data.find(b"\x00", raw, raw + 600)
    if end == -1:
        return None
    try:
        s = data[raw:end].decode("utf-8")
        if s and all(c in "\n\r\t" or 32 <= ord(c) < 0x110000 for c in s):
            return s
    except UnicodeDecodeError:
        return None
    return None

t_sec = [x for x in sections if x[0] == ".text"][0]
t_va0 = IMAGE_BASE + t_sec[1]
t_raw0 = t_sec[3]
text = data[t_raw0:t_raw0 + t_sec[4]]

rd_sec = [x for x in sections if x[0] == ".rdata"][0]
rd_va0 = IMAGE_BASE + rd_sec[1]
rd_va1 = rd_va0 + rd_sec[2]

# 1. Index ALL RIP-relative LEAs in .text pointing into .rdata strings
print("Indexing all .text LEAs...")
lea_by_target = {}
i = 0
while i < len(text) - 6:
    i = text.find(b"\x8d", i)
    if i == -1:
        break
    if i + 6 <= len(text) and (text[i+1] & 0xC7) == 0x05:
        disp = struct.unpack_from("<i", text, i+2)[0]
        target = t_va0 + i + 6 + disp
        if rd_va0 <= target < rd_va1:
            # Verify REX prefix if present
            has_rex = i >= 1 and (text[i-1] & 0xF0) == 0x40 and text[i-1] in (0x48, 0x4C, 0x44, 0x41, 0x49, 0x4D, 0x40, 0x45)
            insn_va = t_va0 + i - (1 if has_rex else 0)
            lea_by_target.setdefault(target, []).append(insn_va)
    i += 1

# Validate candidate LEAs with Capstone (avoid false positives inside immediate/branch operands)
md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True
valid_lea_by_target = {}
for target, vas in lea_by_target.items():
    valid = []
    for va in vas:
        r = va_to_raw(va)
        insns = list(md.disasm(data[r:r+16], va, count=1))
        if not insns and (va != t_va0):
            # try without assumed REX byte
            r2 = va_to_raw(va + 1)
            insns = list(md.disasm(data[r2:r2+16], va + 1, count=1))
        if insns and insns[0].mnemonic == "lea":
            insn = insns[0]
            for op in insn.operands:
                if op.type == 3 and op.mem.base == 41:
                    t = insn.address + insn.size + op.mem.disp
                    if t == target:
                        valid.append(insn.address)
    if valid:
        valid_lea_by_target[target] = valid

# 2. Index ALL 64-bit pointers in .rdata and .data pointing into .rdata strings
print("Indexing all .rdata/.data pointers...")
ptr_by_target = {}
for name, s_va, s_vsz, s_rptr, s_rsz in sections:
    if name not in (".rdata", ".data"):
        continue
    sec_b = data[s_rptr:s_rptr + s_rsz]
    for off in range(0, len(sec_b) - 7, 8):
        val = struct.unpack_from("<Q", sec_b, off)[0]
        if rd_va0 <= val < rd_va1:
            ptr_by_target.setdefault(val, []).append(IMAGE_BASE + s_va + off)

# 3. Collect all strings in the known UI code ranges + tables
ui_code_ranges = [
    ("game_ui", 0x140c40000, 0x140d00000),
    ("interact_prompts", 0x140c34000, 0x140c36000),
    ("debug_hud", 0x14024a000, 0x140250000),
    ("net_shop_prompts", 0x140250000, 0x140280000),
    ("clip_tool", 0x1402c0000, 0x1402d2000),
    ("editor_ui", 0x14034e000, 0x14043a000),
    ("grade_minimap", 0x140474000, 0x140476500),
    ("editor_tuning", 0x14057a000, 0x14058a000),
    ("world_prompts", 0x140930000, 0x1409c0000),
    ("hud_prompts_a", 0x140a7d800, 0x140a81000),
    ("stick_prompts", 0x140bb3700, 0x140bb4200),
]

def classify_lea(va):
    for label, a, b in ui_code_ranges:
        if a <= va < b:
            return label
    return "other"

catalog = {}
for target, lea_vas in valid_lea_by_target.items():
    # Only include if at least one LEA is in our UI ranges
    groups = [classify_lea(v) for v in lea_vas]
    if all(g == "other" for g in groups):
        continue
    s = read_cstr(target)
    if not s:
        continue
    catalog[hex(target)] = {
        "text": s,
        "leas": [{"va": hex(v), "group": classify_lea(v)} for v in sorted(lea_vas)],
        "ptrs": [hex(p) for p in sorted(ptr_by_target.get(target, []))],
    }

CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
out_json = CATALOG_PATH
out_json.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {len(catalog)} unique referenced UI/code strings to {out_json}")
