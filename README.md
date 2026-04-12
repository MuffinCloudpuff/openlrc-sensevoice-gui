# OpenLRC SenseVoice GUI Fork

Chinese-first local fork of [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc), focused on running SenseVoice transcription and LLM subtitle translation through a Streamlit GUI.

This repository is intended for a practical Windows workflow:

- SenseVoice-based transcription with GPU support
- Streamlit GUI instead of CLI-first usage
- custom relay / OpenAI-compatible translation endpoints
- clearer stage progress during long jobs
- translation fee estimation before the LLM step starts

> [!IMPORTANT]
> This is an independent fork and is **not** the official `openlrc` repository.
> If you want the upstream project, go to [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc).

## Attribution

This project is based on [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc), created by `zh-plus`.

- Original project name: `openlrc` / `Open-Lyrics`
- Original license: MIT
- This fork keeps the upstream license and builds on top of that codebase for a different local-product workflow

When redistributing this repository or publishing derived versions, keep the original MIT license text and attribution.

## What This Fork Changes

- Reworked the Streamlit GUI around a Chinese-first local workflow
- Added better progress visibility for preprocessing, transcription, translation, and export
- Added support for custom relay endpoints and relay model detection in the GUI
- Added translation fee estimation and clearer fee-limit warnings before translation starts
- Fixed a GUI validation bug that could make the page appear stuck after clicking the start button
- Added local startup helpers for running the GUI with a GPU environment

## Repository Layout

- [`openlrc/gui_streamlit/home.py`](openlrc/gui_streamlit/home.py): main Streamlit interface
- [`GUI_STARTUP.md`](GUI_STARTUP.md): local GUI startup guide for Windows
- [`run_local.py`](run_local.py): simple local CLI entry point
- [`CHANGELOG.md`](CHANGELOG.md): fork release notes and update history

## Quick Start

### 1. Prepare the environment

You need:

- Python 3.11
- FFmpeg available in `PATH`
- a working CUDA / PyTorch environment if you want GPU inference
- at least one translation credential:
  - direct provider key, or
  - relay endpoint + relay API key

### 2. Install dependencies

This fork currently targets local source usage rather than a polished PyPI release flow.

Typical local setup:

```powershell
git clone https://github.com/MuffinCloudpuff/openlrc-sensevoice-gui.git
cd openlrc-sensevoice-gui
python -m venv .venv
.\.venv\Scripts\pip install -U pip
.\.venv\Scripts\pip install -e .
```

If you use a separate GPU environment, adapt the commands to that environment instead.

### 3. Start the GUI

Follow [`GUI_STARTUP.md`](GUI_STARTUP.md).

Typical command:

```powershell
.\.venv-gpu\Scripts\streamlit.exe run openlrc\gui_streamlit\home.py --server.port 8502
```

Then open:

```text
http://localhost:8502
```

### 4. Configure translation

The GUI supports two common modes:

- direct model credentials such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or `OPENROUTER_API_KEY`
- relay mode through a custom `Base URL` and relay API key

For relay mode, set:

- provider type
- relay `Base URL`
- relay model name
- relay API key

### 5. Run a job

1. Upload audio or video files
2. Choose source language and target language
3. Decide whether to use transcribe-only mode
4. Set the translation fee limit
5. Click the start button

The GUI will show:

- preprocessing progress
- transcription progress
- translation fee estimation before translation starts
- current translation / export status
- live log output

## CLI Entry Point

You can also run a local CLI flow with [`run_local.py`](run_local.py):

```powershell
.\.venv-gpu\Scripts\python.exe .\run_local.py "D:\path\to\audio.mp3" --target-lang zh-cn
```

Transcribe only:

```powershell
.\.venv-gpu\Scripts\python.exe .\run_local.py "D:\path\to\audio.mp3" --skip-trans
```

## Current Notes

- This fork is optimized for local Windows usage.
- The GUI now blocks translation early when the configured fee limit is clearly too low.
- The fee-limit slider supports larger values than upstream-style defaults.
- The repository ignores local runtime artifacts such as virtual environments, logs, output folders, and GUI config files.

## Development Notes

If you want to continue development on this fork:

```powershell
python -m py_compile openlrc\gui_streamlit\home.py
pytest tests\test_chatbot.py tests\test_translate.py -q
```

There is also additional local regression coverage in:

- [`tests/test_opt.py`](tests/test_opt.py)
- [`tests/test_sensevoice_alignment.py`](tests/test_sensevoice_alignment.py)

## Upstream Project

The upstream project remains the right reference if you want the original package, documentation, and broader model support:

- Upstream repository: [`zh-plus/openlrc`](https://github.com/zh-plus/openlrc)
- Upstream license: MIT

## License

This repository is distributed under the MIT license. See [LICENSE](LICENSE).
