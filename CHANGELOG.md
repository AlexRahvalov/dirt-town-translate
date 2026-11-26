# Changelog

All notable changes to **Dirt Town Demo — Multi-Language Localization Plugin** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [1.5.1] - 2026-11-26

- **Fix**: Translated the initial splash screen `loading` badge (`0x14149ac60`, `0x1402433c2` / `0x140244ed2` / `0x140244ee2`) across all 8 non-English locales.

## [1.5.0] - 2026-11-26

- **Feat**: Added 3 new full translations — **Belarusian (`be`)**, **Ukrainian (`uk`)**, and **Polish (`pl`)** — bringing total supported languages to **9** (`en`, `ru`, `be`, `uk`, `pl`, `zh-cn`, `es`, `de`, `pt-br`), all with live hot-swap support.
- **Docs**: Added localized READMEs (`README.be.md`, `README.uk.md`, `README.pl.md`) and updated the language switcher across all 9 READMEs.

## [1.4.0] - 2026-11-26

- **Feat**: Added 4 new full translations — **Simplified Chinese (`zh-cn`)**, **Spanish (`es`)**, **German (`de`)**, and **Brazilian Portuguese (`pt-br`)** — alongside English (`en`) and Russian (`ru`) (6 languages total).
- **Feat**: Configured Windows Microsoft YaHei (`msyh.ttc` / `msyhbd.ttc`) font redirects for `zh-cn` so Dear ImGui 1.92.9 renders CJK glyphs cleanly.
- **Feat**: Translated all in-game coupler, Q-Lock, winch, shackle, brake, and neutral interact prompts (`0x14155f1ca..0x14155f3fc`), attachment names (`bucket`, `plow`, `flipper bucket`, `pallet forks`, `jib`), and `Debug dump`.
- **Feat**: Translated dynamic respawn hint (`Press <key> to respawn` / `Bind Respawn in Controls`) via `std::string` builder patch at `0x140c738c0`.
- **Fix**: Removed hardcoded Russian site name assertion in `verify_plugin.py` so offline verification passes for all locales.
- **Docs**: Added localized READMEs (`README.md`, `README.ru.md`, `README.zh-CN.md`, `README.es.md`, `README.de.md`, `README.pt-BR.md`) with a language switcher header.
- **CI**: Switched GitHub Releases to publish release notes directly from `CHANGELOG.md`.

## [1.3.1] - 2026-11-25

- **Fix**: Corrected `ImGui::PopID` RVA (`0x11798F0`) in `version.dll` to eliminate the `Missing PopID()` Dear ImGui warning in the Settings window.

## [1.3.0] - 2026-11-25

- **Feat**: Added live hot-swap `< Language >` carousel in Settings — switching between Latin/Cyrillic languages updates UI text immediately without restarting the game.
- **Fix**: Fixed HUD machine title bar byte-by-byte loop (`0x140cb329b..0x140cb33de`) that split multi-byte UTF-8 characters into broken 1-byte chunks, and translated `pick`.

## [1.2.0] - 2026-11-25

- **Feat**: Added in-game language switcher UI in the Settings menu (`version.dll`).

## [1.1.1] - 2026-11-25

- **Chore**: Renamed release archive to `DirtTownDemo-Locale-Plugin.zip`.

## [1.1.0] - 2026-11-25

- **Feat**: Added declarative `translations/template.json` & `translations/ru.json` format and offline `validate_translations.py` validator for community languages.

## [1.0.0] - 2026-11-25

- **Feat**: Initial release of the non-invasive `version.dll` runtime localization plugin and direct patcher scripts for Dirt Town Demo (build `ed45b4be7fc6`).
- **CI**: Automated x64 MSVC build and GitHub Release packaging via GitHub Actions.
