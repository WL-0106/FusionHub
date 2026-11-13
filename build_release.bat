@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM   FusionHub 一键打包脚本
REM   源码唯一事实源：本脚本所在目录（改代码只在这里改）
REM   产物输出：源码上一级独立目录 FusionHub_release（可整体删除）
REM ============================================================

set "SRC=%~dp0"
set "OUT=%~dp0..\FusionHub_release"

echo ============================================
echo   FusionHub 一键打包
echo   源码目录: %SRC%
echo   输出目录: %OUT%
echo ============================================
echo.

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [1/4] 未检测到 PyInstaller，正在安装...
    python -m pip install pyinstaller --quiet
) else (
    echo [1/4] PyInstaller 已就绪
)

echo [2/4] 清理旧产物...
if exist "%OUT%" rmdir /s /q "%OUT%"

echo [3/4] 打包中（单文件 EXE，首次较慢，请稍候）...
python -m PyInstaller --clean --noconfirm "%SRC%FusionHub.spec"

echo.
echo [4/4] 检查结果...
if exist "%OUT%\FusionHub.exe" (
    echo   成功: %OUT%\FusionHub.exe
) else (
    echo   失败: 未生成 EXE，请查看上方错误信息
)
echo.
pause
