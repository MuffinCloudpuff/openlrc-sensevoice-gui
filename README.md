# OpenLRC SenseVoice GUI Fork

中文优先的 `openlrc` 分支，重点是通过 Streamlit GUI 运行 SenseVoice 转写和 LLM 字幕翻译。  
A Chinese-first fork of `openlrc`, focused on running SenseVoice transcription and LLM subtitle translation through a Streamlit GUI.

## First Read

在继续之前，先读 [`PROJECT_MAINLINE.md`](PROJECT_MAINLINE.md)。  
Read [`PROJECT_MAINLINE.md`](PROJECT_MAINLINE.md) first.

它是当前仓库的统一入口，明确说明：

- 当前主线是 `SenseVoice + Streamlit + 目录级批处理`
- 当前默认环境是 `.\.venv-gpu`
- 哪些旧的 `Whisper` / 上游式表述只是兼容遗留，不应该当成当前项目方向

## 重要说明 | Important Notice

这是一个独立 fork，不是 `openlrc` 官方仓库。  
This is an independent fork and is not the official `openlrc` repository.

上游项目地址：[`zh-plus/openlrc`](https://github.com/zh-plus/openlrc)  
Upstream repository: [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc)

## 署名与许可证 | Attribution and License

本项目基于 [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc) 二次开发，原作者为 `zh-plus`。  
This project is derived from [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc), originally created by `zh-plus`.

- 原项目名称：`openlrc` / `Open-Lyrics`
- 原项目许可证：MIT
- 本 fork 在保留原许可证的前提下，针对本地中文 GUI 工作流做了定制

- Original project name: `openlrc` / `Open-Lyrics`
- Original license: MIT
- This fork keeps the upstream license and customizes the project for a Chinese-first local GUI workflow

发布或再分发本仓库时，请保留原始 MIT 许可证与署名信息。  
If you redistribute this repository or publish derived versions, keep the original MIT license text and attribution.

## 这个 Fork 做了什么 | What This Fork Changes

- 面向中文本地使用场景重做了 Streamlit GUI  
  Reworked the Streamlit GUI around a Chinese-first local workflow
- 增强了预处理、转写、翻译、导出的阶段进度展示  
  Added clearer phase progress for preprocessing, transcription, translation, and export
- 支持自定义中转接口与中转模型探测  
  Added support for custom relay endpoints and relay model detection
- 在翻译前增加费用预估和费用上限提示  
  Added translation fee estimation and fee-limit warnings before translation starts
- 修复了点击开始处理后前端看似卡住的校验逻辑问题  
  Fixed a GUI validation bug that could make the page appear stuck after clicking the start button
- 增加了本地 GPU 启动辅助脚本和文档  
  Added local startup helpers and documentation for GPU-based usage

## 适用场景 | Intended Use

这个仓库主要面向 Windows 本地工作流，适合以下需求：  
This repository is mainly intended for a local Windows workflow, especially if you want:

- SenseVoice + GPU 转写  
  SenseVoice-based transcription with GPU support
- 图形界面而不是纯 CLI  
  a GUI instead of a CLI-first workflow
- 自定义 OpenAI-compatible / relay 翻译接口  
  custom OpenAI-compatible or relay translation endpoints
- 长任务期间更明确的进度反馈  
  clearer progress feedback during long-running jobs
- 在真正调用 LLM 前先做费用预估  
  translation cost estimation before the LLM step starts

## 仓库结构 | Repository Layout

- [`PROJECT_MAINLINE.md`](PROJECT_MAINLINE.md): 当前仓库统一入口 / canonical project entry for humans and AI
- [`DIRECTORY_BATCH_WORKFLOW_PLAN.md`](DIRECTORY_BATCH_WORKFLOW_PLAN.md): 当前目录级批处理实施计划 / active directory-batch implementation plan
- [`openlrc/gui_streamlit/home.py`](openlrc/gui_streamlit/home.py): 主 Streamlit 页面 / main Streamlit interface
- [`GUI_STARTUP.md`](GUI_STARTUP.md): Windows 本地启动说明 / local startup guide for Windows
- [`run_local.py`](run_local.py): 简单本地 CLI 入口 / simple local CLI entry point
- [`CHANGELOG.md`](CHANGELOG.md): 更新日志 / release notes and change history

## 快速开始 | Quick Start

### 1. 环境准备 | Prepare the Environment

你需要：  
You need:

- Python 3.11
- FFmpeg，并确保已加入 `PATH`  
  FFmpeg available in `PATH`
- 如果想用 GPU 推理，需要可用的 CUDA / PyTorch 环境  
  a working CUDA / PyTorch environment if you want GPU inference
- 至少一种翻译凭证：  
  at least one translation credential:
  - 直连模型 API key  
    direct provider key
  - 或中转接口 + 中转 API key  
    or relay endpoint + relay API key

### 2. 安装依赖 | Install Dependencies

当前这个 fork 更偏向源码本地运行，而不是 PyPI 发布版工作流。  
This fork currently targets local source usage rather than a polished PyPI release workflow.

典型本地安装方式：  
Typical local setup:

```powershell
git clone https://github.com/MuffinCloudpuff/openlrc-sensevoice-gui.git
cd openlrc-sensevoice-gui
python -m venv .venv-gpu
.\.venv-gpu\Scripts\pip install -U pip
.\.venv-gpu\Scripts\pip install -e .
```

当前文档默认都以 `.\.venv-gpu` 为准。  
Current docs assume `.\.venv-gpu` as the default environment.

### 3. 启动 GUI | Start the GUI

先阅读 [`GUI_STARTUP.md`](GUI_STARTUP.md)。  
Read [`GUI_STARTUP.md`](GUI_STARTUP.md) first.

典型启动命令：  
Typical command:

```powershell
.\.venv-gpu\Scripts\streamlit.exe run openlrc\gui_streamlit\home.py --server.port 8502
```

然后打开：  
Then open:

```text
http://localhost:8502
```

### 4. 配置翻译 | Configure Translation

GUI 支持两种常见模式：  
The GUI supports two common modes:

- 直连 API key：`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`OPENROUTER_API_KEY`
- 中转模式：自定义 `Base URL` + relay API key

- direct provider keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`
- relay mode: custom `Base URL` plus a relay API key

如果使用中转模式，需要设置：  
For relay mode, set:

- provider type
- relay `Base URL`
- relay model name
- relay API key

### 5. 运行任务 | Run a Job

1. 选择一个根目录，而不是逐个上传文件  
   Choose a root directory instead of uploading files one by one
2. 让 GUI 递归扫描其中的音频文件  
   Let the GUI recursively scan audio files under that directory
3. 选择源语言、目标语言和是否仅转写  
   Choose source language, target language, and whether to use transcribe-only mode
4. 运行 ASR，并把缓存写入 `.openlrc_cache`  
   Run ASR and persist cache under `.openlrc_cache`
5. 在真正调用翻译前查看费用估算并确认  
   Review translation fee estimates and confirm before any LLM call
6. 只翻译你勾选的文件  
   Translate only the files you selected

GUI 会展示：  
The GUI shows:

- 根目录扫描结果 / root-directory scan results
- ASR 缓存复用状态 / ASR cache reuse status
- 翻译前费用预估与确认 / cost estimation and confirmation before translation
- 当前翻译或导出状态 / current translation or export status
- 实时日志 / live log output

## CLI 入口 | CLI Entry Point

你也可以使用 [`run_local.py`](run_local.py) 进行本地命令行运行：  
You can also use [`run_local.py`](run_local.py) as a simple local CLI entry point:

```powershell
.\.venv-gpu\Scripts\python.exe .\run_local.py "D:\path\to\audio.mp3" --target-lang zh-cn
```

仅转写：  
Transcribe only:

```powershell
.\.venv-gpu\Scripts\python.exe .\run_local.py "D:\path\to\audio.mp3" --skip-trans
```

## 当前特性说明 | Current Notes

- 这个 fork 主要面向 Windows 本地使用  
  This fork is optimized for local Windows usage
- GUI 会在翻译前对明显过低的费用上限直接拦截  
  The GUI now blocks translation early when the configured fee limit is clearly too low
- 费用上限滑块支持比上游默认值更高的范围  
  The fee-limit slider supports larger values than upstream-style defaults
- 仓库已忽略虚拟环境、日志、输出目录、GUI 配置等本地运行产物  
  The repository ignores local runtime artifacts such as virtual environments, logs, output folders, and GUI config files

## 开发说明 | Development Notes

如果你要继续开发这个 fork，可以先跑这些检查：  
If you want to continue development on this fork, start with:

```powershell
.\.venv-gpu\Scripts\python.exe -m py_compile openlrc\directory_workflow.py openlrc\gui_streamlit\home.py
.\.venv-gpu\Scripts\python.exe -m ruff check openlrc\directory_workflow.py openlrc\gui_streamlit\home.py tests\test_directory_workflow.py
.\.venv-gpu\Scripts\python.exe -m pytest tests\test_directory_workflow.py tests\test_config.py tests\test_lazy_imports.py -q
```

另外还有一些本地回归测试：  
There is also additional local regression coverage in:

- [`tests/test_opt.py`](tests/test_opt.py)
- [`tests/test_sensevoice_alignment.py`](tests/test_sensevoice_alignment.py)

## 上游项目 | Upstream Project

如果你想看原始包、原始文档和更广泛的模型支持，请参考上游仓库：  
If you want the original package, upstream documentation, and broader model support, see the upstream repository:

- [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc)

## License

本仓库以 MIT 许可证发布，详见 [LICENSE](LICENSE)。  
This repository is distributed under the MIT license. See [LICENSE](LICENSE).
