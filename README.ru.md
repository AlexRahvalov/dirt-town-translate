[English](README.md) | **Русский** | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Мультиязычный плагин локализации

Runtime-плагин локализации и патчер для **Dirt Town Demo** (Steam build `ed45b4be7fc6`, Windows x64).

## Поддерживаемые языки

| Язык | Код | Файл перевода | Примечания |
|---|---|---|---|
| **English** | `en` | Встроенный оригинал | Мгновенное переключение |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Мгновенное переключение (`Roboto` + `cour.ttf`) |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Системные шрифты `msyh.ttc` / `msyhbd.ttc` (нужен перезапуск для загрузки CJK-шрифтов) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Мгновенное переключение |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Мгновенное переключение |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Мгновенное переключение |

---

## Вариант 1 (рекомендуемый): Runtime-плагин `version.dll` — без правки файлов игры

Файлы игры (`dirttown.exe` и `data.pack`) **не модифицируются на диске**:
- `version.dll` загружается Windows автоматически рядом с `dirttown.exe` и пробрасывает системные вызовы в `System32\version.dll`.
- В оперативной памяти (`VirtualAlloc` в пределах ±1 ГБ от модуля) размещаются переведённые строки, патчатся `RIP`-LEA и таблицы `.rdata`.
- Хук чтения `DIGP`-ресурсов подменяет в памяти переводы TOML-файлов (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, с сохранением штампа `811034dce06dee68` для старых сейвов) и подключает шрифты с поддержкой кириллицы/CJK.

### Установка плагина (для игроков)
1. Скачайте готовый архив `DirtTownDemo-Locale-Plugin.zip` из **Releases** (или **Actions**).
2. Распакуйте `version.dll` и папку `locales/` в папку с игрой рядом с `dirttown.exe`.
3. Выбор языка — **прямо в настройках игры** (переключатель `< Язык >` внизу окна настроек).
   - Латиница и кириллица (`en`, `ru`, `es`, `de`, `pt-br`) переключаются **на лету без перезапуска** (описания техники и карты обновляются после перезапуска).
   - Для **упрощённого китайского (`zh-cn`)** выберите его и **перезапустите игру**, чтобы при старте загрузились системные CJK-шрифты (`msyh.ttc` / `msyhbd.ttc`).
   - Также язык можно задать вручную в `locales/lang.ini`:
     ```ini
     active=ru   # en | ru | zh-cn | es | de | pt-br
     ```
4. Полное удаление: просто удалите `version.dll` и папку `locales/`.

### Сборка `version.dll`
- На GitHub настроен workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) (проверяет переводы в `translations/*.json`, собирает x64 `version.dll` через MSVC и упаковывает `DirtTownDemo-Locale-Plugin.zip` со всеми языками из `locales/`).
- Локально (при наличии VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Как добавить или отредактировать язык (без перекомпиляции `version.dll`)
1. Скопируйте `translations/template.json` → `translations/<код>.json` (например `translations/fr.json`).
2. Переведите значения `"text"` (и `"new"` в разделе `pack_toml`). В `font_redirects` при необходимости укажите системный или кастомный шрифт (или положите файлы в `locales/<код>/override/fonts/`).
3. Проверьте файл перевода на формат-спецификаторы (`%d`, `%zu`, `{}`), суффиксы ImGui и байтовые лимиты (работает без файлов игры):
   ```powershell
   python validate_translations.py <код>
   ```
4. Соберите и проверьте `locales/<код>/exe_patch.dtloc` и `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <код> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <код> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Скопируйте `locales/<код>/` рядом с `version.dll` или отправьте Pull Request.

---

## Вариант 2: Прямой патчер файлов игры (`install.py`)

Если нужно пропатчить `dirttown.exe` и `data.pack` напрямую на диске без `version.dll`:
```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Откат к оригинальным файлам из `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Структура проекта
- `plugin/` — исходники прокси-DLL (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — декларативные JSON-переводы (`template.json`, `ru.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — собранные языковые пакеты (`lang.ini`, `<код>/exe_patch.dtloc`, `<код>/pack_patches.dtpk`, `<код>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — экспорт шаблона и оффлайн-валидатор JSON-переводов.
- `build_plugin.py` / `verify_plugin.py` — генератор и оффлайн-валидатор файлов плагина.
- `loc_strings.py` / `pack_rules.py` — словари перевода интерфейса и TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — скрипты прямого патча файлов игры.
