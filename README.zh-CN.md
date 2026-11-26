[English](README.md) | [Русский](README.ru.md) | [Беларуская](README.be.md) | [Українська](README.uk.md) | [Polski](README.pl.md) | **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | 实时热切换 |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | 实时热切换 |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | 实时热切换 |
| **简体中文** | [Español](README.es.md) | [Deutsch](README.de.md) | [Português (BR)](README.pt-BR.md)

# Dirt Town Demo — 多语言本地化插件

**Dirt Town Demo**（Steam 构建版本 `ed45b4be7fc6`，Windows x64）的运行时多语言插件与补丁工具。

## 支持的语言

| 语言 | 代码 | 翻译文件 | 说明 |
|---|---|---|---|
| **English** | `en` | 游戏内置原版 | 实时热切换 |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | 实时热切换（`Roboto` + `cour.ttf`） |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | 调用 Windows 系统字体 `msyh.ttc` / `msyhbd.ttc`（切换到中文后需重启游戏加载字体） |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | 实时热切换 |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | 实时热切换 |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | 实时热切换 |

---

## 方式 1（推荐）：运行时插件 `version.dll` — 不修改游戏原文件

游戏文件（`dirttown.exe` 与 `data.pack`）**在磁盘上保持完全原样**：
- Windows 会自动加载 `dirttown.exe` 同目录下的 `version.dll`，并将系统调用转发至 `System32\version.dll`。
- 插件在内存中（模块 ±1 GB 范围内的 `VirtualAlloc`）分配翻译字符串，并在运行时修补 `RIP` 相对寻址与 `.rdata` 字符串表。
- 通过拦截 `DIGP` 资源包读取，在内存中动态替换 TOML 文本（`shop.toml`、`key_layouts.toml`、`pad_layouts.toml`、`sites/demo2/demo2.toml`，同时保留 `811034dce06dee68` 存档兼容标识），并重定向字体以支持中文/西里尔字符。

### 安装步骤（玩家）
1. 从 **Releases**（或 **Actions**）下载 `DirtTownDemo-Locale-Plugin.zip`。
2. 将 `version.dll` 和 `locales/` 文件夹解压到游戏根目录（与 `dirttown.exe` 同级）。
3. 在游戏**设置（Settings）**底部直接点击 `< 语言 >` 切换语言：
   - 拉丁语系与俄语（`en`、`ru`、`es`、`de`、`pt-br`）支持**免重启热切换**（商店与地图简介需重启后更新）。
   - 切换至**简体中文（`zh-cn`）**后，请**重启游戏**，以便启动时加载系统微软雅黑字体（`msyh.ttc` / `msyhbd.ttc`）。
   - 也可以在 `locales/lang.ini` 中手动指定语言：
     ```ini
     active=zh-cn   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. 完全卸载：直接删除 `version.dll` 和 `locales/` 文件夹即可。

### 编译 `version.dll`
- GitHub Actions 工作流 [`.github/workflows/build.yml`](.github/workflows/build.yml) 会自动校验所有 `translations/*.json`、使用 MSVC 编译 x64 `version.dll`，并打包包含全部语言的 `DirtTownDemo-Locale-Plugin.zip`。
- 本地编译（需安装 VS Build Tools / CMake）：
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### 添加或修改语言（无需重新编译 `version.dll`）
1. 复制 `translations/template.json` → `translations/<代码>.json`（例如 `translations/ja.json`）。
2. 翻译 `"text"` 字段（以及 `pack_toml` 中的 `"new"` 字段）。如需其他系统字体，可在 `font_redirects` 中配置，或将字体放入 `locales/<代码>/override/fonts/`。
3. 校验格式占位符（`%d`、`%zu`、`{}`）、ImGui 后缀与 PE 字节长度限制（无需游戏文件）：
   ```powershell
   python validate_translations.py <代码>
   ```
4. 生成并校验 `locales/<代码>/exe_patch.dtloc` 与 `pack_patches.dtpk`：
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <代码> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <代码> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. 将 `locales/<代码>/` 复制到 `version.dll` 旁，或提交 Pull Request。

---

## 方式 2：直接修补游戏文件（`install.py`）

如需不使用 `version.dll` 直接修补磁盘上的 `dirttown.exe` 与 `data.pack`：
```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
从 `backup_en/` 恢复原文件：
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## 项目结构
- `plugin/` — 代理 DLL 源码（`CMakeLists.txt`、`version.def`、`src/main.cpp`）。
- `translations/` — 声明式 JSON 翻译文件（`template.json`、`ru.json`、`zh-cn.json`、`es.json`、`de.json`、`pt-br.json`）。
- `locales/` — 编译后的语言包（`lang.ini`、`<代码>/exe_patch.dtloc`、`<代码>/pack_patches.dtpk`、`<代码>/meta.ini`）。
- `export_translations.py` / `validate_translations.py` — 模板导出与离线 JSON 校验器。
- `build_plugin.py` / `verify_plugin.py` — 插件语言包构建与离线验证脚本。
- `loc_strings.py` / `pack_rules.py` — 界面与 TOML 文本字典。
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — 磁盘直接修补脚本。
