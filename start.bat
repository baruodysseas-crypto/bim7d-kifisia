@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 7D-BIM Lifecycle Tool

rem --- find Python (3.10+) -------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo.
  echo  Δεν βρέθηκε Python. Εγκαταστήστε Python 3.12 ή 3.13 από https://www.python.org/downloads/
  echo  και τσεκάρετε "Add python.exe to PATH". Μετά ξανατρέξτε το start.bat.
  echo.
  pause & exit /b 1
)

rem --- one-time environment ------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo  Δημιουργία περιβάλλοντος Python ^(μία φορά^)...
  %PY% -m venv .venv || ( echo  Αποτυχία δημιουργίας venv & pause & exit /b 1 )
)
if not exist ".venv\.installed" (
  echo  Εγκατάσταση βασικών βιβλιοθηκών ^(μία φορά, 2-5 λεπτά^)...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install --only-binary=:all: -r requirements.txt || ( echo  Αποτυχία εγκατάστασης. Στείλτε μου το μήνυμα σφάλματος. & pause & exit /b 1 )
  echo ok> ".venv\.installed"
)
rem --- optional readers (.3dm / .ifc): never block the start ------------------
if not exist ".venv\.optional" (
  echo  Προαιρετικά: ανάγνωση αρχείων .3dm και .ifc...
  ".venv\Scripts\python.exe" -m pip install --only-binary=:all: rhino3dm >nul 2>nul && ( echo    .3dm: ok ) || ( echo    .3dm: δεν είναι διαθέσιμο για αυτή την Python - εξάγετε OBJ/GLB από το Rhino )
  ".venv\Scripts\python.exe" -m pip install --only-binary=:all: ifcopenshell >nul 2>nul && ( echo    .ifc: ok ) || ( echo    .ifc: δεν είναι διαθέσιμο για αυτή την Python - εξάγετε OBJ/GLB )
  echo ok> ".venv\.optional"
)

if "%PORT%"=="" set "PORT=8000"
echo.
echo  Η εφαρμογή τρέχει στο http://127.0.0.1:%PORT%  ^(κλείστε αυτό το παράθυρο για να σταματήσει^)
echo.
start "" "http://127.0.0.1:%PORT%"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
pause
