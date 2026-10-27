import argparse
from pathlib import Path
from mcap.reader import make_reader
from mcap.writer import Writer

def merge_mcap_files(input_dir: Path, output_file: Path):
    if not input_dir.exists():
        print(f" Lỗi: Thư mục không tồn tại: {input_dir}")
        return

    # Lấy danh sách các file .mcap (loại trừ file output nếu nằm chung thư mục)
    mcap_files = sorted(
        [f for f in input_dir.glob("*.mcap") if f.resolve() != output_file.resolve()]
    )

    if not mcap_files:
        print(f" Không tìm thấy file .mcap nào trong: {input_dir}")
        return

    # Tạo thư mục chứa file output nếu chưa có
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f" Tìm thấy {len(mcap_files)} file .mcap.")
    print(f" Đang gộp vào: {output_file}\n" + "-" * 50)

    total_msgs = 0

    with open(output_file, "wb") as f_out:
        writer = Writer(f_out)
        writer.start()

        schema_registry = {}
        channel_map = {}

        for idx, file_path in enumerate(mcap_files, start=1):
            print(f"[{idx}/{len(mcap_files)}] Đang đọc: {file_path.name} ...", end="", flush=True)
            file_msgs = 0

            with open(file_path, "rb") as f_in:
                reader = make_reader(f_in)
                for schema, channel, message in reader.iter_messages():
                    # Đăng ký schema nếu chưa có
                    new_schema_id = 0
                    if schema:
                        schema_key = (schema.name, schema.encoding, schema.data)
                        if schema_key not in schema_registry:
                            schema_registry[schema_key] = writer.register_schema(
                                name=schema.name,
                                encoding=schema.encoding,
                                data=schema.data,
                            )
                        new_schema_id = schema_registry[schema_key]

                    # Đăng ký channel tương ứng cho từng file
                    chan_key = (str(file_path), channel.id)
                    if chan_key not in channel_map:
                        channel_map[chan_key] = writer.register_channel(
                            topic=channel.topic,
                            message_encoding=channel.message_encoding,
                            schema_id=new_schema_id,
                            metadata=channel.metadata,
                        )

                    # Ghi message vào file đích
                    writer.add_message(
                        channel_id=channel_map[chan_key],
                        log_time=message.log_time,
                        data=message.data,
                        publish_time=message.publish_time,
                        sequence=message.sequence,
                    )
                    file_msgs += 1

            total_msgs += file_msgs
            print(f" Xong ({file_msgs:,} tin nhắn)")

        writer.finish()

    size_mb = output_file.stat().st_size / (1024 * 1024)
    print("-" * 50)
    print(" GỘP FILE HOÀN TẤT THÀNH CÔNG!")
    print(f"- Tổng số file đã gộp: {len(mcap_files)}")
    print(f"- Tổng số tin nhắn: {total_msgs:,}")
    print(f"- Dung lượng file kết quả: {size_mb:.2f} MB")
    print(f"- Đường dẫn: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool gộp các file .mcap trong một thư mục thành 1 file duy nhất.")
    parser.add_argument(
        "--input-dir", "-i",
        type=Path,
        required=True,
        help="Đường dẫn thư mục chứa các file .mcap"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Đường dẫn file .mcap kết quả (Mặc định: merged_output.mcap nằm trong thư mục nguồn)"
    )

    args = parser.parse_args()
    
    # Nếu không chỉ định output, tự đặt tên là merged_output.mcap bên trong input_dir
    out_path = args.output if args.output else (args.input_dir / "merged_output.mcap")
    
    merge_mcap_files(args.input_dir, out_path)