# Project Mainline

## Purpose

This document is the canonical entry point for this repository.

If a human developer, an AI agent, or an automation tool needs to understand this project quickly, read this file first.

Its job is to prevent two common mistakes:

1. Following stale upstream `openlrc` assumptions.
2. Using the wrong local environment or the wrong workflow entry.

## Current Mainline

This repository is currently maintained around a Windows-local, GPU-first workflow built on:

- SenseVoice ASR
- Streamlit GUI
- directory-level batch processing
- persistent `.openlrc_cache` reuse
- optional LLM subtitle translation after fee estimation and user confirmation

The mainline is not a generic upstream `openlrc` CLI-first flow.
The mainline is not a Whisper-first flow.

If older comments, examples, tests, or compatibility code mention `whisper`, `whisper_model`, `faster-whisper`, or older upstream behavior, treat them as legacy leftovers unless a file explicitly says otherwise.

## Naming Note

In current code and docs, the concrete ASR backend name is `SenseVoice`.

If someone informally says `SenseWise` when discussing this repository, interpret that as the current SenseVoice-based project line, not as a separate backend.

To avoid ambiguity in code and docs, prefer the actual name used by the codebase:

- `SenseVoice`

## Canonical Environment

The current active environment is:

```text
.\.venv-gpu
```

Use this environment for:

- running Streamlit
- running local CLI commands
- running validation commands
- installing missing developer tools for this project

Do not default to:

- `.\.venv`
- global Python
- any older ad hoc environment

unless you are explicitly doing compatibility cleanup or environment repair.

## Canonical Entry Points

Primary GUI entry:

```powershell
.\.venv-gpu\Scripts\streamlit.exe run openlrc\gui_streamlit\home.py --server.port 8502
```

Primary local CLI entry:

```powershell
.\.venv-gpu\Scripts\python.exe .\run_local.py "D:\path\to\audio.mp3" --target-lang zh-cn
```

Primary startup guide:

- [`GUI_STARTUP.md`](GUI_STARTUP.md)

Primary workflow plan currently being implemented:

- [`DIRECTORY_BATCH_WORKFLOW_PLAN.md`](DIRECTORY_BATCH_WORKFLOW_PLAN.md)

## What The GUI Is Supposed To Do Now

The current target user flow is:

1. Choose a root directory instead of uploading files one by one.
2. Recursively scan supported audio files under that directory.
3. Store ASR cache under:

```text
<root>/.openlrc_cache/
```

4. Reuse valid ASR cache on re-entry instead of re-running ASR.
5. Estimate translation cost after ASR is ready.
6. Wait for user confirmation before any LLM translation.
7. Allow translating only a selected subset of files.
8. Write final `.lrc` back next to the source audio file.

If documentation says the main GUI flow is still “upload files, process immediately, then download a zip”, that description is outdated for the current project direction.

## Current Source Of Truth

When there is a conflict, use this priority order:

1. [`PROJECT_MAINLINE.md`](PROJECT_MAINLINE.md)
2. current code under [`openlrc/gui_streamlit/home.py`](openlrc/gui_streamlit/home.py) and [`openlrc/directory_workflow.py`](openlrc/directory_workflow.py)
3. [`DIRECTORY_BATCH_WORKFLOW_PLAN.md`](DIRECTORY_BATCH_WORKFLOW_PLAN.md)
4. [`GUI_STARTUP.md`](GUI_STARTUP.md)
5. [`README.md`](README.md)
6. upstream `openlrc` expectations

## Legacy Items To Treat Carefully

These may still exist in the repository, but they are not the preferred entry for new work:

- compatibility fields like `whisper_model`
- old tests written around upstream naming
- changelog history from pre-SenseVoice phases
- upstream-oriented references to older transcription backends

Do not use those as the first interpretation of the project.

## Recommended Validation Commands

Run these from the project root with `.\.venv-gpu`:

```powershell
.\.venv-gpu\Scripts\python.exe -m py_compile openlrc\directory_workflow.py openlrc\gui_streamlit\home.py
.\.venv-gpu\Scripts\python.exe -m ruff check openlrc\directory_workflow.py openlrc\gui_streamlit\home.py
.\.venv-gpu\Scripts\python.exe -m pytest tests\test_directory_workflow.py tests\test_config.py tests\test_lazy_imports.py -q
```

Add more test targets as specific features expand, but use the GPU environment as the default execution context.

## Guidance For AI Agents

If you are an AI reading this repo:

- assume `.venv-gpu` is the default runtime and tooling environment
- assume Streamlit GUI is the primary product surface
- assume SenseVoice is the intended ASR path
- assume directory-batch workflow is the current implementation direction
- verify whether older docs are legacy before following them
- prefer current GUI and cache workflow files over upstream-style abstractions

## Short Version

If you only remember five things, remember these:

1. Use `.\.venv-gpu`.
2. The ASR mainline is SenseVoice.
3. The main UI is Streamlit.
4. The active workflow is directory batch + `.openlrc_cache` + translation confirmation.
5. Older Whisper-oriented wording is legacy, not the project direction.
