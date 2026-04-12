# GUI Startup Guide

Before using this file, read [`PROJECT_MAINLINE.md`](PROJECT_MAINLINE.md) first.

This startup guide assumes the current mainline:

- ASR backend: `SenseVoice`
- default environment: `.\.venv-gpu`
- primary product surface: `Streamlit GUI`

This document explains how to start the Streamlit GUI locally on Windows.

## 1. Go to the project directory

```powershell
cd d:\study\workspace\python_workspace\tanslatevioce\studyworkspacepython_workspacetanslatevioceopenlrc
```

## 2. Stop old Streamlit processes

If you have started the GUI before, it is a good idea to stop old instances first.

```powershell
Get-CimInstance Win32_Process |
Where-Object { $_.CommandLine -match 'streamlit.*openlrc\\gui_streamlit\\home.py' } |
ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Optional: check whether the old ports are gone.

```powershell
netstat -ano | Select-String ':8502|:8510|:8511|:8512'
```

If you do not see those ports in `LISTENING` state anymore, the old instances are gone.

## 3. Start the GUI with the GPU environment

```powershell
cd d:\study\workspace\python_workspace\tanslatevioce\studyworkspacepython_workspacetanslatevioceopenlrc
.\.venv-gpu\Scripts\streamlit.exe run openlrc\gui_streamlit\home.py --server.port 8502
```

Then open:

```text
http://localhost:8502
```

## 4. Verify CUDA is available

Open a new terminal and run:

```powershell
cd d:\study\workspace\python_workspace\tanslatevioce\studyworkspacepython_workspacetanslatevioceopenlrc
.\.venv-gpu\Scripts\python.exe -X utf8 -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.version.cuda); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

Expected output looks like:

```text
2.6.0+cu124
True
12.4
NVIDIA GeForce RTX 3050 Laptop GPU
```

## 5. One-line restart command

Stop old instances and start the GUI again:

```powershell
cd d:\study\workspace\python_workspace\tanslatevioce\studyworkspacepython_workspacetanslatevioceopenlrc; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'streamlit.*openlrc\\gui_streamlit\\home.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; .\.venv-gpu\Scripts\streamlit.exe run openlrc\gui_streamlit\home.py --server.port 8502
```

Start only the GUI:

```powershell
cd d:\study\workspace\python_workspace\tanslatevioce\studyworkspacepython_workspacetanslatevioceopenlrc; .\.venv-gpu\Scripts\streamlit.exe run openlrc\gui_streamlit\home.py --server.port 8502
```
