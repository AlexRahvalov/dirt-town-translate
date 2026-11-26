**English** | [Русский](README.ru.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Multi-Language Localization Plugin

Runtime localization plugin and patcher for **Dirt Town Demo** (Steam build `ed45b4be7fc6`, Windows x64).

## Supported Languages

| Language | Code | Translation File | Notes |
|---|---|---|---|
| **English** | `en` | Built-in original | Instant hot-swap |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Instant hot-swap (`Roboto` + `cour.ttf`) |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Uses Windows `msyh.ttc` / `msyhbd.ttc` (restart required when switching to/from CJK) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Instant hot-swap |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Instant hot-swap |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Instant hot-swap |

---

## Option 1 (Recommended): Runtime Plugin `version.dll` — No Game File Edits

Game files (`dirttown.exe` and `data.pack`) are **never modified on disk**:
- Windows loads `version.dll` automatically alongside `dirttown.exe` and forwards system calls to `System32\version.dll`.
- Translated strings are allocated in RAM (`VirtualAlloc` within ±1 GB of the module) and patched into `RIP`-relative LEAs and `.rdata` tables at runtime.
- A hook on the `DIGP` pack reader patches TOML assets in memory (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, preserving the `811034dce06dee68` save stamp) and redirects fonts for Unicode/CJK support.

### Installation (for players)
1. Download `DirtTownDemo-Locale-Plugin.zip` from **Releases** (or **Actions**).
2. Extract `version.dll` and the `locales/` folder into the game directory next to `dirttown.exe`.
3. Choose your language **directly in-game in Settings** (`< Language >` switcher at the bottom of the Settings window).
   - Latin and Cyrillic languages (`en`, `ru`, `es`, `de`, `pt-br`) switch **live without restarting** (shop/map descriptions update on restart).
   - For **Simplified Chinese (`zh-cn`)**, select it and **restart the game** so Windows CJK fonts (`msyh.ttc` / `msyhbd.ttc`) load at startup.
   - You can also set the language manually in `locales/lang.ini`:
     ```ini
     active=en   # en | ru | zh-cn | es | de | pt-br
     ```
4. To uninstall completely: delete `version.dll` and the `locales/` folder.

### Building `version.dll`
- GitHub Actions workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) validates all `translations/*.json`, builds x64 `version.dll` via MSVC, and packages `DirtTownDemo-Locale-Plugin.zip` with all locales from `locales/`.
- Local build (requires VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Adding or Editing a Language (no C++ or DLL rebuild needed)
1. Copy `translations/template.json` → `translations/<code>.json` (e.g. `translations/fr.json`).
2. Translate `"text"` values (and `"new"` in `pack_toml`). Adjust `font_redirects` if your script needs custom or system Windows fonts (or place font files in `locales/<code>/override/fonts/`).
3. Validate format specifiers (`%d`, `%zu`, `{}`), ImGui suffixes, and PE byte limits (works without game files):
   ```powershell
   python validate_translations.py <code>
   ```
4. Build and verify `locales/<code>/exe_patch.dtloc` and `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <code> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <code> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Copy `locales/<code>/` next to `version.dll` or submit a Pull Request.

---

## Option 2: Direct File Patcher (`install.py`)

To patch `dirttown.exe` and `data.pack` directly on disk without `version.dll`:
```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Restore original files from `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Project Structure
- `plugin/` — Proxy DLL source (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — Declarative JSON translations (`template.json`, `ru.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — Compiled plugin locale packs (`lang.ini`, `<code>/exe_patch.dtloc`, `<code>/pack_patches.dtpk`, `<code>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — Template exporter and offline JSON validator.
- `build_plugin.py` / `verify_plugin.py` — Plugin pack builder and offline verifier.
- `loc_strings.py` / `pack_rules.py` — Source UI & TOML string tables.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — Direct disk patcher scripts.
