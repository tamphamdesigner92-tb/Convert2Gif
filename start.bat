@echo off
chcp 65001 >nul
title Video to GIF Studio - Web Application

:: Di chuyển vào đúng thư mục chứa file .bat
cd /d "%~dp0"

echo ============================================================
echo   Đang khởi động Video to GIF Studio (Windows)...
echo ============================================================

:: Kiểm tra lệnh python hoặc py launcher trên Windows
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py -3"
    ) else (
        echo [LỖI] Không tìm thấy Python trên hệ thống Windows.
        echo Vui lòng cài đặt Python 3 từ https://www.python.org và tích chọn "Add Python to PATH".
        pause
        exit /b 1
    )
)

:: Kiểm tra FFmpeg; nếu chưa có trên hệ thống thì tự động tạo .venv và cài imageio-ffmpeg
where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Không tìm thấy FFmpeg trong PATH. Đang chuẩn bị môi trường FFmpeg tích hợp...
    if not exist ".venv\Scripts\python.exe" (
        %PYTHON_CMD% -m venv .venv
    )
    ".venv\Scripts\python.exe" -c "import imageio_ffmpeg" >nul 2>nul
    if %errorlevel% neq 0 (
        ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    )
    set "PYTHON_CMD=.venv\Scripts\python.exe"
)

:: Khởi chạy máy chủ Web và tự động mở trình duyệt mặc định
%PYTHON_CMD% app.py %*

if %errorlevel% neq 0 (
    echo.
    echo [LỖI] Ứng dụng đã dừng đột ngột.
    pause
)
