#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Video to GIF Converter - Web Application
Hỗ trợ chuyển đổi mọi định dạng video sang ảnh động GIF chất lượng cao bằng FFmpeg.
"""

import argparse
import json
import mimetypes
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Thư mục gốc của ứng dụng
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Đảm bảo PATH trên macOS/Linux bao gồm Homebrew
if platform.system() != "Windows":
    extra_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
    current_path = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in current_path and os.path.isdir(p):
            current_path = f"{p}:{current_path}"
    os.environ["PATH"] = current_path

# Quản lý trạng thái các tác vụ chuyển đổi (in-memory)
JOBS = {}
JOBS_LOCK = threading.Lock()


def get_ffmpeg_binary() -> str:
    """Tìm đường dẫn thực thi của FFmpeg từ hệ thống hoặc imageio-ffmpeg."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def get_ffprobe_binary() -> str:
    """Tìm đường dẫn thực thi của FFprobe từ hệ thống."""
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        return ffprobe_path
    return ""


def probe_video_info(filepath: Path) -> dict:
    """Lấy thông tin thời lượng, độ phân giải và FPS của video."""
    info = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "codec": "unknown",
        "size_bytes": filepath.stat().st_size if filepath.exists() else 0,
    }

    ffprobe = get_ffprobe_binary()
    if ffprobe:
        try:
            cmd = [
                ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,codec_name:format=duration",
                "-of", "json",
                str(filepath),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                streams = data.get("streams", [])
                if streams:
                    s = streams[0]
                    info["width"] = int(s.get("width", 0) or 0)
                    info["height"] = int(s.get("height", 0) or 0)
                    info["codec"] = s.get("codec_name", "unknown")
                    fps_raw = s.get("r_frame_rate", "0/1")
                    if "/" in fps_raw:
                        num, den = fps_raw.split("/", 1)
                        if float(den) > 0:
                            info["fps"] = round(float(num) / float(den), 2)
                fmt = data.get("format", {})
                if fmt.get("duration"):
                    info["duration"] = round(float(fmt["duration"]), 2)
                return info
        except Exception:
            pass

    # Fallback: đọc thông tin qua stderr của ffmpeg -i
    ffmpeg = get_ffmpeg_binary()
    if ffmpeg:
        try:
            res = subprocess.run(
                [ffmpeg, "-i", str(filepath)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            stderr = res.stderr
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
            if dur_match:
                h, m, s = dur_match.groups()
                info["duration"] = round(int(h) * 3600 + int(m) * 60 + float(s), 2)
            dim_match = re.search(r"Stream.*Video:.*?,\s*(\d{2,5})x(\d{2,5})", stderr)
            if dim_match:
                info["width"] = int(dim_match.group(1))
                info["height"] = int(dim_match.group(2))
            fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
            if fps_match:
                info["fps"] = float(fps_match.group(1))
        except Exception:
            pass

    return info


def extract_thumbnail(video_path: Path, thumb_path: Path, timestamp: float = 0.0) -> bool:
    """Trích xuất một khung hình JPEG từ video để xem trước (hỗ trợ cả định dạng trình duyệt không phát trực tiếp được)."""
    ffmpeg = get_ffmpeg_binary()
    if not ffmpeg:
        return False
    try:
        cmd = [
            ffmpeg, "-y",
            "-ss", str(max(0.0, timestamp)),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "3",
            str(thumb_path),
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=15)
        return res.returncode == 0 and thumb_path.exists()
    except Exception:
        return False


def run_conversion_job(job_id: str, params: dict):
    """Chạy tiến trình FFmpeg chuyển đổi Video sang GIF chất lượng cao với bộ lọc Palettegen + Paletteuse."""
    ffmpeg = get_ffmpeg_binary()
    if not ffmpeg:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = (
                "Không tìm thấy FFmpeg trên hệ thống. Vui lòng cài đặt FFmpeg "
                "(macOS: brew install ffmpeg | Windows: winget install Gyan.FFmpeg) "
                "hoặc chạy: pip install imageio-ffmpeg"
            )
        return

    input_path = Path(params["input_path"])
    output_filename = params["output_filename"]
    output_path = OUTPUT_DIR / output_filename

    start_time = float(params.get("start_time") or 0)
    end_time = float(params.get("end_time") or 0)
    fps = int(params.get("fps") or 15)
    width = int(params.get("width") or 480)
    speed = float(params.get("speed") or 1.0)
    dither = params.get("dither") or "sierra2_4a"
    max_colors = int(params.get("max_colors") or 256)
    loop = int(params.get("loop") if params.get("loop") is not None else 0)
    effect = params.get("effect") or "normal"  # normal, reverse, boomerang

    fps = max(1, min(50, fps))
    max_colors = max(16, min(256, max_colors))
    speed = max(0.25, min(4.0, speed))

    video_info = probe_video_info(input_path)
    total_video_duration = video_info.get("duration", 0.0)

    duration = 0.0
    if end_time > start_time:
        duration = end_time - start_time
    elif total_video_duration > start_time:
        duration = total_video_duration - start_time

    expected_out_duration = (duration / speed) if duration > 0 else 0.0
    if effect == "boomerang":
        expected_out_duration *= 2.0

    # Xây dựng chuỗi filter phức hợp cho chất lượng GIF tối ưu
    vf_parts = []
    if abs(speed - 1.0) > 0.01:
        pts_factor = round(1.0 / speed, 4)
        vf_parts.append(f"setpts={pts_factor}*PTS")

    vf_parts.append(f"fps={fps}")

    if width > 0:
        vf_parts.append(f"scale={width}:-1:flags=lanczos")
    else:
        vf_parts.append("scale=iw:ih:flags=lanczos")

    base_chain = ",".join(vf_parts)

    if effect == "reverse":
        effect_chain = f"{base_chain},reverse"
    elif effect == "boomerang":
        effect_chain = f"{base_chain},split[main][rev];[rev]reverse[rev_out];[main][rev_out]concat=n=2:v=1:a=0"
    else:
        effect_chain = base_chain

    if dither == "none":
        paletteuse_str = "paletteuse=dither=none"
    elif dither == "bayer":
        paletteuse_str = "paletteuse=dither=bayer:bayer_scale=3"
    else:
        paletteuse_str = f"paletteuse=dither={dither}"

    filter_complex = (
        f"[0:v]{effect_chain},split[s0][s1];"
        f"[s0]palettegen=max_colors={max_colors}:stats_mode=diff[p];"
        f"[s1][p]{paletteuse_str}"
    )

    cmd = [ffmpeg, "-y", "-hide_banner"]
    if start_time > 0:
        cmd.extend(["-ss", f"{start_time:.3f}"])
    if duration > 0 and end_time > start_time:
        cmd.extend(["-t", f"{duration:.3f}"])

    cmd.extend([
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-loop", str(loop),
        "-progress", "pipe:1",
        "-nostats",
        str(output_path),
    ])

    with JOBS_LOCK:
        JOBS[job_id]["status"] = "processing"
        JOBS[job_id]["progress"] = 5

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Đọc tiến độ thực tế từ stdout (-progress pipe:1)
        if proc.stdout:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    val_str = line.split("=", 1)[1]
                    if val_str.isdigit() and expected_out_duration > 0:
                        out_sec = int(val_str) / 1_000_000.0
                        pct = int(min(98, max(5, (out_sec / expected_out_duration) * 100)))
                        with JOBS_LOCK:
                            JOBS[job_id]["progress"] = pct

        _, stderr_output = proc.communicate()

        if proc.returncode != 0 or not output_path.exists():
            err_lines = [l for l in (stderr_output or "").splitlines() if l.strip()]
            short_err = "\n".join(err_lines[-6:]) if err_lines else "Quá trình chuyển đổi thất bại."
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = short_err
            return

        out_info = probe_video_info(output_path)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["progress"] = 100
            JOBS[job_id]["output_url"] = f"/outputs/{urllib.parse.quote(output_filename)}"
            JOBS[job_id]["download_url"] = f"/api/download/{urllib.parse.quote(output_filename)}"
            JOBS[job_id]["output_size"] = output_path.stat().st_size
            JOBS[job_id]["output_width"] = out_info.get("width", 0)
            JOBS[job_id]["output_height"] = out_info.get("height", 0)
            JOBS[job_id]["completed_at"] = time.strftime("%H:%M:%S")

    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)


class GifConverterRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler phục vụ giao diện Web và các API chuyển đổi."""

    def log_message(self, format_str, *args):
        # Giữ log gọn gàng trên terminal
        pass

    def _send_json(self, data: dict, status: int = HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_file(self, filepath: Path, content_type: str = None, download_name: str = None):
        if not filepath.exists() or not filepath.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        if not content_type:
            content_type, _ = mimetypes.guess_type(str(filepath))
            content_type = content_type or "application/octet-stream"

        file_size = filepath.stat().st_size

        # Hỗ trợ HTTP Range cho video preview trên trình duyệt
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                byte_range = range_header.replace("bytes=", "").split("-")
                start = int(byte_range[0]) if byte_range[0] else 0
                end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1

                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.end_headers()

                with open(filepath, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            except Exception:
                pass

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        if download_name:
            encoded_name = urllib.parse.quote(download_name)
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{download_name}\"; filename*=UTF-8''{encoded_name}",
            )
        self.end_headers()

        with open(filepath, "rb") as f:
            shutil.copyfileobj(f, self.wfile, length=65536)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            index_file = TEMPLATES_DIR / "index.html"
            self._serve_file(index_file, "text/html; charset=utf-8")
            return

        if path == "/api/system-info":
            ffmpeg_bin = get_ffmpeg_binary()
            self._send_json({
                "ffmpeg_available": bool(ffmpeg_bin),
                "ffmpeg_path": ffmpeg_bin,
                "platform": platform.system(),
                "output_dir": str(OUTPUT_DIR),
            })
            return

        if path.startswith("/api/status/"):
            job_id = path.split("/api/status/", 1)[1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    self._send_json({"error": "Không tìm thấy tiến trình"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(dict(job))
            return

        if path.startswith("/uploads/"):
            rel_name = urllib.parse.unquote(path.split("/uploads/", 1)[1])
            safe_name = Path(rel_name).name
            self._serve_file(UPLOAD_DIR / safe_name)
            return

        if path.startswith("/outputs/"):
            rel_name = urllib.parse.unquote(path.split("/outputs/", 1)[1])
            safe_name = Path(rel_name).name
            self._serve_file(OUTPUT_DIR / safe_name, "image/gif")
            return

        if path.startswith("/api/download/"):
            rel_name = urllib.parse.unquote(path.split("/api/download/", 1)[1])
            safe_name = Path(rel_name).name
            self._serve_file(OUTPUT_DIR / safe_name, "image/gif", download_name=safe_name)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            query = urllib.parse.parse_qs(parsed.query)
            raw_filename = query.get("filename", ["video.mp4"])[0]
            orig_name = Path(urllib.parse.unquote(raw_filename)).name
            ext = Path(orig_name).suffix.lower() or ".mp4"
            file_id = uuid.uuid4().hex[:10]
            saved_name = f"{file_id}{ext}"
            saved_path = UPLOAD_DIR / saved_name

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                self._send_json({"error": "File tải lên trống."}, HTTPStatus.BAD_REQUEST)
                return

            try:
                remaining = content_length
                with open(saved_path, "wb") as out_f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        out_f.write(chunk)
                        remaining -= len(chunk)

                info = probe_video_info(saved_path)
                thumb_name = f"{file_id}_thumb.jpg"
                thumb_path = UPLOAD_DIR / thumb_name
                thumb_time = min(1.0, info["duration"] * 0.2) if info["duration"] > 0 else 0.0
                has_thumb = extract_thumbnail(saved_path, thumb_path, thumb_time)

                self._send_json({
                    "file_id": file_id,
                    "original_name": orig_name,
                    "saved_name": saved_name,
                    "video_url": f"/uploads/{urllib.parse.quote(saved_name)}",
                    "thumb_url": f"/uploads/{urllib.parse.quote(thumb_name)}" if has_thumb else "",
                    "info": info,
                })
            except Exception as exc:
                self._send_json({"error": f"Lỗi khi lưu file: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/convert":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                self._send_json({"error": "Dữ liệu JSON không hợp lệ"}, HTTPStatus.BAD_REQUEST)
                return

            saved_name = Path(data.get("saved_name", "")).name
            input_path = UPLOAD_DIR / saved_name
            if not saved_name or not input_path.exists():
                self._send_json({"error": "Không tìm thấy file video gốc để chuyển đổi."}, HTTPStatus.BAD_REQUEST)
                return

            orig_stem = Path(data.get("original_name", "video")).stem
            # Làm sạch tên file xuất
            safe_stem = re.sub(r"[^a-zA-Z0-9_\-\u00C0-\u1EF9 ]", "_", orig_stem).strip() or "output"
            job_id = uuid.uuid4().hex[:8]
            output_filename = f"{safe_stem}_{job_id}.gif"

            job_data = {
                "job_id": job_id,
                "status": "queued",
                "progress": 0,
                "original_name": data.get("original_name", saved_name),
                "output_filename": output_filename,
                "error": "",
            }
            with JOBS_LOCK:
                JOBS[job_id] = job_data

            conv_params = {
                "input_path": str(input_path),
                "output_filename": output_filename,
                "start_time": data.get("start_time", 0),
                "end_time": data.get("end_time", 0),
                "fps": data.get("fps", 15),
                "width": data.get("width", 480),
                "speed": data.get("speed", 1.0),
                "dither": data.get("dither", "sierra2_4a"),
                "max_colors": data.get("max_colors", 256),
                "loop": data.get("loop", 0),
                "effect": data.get("effect", "normal"),
            }

            worker = threading.Thread(
                target=run_conversion_job,
                args=(job_id, conv_params),
                daemon=True,
            )
            worker.start()

            self._send_json({"job_id": job_id, "status": "queued"})
            return

        if path == "/api/open-folder":
            try:
                sys_name = platform.system()
                if sys_name == "Darwin":
                    subprocess.Popen(["open", str(OUTPUT_DIR)])
                elif sys_name == "Windows":
                    os.startfile(str(OUTPUT_DIR))
                else:
                    subprocess.Popen(["xdg-open", str(OUTPUT_DIR)])
                self._send_json({"success": True})
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")


def find_free_port(preferred_port: int = 8080) -> int:
    """Kiểm tra cổng ưu tiên, nếu bận sẽ tự động chọn cổng trống tiếp theo."""
    for port in range(preferred_port, preferred_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred_port


def main():
    parser = argparse.ArgumentParser(description="Video to GIF Converter Web App")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port number (default: 8080)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Không tự động mở trình duyệt khi khởi động",
    )
    args = parser.parse_args()

    port = find_free_port(args.port)
    url = f"http://{args.host}:{port}"

    ffmpeg_bin = get_ffmpeg_binary()
    print("=" * 60)
    print("  🎬 VIDEO TO GIF CONVERTER - WEB APPLICATION")
    print("=" * 60)
    print(f"  • Địa chỉ Web : {url}")
    print(f"  • Thư mục GIF : {OUTPUT_DIR}")
    if ffmpeg_bin:
        print(f"  • FFmpeg      : Đã sẵn sàng ({ffmpeg_bin})")
    else:
        print("  • FFmpeg      : [!] Chưa tìm thấy FFmpeg trên hệ thống")
    print("  • Nhấn Ctrl+C để dừng ứng dụng.")
    print("=" * 60)

    if not args.no_browser:
        def _open():
            time.sleep(0.8)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    server = ThreadingHTTPServer((args.host, port), GifConverterRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ Video to GIF Converter.")
        server.server_close()


if __name__ == "__main__":
    main()
