# OpenLRC Web 字幕翻译工具

这是一个基于 [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc) 二次开发的本地字幕转写与翻译工具。当前主线是 **Web 控制台 + 目录级批处理 + SenseVoice ASR + 多翻译后端**，适合在 Windows 本机批量处理音频，生成 `.lrc` 字幕。

> 本仓库是独立 fork，不是 OpenLRC 官方仓库。原项目许可证为 MIT，本 fork 保留原始许可证与署名信息。

## 主要特性

- Web 版控制台：选择根目录后递归扫描音频文件，统一管理任务、日志、缓存和输出。
- 批量预处理：缺失 `_preprocessed.wav` 的音频会先进入批量预处理队列；已有缓存会自动跳过。
- 单路 ASR：ASR 阶段保持单路运行，避免多任务抢占同一张 GPU。
- 缓存复用：ASR、翻译估算和翻译结果写入 `.openlrc_cache`，重复运行时减少等待。
- 实时进度：前端显示预处理、ASR、翻译、导出等阶段进度和当前文件。
- 多翻译后端：支持官方 API、中转平台 API 和本地模型翻译。

## 支持的翻译方式

### 官方 API 翻译

支持常见官方模型接口，包括：

- GPT / OpenAI API
- Gemini / Google API
- Claude / Anthropic API
- OpenRouter API

在 Web 设置中选择「官方 API」，填写对应 API Key 和模型名即可。

### 中转平台 API 翻译

支持自定义中转平台接口，适合使用第三方聚合平台或自建网关。

当前支持两类兼容模式：

- OpenAI 兼容接口
- Anthropic 兼容接口

需要填写：

- Relay Provider
- Base URL
- Model Name
- Relay API Key

### 本地模型翻译

支持本地 HY-MT 模型翻译，当前通过 Ollama 加载 GGUF 模型，并使用本地 tokenizer 目录完成翻译流程。

本地模型模式下不会弹出费用确认框。任务会在 ASR 完成后直接进入本地翻译与导出，因为不会产生远程 API 费用。

本地 HY-MT 需要：

- 已安装并可访问的 Ollama
- HY-MT GGUF 模型文件
- HY-MT tokenizer 目录
- Web 设置中填写 Ollama 地址、模型名、GGUF 路径和 tokenizer 路径

## 环境要求

- Python 3.10 到 3.12，推荐 Python 3.11
- FFmpeg，并确保 `ffmpeg` 可在命令行中直接调用
- Windows 本地环境优先
- 如使用 GPU ASR，需要可用的 CUDA / PyTorch 环境
- 如使用本地 HY-MT，需要安装 Ollama

## 安装

推荐使用本地虚拟环境：

```powershell
git clone https://github.com/MuffinCloudpuff/openlrc-sensevoice-gui.git
cd openlrc-sensevoice-gui

python -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip install -U pip
.\.venv-gpu\Scripts\python.exe -m pip install -e ".[web,local-mt]"
```

如果需要降噪功能，再安装完整依赖：

```powershell
.\.venv-gpu\Scripts\python.exe -m pip install -e ".[web,local-mt,full]"
```

如果你已经有适配 CUDA 的 PyTorch 环境，可以继续沿用现有 `.venv-gpu`。

## 启动 Web 版

当前推荐使用 Web 版：

```powershell
.\.venv-gpu\Scripts\python.exe -m openlrc.gui_web.app --host 127.0.0.1 --port 8502
```

然后打开：

```text
http://127.0.0.1:8502/
```

如果 `8502` 已被占用，可以换一个端口：

```powershell
.\.venv-gpu\Scripts\python.exe -m openlrc.gui_web.app --host 127.0.0.1 --port 8503
```

安装为可执行脚本后，也可以使用：

```powershell
.\.venv-gpu\Scripts\openlrc-web.exe --host 127.0.0.1 --port 8502
```

## 基本使用流程

1. 打开 Web 控制台。
2. 在入口页选择音频根目录。
3. 等待系统递归扫描目录中的音频文件。
4. 在设置中选择翻译后端：官方 API、中转 API 或本地 HY-MT。
5. 配置 ASR 模型、目标语言、是否降噪、是否双语等参数。
6. 点击「开始任务」。
7. 等待批量预处理和 ASR 完成。
8. 如果使用官方 API 或中转 API，查看费用估算并确认需要翻译的文件。
9. 如果使用本地 HY-MT，系统会跳过费用确认，直接执行本地翻译。
10. 在输出页查看生成的字幕文件。

## 预处理并发说明

Web 版会把预处理和 ASR 拆成两个阶段：

- 预处理阶段可以并发处理多个音频。
- ASR 阶段仍保持单路运行，避免同一张 GPU 被多个 ASR 任务抢占。

默认预处理并发为自动模式，规则是：

```text
min(4, cpu_count // 2)
```

高级设置中可以手动设置预处理并发数，范围为 `1-8`。如果机器还同时运行 ASR、Ollama 或其他 GPU 任务，建议先使用默认值或设置为 `4`。

## 输出与缓存

运行后常见产物包括：

- `preprocessed/`：预处理后的音频缓存
- `.openlrc_cache/`：ASR、翻译估算和翻译结果缓存
- `.lrc`：最终字幕文件
- `openlrc_run.log`：任务日志

再次处理同一目录时，系统会优先复用已有缓存。

## 开发与测试

常用测试命令：

```powershell
.\.venv-gpu\Scripts\python.exe -m pytest tests/test_gui_web_services.py tests/test_preprocess.py
```

语法检查：

```powershell
.\.venv-gpu\Scripts\python.exe -m py_compile openlrc\gui_web\services\processing_service.py openlrc\preprocess.py openlrc\openlrc.py
```

## 上游与许可证

本项目基于 [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc) 二次开发。原项目由 `zh-plus` 创建，许可证为 MIT。

本仓库同样以 MIT 许可证发布，详见 [LICENSE](LICENSE)。发布或再分发时，请保留原始 MIT 许可证和上游署名信息。
