# Dirt Town Demo — Русификатор (Russian Localization)

Инструментарий для полной локализации **Dirt Town Demo** (Steam build `ed45b4be7fc6`, Windows x64) на русский язык.

## Что переводится
- Исполняемый файл `dirttown.exe`: добавляется PE-секция `.loc` с русскими строками (главное меню, настройки, магазин, управление, подсказки на экране, редактор участков, названия техники, предупреждения), патчатся `RIP`-относительные адреса, таблицы указателей, длины коротких/SSO-строк и `IMAGE_REL_BASED_DIR64` релокации в `.reloc` для корректной работы под ASLR.
- Ресурсы `data.pack` (формат `DIGP`):
  - `shop.toml` — названия, разделы, характеристики и описания техники;
  - `key_layouts.toml` и `pad_layouts.toml` — названия и описания раскладок;
  - `sites/demo2/demo2.toml` — название карты, задания, диалоги и совместимость сохранёнок оригинальной английской карты (`site.accepts` включает штамп `811034dce06dee68`).
- Шрифты с поддержкой кириллицы:
  - `Roboto-Medium.ttf` / `Roboto-Black.ttf` заменяются на встроенные в `data.pack` кириллические `Roboto-Regular.ttf` / `Roboto-Bold.ttf`;
  - `CourierPrime-Regular.ttf` / `CourierPrime-Bold.ttf` подтягиваются из системных `C:\Windows\Fonts\cour.ttf` и `courbd.ttf`.

> Репозиторий содержит только скрипты сборки патча и словарь перевода. Оригинальные файлы игры и системные шрифты не распространяются.

## Требования
- Windows (x64) с установленной **Dirt Town Demo** (Steam, билд `ed45b4be7fc6`);
- Python 3.11+;
- Библиотека `capstone` (`pip install -r requirements.txt`).

## Установка
1. Убедитесь, что игра закрыта.
2. Установите зависимость:
   ```powershell
   pip install -r requirements.txt
   ```
3. Запустите установщик (путь можно не указывать, если игра в стандартной библиотеке Steam, либо передать через `--game-dir`):
   ```powershell
   python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```

Скрипт автоматически:
- сохранит резервную копию оригинальных `dirttown.exe` и `data.pack` в `<game-dir>\backup_en\`;
- распакует TOML и шрифты во временную папку `work\`;
- сгенерирует каталог ссылок `work\ui_catalog.json`;
- пересоберёт `data.pack` и пропатчит `dirttown.exe`;
- проверит валидность всех переведённых TOML, кириллицу в шрифтах, переадресации в `.text`/`.rdata` и таблицу `.reloc`.

## Откат к английской версии
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

## Структура проекта
- `install.py` — единый скрипт установки и отката.
- `common.py` — общие хелперы PE/`DIGP` и автопоиск папки игры.
- `prep_backup_and_fonts.py` — бэкап оригиналов и подготовка TTF с проверкой кириллического `cmap`.
- `build_loc_catalog.py` — индексация `.text` LEA и `.rdata` указателей в `work/ui_catalog.json`.
- `translate_tomls.py` — перевод TOML-файлов (с проверкой через `tomllib`).
- `repack_pack.py` — перепаковка `DIGP` архива `data.pack`.
- `loc_strings.py` — словарь перевода строк `.rdata` и таблиц UI.
- `patch_exe.py` — бинарный патчер `dirttown.exe` (секция `.loc`, `.reloc` для ASLR, фиксы длин).
- `verify_patch.py` — комплексная верификация `dirttown.exe` и `data.pack`.
