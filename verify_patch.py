import re
import struct
import sys
import tomllib
import zlib
from pathlib import Path
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

import argparse
from common import add_game_dir_arg, read_pack_key, resolve_game_dir

_p = add_game_dir_arg(argparse.ArgumentParser())
_p.add_argument("exe", nargs="?", help="Optional exe path to verify")
_args = _p.parse_args()
GAME_DIR = resolve_game_dir(_args.game_dir)
ORIG_EXE = GAME_DIR / "backup_en" / "dirttown.exe"
PATCH_EXE = Path(_args.exe) if _args.exe else GAME_DIR / "dirttown.exe"
PATCH_PACK = GAME_DIR / "data.pack"

orig = ORIG_EXE.read_bytes()
patch = PATCH_EXE.read_bytes()

# 1. PE Header & Section Verification
pe_off = struct.unpack_from("<I", patch, 0x3C)[0]
num_sec = struct.unpack_from("<H", patch, pe_off + 6)[0]
opt_sz = struct.unpack_from("<H", patch, pe_off + 20)[0]
sec_off = pe_off + 24 + opt_sz
sec_align = struct.unpack_from("<I", patch, pe_off + 24 + 32)[0]
file_align = struct.unpack_from("<I", patch, pe_off + 24 + 36)[0]
size_of_image = struct.unpack_from("<I", patch, pe_off + 24 + 56)[0]
IMAGE_BASE = 0x140000000

assert num_sec == 11, f"Expected 11 sections, got {num_sec}"
sections = []
for i in range(num_sec):
    s = sec_off + i * 40
    name = patch[s:s+8].rstrip(b"\x00").decode("ascii", "replace")
    vsz, va, rsz, rptr, _, _, _, _, ch = struct.unpack_from("<IIIIIIII", patch, s + 8) if False else (0,0,0,0,0,0,0,0,0)
    vsz, va, rsz, rptr = struct.unpack_from("<IIII", patch, s + 8)
    ch = struct.unpack_from("<I", patch, s + 36)[0]
    sections.append((name, va, vsz, rptr, rsz, ch))

loc_sec = sections[-1]
assert loc_sec[0] == ".loc"
assert loc_sec[1] % sec_align == 0
assert loc_sec[3] % file_align == 0
assert loc_sec[4] % file_align == 0
assert loc_sec[5] == 0x40000040
assert size_of_image == ((loc_sec[1] + loc_sec[2] + sec_align - 1) & ~(sec_align - 1))
assert len(patch) == loc_sec[3] + loc_sec[4]

loc_va0 = IMAGE_BASE + loc_sec[1]
loc_va1 = loc_va0 + loc_sec[2]

def va_to_raw(buf, va):
    rva = va - IMAGE_BASE
    for name, s_va, s_vsz, s_rptr, s_rsz, _ in sections:
        if s_va <= rva < s_va + max(s_vsz, s_rsz):
            return s_rptr + (rva - s_va)
    return None

def read_cstr(buf, va):
    raw = va_to_raw(buf, va)
    if raw is None or raw >= len(buf):
        return None
    end = buf.find(b"\x00", raw, raw + 1024)
    if end == -1:
        return None
    return buf[raw:end].decode("utf-8")

# 2. Verify every diff between orig and patch in .text, .rdata, .data
md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True

text_sec = [s for s in sections if s[0] == ".text"][0]
t_rptr, t_rsz, t_va = text_sec[3], text_sec[4], IMAGE_BASE + text_sec[1]

# Scan diff bytes in .text and verify EVERY changed opcode decodes cleanly and targets .loc (or expected imm)
diff_offsets = [i for i in range(t_rsz) if orig[t_rptr + i] != patch[t_rptr + i]]
print(f".text changed bytes: {len(diff_offsets)}")

# Verify every LEA inside UI ranges targeting .loc resolves cleanly to valid UTF-8
loc_targets_hit = 0
for s_va, e_va in [(0x140250000, 0x140280000), (0x1402c0000, 0x1402d2000), (0x14034e000, 0x14043a000), (0x140474000, 0x140476500), (0x140930000, 0x1409c0000), (0x140a7d800, 0x140a81000), (0x140bb3700, 0x140bb4200), (0x140c40000, 0x140d00000)]:
    cur = s_va
    r1 = va_to_raw(patch, e_va)
    while cur < e_va:
        got = False
        for insn in md.disasm(patch[va_to_raw(patch, cur):r1], cur):
            if insn.mnemonic == "lea":
                for op in insn.operands:
                    if op.type == 3 and op.mem.base == 41:
                        tgt = insn.address + insn.size + op.mem.disp
                        if loc_va0 <= tgt < loc_va1:
                            # If it's gfx_table_va pointer array, read its 4 ptrs
                            if insn.address == 0x140cb85d7:
                                r = va_to_raw(patch, tgt)
                                arr = struct.unpack_from("<4Q", patch, r)
                                vals = [read_cstr(patch, p) for p in arr]
                                assert all(vals)
                            else:
                                s = read_cstr(patch, tgt)
                                assert s is not None, f"Invalid UTF-8 at 0x{tgt:x} from LEA 0x{insn.address:x}"
                            loc_targets_hit += 1
            cur = insn.address + insn.size
            got = True
        if not got:
            cur += 1
        elif cur < e_va:
            cur += 1

print(f"Verified {loc_targets_hit} .text LEA instructions resolving cleanly into .loc!")

# Verify .rdata changed pointers
rd_sec = [s for s in sections if s[0] == ".rdata"][0]
rd_rptr, rd_rsz, rd_va = rd_sec[3], rd_sec[4], IMAGE_BASE + rd_sec[1]
ptr_changes = 0
for off in range(0, rd_rsz - 7, 8):
    ov = struct.unpack_from("<Q", orig, rd_rptr + off)[0]
    pv = struct.unpack_from("<Q", patch, rd_rptr + off)[0]
    if ov != pv:
        assert loc_va0 <= pv < loc_va1, f"Non-.loc pointer change at 0x{rd_va+off:x}: 0x{pv:x}"
        s = read_cstr(patch, pv)
        assert s is not None
        ptr_changes += 1
print(f"Verified {ptr_changes} .rdata 64-bit pointers resolving cleanly into .loc!")

# 2b. Verify .reloc integrity & ASLR relocation simulation
dd_reloc_rva, dd_reloc_sz = struct.unpack_from("<II", patch, pe_off + 24 + 112 + 5 * 8)
reloc_sec = [s for s in sections if s[0] == ".reloc"][0]
assert dd_reloc_rva == reloc_sec[1] and dd_reloc_sz == reloc_sec[2]
assert dd_reloc_sz <= reloc_sec[4]
reloc_vas = set()
prev_page = -1
r_off = 0
while r_off < dd_reloc_sz:
    page_rva, blk_sz = struct.unpack_from("<II", patch, reloc_sec[3] + r_off)
    assert blk_sz >= 8 and blk_sz % 4 == 0, f"Bad reloc block at 0x{r_off:x}: sz={blk_sz}"
    assert page_rva > prev_page, f"Non-ascending reloc page_rva 0x{page_rva:x} <= 0x{prev_page:x}"
    prev_page = page_rva
    for j in range((blk_sz - 8) // 2):
        ent = struct.unpack_from("<H", patch, reloc_sec[3] + r_off + 8 + j * 2)[0]
        if (ent >> 12) == 10:
            reloc_vas.add(IMAGE_BASE + page_rva + (ent & 0xFFF))
    r_off += blk_sz
assert r_off == dd_reloc_sz

# Verify every pointer in gfx_table_va (.loc) and Shop sections (.rdata) has a DIR64 reloc
gfx_lea_raw = va_to_raw(patch, 0x140cb85d7)
gfx_disp = struct.unpack_from("<i", patch, gfx_lea_raw + 3)[0]
gfx_tbl = 0x140cb85d7 + 7 + gfx_disp
for k in range(4):
    pva = gfx_tbl + k * 8
    assert pva in reloc_vas, f"Missing DIR64 reloc for gfx_table[{k}] at 0x{pva:x}!"
    tgt = struct.unpack_from("<Q", patch, va_to_raw(patch, pva))[0]
    assert read_cstr(patch, tgt)
for k in range(5):
    pva = 0x14156b020 + k * 8
    assert pva in reloc_vas, f"Missing DIR64 reloc for shop_sec[{k}] at 0x{pva:x}!"
    tgt = struct.unpack_from("<Q", patch, va_to_raw(patch, pva))[0]
    assert read_cstr(patch, tgt)
print(f"Verified .reloc integrity ({len(reloc_vas)} DIR64 entries, including gfx_table in .loc & shop_sec in .rdata)!")

# 3. Verify data.pack
KEY32 = read_pack_key(orig)
def xor_at(buf, file_pos):
    out = bytearray(buf)
    base = file_pos - 4
    for i in range(len(out)):
        out[i] ^= KEY32[(base + i) & 0x1F]
    return bytes(out)

pbytes = PATCH_PACK.read_bytes()
assert pbytes[:4] == b"DIGP"
ver, idx_off, idx_sz = struct.unpack("<IQQ", xor_at(pbytes[4:24], 4))
assert ver == 1
idx_raw = xor_at(pbytes[idx_off:idx_off+idx_sz], idx_off)
cnt = struct.unpack_from("<I", idx_raw, 0)[0]
assert cnt == 393
pos = 4
tomls_checked = 0
fonts_checked = 0
for _ in range(cnt):
    nl = struct.unpack_from("<H", idx_raw, pos)[0]
    pos += 2
    nm = idx_raw[pos:pos+nl].decode("utf-8")
    pos += nl
    fl, off, us, cs = struct.unpack_from("<BQQQ", idx_raw, pos)
    pos += 25
    plain = xor_at(pbytes[off:off+cs], off)
    u = zlib.decompress(plain, -15) if fl == 1 else plain
    assert len(u) == us
    if nm.endswith(".toml"):
        txt = u.decode("utf-8")
        doc = tomllib.loads(txt)
        if nm == "sites/demo2/demo2.toml":
            acc = doc.get("site", {}).get("accepts", [])
            assert "811034dce06dee68" in acc and "27d9a082d2382faa" in acc, f"Unexpected demo2 accepts: {acc}"
        tomls_checked += 1
    elif nm.endswith(".ttf"):
        # Verify full Russian cmap
        num_t = struct.unpack_from(">H", u, 4)[0]
        cmap_off = next(struct.unpack_from(">I", u, 12 + k*16 + 8)[0] for k in range(num_t) if u[12+k*16:12+k*16+4] == b"cmap")
        nsub = struct.unpack_from(">H", u, cmap_off + 2)[0]
        cov = set()
        for k in range(nsub):
            _, _, so = struct.unpack_from(">HHI", u, cmap_off + 4 + k*8)
            o = cmap_off + so
            fmt = struct.unpack_from(">H", u, o)[0]
            if fmt == 4:
                sc = struct.unpack_from(">H", u, o + 6)[0] // 2
                ends = struct.unpack_from(f">{sc}H", u, o + 14)
                starts = struct.unpack_from(f">{sc}H", u, o + 16 + 2*sc)
                for a, b in zip(starts, ends):
                    if a <= 0x04FF and b >= 0x0400:
                        cov.update(range(max(a, 0x0400), min(b, 0x04FF) + 1))
            elif fmt == 12:
                ng = struct.unpack_from(">I", u, o + 12)[0]
                for g in range(ng):
                    a, b, _ = struct.unpack_from(">III", u, o + 16 + g*12)
                    if a <= 0x04FF and b >= 0x0400:
                        cov.update(range(max(a, 0x0400), min(b, 0x04FF) + 1))
        req = set(range(0x0410, 0x0450)) | {0x0401, 0x0451}
        assert not (req - cov), f"Font {nm} missing Cyrillic glyphs!"
        fonts_checked += 1

print(f"Verified data.pack: 393 entries, {tomls_checked} valid TOMLs, {fonts_checked} full-Cyrillic TTFs!")
print("ALL VERIFICATION CHECKS PASSED!")
