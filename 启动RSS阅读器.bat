@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PYW="
if exist "%~dp0python\pythonw.exe" set "PYW=%~dp0python\pythonw.exe"
if not defined PYW if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe" set "PYW=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
if defined PYW goto run
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if defined PYW goto run

echo 没有找到 pythonw.exe，无法启动。
echo 请安装 Python 3.10+（勾选 "Add python.exe to PATH"），或把便携版 Python 放到本目录的 python\ 子目录。
echo.
pause
exit /b 1

:run
start "" "%PYW%" "%~dp0run.py"
exit /b 0
