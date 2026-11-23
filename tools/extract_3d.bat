@echo off
chcp 65001 >nul
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "OBJ=%~1"
if "%OBJ%"=="" set "OBJ=%~dp0..\..\3d_ktirio.obj"
if not exist "%OBJ%" set "OBJ=%~dp0..\3d_ktirio.obj"
echo Διαβάζω: %OBJ%
echo Θα πάρει 10-20 λεπτά για αρχείο 2 GB. Μην κλείσετε το παράθυρο.
"%PY%" "%~dp0extract_3d.py" "%OBJ%"
echo.
echo Τέλος. Τα αρχεία *_light.glb και *_summary.json είναι δίπλα στο OBJ.
pause
