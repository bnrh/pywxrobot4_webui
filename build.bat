@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM  wxrobot_webui — Nuitka Windows 独立打包
REM  产物: dist\wxrobot_webui.dist\wxrobot_webui.exe（含依赖 DLL，无需安装 Python）
REM ============================================================

set "APP_NAME=wxrobot_webui"
set "OUT_DIR=dist"
set "DIST_DIR=%OUT_DIR%\%APP_NAME%.dist"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 python，请先安装 Python 3.11+ 并加入 PATH。
  exit /b 1
)

echo.
echo ===== [1/4] 构建前端静态资源 =====
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 npm。打包前需要 Node.js 以执行 npm run build。
  exit /b 1
)
if not exist "node_modules\" (
  echo 安装前端依赖...
  call npm install
  if errorlevel 1 exit /b 1
)
call npm run build
if errorlevel 1 (
  echo [ERROR] 前端构建失败。
  exit /b 1
)
if not exist "static\dist\" (
  echo [ERROR] 未生成 static\dist，请检查 Vite 构建。
  exit /b 1
)

echo.
echo ===== [2/4] 安装 Python 依赖与 Nuitka =====
python -m pip install -U pip setuptools wheel
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m pip install -U "nuitka>=2.5" "ordered-set" "zstandard"
if errorlevel 1 exit /b 1

echo.
echo ===== [3/4] Nuitka 编译（standalone，首次会下载 MinGW，较慢）=====
if exist "%OUT_DIR%\%APP_NAME%.build\" rmdir /s /q "%OUT_DIR%\%APP_NAME%.build"
if exist "%DIST_DIR%\" rmdir /s /q "%DIST_DIR%"

python -m nuitka ^
  --standalone ^
  --assume-yes-for-downloads ^
  --remove-output ^
  --output-dir="%OUT_DIR%" ^
  --output-filename="%APP_NAME%.exe" ^
  --windows-console-mode=force ^
  --include-package=core ^
  --include-package=server ^
  --include-package=runtime ^
  --include-package=messaging ^
  --include-package=manager ^
  --include-package=routes ^
  --include-package=ai_assistant ^
  --include-package=plugins ^
  --include-package=utils ^
  --include-package=uvicorn ^
  --include-package=fastapi ^
  --include-package=starlette ^
  --include-package=pydantic ^
  --include-package=pydantic_core ^
  --include-package=anyio ^
  --include-package=httpx ^
  --include-package=httpcore ^
  --include-package=multipart ^
  --include-package=loguru ^
  --include-package=PIL ^
  --include-package=numpy ^
  --include-package=zxingcpp ^
  --include-package-data=PIL ^
  --include-package-data=zxingcpp ^
  --include-data-dir=frontend=frontend ^
  --include-data-dir=static=static ^
  --nofollow-import-to=pytest ^
  --nofollow-import-to=tests ^
  --nofollow-import-to=_pytest ^
  --nofollow-import-to=py ^
  --nofollow-import-to=node_modules ^
  --company-name=wxrobot ^
  --product-name=wxrobot_webui ^
  --file-description=wxrobot WebUI Plugin Server ^
  main.py

if errorlevel 1 (
  echo [ERROR] Nuitka 编译失败。
  exit /b 1
)

REM Nuitka 默认以入口脚本名生成目录 main.dist；统一重命名为 wxrobot_webui.dist
if exist "%OUT_DIR%\main.dist\" (
  if exist "%DIST_DIR%\" rmdir /s /q "%DIST_DIR%"
  move /y "%OUT_DIR%\main.dist" "%DIST_DIR%" >nul
)

if not exist "%DIST_DIR%\%APP_NAME%.exe" (
  echo [ERROR] 未找到产物: %DIST_DIR%\%APP_NAME%.exe
  echo 请检查 %OUT_DIR% 目录下的实际输出。
  dir /b "%OUT_DIR%"
  exit /b 1
)

echo.
echo ===== [4/4] 完成 =====
echo 可执行文件: %CD%\%DIST_DIR%\%APP_NAME%.exe
echo.
echo 使用说明:
echo   1. 将整个 "%DIST_DIR%" 文件夹拷贝到目标机器即可运行（无需安装 Python^)
echo   2. 数据库 / uploads / logs 会写在 exe 同目录
echo   3. 容器或远程访问时请在系统设置中将 host 设为 0.0.0.0
echo.
exit /b 0
