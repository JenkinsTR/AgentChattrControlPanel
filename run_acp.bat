@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv" (
  python -m venv .venv
)
call .venv\Scripts\activate.bat

REM Install deps + install this project in editable mode so src/ layout imports work
python -m pip install -r requirements.txt
python -m pip install -e .

python -m acp
endlocal
