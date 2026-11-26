[English](README.md) | [Русский](README.ru.md) | [Беларуская](README.be.md) | [Українська](README.uk.md) | **Polski** | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Wielojęzyczna wtyczka lokalizacyjna

Wtyczka lokalizacyjna w czasie rzeczywistym i patcher dla **Dirt Town Demo** (kompilacja Steam `ed45b4be7fc6`, Windows x64).

## Obsługiwane języki

| Język | Kod | Plik tłumaczenia | Uwagi |
|---|---|---|---|
| **English** | `en` | Wbudowany oryginał | Przełączanie na żywo |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Przełączanie na żywo |
| **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | Przełączanie na żywo |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | Przełączanie na żywo |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | Przełączanie na żywo |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Czcionki systemowe `msyh.ttc` / `msyhbd.ttc` (wymaga restartu dla CJK) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Przełączanie na żywo |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Przełączanie na żywo |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Przełączanie na żywo |

---

## Opcja 1 (zalecana): Wtyczka `version.dll` — bez modyfikacji plików gry

Pliki gry (`dirttown.exe` i `data.pack`) **nie są zmieniane na dysku**:
- Windows automatycznie ładuje `version.dll` obok `dirttown.exe` i przekazuje wywołania systemowe do `System32\version.dll`.
- Przetłumaczone teksty są alokowane w pamięci RAM (`VirtualAlloc` w zakresie ±1 GB od modułu) i podmieniane w instrukcjach `RIP`-LEA oraz tablicach `.rdata`.
- Hook odczytu zasobów `DIGP` podmienia w locie pliki TOML (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, zachowując znacznik zapisów `811034dce06dee68`) i przekierowuje czcionki dla obsługi Unicode/CJK.

### Instalacja (dla graczy)
1. Pobierz `DirtTownDemo-Locale-Plugin.zip` z **Releases** (lub **Actions**).
2. Rozpakuj `version.dll` oraz folder `locales/` do katalogu gry obok `dirttown.exe`.
3. Wybierz język **bezpośrednio w Ustawieniach gry** (przełącznik `< Język >` u dołu okna ustawień).
   - Języki łacińskie i cyrylica (`en`, `ru`, `be`, `uk`, `pl`, `es`, `de`, `pt-br`) przełączają się **na żywo bez restartu** (opisy maszyn i mapy odświeżają się po restarcie).
   - Dla **chińskiego uproszczonego (`zh-cn`)** wybierz język i **zrestartuj grę**, aby załadować systemowe czcionki CJK (`msyh.ttc` / `msyhbd.ttc`).
   - Język można też ustawić ręcznie w `locales/lang.ini`:
     ```ini
     active=pl   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. Pełne odinstalowanie: usuń `version.dll` oraz folder `locales/`.

### Kompilacja `version.dll`
- Workflow GitHub Actions [`.github/workflows/build.yml`](.github/workflows/build.yml) waliduje wszystkie `translations/*.json`, buduje x64 `version.dll` przez MSVC i pakuje `DirtTownDemo-Locale-Plugin.zip`.
- Kompilacja lokalna (VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Jak dodać lub edytować język (bez rekompilacji `version.dll`)
1. Skopiuj `translations/template.json` → `translations/<kod>.json`.
2. Przetłumacz wartości `"text"` (oraz `"new"` w `pack_toml`).
3. Zweryfikuj specyfikatory formatu i limity bajtów:
   ```powershell
   python validate_translations.py <kod>
   ```
4. Zbuduj i sprawdź `locales/<kod>/exe_patch.dtloc` oraz `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <kod> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <kod> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Skopiuj `locales/<kod>/` obok `version.dll` lub wyślij Pull Request.

---

## Opcja 2: Bezpośredni patcher plików na dysku (`install.py`)

```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Przywracanie oryginałów z `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Struktura projektu
- `plugin/` — kod źródłowy proxy DLL (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — deklaratywne tłumaczenia JSON (`template.json`, `ru.json`, `be.json`, `uk.json`, `pl.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — skompilowane pakiety językowe (`lang.ini`, `<kod>/exe_patch.dtloc`, `<kod>/pack_patches.dtpk`, `<kod>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — eksport szablonu i walidator JSON offline.
- `build_plugin.py` / `verify_plugin.py` — generator i weryfikator offline pakietów wtyczki.
- `loc_strings.py` / `pack_rules.py` — bazowe słowniki interfejsu i TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — skrypty bezpośredniego patchowania dysku.
