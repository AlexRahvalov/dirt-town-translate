[English](README.md) | [Русский](README.ru.md) | **Беларуская** | [Українська](README.uk.md) | [Polski](README.pl.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Шматмоўны плагін лакалізацыі

Runtime-плагін лакалізацыі і патчар для **Dirt Town Demo** (Steam build `ed45b4be7fc6`, Windows x64).

## Падтрыманыя мовы

| Мова | Код | Файл перакладу | Заўвагі |
|---|---|---|---|
| **English** | `en` | Убудаваны арыгінал | Імгненнае пераключэнне |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Імгненнае пераключэнне |
| **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | Імгненнае пераключэнне |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | Імгненнае пераключэнне |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | Імгненнае пераключэнне |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Сістэмныя шрыфты `msyh.ttc` / `msyhbd.ttc` (патрэбны перазапуск для CJK) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Імгненнае пераключэнне |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Імгненнае пераключэнне |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Імгненнае пераключэнне |

---

## Варыянт 1 (рэкамендаваны): Runtime-плагін `version.dll` — без змены файлаў гульні

Файлы гульні (`dirttown.exe` і `data.pack`) **не мадыфікуюцца на дыску**:
- `version.dll` загружаецца Windows аўтаматычна побач з `dirttown.exe` і перанакіроўвае сістэмныя выклікі ў `System32\version.dll`.
- У аператыўнай памяці (`VirtualAlloc` у межах ±1 ГБ ад модуля) размяшчаюцца перакладзеныя радкі, патчацца `RIP`-LEA і табліцы `.rdata`.
- Хук чытання `DIGP`-рэсурсаў падмяняе ў памяці TOML-файлы (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, захоўваючы штамп сейваў `811034dce06dee68`) і падключае шрыфты Unicode/CJK.

### Усталяванне (для гульцоў)
1. Спампуйце `DirtTownDemo-Locale-Plugin.zip` з **Releases** (або **Actions**).
2. Распакуйце `version.dll` і папку `locales/` у папку з гульнёй побач з `dirttown.exe`.
3. Абярыце мову **непасрэдна ў Наладах гульні** (пераключальнік `< Мова >` унізе акна налад).
   - Лацініца і кірыліца (`en`, `ru`, `be`, `uk`, `pl`, `es`, `de`, `pt-br`) пераключаюцца **на ляту без перазапуску** (апісанні тэхнікі і карты абнаўляюцца пасля перазапуску).
   - Для **спрошчанай кітайскай (`zh-cn`)** абярыце яе і **перазапусціце гульню**, каб загрузіліся сістэмныя CJK-шрыфты (`msyh.ttc` / `msyhbd.ttc`).
   - Таксама мову можна задаць уручную ў `locales/lang.ini`:
     ```ini
     active=be   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. Поўнае выдаленне: проста выдаліце `version.dll` і папку `locales/`.

### Зборка `version.dll`
- GitHub Actions workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) правярае ўсе `translations/*.json`, збірае x64 `version.dll` праз MSVC і пакуе `DirtTownDemo-Locale-Plugin.zip`.
- Лакальная зборка (VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Як дадаць або адрэдагаваць мову (без перакампіляцыі `version.dll`)
1. Скапіруйце `translations/template.json` → `translations/<код>.json`.
2. Перакладзіце значэнні `"text"` (і `"new"` у `pack_toml`).
3. Праверце фарматныя спецыфікатары і байтавыя ліміты:
   ```powershell
   python validate_translations.py <код>
   ```
4. Збярыце і праверце `locales/<код>/exe_patch.dtloc` і `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <код> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <код> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Скапіруйце `locales/<код>/` побач з `version.dll` або адпраўце Pull Request.

---

## Варыянт 2: Прамы патчар файлаў гульні (`install.py`)

```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Адкат з `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Структура праекта
- `plugin/` — зыходнікі проксі-DLL (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — дэкларатыўныя JSON-пераклады (`template.json`, `ru.json`, `be.json`, `uk.json`, `pl.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — сабраныя моўныя пакеты (`lang.ini`, `<код>/exe_patch.dtloc`, `<код>/pack_patches.dtpk`, `<код>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — экспарт шаблона і афлайн-валідатар JSON.
- `build_plugin.py` / `verify_plugin.py` — генератар і афлайн-верыфікатар пакетаў плагіна.
- `loc_strings.py` / `pack_rules.py` — слоўнікі інтэрфейсу і TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — скрыпты прамога патча файлаў гульні.
