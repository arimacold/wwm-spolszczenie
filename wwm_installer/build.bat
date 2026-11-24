@echo off
rem ============================================================================
rem  Build instalatora: Nuitka w trybie "standalone" (folder, BEZ onefile).
rem  Wymagania: Windows, Python 3.10+ (python.org), internet przy pierwszym uruchomieniu
rem  (Nuitka sama pobierze kompilator MinGW64, jeśli nie masz Visual Studio Build Tools).
rem  Wynik: build\WWM-Spolszczenie\  oraz  WWM-Spolszczenie.zip
rem ============================================================================
setlocal
cd /d "%~dp0"

python -m venv .venv-build || goto :error
call .venv-build\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt nuitka || goto :error

if exist build rmdir /s /q build

python -m nuitka ^
  --standalone ^
  --assume-yes-for-downloads ^
  --enable-plugin=pyside6 ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=assets\ikona.ico ^
  --company-name="Arima" ^
  --product-name="Where Winds Meet - Instalator spolszczenia" ^
  --file-description="Instalator polskiego tlumaczenia Where Winds Meet" ^
  --file-version=2.2.0.0 ^
  --product-version=2.2.0.0 ^
  --include-package=wwmpl ^
  --nofollow-import-to=pytest,tkinter,unittest,PIL ^
  --output-dir=build ^
  --output-filename=WWM-Spolszczenie.exe ^
  main.py || goto :error

ren build\main.dist WWM-Spolszczenie
powershell -NoProfile -Command "Compress-Archive -Path 'build\WWM-Spolszczenie' -DestinationPath 'WWM-Spolszczenie.zip' -Force"
powershell -NoProfile -Command "Get-FileHash 'WWM-Spolszczenie.zip' -Algorithm SHA256 | Format-List"

echo.
echo Gotowe: WWM-Spolszczenie.zip (rozpakuj i uruchom WWM-Spolszczenie\WWM-Spolszczenie.exe)
echo Pamietaj: podpisz EXE, nie uzywaj UPX, wrzuc ZIP do GitHub Releases razem z SHA-256.
exit /b 0

:error
echo.
echo BLAD budowania. Sprawdz komunikaty powyzej.
exit /b 1
