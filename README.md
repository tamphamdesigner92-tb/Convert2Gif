# Video to GIF Studio (Web Application)

Ứng dụng Web viết bằng Python giúp chuyển đổi mọi định dạng video (`MP4`, `MOV`, `MKV`, `AVI`, `WEBM`, `FLV`, `WMV`, `M4V`, `TS`, `3GP`, `MPEG`, ...) sang ảnh động **GIF** chất lượng cao sử dụng thuật toán **2-Pass Palette (`palettegen` + `paletteuse`)** của FFmpeg.

## Cách khởi động nhanh (Tự động mở trình duyệt)

- **Trên macOS / Linux**:
  Mở Terminal hoặc chạy trực tiếp file [`start.sh`](./start.sh):
  ```bash
  ./start.sh
  ```
- **Trên Windows**:
  Nhấp đúp chuột (Double-click) vào file [`start.bat`](./start.bat).

Khi khởi chạy, ứng dụng sẽ tự động tìm cổng trống (mặc định `http://127.0.0.1:8080`) và mở trình duyệt Web của bạn.

## Tính năng chính
- **Hỗ trợ mọi định dạng video**: Phát trực tiếp trên trình duyệt hoặc tự động trích xuất ảnh thu nhỏ (thumbnail) và thông số kỹ thuật đối với các định dạng trình duyệt không hỗ trợ phát gốc (như `.mkv`, `.avi`, `.flv`, `.wmv`).
- **Tuỳ chỉnh linh hoạt**:
  - Cắt đoạn video theo giây bắt đầu / kết thúc (có nút lấy mốc thời gian trực tiếp từ khung phát video).
  - Chọn độ phân giải (`320px`, `480px`, `640px`, `720px`, `1080px`, hoặc giữ nguyên gốc).
  - Tuỳ chỉnh tốc độ khung hình (`10` – `30 FPS`) và tốc độ phát (`0.5x` – `2.0x`).
  - Hiệu ứng chuyển động: Bình thường, Tua ngược (`Reverse`), hoặc `Boomerang` (Tiến + Lùi).
  - Tuỳ chọn bảng màu Dithering (`Sierra2_4a`, `Floyd-Steinberg`, `Bayer`, `None`) và số lượng màu tối đa (`64` – `256` màu).
- **Theo dõi tiến độ thời gian thực**: Hiển thị phần trăm tải lên và phần trăm render GIF trực tiếp.
- **Lưu trữ tiện lợi**: Tải trực tiếp trên trình duyệt hoặc nhấn **Mở thư mục GIF trên máy** để mở thư mục `outputs/`.
