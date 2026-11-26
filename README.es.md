[English](README.md) | [Русский](README.ru.md) | [Беларуская](README.be.md) | [Українська](README.uk.md) | [Polski](README.pl.md) | [简体中文](README.zh-CN.md) | **Español** | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — Plugin de localización multilingüe

Plugin de localización en tiempo de ejecución y parcheador para **Dirt Town Demo** (compilación de Steam `ed45b4be7fc6`, Windows x64).

## Idiomas compatibles

| Idioma | Código | Archivo de traducción | Notas |
|---|---|---|---|
| **English** | `en` | Original integrado | Cambio en vivo |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Cambio en vivo (`Roboto` + `cour.ttf`) |
| **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | Cambio en vivo |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | Cambio en vivo |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | Cambio en vivo |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Usa fuentes de Windows `msyh.ttc` / `msyhbd.ttc` (requiere reiniciar al cambiar a CJK) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Cambio en vivo |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Cambio en vivo |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Cambio en vivo |

---

## Opción 1 (recomendada): Plugin en tiempo de ejecución `version.dll` — Sin modificar archivos del juego

Los archivos del juego (`dirttown.exe` y `data.pack`) **no se modifican en disco**:
- Windows carga `version.dll` automáticamente junto a `dirttown.exe` y reenvía las llamadas del sistema a `System32\version.dll`.
- Las cadenas traducidas se cargan en RAM (`VirtualAlloc` dentro de ±1 GB del módulo) y parchean los LEA relativos a `RIP` y las tablas `.rdata` en memoria.
- Un hook en el lector de paquetes `DIGP` aplica traducciones TOML en memoria (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, conservando el sello de guardado `811034dce06dee68`) y redirige las fuentes para soporte Unicode/CJK.

### Instalación (para jugadores)
1. Descarga `DirtTownDemo-Locale-Plugin.zip` desde **Releases** (o **Actions**).
2. Extrae `version.dll` y la carpeta `locales/` en la carpeta del juego junto a `dirttown.exe`.
3. Selecciona tu idioma **directamente en Ajustes del juego** (selector `< Idioma >` en la parte inferior de la ventana de Ajustes).
   - Los idiomas latinos y cirílico (`en`, `ru`, `es`, `de`, `pt-br`) cambian **en vivo sin reiniciar** (las descripciones de la tienda y del mapa se actualizan al reiniciar).
   - Para **Chino simplificado (`zh-cn`)**, selecciónalo y **reinicia el juego** para cargar las fuentes CJK de Windows (`msyh.ttc` / `msyhbd.ttc`).
   - También puedes configurarlo manualmente en `locales/lang.ini`:
     ```ini
     active=es   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. Desinstalación completa: simplemente elimina `version.dll` y la carpeta `locales/`.

### Compilar `version.dll`
- El flujo de GitHub Actions [`.github/workflows/build.yml`](.github/workflows/build.yml) valida todos los `translations/*.json`, compila `version.dll` x64 con MSVC y empaqueta `DirtTownDemo-Locale-Plugin.zip` con todos los idiomas de `locales/`.
- Compilación local (requiere VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Cómo añadir o editar un idioma (sin recompilar `version.dll`)
1. Copia `translations/template.json` → `translations/<código>.json` (por ejemplo `translations/fr.json`).
2. Traduce los valores `"text"` (y `"new"` en `pack_toml`). Ajusta `font_redirects` si tu idioma requiere otra fuente del sistema o personalizada (o coloca fuentes en `locales/<código>/override/fonts/`).
3. Valida especificadores de formato (`%d`, `%zu`, `{}`), sufijos de ImGui y límites de bytes PE (funciona sin los archivos del juego):
   ```powershell
   python validate_translations.py <código>
   ```
4. Compila y verifica `locales/<código>/exe_patch.dtloc` y `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <código> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <código> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Copia `locales/<código>/` junto a `version.dll` o envía un Pull Request.

---

## Opción 2: Parcheador directo en disco (`install.py`)

Para parchear `dirttown.exe` y `data.pack` directamente en disco sin `version.dll`:
```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Restaurar los archivos originales desde `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Estructura del proyecto
- `plugin/` — Código fuente de la DLL proxy (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — Traducciones declarativas en JSON (`template.json`, `ru.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — Paquetes compilados de idioma (`lang.ini`, `<código>/exe_patch.dtloc`, `<código>/pack_patches.dtpk`, `<código>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — Exportador de plantilla y validador JSON sin conexión.
- `build_plugin.py` / `verify_plugin.py` — Generador y verificador sin conexión de paquetes del plugin.
- `loc_strings.py` / `pack_rules.py` — Diccionarios base de interfaz y TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — Scripts de parcheo directo en disco.
