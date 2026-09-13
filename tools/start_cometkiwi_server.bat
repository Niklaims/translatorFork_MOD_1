@echo off
chcp 65001 >nul
rem Запуск счётного сервера COMETKiwi на ПК с видеокартой.
rem Отредактируйте три строки ниже под свою машину и положите ярлык
rem на этот файл в автозагрузку, если хотите, чтобы он поднимался сам.

set KIWI_PYTHON=C:\kiwi\venv\Scripts\python.exe
rem Каталог, в котором лежит сам файл .ckpt (у модели с Hugging Face — подкаталог checkpoints).
set KIWI_WEIGHTS=C:\kiwi\weights\wmt22-cometkiwi-da\checkpoints
set KIWI_MODEL=wmt22-cometkiwi-da

"%KIWI_PYTHON%" "%~dp0translation_qa_cometkiwi_server.py" ^
  --model-dir "%KIWI_WEIGHTS%" ^
  --model "%KIWI_MODEL%" ^
  --device cuda ^
  --port 8765

pause
