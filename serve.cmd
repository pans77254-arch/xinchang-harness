@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [serve.cmd] cwd=%CD%
echo [serve.cmd] PATH 中的 python / py：
where python 2>nul
where py 2>nul
echo.

set "PY_EXE="

REM 1) 优先 py -3（Windows 官方启动器，避开商店占位符）
py -3 -c "print('ok')" >nul 2>nul
if not errorlevel 1 (
  set "PY_CMD=py -3"
  goto :run
)

REM 2) 扫描 where python，跳过 WindowsApps 假 python
for /f "delims=" %%I in ('where python 2^>nul') do (
  echo %%I | findstr /I "WindowsApps" >nul
  if errorlevel 1 (
    "%%I" -c "print('ok')" >nul 2>nul
    if not errorlevel 1 (
      set "PY_CMD=%%I"
      goto :run
    )
  ) else (
    echo [serve.cmd] 跳过商店占位符: %%I
  )
)

REM 3) 常见安装路径
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
  "C:\Python312\python.exe"
  "C:\Python311\python.exe"
) do (
  if exist %%~P (
    %%~P -c "print('ok')" >nul 2>nul
    if not errorlevel 1 (
      set "PY_CMD=%%~P"
      goto :run
    )
  )
)

echo [serve.cmd] ERROR: 未找到可用的 Python。
echo.
echo 原因：exit 9009 通常是 PATH 里只有「Microsoft Store 占位 python」，真正的 python.exe 不存在。
echo 处理：安装 Python 3.10+ 并勾选 Add python.exe to PATH，
echo 或安装后用: py -3 serve.py start
echo 下载: https://www.python.org/downloads/windows/
exit /b 9009

:run
if "%~1"=="" (set "ACTION=status") else (set "ACTION=%~1")
echo [serve.cmd] use=!PY_CMD!
echo [serve.cmd] action=%ACTION%
echo.

!PY_CMD! -u "%ROOT%serve.py" %ACTION%
set "CODE=!errorlevel!"
echo.
echo [serve.cmd] exit_code=!CODE!
if !CODE! == 9009 (
  echo [serve.cmd] 仍是 9009：请安装 Python 或用「py -3 serve.py start」
)
exit /b !CODE!
