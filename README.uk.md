[English](README.md) | [Русский](README.ru.md) | [Беларуская](README.be.md) | **Українська** | [Polski](README.pl.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Багатомовний плагін локалізації

Runtime-плагін локалізації та патчер для **Dirt Town Demo** (Steam build `ed45b4be7fc6`, Windows x64).

## Підтримувані мови

| Мова | Код | Файл перекладу | Примітки |
|---|---|---|---|
| **English** | `en` | Вбудований оригінал | Миттєве перемикання |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Миттєве перемикання |
| **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | Миттєве перемикання |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | Миттєве перемикання |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | Миттєве перемикання |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Системні шрифти `msyh.ttc` / `msyhbd.ttc` (потрібен перезапуск для CJK) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Миттєве перемикання |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Миттєве перемикання |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Миттєве перемикання |

---

## Варіант 1 (рекомендований): Runtime-плагін `version.dll` — без зміни файлів гри

Файли гри (`dirttown.exe` і `data.pack`) **не змінюються на диску**:
- `version.dll` завантажується Windows автоматично поруч із `dirttown.exe` та перенаправляє системні виклики у `System32\version.dll`.
- В оперативній пам'яті (`VirtualAlloc` у межах ±1 ГБ від модуля) розміщуються перекладені рядки, патчаться `RIP`-LEA та таблиці `.rdata`.
- Хук читання `DIGP`-ресурсів підміняє в пам'яті TOML-файли (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, зберігаючи штамп сейвів `811034dce06dee68`) і підключає шрифти Unicode/CJK.

### Встановлення (для гравців)
1. Завантажте `DirtTownDemo-Locale-Plugin.zip` із **Releases** (або **Actions**).
2. Розпакуйте `version.dll` та папку `locales/` у папку з грою поруч із `dirttown.exe`.
3. Оберіть мову **безпосередньо в Налаштуваннях гри** (перемикач `< Мова >` унизу вікна налаштувань).
   - Латиниця та кирилиця (`en`, `ru`, `be`, `uk`, `pl`, `es`, `de`, `pt-br`) перемикаються **на льоту без перезапуску** (описи техніки та мапи оновлюються після перезапуску).
   - Для **спрощеної китайської (`zh-cn`)** оберіть її та **перезапустіть гру**, щоб завантажилися системні CJK-шрифти (`msyh.ttc` / `msyhbd.ttc`).
   - Також мову можна задати вручну в `locales/lang.ini`:
     ```ini
     active=uk   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. Повне видалення: просто видаліть `version.dll` і папку `locales/`.

### Збірка `version.dll`
- GitHub Actions workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) перевіряє всі `translations/*.json`, збирає x64 `version.dll` через MSVC та пакує `DirtTownDemo-Locale-Plugin.zip`.
- Локальна збірка (VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Як додати або відредагувати мову (без перекомпіляції `version.dll`)
1. Скопіюйте `translations/template.json` → `translations/<код>.json`.
2. Перекладіть значення `"text"` (і `"new"` у `pack_toml`).
3. Перевірте форматні специфікатори та байтові ліміти:
   ```powershell
   python validate_translations.py <код>
   ```
4. Зберіть і перевірте `locales/<код>/exe_patch.dtloc` та `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <код> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <код> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Скопіюйте `locales/<код>/` поруч із `version.dll` або надішліть Pull Request.

---

## Варіант 2: Прямий патчер файлів гри (`install.py`)

```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Відкат із `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Структура проєкту
- `plugin/` — вихідний код проксі-DLL (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — декларативні JSON-переклади (`template.json`, `ru.json`, `be.json`, `uk.json`, `pl.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — зібрані мовні пакети (`lang.ini`, `<код>/exe_patch.dtloc`, `<код>/pack_patches.dtpk`, `<код>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — експорт шаблону й офлайн-валідатор JSON.
- `build_plugin.py` / `verify_plugin.py` — генератор і офлайн-верифікатор пакетів плагіна.
- `loc_strings.py` / `pack_rules.py` — словники інтерфейсу та TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — скрипти прямого патчу файлів гри.
