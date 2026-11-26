[English](README.md) | [Русский](README.ru.md) | [Беларуская](README.be.md) | [Українська](README.uk.md) | [Polski](README.pl.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | **Deutsch** | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Mehrsprachiges Lokalisierungs-Plugin

Runtime-Lokalisierungs-Plugin und Patcher für **Dirt Town Demo** (Steam-Build `ed45b4be7fc6`, Windows x64).

## Unterstützte Sprachen

| Sprache | Code | Übersetzungsdatei | Hinweise |
|---|---|---|---|
| **English** | `en` | Integriertes Original | Live-Wechsel |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Live-Wechsel (`Roboto` + `cour.ttf`) |
| **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | Live-Wechsel |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | Live-Wechsel |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | Live-Wechsel |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Nutzt Windows-Schriften `msyh.ttc` / `msyhbd.ttc` (Neustart nach Wechsel auf CJK erforderlich) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Live-Wechsel |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Live-Wechsel |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Live-Wechsel |

---

## Option 1 (empfohlen): Runtime-Plugin `version.dll` — Keine Änderungen an Spieldateien

Die Spieldateien (`dirttown.exe` und `data.pack`) werden **auf der Festplatte nicht verändert**:
- Windows lädt `version.dll` automatisch neben `dirttown.exe` und leitet Systemaufrufe an `System32\version.dll` weiter.
- Übersetzte Zeichenketten werden im Arbeitsspeicher (`VirtualAlloc` innerhalb ±1 GB vom Modul) abgelegt und zur Laufzeit in `RIP`-relative LEAs sowie `.rdata`-Tabellen eingetragen.
- Ein Hook im `DIGP`-Paketleser ersetzt TOML-Dateien im Speicher (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, unter Beibehaltung des Spielstand-Stempels `811034dce06dee68`) und leitet Schriftarten für Unicode/CJK um.

### Installation (für Spieler)
1. Lade `DirtTownDemo-Locale-Plugin.zip` aus **Releases** (oder **Actions**) herunter.
2. Entpacke `version.dll` und den Ordner `locales/` in den Spielordner neben `dirttown.exe`.
3. Wähle die Sprache **direkt in den Spieleinstellungen** (`< Sprache >`-Umschalter unten im Einstellungsfenster).
   - Lateinische und kyrillische Sprachen (`en`, `ru`, `es`, `de`, `pt-br`) wechseln **sofort ohne Neustart** (Shop- und Kartenbeschreibungen aktualisieren sich nach einem Neustart).
   - Für **Vereinfachtes Chinesisch (`zh-cn`)** die Sprache wählen und das **Spiel neu starten**, damit die Windows-CJK-Schriften (`msyh.ttc` / `msyhbd.ttc`) beim Start geladen werden.
   - Alternativ manuell in `locales/lang.ini` setzen:
     ```ini
     active=de   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. Vollständige Deinstallation: einfach `version.dll` und den Ordner `locales/` löschen.

### `version.dll` kompilieren
- Der GitHub-Actions-Workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) prüft alle `translations/*.json`, baut x64 `version.dll` mit MSVC und packt `DirtTownDemo-Locale-Plugin.zip` mit allen Sprachen aus `locales/`.
- Lokal bauen (VS Build Tools / CMake erforderlich):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Neue Sprache hinzufügen oder bearbeiten (ohne Neukompilierung von `version.dll`)
1. Kopiere `translations/template.json` → `translations/<Code>.json` (z. B. `translations/fr.json`).
2. Übersetze die `"text"`-Werte (und `"new"` unter `pack_toml`). Passe bei Bedarf `font_redirects` an oder lege eigene Schriften in `locales/<Code>/override/fonts/` ab.
3. Prüfe Format-Platzhalter (`%d`, `%zu`, `{}`), ImGui-Suffixe und PE-Bytegrenzen (funktioniert ohne Spieldateien):
   ```powershell
   python validate_translations.py <Code>
   ```
4. Erstelle und prüfe `locales/<Code>/exe_patch.dtloc` und `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <Code> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <Code> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Kopiere `locales/<Code>/` neben `version.dll` oder reiche einen Pull Request ein.

---

## Option 2: Direkter Datei-Patcher (`install.py`)

Um `dirttown.exe` und `data.pack` direkt auf der Festplatte ohne `version.dll` zu patchen:
```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Originaldateien aus `backup_en/` wiederherstellen:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Projektstruktur
- `plugin/` — Quellcode der Proxy-DLL (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — Deklarative JSON-Übersetzungen (`template.json`, `ru.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — Kompilierte Sprachpakete (`lang.ini`, `<Code>/exe_patch.dtloc`, `<Code>/pack_patches.dtpk`, `<Code>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — Vorlagen-Export und Offline-JSON-Validator.
- `build_plugin.py` / `verify_plugin.py` — Generator und Offline-Prüfskript für Sprachpakete.
- `loc_strings.py` / `pack_rules.py` — Basis-Wörterbücher für UI und TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — Skripte zum direkten Festplatten-Patch.
