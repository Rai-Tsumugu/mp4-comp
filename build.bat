@echo off
chcp 65001 >nul

echo ==============================
echo  mp4-comp ビルドスクリプト
echo ==============================
echo.

:: PyInstaller がインストールされているか確認
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller が見つかりません。インストールしています...
    pip install pyinstaller
    if errorlevel 1 (
        echo [エラー] PyInstaller のインストールに失敗しました。
        pause
        exit /b 1
    )
)

echo ビルドを開始します...
echo.

:: 以前のビルド成果物を削除
if exist dist\mp4-comp.exe (
    echo 以前の dist\mp4-comp.exe を削除しています...
    del /f dist\mp4-comp.exe
)

:: PyInstaller でビルド
pyinstaller mp4comp.spec

if errorlevel 1 (
    echo.
    echo [エラー] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo ==============================
echo  ビルド完了!
echo  dist\mp4-comp.exe を確認してください。
echo.
echo  注意: 実行には FFmpeg が必要です。
echo  ffmpeg と ffprobe が PATH に含まれている
echo  必要があります。
echo ==============================
echo.
pause
