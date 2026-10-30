"""
MCAPConverter Studio - Launcher Entrypoint
Tự động khởi chạy FastAPI Server và mở giao diện Web trên trình duyệt mặc định.
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Đảm bảo mã hóa UTF-8 cho console Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import uvicorn

PORT = 8000
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def open_browser():
    time.sleep(1.2)
    print(f"\n[TRÌNH DUYỆT] Đang tự động mở giao diện tại: {URL}")
    webbrowser.open(URL)


def main():
    print("=" * 65)
    print("           MCAP STUDIO - BỘ CÔNG CỤ XỬ LÝ 2 CHIỀU MCAP")
    print("=" * 65)
    print(f" * Khởi động máy chủ cục bộ: {URL}")
    print(" * Môi trường Python: " + sys.executable)
    print(" * Nhấn Ctrl+C trong cửa sổ này để tắt máy chủ khi dùng xong.")
    print("=" * 65 + "\n")

    # Luồng mở trình duyệt
    threading.Thread(target=open_browser, daemon=True).start()

    # Chạy uvicorn server
    uvicorn.run("gui.backend.app:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
