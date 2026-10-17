#!/usr/bin/env bash
# ==============================================================================
# Khởi động ứng dụng Video to GIF Converter và tự động mở trình duyệt (macOS/Linux)
# ==============================================================================

set -e

# Di chuyển vào thư mục chứa file script
cd "$(dirname "$0")"

# Bổ sung đường dẫn Homebrew cho macOS (Apple Silicon & Intel)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "============================================================"
echo "  Đang khởi động Video to GIF Studio (macOS / Linux)..."
echo "============================================================"

# Kiểm tra Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[LỖI] Không tìm thấy Python 3 trên máy."
    echo "Vui lòng cài đặt Python 3 từ https://www.python.org hoặc qua Homebrew: brew install python"
    read -r -p "Nhấn Enter để đóng..."
    exit 1
fi

# Kiểm tra FFmpeg; nếu chưa có trên hệ thống thì tự động cài imageio-ffmpeg vào .venv
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[!] Không tìm thấy FFmpeg hệ thống. Đang kiểm tra gói imageio-ffmpeg dự phòng..."
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi
    source .venv/bin/activate
    python3 -c "import imageio_ffmpeg" >/dev/null 2>&1 || pip install -r requirements.txt
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python3"
fi

# Chạy ứng dụng (app.py sẽ tự động chọn cổng trống và mở trình duyệt mặc định)
exec "$PYTHON_CMD" app.py "$@"
