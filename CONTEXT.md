# MCAPConverter - Bối Cảnh Dự Án & Nhật Ký Kỹ Thuật (Context & Log)

Tài liệu này tổng hợp toàn bộ bối cảnh dữ liệu, cấu trúc hệ thống, các lưu ý kỹ thuật (pitfalls) và nhật ký thực thi để nạp nhanh context cho các phiên làm việc và AI tiếp theo.

---

## 1. Tổng Quan Dự Án (Project Overview)
- **Mục tiêu**: Chuyển đổi và xử lý các tập tin `.mcap` dạng multipart (ghi lại từ hệ thống thiết bị ghi hình/robot như HumanEgo) thành các video `.mp4` hoàn chỉnh, chất lượng cao, đồng bộ thời gian và hỗ trợ xử lý đa camera.
- **Môi trường thực thi**:
  - Hệ điều hành: Windows (Shell: **PowerShell 7**)
  - Python Environment: Python 3.11 tại `d:\MCAPConverter\.venv`
  - Thư viện chính: `mcap (1.6.0)`, `protobuf`, `ffmpeg` (bản build full 8.1.2 gyan.dev hỗ trợ HEVC, H.264, x265, v.v.)

---

## 2. Đặc Tả Dữ Liệu MCAP (Data Specifications)

### 2.1. Cấu trúc Topic & Schema
Dữ liệu trong các file MCAP thuộc bộ dataset này sử dụng mã hóa **Protobuf** (KHÔNG PHẢI ROS2 / CDR):
- **Schema**: `foxglove.CompressedVideo` (Protobuf)
  - `field 1` (`wire=2`): `timestamp` (`google.protobuf.Timestamp`: field 1: `seconds`, field 2: `nanos`)
  - `field 2` (`wire=2`): `frame_id` (`string`)
  - `field 3` (`wire=2`): `data` (`bytes` - chứa chuỗi byte nén Annex-B của video)
  - `field 4` (`wire=2`): `format` (`string` - giá trị: `"h265"`)

### 2.2. Danh sách Channels trong MCAP
1. `/top-left-camera/image-raw`: Luồng video camera mắt trái
2. `/top-right-camera/image-raw`: Luồng video camera mắt phải
3. `/top-left-camera/camera-info`: Thông số nội quan (intrinsics) camera trái
4. `/top-right-camera/camera-info`: Thông số nội quan camera phải
5. `/ego/imu`: Dữ liệu cảm biến đo quán tính IMU
6. `/tf_static`: Tọa độ các khớp và camera
7. `/camera/exposure_diagnostics`: Chẩn đoán độ phơi sáng camera

### 2.3. Định dạng Video Stream
- **Codec**: **H.265 / HEVC** (Annex-B stream, mỗi NAL bắt đầu bằng `00 00 00 01`)
- **Độ phân giải**: **1920 × 1200**
- **Frame Rate**: **~30.106 FPS** (Khoảng cách giữa các frame là `0.033216s`, tính từ timestamp thực tế)
- **Đặc tính phân mảnh**:
  - Mỗi file `.mcap` đại diện cho một part dài xấp xỉ **1 phút** (~1,827 - 1,830 frames).
  - Đầu mỗi part đều chứa NAL units: VPS (`0x40`), SPS (`0x42`), PPS, và IDR Keyframe, cho phép nối chuỗi (concatenate) bitstream trực tiếp ở mức lossless mà không bị lỗi giải mã.

---

## 3. Các Vấn Đề Kỹ Thuật Quan Trọng Cần Tránh (Critical Pitfalls)

| Vấn đề | Chi tiết & Nguyên nhân | Giải pháp chuẩn |
| :--- | :--- | :--- |
| **Không dùng ROS2 Decoder** | File MCAP dùng protobuf `foxglove.CompressedVideo`. Thư viện `mcap_ros2` với `DecoderFactory` sẽ báo lỗi hoặc không decode được schema. | Dùng parser varint/protobuf nhẹ tự viết (`parse_compressed_video`) hoặc `mcap.protobuf`. |
| **cv2.imdecode thất bại trên raw H.265** | `cv2.imdecode` chỉ hỗ trợ container image (JPEG/PNG/WebP), không thể decode trực tiếp raw Annex-B H.265 NAL stream. | Sử dụng **FFmpeg** để remux hoặc decode. |
| **Tràn bộ nhớ RAM (OOM)** | Đọc cả mảng frame uncompressed của 1 file vào RAM (1,830 frame × 1920 × 1200 × 3 = ~12.6 GB/part) sẽ gây tràn RAM khi chạy batch. | Dùng cơ chế **streaming trực tiếp** (pipe vào stdin của FFmpeg) không lưu mảng frame trong RAM. |
| **Deadlock pipe FFmpeg** | Nếu bắt `stderr=subprocess.PIPE` của FFmpeg mà không đọc bất đồng bộ, bộ đệm pipe hệ thống bị đầy sẽ gây treo tiến trình (deadlock). | Sử dụng daemon thread đọc `stderr` liên tục hoặc redirect log. |
| **Thiếu Part do Google Drive Zip** | Khi tải từ Google Drive, dữ liệu lớn bị tách thành nhiều file zip (`-001.zip`, `-002.zip`). Một thư mục con có thể chỉ chứa một vài part (vd: part 0, 10, 13). | Script cần có tính năng **Gap Detection** để thông báo cho người dùng phần nào bị thiếu. |
| **Windows Console Encoding** | Mặc định PowerShell/cmd có thể dùng `cp1252` gây lỗi `UnicodeEncodeError` khi in tiếng Việt. | Cần cấu hình `sys.stdout.reconfigure(encoding="utf-8")`. |

---

## 4. Danh Mục Script Trong Repository

### 4.1. `convert_mcap.py` (Script Production Chính)
- **Mục đích**: Chuyển đổi toàn bộ các part MCAP trong thư mục thành video MP4 hoàn chỉnh.
- **Tính năng**:
  - Hỗ trợ xuất đồng thời cả 2 camera (Top-Left & Top-Right) trong **1 lần đọc duy nhất** (tiết kiệm 50% I/O).
  - Stream trực tiếp qua stdin của FFmpeg, **lossless copy (`-c:v copy -tag:v hvc1`)**, không tốn ổ cứng tạm.
  - Tốc độ xử lý cực cao: **~10,000 - 11,000 FPS**.
  - Tự động nhận diện FPS từ timestamp phần cứng.
  - Tự động cảnh báo part bị thiếu/ngắt quãng.
  - Có tùy chọn `--h264` để re-encode cho các thiết bị cũ.

**Cú pháp CLI (PowerShell 7)**:
```powershell
# Chuyển đổi cả 2 camera (mặc định)
.\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder"

# Tùy chọn camera: both (cả 2), left (trái), right (phải)
.\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --camera left

# Chỉ định thư mục xuất file khác
.\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --output-dir "D:\MCAPConverter\output"

# Re-encode H.264
.\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --h264
```

### 4.2. `inject_video_to_mcap.py` (Script Nạp Ngược Video vào MCAP)
- **Mục đích**: Nhận video MP4 đã chỉnh sửa (làm mờ mặt, trim, gán nhãn...) và nạp ngược lại vào cấu trúc file `part_xxxxx.mcap` gốc.
- **Tính năng**:
  - Tự động đọc `session.json` để đồng bộ timestamp và part index tương ứng.
  - Hỗ trợ thay thế linh hoạt: cả 2 camera hoặc chỉ 1 camera (giữ nguyên camera còn lại từ MCAP gốc).
  - Tự động nén lại bằng H.265 Annex-B hoặc copy trực tiếp nếu MP4 là HEVC.
  - Bảo toàn 100% dữ liệu cảm biến: `/ego/imu`, `/top-*-camera/camera-info`, `/tf_static`, `/camera/exposure_diagnostics`.
  - Hỗ trợ video bị cắt ngắn (trim) thông qua cờ `--trim-start-frame` hoặc tự động dừng khi hết frame.

**Cú pháp CLI (PowerShell 7)**:
```powershell
# Nạp lại video vào MCAP (tự nhận diện video top_left và top_right trong thư mục)
.\.venv\Scripts\python inject_video_to_mcap.py "D:\path\to\original_mcap_dir" --output-dir "D:\MCAPConverter\output\repacked_session"

# Chỉ định rõ video đã sửa cho từng camera
.\.venv\Scripts\python inject_video_to_mcap.py "D:\path\to\original_mcap_dir" `
    --video-left "D:\path\to\edited_left.mp4" `
    --video-right "D:\path\to\edited_right.mp4" `
    --output-dir "D:\path\to\output_mcap_dir"

# Nếu video MP4 đã bị chỉnh sửa/đổi codec sang H.264, dùng --reencode:
.\.venv\Scripts\python inject_video_to_mcap.py "D:\path\to\original_mcap_dir" `
    --video-left "D:\path\to\blurred_left.mp4" `
    --reencode `
    --output-dir "D:\path\to\output_mcap_dir"
```

### 4.3. `merge_mcap.py` (Script Gộp MCAP Multipart & Đa Session)
- **Mục đích**: Gộp các part `part_xxxxx.mcap` trong 1 session HOẶC gộp đồng thời nhiều thư mục session thành 1 file `.mcap` duy nhất.
- **Tính năng**:
  - Lossless copy trực tiếp ở cấp độ message/chunk, không cần giải mã lại bitstream video hay protobuf.
  - Tốc độ cực nhanh: **~30,000 - 40,000 messages/giây** (~108 MB/s).
  - Tự động nhận diện thứ tự part và cảnh báo khoảng part bị thiếu (Gap Detection).
  - Tự động tịnh tiến timeline liền mạch (**Seamless Timeline Shift**) giữa các session: xử lý triệt để vấn đề mỗi session bị reset timestamp về 0.
  - Đồng bộ sâu cả timestamp container MCAP (`msg.log_time`/`msg.publish_time`) lẫn timestamp trong Protobuf payload của `foxglove.CompressedVideo`.
  - Hỗ trợ nén chunk bằng **Zstandard (ZSTD)** hoặc **LZ4** giúp tối ưu dung lượng và hỗ trợ random seek trên Foxglove Studio.
  - Bảo toàn 100% video stream, metadata (`session-metadata`, `capture-quality`), camera-info, IMU và timestamps.
  - Hỗ trợ truyền 1 thư mục cha chứa nhiều session con, hoặc liệt kê nhiều thư mục session riêng lẻ.

**Cú pháp CLI (PowerShell 7)**:
```powershell
# Gộp toàn bộ part trong 1 thư mục session
.\.venv\Scripts\python merge_mcap.py "D:\path\to\mcap_folder"

# Gộp TẤT CẢ các session con trong 1 thư mục cha (ví dụ: TSTECO_SPA_20261026)
.\.venv\Scripts\python merge_mcap.py "D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026"

# Gộp nhiều session cụ thể
.\.venv\Scripts\python merge_mcap.py "D:\path\to\session_1" "D:\path\to\session_2" -o "D:\MCAPConverter\output\merged.mcap"

# Xem trước danh sách các session và dung lượng mà không ghi file (Dry run)
.\.venv\Scripts\python merge_mcap.py "D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026" --dry-run
```

### 4.4. `extract_video.py` & `test.py`
- Các script thử nghiệm ban đầu trong quá trình nghiên cứu cấu trúc dữ liệu.

---

## 5. Quy Trình Làm Việc Hai Chiều (Two-Way Pipeline)

```
Bước 1: Trích xuất video & metadata
  .\.venv\Scripts\python convert_mcap.py "D:\data\session_01"
  --> Tạo ra session_01_top_left.mp4, session_01_top_right.mp4, session_01_session.json

Bước 2: Xử lý video độc lập (AI / OpenCV / DaVinci / Face Blurring)
  --> Tạo ra video đã chỉnh sửa: edited_top_left.mp4, edited_top_right.mp4

Bước 3: Nạp ngược video vào MCAP multipart
  .\.venv\Scripts\python inject_video_to_mcap.py "D:\data\session_01" `
      --video-left "D:\data\edited_top_left.mp4" `
      --output-dir "D:\data\session_01_processed"
  --> Tạo ra thư mục mới chứa part_00000.mcap, ... chuẩn 100% format gốc
```

---

## 6. Nhật Ký Xử Lý (Execution Log)

### Lần chạy: 2026-10-20
- **Thư mục nguồn**: `D:\TST\HumanEgo_Videos\20261019_SPA-20261020T023851Z-1-002\20261019_SPA\20261019_040342`
- **1. Xuất MP4 & Metadata**:
  - `20261019_040342_top_left.mp4`: 5,487 frames | 3.04 phút | 120.12 MB
  - `20261019_040342_top_right.mp4`: 5,487 frames | 3.04 phút | 120.00 MB
  - `20261019_040342_session.json`: 3 parts mapping | 5,487 timestamps
- **2. Kiểm nghiệm Nạp ngược (Roundtrip Test)**:
  - Công cụ: `inject_video_to_mcap.py`
  - Kết quả: Nạp thành công 71,319 messages vào 3 file part mới trong 3.73s (~19,100 msg/s).
  - Tỷ lệ khớp: Khớp chính xác 100% schemas, channels, số lượng frame video và dữ liệu cảm biến (IMU: 18,293 msgs/part, camera-info: 1 msg/part, tf_static: 1 msg/part).

### Lần chạy: 2026-10-23 (Tối ưu hóa nạp video từ CapCut & Hỗ trợ GPU)
- **Vấn đề**: Video sau khi chỉnh sửa bằng CapCut xuất ra ở định dạng mặc định H.264 (AVC) khiến `inject_video_to_mcap.py` phải dùng CPU `libx265` nén lại cho cả 2 camera, tốn ~45-50s/part.
- **Giải pháp tối ưu chuẩn**:
  1. **Thiết lập CapCut chuẩn**:
     - **Format**: MP4
     - **Codec**: Chọn **HEVC** (H.265) thay vì H.264 mặc định -> Kích hoạt chế độ **Lossless Stream Copy** (~1-1.5s/part).
     - **Resolution**: Giữ nguyên **1920x1200** (khớp camera intrinsics).
     - **Frame rate**: 30 fps (đồng bộ 1:1 với timeline).
  2. **Cập nhật script `inject_video_to_mcap.py`**:
     - Tự động nhận diện GPU tăng tốc phần cứng (Intel Quick Sync `hevc_qsv` / NVIDIA `hevc_nvenc`) khi bắt buộc phải re-encode video H.264.
     - Tối ưu hóa vòng lặp thông điệp (chuyển import ra ngoài vòng lặp message).

### Lần chạy: 2026-10-30 (Phát triển MCAP Studio GUI Trực Quan 4 Bước)
- **Mục tiêu**: Xây dựng giao diện Web App cục bộ hoàn chỉnh (FastAPI + Modern Dark Web UI) theo quy trình 4 bước khép kín.
- **Thực thi**:
  1. Khởi động nhanh 1-click qua `run_gui.bat` / `run_gui.ps1` / `gui_app.py`.
  2. Bước 1: Trích xuất MP4 từ MCAP multipart (`convert_mcap.py`).
  3. Bước 2: Nạp ngược video CapCut vào MCAP (`inject_video_to_mcap_v2.py`), tích hợp cẩm nang cấu hình CapCut lossless.
  4. Bước 3: Mở Foxglove Studio Desktop xem video & Tách các part vào thư mục con quy ước `..._P1/P2/P3` (mỗi nhóm <= 30 part ~ 30 phút).
  5. Bước 4: Gộp batch tất cả các thư mục con thành 1 file MCAP duy nhất (`<folder_P1>.mcap`) đặt bên trong từng folder và bảo toàn part gốc.
  6. Tích hợp nút bật cửa sổ chọn thư mục/file native Windows Explorer, tự động tìm thấy Foxglove Studio tại `AppData\Local\Programs\desktop\Foxglove.exe`, stream log qua WebSocket theo thời gian thực.