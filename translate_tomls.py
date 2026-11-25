import tomllib

from common import OVERRIDES_DIR as out_dir
from common import UNPACKED_DIR as unpacked
from pack_rules import PACK_TOML_PATCHES


def replace_checked(text: str, replacements: list[tuple[str, str]], label: str) -> str:
    for old, new in replacements:
        cnt = text.count(old)
        assert cnt >= 1, f"{label}: missing expected literal: {old!r}"
        text = text.replace(old, new)
    return text


def main() -> None:
    parsed = {}
    for rel_path, rules in PACK_TOML_PATCHES:
        src = (unpacked / rel_path).read_text("utf-8")
        dst = replace_checked(src, rules, rel_path)
        dst_file = out_dir / rel_path
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_text(dst, encoding="utf-8")
        parsed[rel_path] = tomllib.loads(dst)

    demo = parsed["sites/demo2/demo2.toml"]
    assert demo["name"] == "Цветочный холм"
    assert demo["site"]["byline"] == "Демо-карта"
    assert demo["mission"]["title"] == "Перевозка песка и не только"
    assert "811034dce06dee68" in demo["site"]["accepts"]
    print(f"All {len(PACK_TOML_PATCHES)} TOML files translated & validated via tomllib cleanly!")


if __name__ == "__main__":
    main()
