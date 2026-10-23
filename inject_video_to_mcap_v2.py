"""
MCAP Video Injector & Repacker
Nạp lại video MP4 (đã chỉnh sửa/làm mờ mặt/trim) vào cấu trúc file MCAP multipart ban đầu.
Bảo toàn 100% dữ liệu cảm biến (IMU, TF, Camera Info, Timestamps) và cấu trúc thư mục gốc.
 
Bản tối ưu tốc độ:
  - Tắt nén chunk MCAP (payload đã là HEVC, nén lại vô ích) và tắt CRC.
  - Đọc pipe ffmpeg theo chunk lớn, tách frame không còn O(n^2).
  - Cho phép chọn encoder GPU (--encoder) khi video đầu vào không phải HEVC.
  - Hiện cảnh báo rõ khi đang phải re-encode, và in lỗi ffmpeg nếu có.
"""
 
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple
 
# Đảm bảo in tiếng Việt an toàn trên Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
 
from mcap.reader import make_reader
from mcap.writer import CompressionType, Writer
 
from convert_mcap import parse_compressed_video
 
# Kích thước đọc pipe từ ffmpeg (byte)
READ_CHUNK_SIZE = 4 * 1024 * 1024
# Kích thước chunk khi ghi MCAP (byte)
MCAP_CHUNK_SIZE = 4 * 1024 * 1024
 
ENCODER_CHOICES = ["libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf"]
 
 
def ensure_ffmpeg() -> str:
    """Tự động tìm kiếm ffmpeg, load PATH mới từ Windows Registry nếu terminal chưa khởi động lại."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return ffmpeg_bin
 
    if sys.platform == "win32":
        try:
            import winreg
            for key_path in [r"Environment", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"]:
                root = winreg.HKEY_LOCAL_MACHINE if "CurrentControlSet" in key_path else winreg.HKEY_CURRENT_USER
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        val, _ = winreg.QueryValueEx(key, "Path")
                        for p in val.split(";"):
                            p = p.strip()
                            if p and p not in os.environ["PATH"]:
                                os.environ["PATH"] += ";" + p
                except Exception:
                    pass
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                return ffmpeg_bin
        except Exception:
            pass
 
    return "ffmpeg"
 
 
def make_writer(out_f) -> Writer:
    """
    Tạo MCAP Writer không nén chunk và không tính CRC (nhanh hơn rõ rệt).
    Payload video HEVC đã nén sẵn nên zstd chỉ tốn CPU mà không giảm dung lượng.
    """
    kwargs = dict(chunk_size=MCAP_CHUNK_SIZE, compression=CompressionType.NONE)
    try:
        return Writer(out_f, enable_crcs=False, enable_data_crcs=False, **kwargs)
    except TypeError:
        # Bản mcap cũ không có tham số CRC
        return Writer(out_f, **kwargs)
 
 
def encode_varint(value: int) -> bytes:
    """Mã hóa một số nguyên dương thành định dạng protobuf varint."""
    parts = []
    while value >= 0x80:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)
 
 
def encode_timestamp(ts_ns: int) -> bytes:
    """Mã hóa google.protobuf.Timestamp từ số nanosecond."""
    seconds = ts_ns // 1_000_000_000
    nanos = ts_ns % 1_000_000_000
    buf = bytearray()
    if seconds > 0:
        buf.extend(encode_varint((1 << 3) | 0))  # field 1, wire 0
        buf.extend(encode_varint(seconds))
    if nanos > 0:
        buf.extend(encode_varint((2 << 3) | 0))  # field 2, wire 0
        buf.extend(encode_varint(nanos))
    return bytes(buf)
 
 
def encode_compressed_video(ts_ns: int, frame_id: str, data: bytes, fmt: str = "h265") -> bytes:
    """Đóng gói dữ liệu khung hình vào protobuf foxglove.CompressedVideo."""
    ts_bytes = encode_timestamp(ts_ns)
    frame_id_bytes = frame_id.encode("utf-8")
    fmt_bytes = fmt.encode("utf-8")
 
    buf = bytearray()
    # field 1: timestamp (wire 2)
    buf.extend(encode_varint((1 << 3) | 2))
    buf.extend(encode_varint(len(ts_bytes)))
    buf.extend(ts_bytes)
 
    # field 2: frame_id (wire 2)
    if frame_id_bytes:
        buf.extend(encode_varint((2 << 3) | 2))
        buf.extend(encode_varint(len(frame_id_bytes)))
        buf.extend(frame_id_bytes)
 
    # field 3: data (wire 2)
    buf.extend(encode_varint((3 << 3) | 2))
    buf.extend(encode_varint(len(data)))
    buf.extend(data)
 
    # field 4: format (wire 2)
    buf.extend(encode_varint((4 << 3) | 2))
    buf.extend(encode_varint(len(fmt_bytes)))
    buf.extend(fmt_bytes)
 
    return bytes(buf)
 
 
def is_hevc_video(video_path: Path) -> bool:
    """Kiểm tra video đầu vào có phải là HEVC / H.265 không."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout.strip().lower() in ("hevc", "h265")
    except Exception:
        return False
 
 
def get_video_frame_count(video_path: Path) -> int:
    """Đếm số lượng khung hình của file video MP4."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_packets",
        "-show_entries",
        "stream=nb_read_packets",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        val = res.stdout.strip()
        if val.isdigit():
            return int(val)
    except Exception:
        pass
    return 0
 
 
def build_reencode_args(encoder: str) -> List[str]:
    """
    Tham số ffmpeg để re-encode sang HEVC Annex-B có AUD delimiter.
    Luôn tắt B-frame để thứ tự frame trong stream khớp thứ tự message.
    """
    if encoder == "hevc_nvenc":
        return [
            "-c:v", "hevc_nvenc",
            "-preset", "p1",
            "-rc", "vbr", "-cq", "20", "-b:v", "0",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
            "-bsf:v", "hevc_metadata=aud=insert",
        ]
    if encoder == "hevc_qsv":
        return [
            "-c:v", "hevc_qsv",
            "-preset", "veryfast",
            "-global_quality", "20",
            "-bf", "0",
            "-bsf:v", "hevc_metadata=aud=insert",
        ]
    if encoder == "hevc_amf":
        return [
            "-c:v", "hevc_amf",
            "-quality", "speed",
            "-rc", "cqp", "-qp_i", "20", "-qp_p", "20",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
            "-bsf:v", "hevc_metadata=aud=insert",
        ]
    # Mặc định: CPU libx265
    return [
        "-c:v", "libx265",
        "-preset", "ultrafast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-x265-params", "aud=1:bframes=0",
    ]
 
 
class MP4FrameStreamer:
    """
    Generator đọc streaming các khung hình H.265 Annex-B từ file video MP4
    sử dụng FFmpeg pipe với AUD delimiter, không ghi file trung gian.
    """
 
    def __init__(self, video_path: Path, reencode: bool = False, encoder: str = "libx265"):
        self.video_path = video_path
        self.reencode = reencode
        self.encoder = encoder
        self.is_hevc = is_hevc_video(video_path)
        self.proc: Optional[subprocess.Popen] = None
        self.stderr_tail: deque = deque(maxlen=30)
        self._closed = False
        self._stderr_thread: Optional[threading.Thread] = None
 
        self.use_copy = self.is_hevc and not self.reencode
        if self.use_copy:
            print(f"   ⚡ {video_path.name}: HEVC -> stream copy (nhanh)")
        else:
            reason = "--reencode" if self.reencode else "video không phải HEVC"
            print(
                f"   🐢 {video_path.name}: phải re-encode ({reason}) bằng {self.encoder}. "
                f"Xuất video bằng HEVC/H.265 để bỏ qua bước này."
            )
 
        self._generator = self._frame_generator()
 
    def _drain_stderr(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                decoded = line.decode("utf-8", errors="ignore").strip()
                if decoded:
                    self.stderr_tail.append(decoded)
        except Exception:
            pass
 
    def _frame_generator(self) -> Generator[bytes, None, None]:
        cmd = [ensure_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(self.video_path)]
 
        if self.use_copy:
            # Stream copy trực tiếp (lossless, cực nhanh)
            cmd.extend([
                "-c:v", "copy",
                "-bsf:v", "hevc_mp4toannexb,hevc_metadata=aud=insert",
                "-f", "hevc",
                "pipe:1",
            ])
        else:
            cmd.extend(build_reencode_args(self.encoder))
            cmd.extend(["-f", "hevc", "pipe:1"])
 
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=READ_CHUNK_SIZE,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
 
        aud_pattern = b"\x00\x00\x00\x01\x46"
        buffer = bytearray()
        start = 0  # đầu frame hiện tại trong buffer
 
        while True:
            chunk = self.proc.stdout.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            buffer.extend(chunk)
 
            # Tách tất cả frame hoàn chỉnh trong buffer bằng offset,
            # chỉ xóa phần đã dùng MỘT lần sau vòng lặp (tránh memmove mỗi frame).
            while True:
                pos = buffer.find(aud_pattern, start + 5)
                if pos == -1:
                    break
                yield bytes(buffer[start:pos])
                start = pos
 
            if start:
                del buffer[:start]
                start = 0
 
        if buffer:
            yield bytes(buffer)
 
        rc = self.proc.wait()
        if self._stderr_thread:
            self._stderr_thread.join(timeout=2.0)
        if rc != 0 and not self._closed:
            print(f"⚠️  ffmpeg ({self.video_path.name}) trả về mã lỗi {rc}")
            for line in list(self.stderr_tail)[-10:]:
                print(f"     {line}")
 
    def next_frame(self) -> Optional[bytes]:
        try:
            return next(self._generator)
        except StopIteration:
            return None
 
    def close(self):
        self._closed = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
 
 
def natural_sort_key(path: Path):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", path.name)]
 
 
def find_mcap_files(directory: Path) -> List[Path]:
    files = list(directory.glob("*.mcap"))
    files.sort(key=natural_sort_key)
    return files
 
 
def inject_video_to_mcap(
    original_mcap_dir: Path,
    output_dir: Path,
    video_left: Optional[Path] = None,
    video_right: Optional[Path] = None,
    session_json_path: Optional[Path] = None,
    reencode: bool = False,
    trim_start_frame: int = 0,
    encoder: str = "libx265",
):
    if not original_mcap_dir.exists() or not original_mcap_dir.is_dir():
        print(f"❌ Lỗi: Thư mục MCAP gốc không tồn tại: {original_mcap_dir}")
        sys.exit(1)
 
    mcap_files = find_mcap_files(original_mcap_dir)
    if not mcap_files:
        print(f"❌ Lỗi: Không tìm thấy file .mcap nào trong {original_mcap_dir}")
        sys.exit(1)
 
    if video_left is None and video_right is None:
        print("❌ Lỗi: Bạn phải chỉ định ít nhất 1 video thay thế (--video-left hoặc --video-right)!")
        sys.exit(1)
 
    output_dir.mkdir(parents=True, exist_ok=True)
    folder_name = original_mcap_dir.name
 
    print("=" * 65)
    print(f"  THƯ MỤC MCAP GỐC   : {original_mcap_dir}")
    print(f"  TỔNG SỐ PART GỐC   : {len(mcap_files)}")
    print(f"  THƯ MỤC XUẤT MỚI   : {output_dir}")
    if video_left:
        print(f"  VIDEO TOP-LEFT     : {video_left.name}")
    if video_right:
        print(f"  VIDEO TOP-RIGHT    : {video_right.name}")
    print(f"  CHẾ ĐỘ MÃ HÓA      : {'Re-encode ' + encoder if reencode else 'Tự động (Copy nếu HEVC)'}")
    if trim_start_frame > 0:
        print(f"  TRIM OFFSET BẮT ĐẦU: Bỏ qua {trim_start_frame} frame đầu")
    print("=" * 65)
 
    # Đọc session.json nếu có
    session_metadata = None
    if session_json_path and session_json_path.exists():
        with open(session_json_path, "r", encoding="utf-8") as sf:
            session_metadata = json.load(sf)
    else:
        # Tự tìm session.json trong thư mục gốc
        candidate = original_mcap_dir / f"{folder_name}_session.json"
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as sf:
                session_metadata = json.load(sf)
                print(f"ℹ️  Đã tự động tải metadata: {candidate.name}")
 
    # Khởi tạo frame streamer cho từng camera được chỉ định
    streamers: Dict[str, MP4FrameStreamer] = {}
    target_topics = {}
 
    if video_left and video_left.exists():
        print(f"🎬 Khởi tạo giải mã video Top-Left: {video_left}")
        streamers["left"] = MP4FrameStreamer(video_left, reencode=reencode, encoder=encoder)
        target_topics["/top-left-camera/image-raw"] = ("left", "top_left_camera")
 
    if video_right and video_right.exists():
        print(f"🎬 Khởi tạo giải mã video Top-Right: {video_right}")
        streamers["right"] = MP4FrameStreamer(video_right, reencode=reencode, encoder=encoder)
        target_topics["/top-right-camera/image-raw"] = ("right", "top_right_camera")
 
    # Bỏ qua các frame đầu nếu có trim_start_frame
    if trim_start_frame > 0:
        print(f"⏩ Đang tua qua {trim_start_frame} frame đầu...")
        for streamer in streamers.values():
            for _ in range(trim_start_frame):
                streamer.next_frame()
 
    start_time = time.perf_counter()
    total_injected_frames = {k: 0 for k in streamers}
    total_messages_written = 0
 
    print("\n🚀 Bắt đầu quá trình nạp video vào các file MCAP part...")
 
    # Xử lý từng part MCAP
    for idx, orig_part in enumerate(mcap_files, 1):
        out_part = output_dir / orig_part.name
        part_start_time = time.perf_counter()
        part_injected_frames = {k: 0 for k in streamers}
        part_msg_count = 0
 
        # Kiểm tra xem streamers còn frame nào không
        is_streamer_exhausted = False
 
        with open(orig_part, "rb") as in_f, open(out_part, "wb") as out_f:
            reader = make_reader(in_f)
            writer = make_writer(out_f)
            writer.start()
 
            summary = reader.get_summary()
 
            # Đăng ký lại toàn bộ schemas
            schema_map: Dict[int, int] = {}
            for orig_s_id, s in summary.schemas.items():
                new_s_id = writer.register_schema(name=s.name, encoding=s.encoding, data=s.data)
                schema_map[orig_s_id] = new_s_id
 
            # Đăng ký lại toàn bộ channels
            channel_map: Dict[int, int] = {}
            for orig_c_id, c in summary.channels.items():
                new_s_id = schema_map.get(c.schema_id, c.schema_id)
                new_c_id = writer.register_channel(
                    topic=c.topic,
                    message_encoding=c.message_encoding,
                    schema_id=new_s_id,
                    metadata=c.metadata,
                )
                channel_map[orig_c_id] = new_c_id
 
            # Đọc và ghi từng message
            for schema, channel, msg in reader.iter_messages():
                topic = channel.topic
                dest_channel_id = channel_map[channel.id]
 
                if topic in target_topics:
                    cam_key, frame_id = target_topics[topic]
                    streamer = streamers[cam_key]
 
                    # Lấy frame mới từ MP4
                    new_frame_data = streamer.next_frame()
 
                    if new_frame_data is not None:
                        # Trích xuất timestamp gốc của message
                        orig_ts, _, _ = parse_compressed_video(msg.data)
                        if orig_ts is None:
                            orig_ts = msg.log_time
 
                        # Đóng gói protobuf mới với frame đã chỉnh sửa
                        new_msg_data = encode_compressed_video(
                            ts_ns=orig_ts,
                            frame_id=frame_id,
                            data=new_frame_data,
                            fmt="h265",
                        )
 
                        writer.add_message(
                            channel_id=dest_channel_id,
                            log_time=msg.log_time,
                            data=new_msg_data,
                            publish_time=msg.publish_time,
                            sequence=msg.sequence,
                        )
                        part_injected_frames[cam_key] += 1
                        total_injected_frames[cam_key] += 1
                        part_msg_count += 1
                        total_messages_written += 1
                    else:
                        is_streamer_exhausted = True
                        # Nếu video đã trim hết, không ghi tiếp frame video
                        continue
                else:
                    # Các topic không bị thay thế (IMU, camera-info, tf_static...)
                    # Nếu video đã trim hết từ trước, có thể dừng hoặc ghi tiếp
                    if is_streamer_exhausted:
                        continue
 
                    writer.add_message(
                        channel_id=dest_channel_id,
                        log_time=msg.log_time,
                        data=msg.data,
                        publish_time=msg.publish_time,
                        sequence=msg.sequence,
                    )
                    part_msg_count += 1
                    total_messages_written += 1
 
            writer.finish()
 
        part_duration = time.perf_counter() - part_start_time
        frames_desc = ", ".join(f"{k}: {part_injected_frames[k]}" for k in streamers)
        out_size_mb = out_part.stat().st_size / (1024 * 1024)
 
        print(
            f" [{idx:02d}/{len(mcap_files):02d}] {out_part.name:<18} "
            f"| Frames ({frames_desc}) "
            f"| Tổng msgs: {part_msg_count:<5} "
            f"| Size: {out_size_mb:5.1f} MB "
            f"| ({part_duration:4.2f}s)"
        )
 
        if is_streamer_exhausted:
            print("ℹ️  Video MP4 đã hết khung hình (kết thúc phần video đã trim). Dừng nạp.")
            break
 
    # Đóng các streamer
    for streamer in streamers.values():
        streamer.close()
 
    total_time = time.perf_counter() - start_time
    print("\n" + "=" * 65)
    print("🎉 HOÀN TẤT NẠP VIDEO VÀO MCAP THÀNH CÔNG!")
    print(f"   - Thư mục MCAP mới: {output_dir}")
    for k in streamers:
        print(f"   - Đã nạp camera [{k}]: {total_injected_frames[k]:,} frames")
    print(f"   - Tổng số message ghi: {total_messages_written:,}")
    print(f"   - Tổng thời gian: {total_time:.2f}s (Tốc độ ~{total_messages_written / total_time:.1f} msg/s)")
    print("=" * 65)
 
 
def main():
    parser = argparse.ArgumentParser(
        description="Nạp lại video MP4 đã chỉnh sửa vào các file MCAP multipart."
    )
    parser.add_argument(
        "original_mcap_dir",
        type=str,
        nargs="?",
        default=r"D:\TST\HumanEgo_Videos\20261019_SPA-20261020T023851Z-1-002\20261019_SPA\20261019_040342",
        help="Đường dẫn đến thư mục chứa các file .mcap gốc",
    )
    parser.add_argument(
        "--video-left",
        "-vl",
        type=str,
        default=None,
        help="Đường dẫn đến video MP4 thay thế cho Top-Left camera",
    )
    parser.add_argument(
        "--video-right",
        "-vr",
        type=str,
        default=None,
        help="Đường dẫn đến video MP4 thay thế cho Top-Right camera",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=r"D:\MCAPConverter\output\20261019_040342_repacked",
        help="Thư mục xuất các file .mcap mới",
    )
    parser.add_argument(
        "--session-json",
        "-s",
        type=str,
        default=None,
        help="Đường dẫn đến file session.json (mặc định tự tìm trong thư mục gốc)",
    )
    parser.add_argument(
        "--reencode",
        action="store_true",
        help="Bắt buộc mã hóa lại sang HEVC (nếu video đã bị chỉnh sửa/đổi codec)",
    )
    parser.add_argument(
        "--encoder",
        choices=ENCODER_CHOICES,
        default="libx265",
        help="Encoder dùng khi phải re-encode: libx265 (CPU, mặc định), "
             "hevc_nvenc (Nvidia), hevc_qsv (Intel), hevc_amf (AMD)",
    )
    parser.add_argument(
        "--trim-start-frame",
        type=int,
        default=0,
        help="Số lượng frame bị cắt ở đầu (nếu video đã bị trim đầu)",
    )
 
    args = parser.parse_args()
 
    orig_dir = Path(args.original_mcap_dir)
    out_dir = Path(args.output_dir)
    vl = Path(args.video_left) if args.video_left else None
    vr = Path(args.video_right) if args.video_right else None
    sj = Path(args.session_json) if args.session_json else None
 
    # Tự động phát hiện video mặc định nếu không truyền tham số
    if vl is None and vr is None:
        default_vl = orig_dir / f"{orig_dir.name}_top_left.mp4"
        default_vr = orig_dir / f"{orig_dir.name}_top_right.mp4"
        if default_vl.exists():
            vl = default_vl
        if default_vr.exists():
            vr = default_vr
 
    inject_video_to_mcap(
        original_mcap_dir=orig_dir,
        output_dir=out_dir,
        video_left=vl,
        video_right=vr,
        session_json_path=sj,
        reencode=args.reencode,
        trim_start_frame=args.trim_start_frame,
        encoder=args.encoder,
    )
 
 
if __name__ == "__main__":
    main()
 