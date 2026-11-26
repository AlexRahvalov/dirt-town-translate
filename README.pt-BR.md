[English](README.md) | [Русский](README.ru.md) | [Беларуская](README.be.md) | [Українська](README.uk.md) | [Polski](README.pl.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [Deutsch](README.de.md) | **Português (BR)**

# Dirt Town Demo — Plugin de Localização Multilíngue

Plugin de localização em tempo de execução e patcher para **Dirt Town Demo** (compilação Steam `ed45b4be7fc6`, Windows x64).

## Idiomas suportados

| Idioma | Código | Arquivo de tradução | Observações |
|---|---|---|---|
| **English** | `en` | Original integrado | Troca ao vivo |
| **Русский** | `ru` | [`translations/ru.json`](translations/ru.json) | Troca ao vivo (`Roboto` + `cour.ttf`) |
| **Беларуская** | `be` | [`translations/be.json`](translations/be.json) | Troca ao vivo |
| **Українська** | `uk` | [`translations/uk.json`](translations/uk.json) | Troca ao vivo |
| **Polski** | `pl` | [`translations/pl.json`](translations/pl.json) | Troca ao vivo |
| **简体中文** | `zh-cn` | [`translations/zh-cn.json`](translations/zh-cn.json) | Usa fontes do Windows `msyh.ttc` / `msyhbd.ttc` (requer reiniciar ao alternar para CJK) |
| **Español** | `es` | [`translations/es.json`](translations/es.json) | Troca ao vivo |
| **Deutsch** | `de` | [`translations/de.json`](translations/de.json) | Troca ao vivo |
| **Português (BR)** | `pt-br` | [`translations/pt-br.json`](translations/pt-br.json) | Troca ao vivo |

---

## Opção 1 (recomendada): Plugin em tempo de execução `version.dll` — Sem alterar arquivos do jogo

Os arquivos do jogo (`dirttown.exe` e `data.pack`) **não são modificados no disco**:
- O Windows carrega `version.dll` automaticamente ao lado de `dirttown.exe` e encaminha as chamadas do sistema para `System32\version.dll`.
- As strings traduzidas são alocadas na RAM (`VirtualAlloc` dentro de ±1 GB do módulo) e aplicadas em tempo de execução nos LEAs relativos a `RIP` e nas tabelas `.rdata`.
- Um hook no leitor de pacotes `DIGP` aplica traduções TOML em memória (`shop.toml`, `key_layouts.toml`, `pad_layouts.toml`, `sites/demo2/demo2.toml`, preservando o selo de save `811034dce06dee68`) e redireciona fontes para suporte Unicode/CJK.

### Instalação (para jogadores)
1. Baixe `DirtTownDemo-Locale-Plugin.zip` em **Releases** (ou **Actions**).
2. Extraia `version.dll` e a pasta `locales/` na pasta do jogo ao lado de `dirttown.exe`.
3. Escolha o idioma **diretamente nas Configurações do jogo** (seletor `< Idioma >` na parte inferior da janela de Configurações).
   - Idiomas latinos e cirílico (`en`, `ru`, `es`, `de`, `pt-br`) alternam **ao vivo sem reiniciar** (descrições da loja e do mapa atualizam ao reiniciar).
   - Para **Chinês Simplificado (`zh-cn`)**, selecione-o e **reinicie o jogo** para carregar as fontes CJK do Windows (`msyh.ttc` / `msyhbd.ttc`).
   - Você também pode definir o idioma manualmente em `locales/lang.ini`:
     ```ini
     active=pt-br   # en | ru | be | uk | pl | zh-cn | es | de | pt-br
     ```
4. Desinstalação completa: basta apagar `version.dll` e a pasta `locales/`.

### Compilar `version.dll`
- O workflow do GitHub Actions [`.github/workflows/build.yml`](.github/workflows/build.yml) valida todos os `translations/*.json`, compila `version.dll` x64 com MSVC e empacota `DirtTownDemo-Locale-Plugin.zip` com todos os idiomas de `locales/`.
- Compilação local (requer VS Build Tools / CMake):
  ```powershell
  cmake -S plugin -B build -A x64
  cmake --build build --config Release
  ```

### Como adicionar ou editar um idioma (sem recompilar `version.dll`)
1. Copie `translations/template.json` → `translations/<código>.json` (por exemplo `translations/fr.json`).
2. Traduza os valores `"text"` (e `"new"` em `pack_toml`). Ajuste `font_redirects` se necessário ou coloque fontes em `locales/<código>/override/fonts/`.
3. Valide especificadores de formato (`%d`, `%zu`, `{}`), sufixos ImGui e limites de bytes PE (funciona sem os arquivos do jogo):
   ```powershell
   python validate_translations.py <código>
   ```
4. Gere e valide `locales/<código>/exe_patch.dtloc` e `pack_patches.dtpk`:
   ```powershell
   pip install -r requirements.txt
   python build_loc_catalog.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python build_plugin.py --locale <código> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   python verify_plugin.py --locale <código> --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
   ```
5. Copie `locales/<código>/` ao lado de `version.dll` ou envie um Pull Request.

---

## Opção 2: Patcher direto em disco (`install.py`)

Para aplicar o patch em `dirttown.exe` e `data.pack` diretamente no disco sem `version.dll`:
```powershell
pip install -r requirements.txt
python install.py --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```
Restaurar os arquivos originais a partir de `backup_en/`:
```powershell
python install.py --restore --game-dir "D:\SteamLibrary\steamapps\common\Dirt Town Demo"
```

---

## Estrutura do projeto
- `plugin/` — Código-fonte da DLL proxy (`CMakeLists.txt`, `version.def`, `src/main.cpp`).
- `translations/` — Traduções declarativas em JSON (`template.json`, `ru.json`, `zh-cn.json`, `es.json`, `de.json`, `pt-br.json`).
- `locales/` — Pacotes compilados de idioma (`lang.ini`, `<código>/exe_patch.dtloc`, `<código>/pack_patches.dtpk`, `<código>/meta.ini`).
- `export_translations.py` / `validate_translations.py` — Exportador de modelo e validador JSON offline.
- `build_plugin.py` / `verify_plugin.py` — Construtor e verificador offline dos pacotes do plugin.
- `loc_strings.py` / `pack_rules.py` — Dicionários base de interface e TOML.
- `install.py` / `patch_exe.py` / `repack_pack.py` / `verify_patch.py` — Scripts de patch direto em disco.
