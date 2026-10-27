"""
MCAP Part & Multi-Session Merger
Gộp các file .mcap multipart trong 1 thư mục HOẶC gộp nhiều thư mục session thành 1 file .mcap duy nhất.
Lossless copy trực tiếp, tự động tịnh tiến timeline liền mạch, bảo toàn schemas, channels, metadata và timestamps.
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Đảm bảo in tiếng Việt an toàn trên Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcap.reader import make_reader
from mcap.writer import CompressionType, Writer


@dataclass
class SessionInfo:
    name: str
    folder: Path
    files: List[Path]


def natural_sort_key(path: Path) -> List[object]:
    """Sắp xếp tự nhiên theo số hiệu part hoặc tên folder (024343, 040301...)."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", path.name)]


def find_mcap_parts(directory: Path) -> List[Path]:
    """Tìm tất cả các file .mcap trong thư mục và sắp xếp theo thứ tự số part."""
    files = [f for f in directory.glob("*.mcap") if not f.name.endswith("_merged.mcap")]
    files.sort(key=natural_sort_key)
    return files


def check_missing_parts(files: List[Path]) -> List[Tuple[int, int]]:
    """Kiểm tra và trả về danh sách các khoảng part bị gián đoạn / ngắt quãng."""
    indexed_parts = []
    for f in files:
        m = re.search(r"part_(\d+)", f.name)
        if m:
            indexed_parts.append((int(m.group(1)), f))

    if not indexed_parts:
        return []

    gaps = []
    for i in range(len(indexed_parts) - 1):
        curr_idx = indexed_parts[i][0]
        next_idx = indexed_parts[i + 1][0]
        if next_idx > curr_idx + 1:
            gaps.append((curr_idx + 1, next_idx - 1))

    return gaps


def parse_part_range(range_str: str) -> Tuple[int, int]:
    """Parse chuỗi part-range dạng '0-10' hoặc '5'."""
    if "-" in range_str:
        parts = range_str.split("-")
        return int(parts[0]), int(parts[1])
    val = int(range_str)
    return val, val


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
        buf.extend(encode_varint((1 << 3) | 0))  # field 1 (seconds), wire 0
        buf.extend(encode_varint(seconds))
    if nanos > 0:
        buf.extend(encode_varint((2 << 3) | 0))  # field 2 (nanos), wire 0
        buf.extend(encode_varint(nanos))
    return bytes(buf)


def shift_compressed_video_bytes(raw_bytes: bytes, new_ts_ns: int) -> bytes:
    """
    Tịnh tiến timestamp trong trường field 1 của protobuf foxglove.CompressedVideo
    mà không cần parse/decode toàn bộ payload video byte lớn (cực nhanh).
    """
    if raw_bytes and raw_bytes[0] == 0x0A:  # field 1, wire 2 (0x0A)
        pos = 1
        sz = 0
        shift = 0
        length = len(raw_bytes)
        while pos < length:
            b = raw_bytes[pos]
            pos += 1
            sz |= (b & 0x7F) << shift
            if b < 0x80:
                break
            shift += 7

        rest_of_message = raw_bytes[pos + sz :]
        ts_bytes = encode_timestamp(new_ts_ns)
        header = bytearray([0x0A])
        header.extend(encode_varint(len(ts_bytes)))
        header.extend(ts_bytes)
        return bytes(header) + rest_of_message

    return raw_bytes


def discover_sessions(input_paths: List[Path]) -> List[SessionInfo]:
    """
    Tự động phát hiện các session từ danh sách đường dẫn truyền vào.
    Hỗ trợ:
      1. Truyền 1 thư mục session cụ thể
      2. Truyền 1 thư mục cha chứa nhiều thư mục con session
      3. Truyền danh sách nhiều thư mục session
    """
    sessions: List[SessionInfo] = []

    for path in input_paths:
        path = path.resolve()
        if not path.exists():
            print(f"[CẢNH BÁO] Bỏ qua đường dẫn không tồn tại: {path}")
            continue

        if path.is_file():
            # Nếu truyền trực tiếp file .mcap lẻ
            sessions.append(SessionInfo(name=path.stem, folder=path.parent, files=[path]))
            continue

        # Kiểm tra xem chính thư mục này có chứa part_*.mcap không
        direct_parts = find_mcap_parts(path)
        if direct_parts:
            sessions.append(SessionInfo(name=path.name, folder=path, files=direct_parts))
        else:
            # Nếu không có part trực tiếp, kiểm tra các thư mục con bên trong
            subdirs = [d for d in path.iterdir() if d.is_dir()]
            subdirs.sort(key=natural_sort_key)
            found_sub = False
            for subdir in subdirs:
                sub_parts = find_mcap_parts(subdir)
                if sub_parts:
                    sessions.append(SessionInfo(name=subdir.name, folder=subdir, files=sub_parts))
                    found_sub = True

            if not found_sub:
                print(f"[CẢNH BÁO] Không tìm thấy file .mcap nào trong: {path}")

    return sessions


def merge_sessions(
    sessions: List[SessionInfo],
    output_file: Path,
    compression: str = "zstd",
    chunk_size_mb: int = 4,
    shift_timeline: bool = True,
    deep_timestamp_sync: bool = True,
    include_metadata: bool = True,
    include_attachments: bool = True,
    part_range: Optional[Tuple[int, int]] = None,
) -> bool:
    """
    Gộp nhiều session (hoặc 1 session) thành 1 file MCAP hoàn chỉnh.
    """
    if not sessions:
        print("[LỖI] Không có session nào để xử lý.")
        return False

    comp_map = {
        "zstd": CompressionType.ZSTD,
        "lz4": CompressionType.LZ4,
        "none": CompressionType.NONE,
    }
    comp_type = comp_map.get(compression.lower(), CompressionType.ZSTD)
    chunk_size = chunk_size_mb * 1024 * 1024

    output_file = output_file.resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_file.with_suffix(".mcap.tmp")

    total_files = sum(len(s.files) for s in sessions)
    total_input_bytes = sum(sum(f.stat().st_size for f in s.files) for s in sessions)

    print("\n" + "=" * 75)
    print("                 MCAP MULTI-SESSION & PART MERGER")
    print("=" * 75)
    print(f" Số lượng session       : {len(sessions)} thư mục")
    for s_idx, s in enumerate(sessions, 1):
        s_size_mb = sum(f.stat().st_size for f in s.files) / (1024 * 1024)
        print(f"   [{s_idx:02d}] {s.name:<25} ({len(s.files)} parts | {s_size_mb:8.1f} MB)")
    print("-" * 75)
    print(f" Tổng số file part     : {total_files} files")
    print(f" Tổng dung lượng gốc   : {total_input_bytes / (1024 * 1024):.2f} MB ({total_input_bytes / (1024 * 1024 * 1024):.2f} GB)")
    print(f" File đầu ra           : {output_file.name}")
    print(f" Thư mục xuất          : {output_file.parent}")
    print(f" Chế độ nén chunk      : {compression.upper()} ({chunk_size_mb} MB/chunk)")
    print(f" Nối tiếp timeline     : {'BẬT (Liền mạch liên tục)' if shift_timeline else 'TẮT (Giữ nguyên)'}")
    print(f" Đồng bộ sâu video     : {'BẬT (Protobuf payload)' if deep_timestamp_sync else 'TẮT (Chỉ MCAP header)'}")
    print("=" * 75 + "\n")

    # Bản đồ schemas và channels toàn cục
    global_schemas: Dict[Tuple[str, str, bytes], int] = {}
    global_channels: Dict[Tuple[str, str, int], int] = {}
    video_channels: Set[int] = set()

    topic_message_counts: Dict[str, int] = {}
    total_messages = 0
    start_time = time.perf_counter()

    current_timeline_offset_ns = 0
    last_session_max_ts_ns = 0
    frame_interval_ns = 33_216_000  # Mặc định ~30.106 FPS (~33.2ms)

    try:
        with open(temp_output, "wb") as out_f:
            writer = Writer(out_f, compression=comp_type, chunk_size=chunk_size)
            writer.start()

            for sess_idx, session in enumerate(sessions, 1):
                sess_start_time = time.perf_counter()
                sess_msg_count = 0
                sess_max_ts_ns = 0

                # Lọc file theo part_range nếu có
                session_files = session.files
                if part_range is not None:
                    min_p, max_p = part_range
                    filtered = []
                    for f in session_files:
                        m = re.search(r"part_(\d+)", f.name)
                        if m and min_p <= int(m.group(1)) <= max_p:
                            filtered.append(f)
                    session_files = filtered

                # Tính toán timeline offset cho session này
                if shift_timeline:
                    if sess_idx == 1:
                        current_timeline_offset_ns = 0
                    else:
                        current_timeline_offset_ns = last_session_max_ts_ns + frame_interval_ns

                offset_sec = current_timeline_offset_ns / 1e9
                print(f"\n▶ Đang xử lý Session [{sess_idx}/{len(sessions)}]: {session.name} "
                      f"(Offset: +{offset_sec:,.2f}s | {len(session_files)} parts)")

                for p_idx, part_path in enumerate(session_files, 1):
                    part_start_time = time.perf_counter()
                    part_size_mb = part_path.stat().st_size / (1024 * 1024)
                    part_msg_count = 0

                    with open(part_path, "rb") as in_f:
                        reader = make_reader(in_f)
                        summary = reader.get_summary()

                        # 1. Đăng ký Schemas
                        local_schema_to_dest: Dict[int, int] = {}
                        if summary and summary.schemas:
                            for orig_sid, s in summary.schemas.items():
                                schema_key = (s.name, s.encoding, s.data)
                                if schema_key not in global_schemas:
                                    global_schemas[schema_key] = writer.register_schema(
                                        name=s.name, encoding=s.encoding, data=s.data
                                    )
                                local_schema_to_dest[orig_sid] = global_schemas[schema_key]

                        # 2. Đăng ký Channels
                        local_channel_to_dest: Dict[int, int] = {}
                        if summary and summary.channels:
                            for orig_cid, c in summary.channels.items():
                                dest_sid = (
                                    local_schema_to_dest.get(c.schema_id, c.schema_id)
                                    if c.schema_id != 0
                                    else 0
                                )
                                channel_key = (c.topic, c.message_encoding, dest_sid)
                                if channel_key not in global_channels:
                                    dest_cid = writer.register_channel(
                                        topic=c.topic,
                                        message_encoding=c.message_encoding,
                                        schema_id=dest_sid,
                                        metadata=c.metadata,
                                    )
                                    global_channels[channel_key] = dest_cid
                                    if "image-raw" in c.topic or "CompressedVideo" in str(c.metadata):
                                        video_channels.add(dest_cid)

                                local_channel_to_dest[orig_cid] = global_channels[channel_key]

                        # 3. Sao chép Metadata
                        if include_metadata:
                            try:
                                for m in reader.iter_metadata():
                                    meta_data = dict(m.metadata)
                                    meta_data["_source_session"] = session.name
                                    meta_name = f"{m.name}_{session.name}" if len(sessions) > 1 else m.name
                                    writer.add_metadata(name=meta_name, data=meta_data)
                            except Exception:
                                pass

                        # 4. Sao chép Attachments
                        if include_attachments:
                            try:
                                for att in reader.iter_attachments():
                                    writer.add_attachment(
                                        create_time=att.create_time + current_timeline_offset_ns,
                                        log_time=att.log_time + current_timeline_offset_ns,
                                        name=f"{session.name}_{att.name}" if len(sessions) > 1 else att.name,
                                        media_type=att.media_type,
                                        data=att.data,
                                    )
                            except Exception:
                                pass

                        # 5. Duyệt và ghi Messages
                        for _, channel, msg in reader.iter_messages():
                            dest_cid = local_channel_to_dest[channel.id]
                            new_log_time = msg.log_time + current_timeline_offset_ns
                            new_pub_time = msg.publish_time + current_timeline_offset_ns

                            if new_log_time > sess_max_ts_ns:
                                sess_max_ts_ns = new_log_time

                            # Tịnh tiến payload video nếu cần
                            msg_data = msg.data
                            if deep_timestamp_sync and current_timeline_offset_ns > 0:
                                if dest_cid in video_channels or "image-raw" in channel.topic:
                                    msg_data = shift_compressed_video_bytes(msg.data, new_log_time)

                            writer.add_message(
                                channel_id=dest_cid,
                                log_time=new_log_time,
                                data=msg_data,
                                publish_time=new_pub_time,
                                sequence=msg.sequence,
                            )
                            part_msg_count += 1
                            topic_message_counts[channel.topic] = topic_message_counts.get(channel.topic, 0) + 1

                    sess_msg_count += part_msg_count
                    total_messages += part_msg_count
                    part_dur = time.perf_counter() - part_start_time
                    spd = part_msg_count / part_dur if part_dur > 0 else 0

                    print(
                        f"   [{p_idx:02d}/{len(session_files):02d}] {part_path.name:<18} "
                        f"| {part_msg_count:>6,} msgs "
                        f"| {part_size_mb:6.1f} MB "
                        f"| {part_dur:4.2f}s "
                        f"({spd:>7,.0f} msg/s)"
                    )

                last_session_max_ts_ns = sess_max_ts_ns
                sess_dur = time.perf_counter() - sess_start_time
                print(f"   ✔ Hoàn tất {session.name}: {sess_msg_count:,} msgs trong {sess_dur:.2f}s")

            # Kết xuất Index và Summary
            print("\n[ĐANG XỬ LÝ] Đang kết xuất bảng chỉ mục và metadata cuối cùng (writer.finish)...")
            writer.finish()

        # Đổi tên file tạm thành file chính thức an toàn
        if output_file.exists():
            output_file.unlink()
        temp_output.rename(output_file)

    except KeyboardInterrupt:
        print("\n\n[HỦY] Người dùng đã dừng tiến trình gộp file.")
        if temp_output.exists():
            temp_output.unlink()
        return False
    except Exception as e:
        print(f"\n[LỖI] Quá trình gộp file thất bại: {e}")
        if temp_output.exists():
            temp_output.unlink()
        raise e

    total_duration = time.perf_counter() - start_time
    final_size_bytes = output_file.stat().st_size
    final_size_mb = final_size_bytes / (1024 * 1024)
    compression_ratio = (final_size_bytes / total_input_bytes) * 100 if total_input_bytes > 0 else 100
    overall_speed = total_messages / total_duration if total_duration > 0 else 0

    print("\n" + "=" * 75)
    print("                     KẾT QUẢ GỘP HOÀN TẤT")
    print("=" * 75)
    print(f" File hoàn chỉnh        : {output_file}")
    print(f" Dung lượng file gộp   : {final_size_mb:.2f} MB ({final_size_mb / 1024:.2f} GB) [Tỷ lệ: {compression_ratio:.1f}%]")
    print(f" Tổng số session        : {len(sessions)}")
    print(f" Tổng số messages       : {total_messages:,}")
    print(f" Tổng thời lượng video  : {last_session_max_ts_ns / 1e9 / 60:.2f} phút")
    print(f" Thời gian thực thi     : {total_duration:.2f} giây")
    print(f" Tốc độ xử lý trung bình: {overall_speed:,.0f} msgs/giây ({total_input_bytes / (1024*1024*total_duration):.1f} MB/s)")
    print("-" * 75)
    print(" Thống kê messages theo topic:")
    for topic, count in sorted(topic_message_counts.items(), key=lambda x: -x[1]):
        print(f"   - {topic:<40}: {count:>8,} messages")
    print("=" * 75 + "\n")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Gộp (Merge) các file .mcap trong 1 thư mục HOẶC gộp nhiều thư mục session thành 1 file .mcap duy nhất.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  # 1. Gộp toàn bộ part trong 1 thư mục session:
  python merge_mcap.py "D:\\data\\session_01"

  # 2. Gộp nhiều thư mục session cụ thể:
  python merge_mcap.py "D:\\data\\session_01" "D:\\data\\session_02" -o "D:\\output\\merged_sessions.mcap"

  # 3. Gộp tất cả các session con bên trong 1 thư mục cha:
  python merge_mcap.py "D:\\TST\\HumanEgo_Videos\\TSTECO_SPA_20261026"

  # 4. Chỉ gộp khoảng part 0 đến 5 cho mỗi session:
  python merge_mcap.py "D:\\data\\session_01" "D:\\data\\session_02" --part-range 0-5

  # 5. Xem trước danh sách file và timeline mà không ghi file (Dry run):
  python merge_mcap.py "D:\\data\\session_01" "D:\\data\\session_02" --dry-run
        """,
    )

    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Đường dẫn đến một hoặc nhiều thư mục session, hoặc 1 thư mục cha chứa các session con.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Đường dẫn file .mcap đầu ra. Mặc định: <session_name>_merged.mcap",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Thư mục lưu file đầu ra (nếu không chỉ định -o).",
    )
    parser.add_argument(
        "--compression",
        choices=["zstd", "lz4", "none"],
        default="zstd",
        help="Thuật toán nén chunk (mặc định: zstd).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=4,
        help="Kích thước chunk tính bằng MB (mặc định: 4).",
    )
    parser.add_argument(
        "--part-range",
        type=str,
        default=None,
        help="Giới hạn khoảng part cần gộp, ví dụ: 0-10 hoặc 5.",
    )
    parser.add_argument(
        "--no-shift-timeline",
        action="store_true",
        help="Không tịnh tiến timeline nối tiếp (giữ nguyên timestamp gốc của từng session).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ kiểm tra danh sách file và gap part mà không thực hiện ghi file.",
    )

    args = parser.parse_args()

    # Tự động phát hiện danh sách session
    sessions = discover_sessions(args.inputs)
    if not sessions:
        print("[LỖI] Không tìm thấy session hoặc file .mcap hợp lệ nào từ các đường dẫn đã cho.")
        sys.exit(1)

    # Kiểm tra gap part trong từng session
    total_parts = 0
    for s in sessions:
        total_parts += len(s.files)
        gaps = check_missing_parts(s.files)
        if gaps:
            print("\n" + "!" * 75)
            print(f"[CẢNH BÁO] Phát hiện part bị gián đoạn trong Session '{s.name}':")
            for start, end in gaps:
                if start == end:
                    print(f"   - Thiếu: part_{start:05d}.mcap")
                else:
                    print(f"   - Thiếu: part_{start:05d}.mcap -> part_{end:05d}.mcap")
            print("   Các part hiện có vẫn sẽ được nối tiếp liên tục theo thời gian.")
            print("!" * 75 + "\n")

    part_range_tuple = None
    if args.part_range:
        part_range_tuple = parse_part_range(args.part_range)
        print(f"[THÔNG TIN] Đã áp dụng bộ lọc part-range: {args.part_range}")

    # Xác định đường dẫn file đầu ra
    if args.output:
        output_file = args.output.resolve()
    else:
        if len(sessions) == 1:
            out_name = f"{sessions[0].name}_merged.mcap"
            parent_dir = sessions[0].folder
        else:
            # Nhiều session
            if len(args.inputs) == 1 and args.inputs[0].is_dir():
                out_name = f"{args.inputs[0].name}_all_sessions_merged.mcap"
                parent_dir = args.inputs[0]
            else:
                out_name = f"multi_sessions_{sessions[0].name}_to_{sessions[-1].name}_merged.mcap"
                parent_dir = sessions[0].folder.parent

        if args.output_dir:
            output_file = (args.output_dir / out_name).resolve()
        else:
            output_file = (parent_dir / out_name).resolve()

    if args.dry_run:
        print("\n" + "=" * 75)
        print("                         DRY RUN PREVIEW")
        print("=" * 75)
        print(f"Tổng số Session : {len(sessions)}")
        print(f"Tổng số Part    : {total_parts} files")
        total_raw_mb = sum(sum(f.stat().st_size for f in s.files) for s in sessions) / (1024 * 1024)
        print(f"Tổng dung lượng : {total_raw_mb:,.1f} MB ({total_raw_mb/1024:.2f} GB)")
        print(f"File đầu ra     : {output_file}")
        print("-" * 75)
        for s_idx, s in enumerate(sessions, 1):
            s_mb = sum(f.stat().st_size for f in s.files) / (1024 * 1024)
            print(f" [{s_idx:02d}] Session: {s.name:<25} | {len(s.files)} parts | {s_mb:7.1f} MB")
            for f in s.files[:3]:
                print(f"      - {f.name} ({f.stat().st_size / (1024*1024):.1f} MB)")
            if len(s.files) > 3:
                print(f"      ... và {len(s.files) - 3} part tiếp theo")
        print("=" * 75 + "\n")
        return

    # Thực hiện merge
    success = merge_sessions(
        sessions=sessions,
        output_file=output_file,
        compression=args.compression,
        chunk_size_mb=args.chunk_size,
        shift_timeline=not args.no_shift_timeline,
        deep_timestamp_sync=True,
        part_range=part_range_tuple,
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
