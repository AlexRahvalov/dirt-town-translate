"""Validate all community translation JSON files against schema, format parity, and PE byte limits."""

import json
import re
import sys
from pathlib import Path

from common import ROOT_DIR

FMT_RE = re.compile(r"(?:%(?:[0-9#+\- .*]*)(?:ll|l|z)?[dfsuxXocp%])|\{\}")

# Hard PE code/buffer constraints observed in dirttown.exe (build ed45b4be7fc6)
BUTTON_31B_VAS = {
    "0x14156220e", "0x1415634ad", "0x141563564", "0x1415635d3", "0x14156365f",
    "0x141562036", "0x141562901", "0x141562959", "0x1415629c8", "0x1415634bc",
    "0x1415634e6", "0x141563556", "0x14156355f", "0x141563580", "0x141563658",
    "0x1415636ea", "0x1415636f2", "0x14156494d", "0x141564a96", "0x141564a9f",
    "0x141564add", "0x141564ae8", "0x141565fa2", "0x141566053", "0x1415691ed",
    "0x1415691f3",
}
SSO_15B_VAS = {"0x141561fe0", "0x141561e07", "0x141561fd6", "0x141561fe9"}
IMM7_MAX_VAS = {"0x14156063a", "0x141560650", "0x141562968", "0x141565fb2"}
MIN_16B_VAS = {"0x141560650", "0x14156ae4c", "0x14156ae61", "0x14156ae90", "0x14156ae79"}
EXACT_MAX_LIMITS = {
    "0x14149c350": 54,
    "0x14154a31a": 20,
    "0x14154a376": 30,
    "0x14154a390": 30,
    "0x141562968": 37,
}


def fmt_tokens(s: str) -> list[str]:
    return [t for t in FMT_RE.findall(s) if t != "%%"]


def imgui_suffix(s: str) -> str:
    for sep in ("###", "##"):
        idx = s.find(sep)
        if idx != -1:
            return s[idx:]
    return ""


def validate_doc(doc: dict, template: dict, name: str) -> list[str]:
    errs: list[str] = []

    if not doc.get("meta", {}).get("code"):
        errs.append(f"{name}: missing meta.code")

    for k in ("yes", "no"):
        item = doc.get("inline_literals", {}).get(k)
        if not item or not isinstance(item.get("text"), str):
            errs.append(f"{name}: missing inline_literals.{k}.text")
        else:
            bl = len(item["text"].encode("utf-8"))
            if not (1 <= bl <= 7):
                errs.append(f"{name}: inline_literals.{k} '{item['text']}' is {bl}B (must be 1..7 UTF-8 bytes)")

    for k, tmpl in template["simd_strings"].items():
        item = doc.get("simd_strings", {}).get(k)
        if not item or not isinstance(item.get("text"), str):
            errs.append(f"{name}: missing simd_strings.{k}.text")
        else:
            bl = len(item["text"].encode("utf-8"))
            mx = tmpl["max_bytes"]
            if not (1 <= bl <= mx):
                errs.append(f"{name}: simd_strings.{k} is {bl}B (max {mx} UTF-8 bytes)")

    if len(doc.get("graphics_presets", [])) != 4:
        errs.append(f"{name}: graphics_presets must have 4 entries")
    if len(doc.get("shop_sections", [])) != 5:
        errs.append(f"{name}: shop_sections must have 5 entries")

    for va, tmpl in template["exe_strings"].items():
        entry = doc.get("exe_strings", {}).get(va)
        if not entry or not isinstance(entry.get("text"), str):
            errs.append(f"{name}: missing exe_strings.{va}")
            continue
        txt = entry["text"]
        en = tmpl["en"]
        if fmt_tokens(en) != fmt_tokens(txt):
            errs.append(f"{name}: exe_strings.{va} format mismatch: {fmt_tokens(en)} vs {fmt_tokens(txt)}")
        if imgui_suffix(en) != imgui_suffix(txt):
            errs.append(f"{name}: exe_strings.{va} ImGui ## suffix mismatch")
        bl = len(txt.encode("utf-8"))
        if va in BUTTON_31B_VAS and bl > 31:
            errs.append(f"{name}: button exe_strings.{va} ({txt!r}) is {bl}B > 31B max")
        if va in SSO_15B_VAS and bl > 15:
            errs.append(f"{name}: SSO exe_strings.{va} ({txt!r}) is {bl}B > 15B max")
        if va in IMM7_MAX_VAS and bl > 127:
            errs.append(f"{name}: imm8 exe_strings.{va} is {bl}B > 127B max")
        if va in MIN_16B_VAS and bl < 16:
            errs.append(f"{name}: heap exe_strings.{va} ({txt!r}) is {bl}B < 16B min")
        if va in EXACT_MAX_LIMITS and bl > EXACT_MAX_LIMITS[va]:
            errs.append(f"{name}: exe_strings.{va} ({txt!r}) is {bl}B > {EXACT_MAX_LIMITS[va]}B max")

    for sec in ("controls", "free_cam", "look_around", "vehicle_tabs", "extra_ui"):
        tsec = template["table_strings"][sec]
        dsec = doc.get("table_strings", {}).get(sec, {})
        for k in tsec:
            if k not in dsec or not isinstance(dsec[k].get("text"), str):
                errs.append(f"{name}: missing table_strings.{sec}.{k}")

    for k in template["table_strings"]["machine_display"]:
        md = doc.get("table_strings", {}).get("machine_display", {}).get(k, {})
        if not isinstance(md.get("full"), str) or not isinstance(md.get("short"), str):
            errs.append(f"{name}: missing table_strings.machine_display.{k}.full/short")

    for k in template["table_strings"]["editor"]:
        if not isinstance(doc.get("table_strings", {}).get("editor", {}).get(k), str):
            errs.append(f"{name}: missing table_strings.editor[{k!r}]")

    for fname, rules in template["pack_toml"].items():
        drules = doc.get("pack_toml", {}).get(fname, [])
        if len(drules) != len(rules):
            errs.append(f"{name}: pack_toml.{fname} expected {len(rules)} rules, got {len(drules)}")
            continue
        for idx, (tr, dr) in enumerate(zip(rules, drules)):
            if dr.get("old") != tr["old"] or not isinstance(dr.get("new"), str):
                errs.append(f"{name}: pack_toml.{fname}[{idx}] modified 'old' key or missing 'new'")
            elif fmt_tokens(tr["old"]) != fmt_tokens(dr["new"]):
                errs.append(f"{name}: pack_toml.{fname}[{idx}] format mismatch")

    return errs


def main() -> int:
    tdir = ROOT_DIR / "translations"
    tmpl_path = tdir / "template.json"
    template = json.loads(tmpl_path.read_text("utf-8"))

    targets = [tdir / f"{arg}.json" if not arg.endswith(".json") else Path(arg) for arg in sys.argv[1:]]
    if not targets:
        targets = sorted(p for p in tdir.glob("*.json") if p.name != "template.json")

    all_errs: list[str] = []
    for p in targets:
        doc = json.loads(p.read_text("utf-8"))
        errs = validate_doc(doc, template, p.name)
        if errs:
            all_errs.extend(errs)
        else:
            print(f"Validated {p.name}: OK ({len(doc['exe_strings'])} exe strings, {sum(len(v) for v in doc['pack_toml'].values())} TOML rules)")

    if all_errs:
        for e in all_errs:
            print("ERROR:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
