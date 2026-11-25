import argparse
import os
import struct
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
WORK_DIR = ROOT_DIR / "work"
UNPACKED_DIR = WORK_DIR / "unpacked"
OVERRIDES_DIR = WORK_DIR / "packed_overrides"
CATALOG_PATH = WORK_DIR / "ui_catalog.json"

IMAGE_BASE = 0x140000000

DEFAULT_GAME_CANDIDATES = [
    Path(r"D:\SteamLibrary\steamapps\common\Dirt Town Demo"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Dirt Town Demo"),
    Path(r"C:\SteamLibrary\steamapps\common\Dirt Town Demo"),
    Path(r"E:\SteamLibrary\steamapps\common\Dirt Town Demo"),
]


def resolve_game_dir(cli_arg: str | None = None) -> Path:
    """Resolve the Dirt Town Demo installation directory."""
    if cli_arg:
        p = Path(cli_arg)
        if (p / "dirttown.exe").exists():
            return p
        raise FileNotFoundError(f"dirttown.exe not found in {p}")
    env_dir = os.environ.get("DIRT_TOWN_DIR")
    if env_dir:
        p = Path(env_dir)
        if (p / "dirttown.exe").exists():
            return p
        raise FileNotFoundError(f"DIRT_TOWN_DIR={p} does not contain dirttown.exe")
    for cand in DEFAULT_GAME_CANDIDATES:
        if (cand / "dirttown.exe").exists():
            return cand
    raise FileNotFoundError(
        "Could not locate Dirt Town Demo. Pass --game-dir \"<path to Dirt Town Demo>\"."
    )


def add_game_dir_arg(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--game-dir",
        help="Path to Dirt Town Demo folder (containing dirttown.exe and data.pack)",
    )
    return parser


def parse_pe_sections(exe_bytes: bytes):
    """Return (pe_off, num_sec, opt_sz, sec_off, sec_align, file_align, size_of_image_off, size_of_headers, sections)."""
    pe_off = struct.unpack_from("<I", exe_bytes, 0x3C)[0]
    num_sec = struct.unpack_from("<H", exe_bytes, pe_off + 6)[0]
    opt_sz = struct.unpack_from("<H", exe_bytes, pe_off + 20)[0]
    sec_off = pe_off + 24 + opt_sz
    sec_align = struct.unpack_from("<I", exe_bytes, pe_off + 24 + 32)[0]
    file_align = struct.unpack_from("<I", exe_bytes, pe_off + 24 + 36)[0]
    size_of_image_off = pe_off + 24 + 56
    size_of_headers = struct.unpack_from("<I", exe_bytes, pe_off + 24 + 60)[0]
    sections = []
    for i in range(num_sec):
        s = sec_off + i * 40
        name = exe_bytes[s:s + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsz, va, rsz, rptr = struct.unpack_from("<IIII", exe_bytes, s + 8)
        ch = struct.unpack_from("<I", exe_bytes, s + 36)[0]
        sections.append((name, va, vsz, rptr, rsz, ch))
    return pe_off, num_sec, opt_sz, sec_off, sec_align, file_align, size_of_image_off, size_of_headers, sections


def va_to_raw(sections, va: int) -> int | None:
    rva = va - IMAGE_BASE
    for _, s_va, s_vsz, s_rptr, s_rsz, _ in sections:
        if s_va <= rva < s_va + max(s_vsz, s_rsz):
            return s_rptr + (rva - s_va)
    return None


def read_pack_key(exe_bytes: bytes) -> bytes:
    """Read the 32-byte DIGP XOR key from dirttown.exe (.rdata VA 0x14156eb40)."""
    _, _, _, _, _, _, _, _, sections = parse_pe_sections(exe_bytes)
    raw = va_to_raw(sections, 0x14156EB40)
    assert raw is not None, "Could not resolve pack key VA 0x14156eb40"
    return exe_bytes[raw:raw + 32]


def xor_at(buf: bytes | bytearray, file_pos: int, key32: bytes) -> bytes:
    out = bytearray(buf)
    base = file_pos - 4
    for i in range(len(out)):
        out[i] ^= key32[(base + i) & 0x1F]
    return bytes(out)
