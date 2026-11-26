"""Export translations/template.json and translations/ru.json from loc_strings.py and pack_rules.py."""

import json
from pathlib import Path

from common import ROOT_DIR
from loc_strings import (
    CONTROLS_PTR_TRANSLATIONS,
    EDITOR_STR_PTR_MAP,
    EXTRA_UI_PTR_TABLES,
    FREE_CAM_PTR_TRANSLATIONS,
    GRAPHICS_PRESET_UI,
    LOOK_AROUND_PTR_TRANSLATIONS,
    MACHINE_DISPLAY_ROWS,
    SHOP_SECTIONS_UI,
    STRING_PATCHES,
    VEHICLE_TAB_PTR_TRANSLATIONS,
)
from pack_rules import DEMO2_REPL, FONT_REDIRECTS, KEY_LAYOUT_REPL, PAD_LAYOUT_REPL, SHOP_REPL

SIMD_DEFS = {
    "clear_pad_26b": {
        "en": "clear the pad for the crew",
        "ru": "очистить зону.",
        "max_bytes": 26,
    },
    "seat_37b": {
        "en": "step out of the seat to take delivery",
        "ru": "сначала нужно выйти!",
        "max_bytes": 37,
    },
    "flat_51b": {
        "en": "there is no flat ground nearby for the delivery.",
        "ru": "тут нет ровного места рядом.",
        "max_bytes": 51,
    },
    "dealer_46b": {
        "en": "the dealer has none of those left on the lot",
        "ru": "этой техники нет у дилера",
        "max_bytes": 46,
    },
    "item_31b": {
        "en": "the item is no longer installed",
        "ru": "объект не найден.",
        "max_bytes": 31,
    },
}


def build_doc(use_russian: bool) -> dict:
    def pick(en: str, ru: str) -> str:
        return ru if use_russian else en

    # NOTE: demo2.toml site.accepts is technical compatibility metadata, kept verbatim in pack_toml_static
    doc = {
        "meta": {
            "code": "ru" if use_russian else "template",
            "name": "Русский" if use_russian else "English (Template)",
            "game_build": "ed45b4be7fc6",
            "version": 1,
        },
        "inline_literals": {
            "yes": {"en": "yes", "text": pick("yes", "да"), "max_bytes": 7},
            "no": {"en": "no", "text": pick("no", "нет"), "max_bytes": 7},
            "bucket": {"en": "bucket", "text": pick("bucket", "ковш"), "max_bytes": 15},
            "plow": {"en": "plow", "text": pick("plow", "отвал"), "max_bytes": 15},
            "jib": {"en": "jib", "text": pick("jib", "гусёк"), "max_bytes": 15},
            "flipper_bucket": {"en": "flipper bucket", "text": pick("flipper bucket", "перекид."), "max_bytes": 15},
            "pallet_forks": {"en": "pallet forks", "text": pick("pallet forks", "вилы"), "max_bytes": 15},
            "respawn_prefix": {"en": "Press ", "text": pick("Press ", "Нажмите "), "max_bytes": 60},
            "respawn_suffix": {"en": " to respawn", "text": pick(" to respawn", " для возрождения"), "max_bytes": 60},
            "respawn_bind": {"en": "Bind Respawn in Controls", "text": pick("Bind Respawn in Controls", "Назначьте Возрождение в Управлении"), "max_bytes": 90},
        },
        "simd_strings": {
            k: {"en": v["en"], "text": pick(v["en"], v["ru"]), "max_bytes": v["max_bytes"]}
            for k, v in SIMD_DEFS.items()
        },
        "font_redirects": [
            {"pack_key": k, "kind": kind, "target": tgt}
            for k, kind, tgt in FONT_REDIRECTS
        ],
        "graphics_presets": GRAPHICS_PRESET_UI if use_russian else ["low", "medium", "high", "ultra"],
        "shop_sections": SHOP_SECTIONS_UI if use_russian else ["Loaders", "Earthmoving", "Haulage", "Farm", "Getting about"],
        "exe_strings": {
            hex(va): {"en": en, "text": pick(en, ru)}
            for va, (en, ru, _) in STRING_PATCHES.items()
        },
        "table_strings": {
            "controls": {
                hex(va): {"en": en, "text": pick(en, ru)}
                for va, (en, ru) in CONTROLS_PTR_TRANSLATIONS.items()
            },
            "free_cam": {
                hex(va): {"en": en, "text": pick(en, ru)}
                for va, (en, ru) in FREE_CAM_PTR_TRANSLATIONS.items()
            },
            "look_around": {
                hex(va): {"en": en, "text": pick(en, ru)}
                for va, (en, ru) in LOOK_AROUND_PTR_TRANSLATIONS.items()
            },
            "vehicle_tabs": {
                hex(va): {"en": en, "text": pick(en, ru)}
                for va, (en, ru) in VEHICLE_TAB_PTR_TRANSLATIONS.items()
            },
            "machine_display": {
                hex(row_va): {
                    "full_en": full_en,
                    "full": pick(full_en, full_ru),
                    "short_en": short_en,
                    "short": pick(short_en, short_ru),
                }
                for row_va, full_en, full_ru, short_en, short_ru in MACHINE_DISPLAY_ROWS
            },
            "editor": {
                en: pick(en, ru)
                for en, ru in EDITOR_STR_PTR_MAP.items()
            },
            "extra_ui": {
                hex(pva): {"en": en, "text": pick(en, ru)}
                for pva, _, en, ru in EXTRA_UI_PTR_TABLES
            },
        },
        "pack_toml": {
            "shop.toml": [{"old": o, "new": o if not use_russian else n} for o, n in SHOP_REPL],
            "key_layouts.toml": [{"old": o, "new": o if not use_russian else n} for o, n in KEY_LAYOUT_REPL],
            "pad_layouts.toml": [{"old": o, "new": o if not use_russian else n} for o, n in PAD_LAYOUT_REPL],
            "sites/demo2/demo2.toml": [
                {"old": o, "new": n if (use_russian or o.startswith("accepts =")) else o}
                for o, n in DEMO2_REPL
            ],
        },
    }
    return doc


def main() -> None:
    out_dir = ROOT_DIR / "translations"
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, is_ru in [("template.json", False), ("ru.json", True)]:
        p = out_dir / fname
        p.write_text(json.dumps(build_doc(is_ru), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
