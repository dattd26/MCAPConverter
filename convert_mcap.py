"""
MCAP to MP4 Video Converter for Multi-Camera Streams
Chuyển đổi các part MCAP trong thư mục thành video MP4 hoàn chỉnh.
Hỗ trợ stream trực tiếp vào FFmpeg không tốn dung lượng tạm, giữ nguyên chất lượng (lossless copy).
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Đảm bảo in tiếng Việt và ký tự đặc biệt an toàn trên Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcap.reader import make_reader



def parse_compressed_video(raw_bytes: bytes) -> Tuple[Optional[int], Optional[bytes], str]:
    """
    Giải mã cấu trúc protobuf foxglove.CompressedVideo mà không cần protobuf runtime:
      field 1 (wire=2): timestamp (google.protobuf.Timestamp: 1=seconds, 2=nanos)
      field 2 (wire=2): frame_id (string)
      field 3 (wire=2): data (bytes)
      field 4 (wire=2): format (string)
    """
    pos = 0
    length = len(raw_bytes)
    ts_ns: Optional[int] = None
    data: Optional[bytes] = None
    fmt = "h265"

    while pos < length:
        val = 0
        shift = 0
        while pos < length:
            b = raw_bytes[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if b < 0x80:
                break
            shift += 7

        number = val >> 3
        wire = val & 7

        if wire == 0:
            while pos < length and raw_bytes[pos] >= 0x80:
                pos += 1
            pos += 1
        elif wire == 1:
            pos += 8
        elif wire == 2:
            sz = 0
            shift = 0
            while pos < length:
                b = raw_bytes[pos]
                pos += 1
                sz |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7

            field_bytes = raw_bytes[pos : pos + sz]
            pos += sz

            if number == 1:  # timestamp
                p2 = 0
                sec = 0
                nano = 0
                while p2 < len(field_bytes):
                    k2 = 0
                    s2 = 0
                    while p2 < len(field_bytes):
                        b2 = field_bytes[p2]
                        p2 += 1
                        k2 |= (b2 & 0x7F) << s2
                        if b2 < 0x80:
                            break
                        s2 += 7
                    n2 = k2 >> 3
                    w2 = k2 & 7
                    if w2 == 0:
                        v2 = 0
                        s2 = 0
                        while p2 < len(field_bytes):
                            b2 = field_bytes[p2]
                            p2 += 1
                            v2 |= (b2 & 0x7F) << s2
                            if b2 < 0x80:
                                break
                            s2 += 7
                        if n2 == 1:
                            sec = v2
                        elif n2 == 2:
                            nano = v2
                ts_ns = sec * 1_000_000_000 + nano
            elif number == 3:  # compressed video data
                data = field_bytes
            elif number == 4:  # video format (h265/hevc/h264)
                fmt = field_bytes.decode("utf-8", errors="ignore")
        elif wire == 5:
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire}")

    return ts_ns, data, fmt


def natural_sort_key(path: Path):
    """Sắp xếp tự nhiên theo số hiệu part (part_00000, part_00001, ...)."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", path.name)]


def find_mcap_files(directory: Path) -> List[Path]:
    """Tìm tất cả file .mcap trong thư mục và sắp xếp theo thứ tự số."""
    files = list(directory.glob("*.mcap"))
    files.sort(key=natural_sort_key)
    return files


def check_missing_parts(files: List[Path]):
    """Kiểm tra và cảnh báo nếu có các part bị gián đoạn / ngắt quãng."""
    indexed_parts = []
    for f in files:
        m = re.search(r"part_(\d+)", f.name)
        if m:
            indexed_parts.append((int(m.group(1)), f))

    if not indexed_parts:
        return

    gaps = []
    for i in range(len(indexed_parts) - 1):
        curr_idx = indexed_parts[i][0]
        next_idx = indexed_parts[i + 1][0]
        if next_idx > curr_idx + 1:
            gaps.append((curr_idx + 1, next_idx - 1))

    if gaps:
        print("\n" + "=" * 60)
        print("⚠️  CẢNH BÁO: Phát hiện các part bị gián đoạn trong thư mục:")
        for start, end in gaps:
            if start == end:
                print(f"   - Thiếu part_{start:05d}.mcap")
            else:
                print(f"   - Thiếu từ part_{start:05d}.mcap đến part_{end:05d}.mcap")
        print("   Các part hiện có vẫn sẽ được nối liên tục theo thứ tự thời gian.")
        print("=" * 60 + "\n")


def estimate_fps(sample_mcap: Path, topic: str, max_samples: int = 100) -> float:
    """Tự động tính toán FPS từ khoảng cách timestamp giữa các frame đầu tiên."""
    timestamps = []
    with open(sample_mcap, "rb") as f:
        reader = make_reader(f)
        for _, _, msg in reader.iter_messages(topics=[topic]):
            ts, _, _ = parse_compressed_video(msg.data)
            if ts is not None:
                timestamps.append(ts)
                if len(timestamps) >= max_samples:
                    break

    if len(timestamps) >= 2:
        deltas = [(b - a) / 1e9 for a, b in zip(timestamps, timestamps[1:]) if b > a]
        if deltas:
            median_dt = statistics.median(deltas)
            if median_dt > 0:
                fps = round(1.0 / median_dt, 3)
                return fps

    return 30.0  # Mặc định an toàn nếu không đọc được timestamp


class FFmpegStreamer:
    """Quản lý tiến trình FFmpeg để ghi stream trực tiếp qua pipe stdin."""

    def __init__(self, output_path: Path, fps: float, codec: str = "hevc", reencode_h264: bool = False):
        self.output_path = output_path
        self.fps = fps
        self.codec = codec
        self.reencode_h264 = reencode_h264
        self.frames_written = 0
        self.bytes_written = 0
        self.stderr_lines: List[str] = []

        cmd = [
            "ffmpeg",
            "-y",
            "-r",
            f"{self.fps}",
            "-f",
            self.codec,
            "-i",
            "pipe:0",
        ]

        if self.reencode_h264:
            cmd.extend([
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
            ])
        else:
            # Lossless remuxing: sao chép stream, gắn cờ tương thích hvc1 cho HEVC
            cmd.extend([
                "-c:v",
                "copy",
            ])
            if self.codec in ("hevc", "h265"):
                cmd.extend(["-tag:v", "hvc1"])

        cmd.append(str(output_path))
        self.cmd = cmd

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10 * 1024 * 1024,  # Buffer 10MB
        )

        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

    def _read_stderr(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                decoded = line.decode("utf-8", errors="ignore").strip()
                if decoded:
                    self.stderr_lines.append(decoded)
                    if len(self.stderr_lines) > 50:
                        self.stderr_lines.pop(0)
        except Exception:
            pass

    def write_frame(self, frame_data: bytes):
        if self.proc.stdin is not None:
            self.proc.stdin.write(frame_data)
            self.frames_written += 1
            self.bytes_written += len(frame_data)

    def close(self) -> int:
        if self.proc.stdin:
            try:
                self.proc.stdin.flush()
                self.proc.stdin.close()
            except Exception:
                pass

        ret_code = self.proc.wait()
        self._stderr_thread.join(timeout=2.0)
        return ret_code


def convert_folder(
    input_dir: Path,
    output_dir: Optional[Path] = None,
    camera_mode: str = "both",
    override_fps: Optional[float] = None,
    reencode_h264: bool = False,
):
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Lỗi: Thư mục nguồn không tồn tại: {input_dir}")
        sys.exit(1)

    mcap_files = find_mcap_files(input_dir)
    if not mcap_files:
        print(f"Lỗi: Không tìm thấy file .mcap nào trong {input_dir}")
        sys.exit(1)

    if output_dir is None:
        output_dir = input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    folder_name = input_dir.name
    print("=" * 60)
    print(f"  THƯ MỤC NGUỒN: {input_dir}")
    print(f"  TỔNG SỐ PHẦN (PARTS): {len(mcap_files)}")
    print(f"  THƯ MỤC ĐÍCH: {output_dir}")
    print(f"  CHẾ ĐỘ CAMERA: {camera_mode}")
    print(f"  ĐỊNH DẠNG: {'H.264 Re-encode' if reencode_h264 else 'H.265 Lossless Copy'}")
    print("=" * 60)

    check_missing_parts(mcap_files)

    # Cấu hình các topic camera cần xử lý
    camera_configs = {
        "left": {
            "topic": "/top-left-camera/image-raw",
            "suffix": "top_left",
            "name": "Top Left Camera",
        },
        "right": {
            "topic": "/top-right-camera/image-raw",
            "suffix": "top_right",
            "name": "Top Right Camera",
        },
    }

    active_cameras = {}
    if camera_mode in ("both", "left"):
        active_cameras["left"] = camera_configs["left"]
    if camera_mode in ("both", "right"):
        active_cameras["right"] = camera_configs["right"]

    # Ước lượng FPS
    sample_topic = list(active_cameras.values())[0]["topic"]
    if override_fps is not None and override_fps > 0:
        fps = override_fps
        print(f"⏱️  FPS được chỉ định: {fps:.3f}")
    else:
        fps = estimate_fps(mcap_files[0], sample_topic)
        print(f"⏱️  Tự động nhận diện FPS: {fps:.3f}")

    # Khởi tạo các FFmpegStreamer cho từng camera
    streamers: Dict[str, FFmpegStreamer] = {}
    topic_to_cam_key: Dict[str, str] = {}

    for cam_key, cam_info in active_cameras.items():
        out_filename = f"{folder_name}_{cam_info['suffix']}.mp4"
        out_path = output_dir / out_filename
        streamer = FFmpegStreamer(out_path, fps=fps, codec="hevc", reencode_h264=reencode_h264)
        streamers[cam_key] = streamer
        topic_to_cam_key[cam_info["topic"]] = cam_key
        print(f"🎥 Khởi tạo xuất {cam_info['name']} -> {out_path.name}")

    monitored_topics = list(topic_to_cam_key.keys())

    start_time = time.perf_counter()
    total_frames = 0
    parts_metadata = []
    global_frame_idx = 0

    print("\n🚀 Bắt đầu chuyển đổi dữ liệu...")

    for idx, mcap_path in enumerate(mcap_files, 1):
        part_start_time = time.perf_counter()
        part_frames = {k: 0 for k in active_cameras}
        part_timestamps = []

        try:
            with open(mcap_path, "rb") as f:
                reader = make_reader(f)
                for schema, channel, msg in reader.iter_messages(topics=monitored_topics):
                    cam_key = topic_to_cam_key.get(channel.topic)
                    if not cam_key:
                        continue

                    ts, frame_bytes, _ = parse_compressed_video(msg.data)
                    if frame_bytes:
                        streamers[cam_key].write_frame(frame_bytes)
                        part_frames[cam_key] += 1
                        total_frames += 1
                        # Lưu timestamp từ camera đại diện (left hoặc right đầu tiên)
                        if cam_key == list(active_cameras.keys())[0] and ts is not None:
                            part_timestamps.append(ts)

            part_count = max(part_frames.values()) if part_frames else 0
            part_idx_match = re.search(r"part_(\d+)", mcap_path.name)
            part_num = int(part_idx_match.group(1)) if part_idx_match else idx - 1

            parts_metadata.append({
                "file_name": mcap_path.name,
                "part_index": part_num,
                "start_frame_idx": global_frame_idx,
                "end_frame_idx": global_frame_idx + part_count - 1 if part_count > 0 else global_frame_idx,
                "frame_count": part_count,
                "start_time_ns": part_timestamps[0] if part_timestamps else None,
                "end_time_ns": part_timestamps[-1] if part_timestamps else None,
                "frame_timestamps_ns": part_timestamps,
            })
            global_frame_idx += part_count

            part_duration = time.perf_counter() - part_start_time
            part_frame_sum = sum(part_frames.values())
            part_fps = (part_frame_sum / part_duration) if part_duration > 0 else 0

            frames_desc = ", ".join(f"{k}: {part_frames[k]}" for k in active_cameras)
            print(
                f" [{idx:02d}/{len(mcap_files):02d}] {mcap_path.name:<18} "
                f"| Frames ({frames_desc}) "
                f"| Tốc độ: {part_fps:5.0f} fps ({part_duration:4.2f}s)"
            )
        except Exception as e:
            print(f"❌ Lỗi khi đọc file {mcap_path.name}: {e}")


    print("\n⏳ Đang kết thúc đóng gói các file video MP4...")
    for cam_key, streamer in streamers.items():
        ret = streamer.close()
        out_path = streamer.output_path
        if ret == 0 and out_path.exists():
            file_size_mb = out_path.stat().st_size / (1024 * 1024)
            duration_sec = streamer.frames_written / streamer.fps if streamer.fps > 0 else 0
            print(
                f"✅ Hoàn tất [{active_cameras[cam_key]['name']}]:\n"
                f"   - File: {out_path}\n"
                f"   - Số frames: {streamer.frames_written:,}\n"
                f"   - Thời lượng: {duration_sec / 60:.2f} phút ({duration_sec:.1f} giây)\n"
                f"   - Kích thước: {file_size_mb:.2f} MB"
            )
        else:
            print(f"❌ FFmpeg trả về mã lỗi {ret} cho camera {cam_key}!")
            if streamer.stderr_lines:
                print("   Chi tiết lỗi FFmpeg:")
                for line in streamer.stderr_lines[-10:]:
                    print(f"   {line}")

    # Lưu metadata phiên chuyển đổi vào session.json để hỗ trợ chuyển đổi ngược về MCAP
    session_data = {
        "session_name": folder_name,
        "input_directory": str(input_dir),
        "fps": fps,
        "camera_mode": camera_mode,
        "cameras": {
            k: {
                "name": active_cameras[k]["name"],
                "topic": active_cameras[k]["topic"],
                "video_file": streamers[k].output_path.name,
                "total_frames": streamers[k].frames_written,
            }
            for k in active_cameras
        },
        "total_parts": len(mcap_files),
        "total_frames": total_frames // len(active_cameras) if active_cameras else total_frames,
        "parts": parts_metadata,
    }

    session_file = output_dir / f"{folder_name}_session.json"
    with open(session_file, "w", encoding="utf-8") as sf:
        json.dump(session_data, sf, indent=2)

    print(f"\n📋 Đã lưu metadata phiên chuyển đổi tại: {session_file}")

    total_time = time.perf_counter() - start_time
    print(f"\n🎉 Hoàn thành toàn bộ tiến trình trong {total_time:.2f} giây! ({total_frames / total_time:.1f} fps tổng cộng)")


def main():
    parser = argparse.ArgumentParser(
        description="Chuyển đổi các part MCAP thành video MP4 hoàn chỉnh (top-left & top-right)."
    )
    parser.add_argument(
        "input_dir",
        type=str,
        nargs="?",
        default=r"D:\TST\HumanEgo_Videos\20261019_SPA-20261020T023851Z-1-002\20261019_SPA\20261019_040342",
        help="Đường dẫn đến thư mục chứa các file .mcap",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Thư mục lưu video đầu ra (mặc định lưu tại thư mục nguồn)",
    )
    parser.add_argument(
        "--camera",
        "-c",
        choices=["both", "left", "right"],
        default="both",
        help="Lựa chọn camera cần xuất: both (cả 2), left (top-left), right (top-right)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Chỉ định FPS thủ công (mặc định tự động nhận diện từ timestamps)",
    )
    parser.add_argument(
        "--h264",
        action="store_true",
        help="Mã hóa lại sang định dạng H.264 (tương thích mọi thiết bị/trình duyệt)",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else None

    convert_folder(
        input_dir=input_dir,
        output_dir=output_dir,
        camera_mode=args.camera,
        override_fps=args.fps,
        reencode_h264=args.h264,
    )


if __name__ == "__main__":
    main()
