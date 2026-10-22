import os
import glob
import json
import cv2
import numpy as np
from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory

input_folder = r"D:\TST\HumanEgo_Videos\20261019_SPA-20261020T023851Z-1-002\20261019_SPA\20261019_044407"  # Thư mục chứa 50 file mcap
output_mp4 = r"D:\MCAPConverter\output\combined_stereo_sbs.mp4"
metadata_file = r"D:\MCAPConverter\output\session.json"

topic_left = "/top-left-camera/image-raw"
topic_right = "/top-right-camera/image-raw"
fps = 30.0

# Lấy danh sách file và sắp xếp theo tên
mcap_files = sorted(glob.glob(os.path.join(input_folder, "*.mcap")))
batch_info = []

out = None
total_written = 0

for file_path in mcap_files:
    file_name = os.path.basename(file_path)
    print(f"Đang xử lý: {file_name}...")

    left_frames = []
    right_frames = []

    with open(file_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for schema, channel, message, ros_msg in reader.iter_decoded_messages(topics=[topic_left, topic_right]):
            np_arr = np.frombuffer(ros_msg.data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            if channel.topic == topic_left:
                left_frames.append(frame)
            elif channel.topic == topic_right:
                right_frames.append(frame)

    pair_count = min(len(left_frames), len(right_frames))

    if pair_count > 0:
        h, w, _ = left_frames[0].shape
        if out is None:
            # Chiều ngang gấp đôi vì ghép Side-by-Side (L + R)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(output_mp4, fourcc, fps, (w * 2, h))

        for i in range(pair_count):
            sbs_frame = np.hstack((left_frames[i], right_frames[i]))
            out.write(sbs_frame)

        # Lưu lại số frame của file này để sau này cắt trả lại
        batch_info.append({
            "original_file": file_name,
            "frame_count": pair_count
        })
        total_written += pair_count

if out:
    out.release()

# Lưu metadata mapping
with open(metadata_file, "w", encoding="utf-8") as f:
    json.dump(batch_info, f, indent=4)

print(f"\n Hoàn tất gộp {len(batch_info)} file ({total_written} frames) thành {output_mp4}")
print(f" Metadata lưu tại: {metadata_file}")