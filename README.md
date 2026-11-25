# Dirt Town Demo — Русификатор (Plugin & Patcher)

Локализация **Dirt Town Demo** (Steam build `ed45b4be7fc6`, Windows x64) на русский язык.

## Вариант 1 (рекомендуемый): Runtime-плагин `version.dll` — без правки файлов игры
Файлы игры (`dirttown.exe` и `data.pack`) **не модифицируются на диске**:
- `version.dll` загружается Windows автоматически рядом с `dirttown.exe` и пробрасывает системные вызовы в `System32\version.dll`.
- В оперативной памяти (`VirtualAlloc` в пределах ±1 ГБ от модуля) размещаются переведённые строки, патчатся `RIP`-LEA и таблицы `.rdata`.
- Хук чтения `DIGP`-ресурсов подменяет в памяти переводы TOML-файлов (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, с сохранением штампов `811034dce06dee68` для старых сейвов) и подключает кириллические шрифты (`Roboto-Regular`/`Bold` из `data.pack` + системные `cour.ttf`/`courbd.ttf`).

### Установка плагина (для игроков)
1. Скачайте готовый архив `DirtTownDemo-RU-Plugin.zip` из **Actions** (или **Releases** при теге `v*`).
2. Распакуйте `version.dll` и папку `locales/` в папку с игрой рядом с `dirttown.exe`.
3. Для переключения языка или отключения редактируйте `locales/lang.ini`:
   ```ini
   active=ru   # поставьте active=en для отключения перевода
   ```
4. Полное удаление: просто удалите `version.dll` и папку `locales/`.

### Сборка `version.dll`
- На GitHub настроен workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) (собирает x64 `version.dll` через MSVC и упаковывает `DirtTownDemo-RU-Plugin.zip`).
- Локально (при наличии VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```
- Генерация и проверка бинарных патчей локали (`locales/ru/exe_patch.dtloc`, `locales/ru/pack_patches.dtpk`):
  ```powershell
  pip install -r requirements.txt
  python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
  python build_plugin.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
  python verify_plugin.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
  ```

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
- `locales/` — языковые пакеты (`lang.ini`, `ru/exe_patch.dtloc`, `ru/pack_patches.dtpk`).
- `build_plugin.py` / `verify_plugin.py` — генератор и оффлайн-валидатор файлов плагина.
- `loc_strings.py` / `pack_rules.py` — словари перевода интерфейса и TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — скрипты прямого патча файлов игры.
