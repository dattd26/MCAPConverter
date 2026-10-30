# MCAPConverter - Bộ Công Cụ Chuyển Đổi MCAP ⇋ MP4 & Xử Lý Dữ Liệu Hai Chiều

Bộ công cụ xử lý dữ liệu video hai chiều hiệu năng cao chuyên biệt cho các tập tin `.mcap` dạng phân mảnh (multipart) từ hệ thống ghi hình Stereo/Ego-centric (như **HumanEgo**).

---

## 📌 Tính Năng Nổi Bật

- **Giao diện trực quan MCAP Studio (Mới)**:
  - Khởi động 1-click qua `run_gui.bat` hoặc PowerShell.
  - Tích hợp trọn vẹn luồng 4 bước: Trích xuất MP4 ➔ Nạp ngược CapCut ➔ Mở Foxglove & Tách folder dưới 30p (`_P1`, `_P2`) ➔ Gộp batch MCAP.
  - Hỗ trợ nút chọn thư mục/file native Windows Explorer, stream log thời gian thực và tự động liên kết Foxglove Studio Desktop.
- **Chuyển đổi 2 chiều hoàn chỉnh**:
  - **Chiều đi (`convert_mcap.py`)**: Tách xuất đồng thời cả 2 camera (Top-Left & Top-Right) thành các video `.mp4` hoàn chỉnh, kèm file đồng bộ `session.json`.
  - **Chiều về (`inject_video_to_mcap.py`)**: Nhận video `.mp4` đã qua xử lý (làm mờ mặt, gắn nhãn, hậu kỳ...) và nạp ngược lại vào cấu trúc các file `part_xxxxx.mcap` gốc.
  - **Gộp part (`merge_mcap.py`)**: Gộp toàn bộ các part rời rạc thành 1 file `.mcap` duy nhất để thuận tiện lưu trữ hoặc mở trên Foxglove Studio / Rviz.
- **Bảo toàn dữ liệu cảm biến 100%**:
  - Giữ nguyên vẹn toàn bộ các kênh đo quán tính (`/ego/imu`), thông số nội quan camera (`/top-*-camera/camera-info`), khung tọa độ (`/tf_static`) và phơi sáng (`/camera/exposure_diagnostics`).
- **Hiệu năng xử lý vượt trội**:
  - Áp dụng cơ chế **Lossless Remuxing (Stream Copy)** thông qua stdin pipe của FFmpeg, không sinh file rác tạm thời.
  - Tốc độ trích xuất đạt **~10,000 - 11,000 FPS**.
  - Tốc độ gộp file đạt **~30,000 - 40,000 messages/giây** (~108 MB/s).
  - Đọc đồng thời 2 luồng camera trong **1 lần đọc đĩa duy nhất** (tiết kiệm 50% I/O ổ cứng).
- **Tự động hóa thông minh**:
  - Tự động phát hiện part bị thiếu hoặc ngắt quãng (Gap Detection do tải nhiều file zip từ Google Drive).
  - Tự động trích xuất và tính toán FPS chính xác từ timestamp phần cứng nanosecond.
  - Tự động nhận diện GPU tăng tốc phần cứng (**NVIDIA NVENC** / **Intel QSV**) khi bắt buộc phải re-encode video H.264 về chuẩn H.265.

---

## 🛠️ Yêu Cầu Hệ Thống & Cài Đặt

### 1. Yêu cầu môi trường
- **Hệ điều hành**: Windows 10/11 (khuyến nghị chạy trên **PowerShell 7 (`pwsh`)**).
- **Python**: Phiên bản `3.10` hoặc `3.11` (được cấu hình trong `.venv`).
- **FFmpeg**: Bản build đầy đủ hỗ trợ HEVC/H.265 (ví dụ [gyan.dev full build](https://www.gyan.dev/ffmpeg/builds/)) và đã thêm vào biến môi trường `PATH`.

### 2. Cài đặt môi trường ảo (Virtualenv)

Mở **PowerShell 7** tại thư mục dự án:

```powershell
# Tạo môi trường ảo (nếu chưa có)
python -m venv .venv

# Kích hoạt môi trường ảo
.\.venv\Scripts\Activate.ps1

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

---

## 🖥️ Khởi Động Giao Diện Đồ Họa (MCAP Studio GUI)

Để sử dụng toàn bộ quy trình 4 bước qua giao diện trực quan thân thiện:

```powershell
# Cách 1 (Khuyên dùng): Click đúp chuột vào file run_gui.bat hoặc chạy qua PowerShell:
.\run_gui.bat

# Cách 2: Chạy trực tiếp qua Python
.\.venv\Scripts\python gui_app.py
```
> Trình duyệt web sẽ tự động bật tại địa chỉ `http://localhost:8000`.

---

## 🚀 Hướng Dẫn Sử Dụng Chi Tiết (CLI)

```
                       QUY TRÌNH LÀM VIỆC HAI CHIỀU
                       
  [MCAP Parts Gốc] ───(convert_mcap.py)───► [Video MP4] + [session.json]
         │                                        │
         │ (merge_mcap.py)                (Hậu kỳ / AI / Blur)
         ▼                                        │
  [1 File MCAP Duy Nhất]                          ▼
  [MCAP Mới (Repacked)] ◄──(inject_video_to_mcap.py)── [Video Đã Sửa]
```

---

### PHẦN 1: Trích Xuất MCAP Sang Video MP4 (`convert_mcap.py`)

#### 1. Chuyển đổi toàn bộ thư mục (Cả 2 camera - Khuyến nghị)
Mặc định script sẽ trích xuất cả 2 camera (Top-Left và Top-Right) thành 2 file MP4 và tạo file `session.json` lưu mốc thời gian:

```powershell
.\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder"
```

#### 2. Chỉ trích xuất một camera cụ thể
- Chỉ lấy camera trái:
  ```powershell
  .\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --camera left
  ```
- Chỉ lấy camera phải:
  ```powershell
  .\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --camera right
  ```

#### 3. Tùy chọn nâng cao
- **Chỉ định thư mục xuất file khác**:
  ```powershell
  .\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --output-dir "D:\MCAPConverter\output"
  ```
- **Chuyển đổi sang định dạng H.264 (tương thích thiết bị cũ)**:
  ```powershell
  .\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --h264
  ```
- **Cố định số khung hình trên giây (FPS)**:
  ```powershell
  .\.venv\Scripts\python convert_mcap.py "D:\path\to\mcap_folder" --fps 30.0
  ```

---

### PHẦN 2: Nạp Ngược Video Đã Sửa Vào MCAP (`inject_video_to_mcap.py`)

Sau khi bạn đã chỉnh sửa video (ví dụ: làm mờ khuôn mặt, che biển số xe, crop hoặc hiệu chỉnh màu sắc), sử dụng script này để nạp ngược lại vào cấu trúc multipart MCAP ban đầu.

#### 1. Nạp video Top-Left (Camera phải và các cảm biến giữ nguyên gốc)
```powershell
.\.venv\Scripts\python inject_video_to_mcap.py "D:\path\to\original_mcap_folder" `
    --video-left "D:\path\to\edited_top_left.mp4" `
    --output-dir "D:\path\to\output_mcap_folder"
```

#### 2. Nạp đồng thời cả 2 camera đã sửa
```powershell
.\.venv\Scripts\python inject_video_to_mcap.py "D:\path\to\original_mcap_folder" `
    --video-left "D:\path\to\edited_top_left.mp4" `
    --video-right "D:\path\to\edited_top_right.mp4" `
    --output-dir "D:\path\to\output_mcap_folder"
```

#### 3. Xử lý video bị cắt ngắn thời lượng (Trim)
Nếu video đã bị cắt bớt một số frame ở phần đầu, truyền tham số `--trim-start-frame` để đồng bộ đúng mốc thời gian:
```powershell
.\.venv\Scripts\python inject_video_to_mcap.py "D:\path\to\original_mcap_folder" `
    --video-left "D:\path\to\edited_top_left.mp4" `
    --trim-start-frame 150 `
    --output-dir "D:\path\to\output_mcap_folder"
```

> **Lưu ý quan trọng**: Thư mục đầu ra (`--output-dir`) phải là một thư mục mới riêng biệt để tránh ghi đè làm hỏng các file `.mcap` gốc.

---

### PHẦN 3: Gộp Các Part & Nhiều Folder MCAP Thành 1 File Duy Nhất (`merge_mcap.py`)

Gộp toàn bộ các part `part_xxxxx.mcap` trong một thư mục session **HOẶC gộp đồng thời nhiều thư mục session** thành một file `.mcap` hoàn chỉnh duy nhất để thuận tiện lưu trữ hoặc mở trực tiếp trên **Foxglove Studio**.

Script tự động giải quyết bài toán **reset timestamp về 0 ở đầu mỗi session** bằng cơ chế **tịnh tiến timeline liền mạch (seamless timeline shift)** cả ở MCAP container header lẫn bên trong Protobuf payload của video.

#### 1. Gộp toàn bộ part trong 1 thư mục session
```powershell
.\.venv\Scripts\python merge_mcap.py "D:\path\to\session_folder"
```
File xuất ra mặc định sẽ có tên `<tên_thư_mục>_merged.mcap`.

#### 2. Gộp TẤT CẢ các thư mục session con bên trong 1 thư mục cha
Ví dụ gộp cả 5 ca quay trong `D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026`:
```powershell
.\.venv\Scripts\python merge_mcap.py "D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026"
```
Script sẽ tự động phát hiện tất cả các folder session con (`20261026_024343`, `20261026_040301`,...), sắp xếp theo thứ tự thời gian và nối tiếp timeline liên tục.

#### 3. Gộp nhiều thư mục session cụ thể và chỉ định file xuất
```powershell
.\.venv\Scripts\python merge_mcap.py `
    "D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026\20261026_024343" `
    "D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026\20261026_040301" `
    -o "D:\MCAPConverter\output\two_sessions_merged.mcap"
```

#### 4. Xem trước danh sách file, các session và dung lượng mà không ghi file (Dry run)
```powershell
.\.venv\Scripts\python merge_mcap.py "D:\TST\HumanEgo_Videos\TSTECO_SPA_20261026" --dry-run
```

---

## 🎬 Hướng Dẫn Thiết Lập Video Editor Chuẩn (CapCut / Premiere / DaVinci)

Khi chỉnh sửa video trích xuất (làm mờ mặt, hậu kỳ) để chuẩn bị nạp ngược vào MCAP bằng `inject_video_to_mcap.py`, việc thiết lập đúng thông số xuất video sẽ quyết định tốc độ nạp:

| Thông Số | Giá Trị Thiết Lập Chuẩn | Ý Nghĩa Kỹ Thuật |
| :--- | :--- | :--- |
| **Định dạng (Format)** | **MP4** | Container tiêu chuẩn |
| **Bộ mã hóa (Codec)** | **HEVC / H.265** *(Không chọn H.264)* | Kích hoạt chế độ **Lossless Stream Copy** (~1-1.5s/part). Nếu để H.264, script sẽ phải re-encode tốn 45-50s/part. |
| **Độ phân giải** | **1920 × 1200** *(Khớp chính xác)* | Giữ nguyên tỷ lệ 16:10 để bảo toàn camera intrinsics |
| **Tốc độ khung hình (FPS)** | **30 fps** (hoặc đồng bộ 1:1 timeline gốc) | Tránh lệch frame và lệch mốc thời gian IMU |

> **Cơ chế tăng tốc phần cứng (Hardware Acceleration)**:  
> Trong trường hợp bắt buộc phải re-encode video H.264 sang H.265, `inject_video_to_mcap.py` sẽ tự động phát hiện và kích hoạt GPU:
> - **NVIDIA NVENC**: `hevc_nvenc` (ưu tiên 1)
> - **Intel Quick Sync**: `hevc_qsv` (ưu tiên 2)
> - **CPU**: `libx265` (dự phòng khi không có GPU)

---

## 📊 Bảng Tham Số Dòng Lệnh (CLI Arguments)

### Tham số `convert_mcap.py`
| Tham số | Viết tắt | Mặc định | Mô tả |
| :--- | :---: | :---: | :--- |
| `input_dir` | | *Bắt buộc* | Đường dẫn đến thư mục chứa các file `part_xxxxx.mcap` |
| `--output-dir` | `-o` | Cùng thư mục nguồn | Thư mục lưu các file `.mp4` và `session.json` xuất ra |
| `--camera` | `-c` | `both` | Tùy chọn camera xuất: `both` (cả hai), `left`, hoặc `right` |
| `--fps` | | Tự động nhận diện | Ghi đè số FPS thay vì tự động tính từ timestamp phần cứng |
| `--h264` | | `False` | Bật mã hóa lại sang H.264 (nếu không dùng sẽ là H.265 copy) |

### Tham số `inject_video_to_mcap.py`
| Tham số | Viết tắt | Mặc định | Mô tả |
| :--- | :---: | :---: | :--- |
| `original_mcap_dir` | | *Bắt buộc* | Đường dẫn thư mục chứa các file `.mcap` gốc |
| `--video-left` | `-vl` | `None` | Đường dẫn file MP4 thay thế cho camera Top-Left |
| `--video-right` | `-vr` | `None` | Đường dẫn file MP4 thay thế cho camera Top-Right |
| `--output-dir` | `-o` | *Bắt buộc* | Thư mục ghi các file `.mcap` mới được đóng gói lại |
| `--session-json` | `-s` | Tự tìm trong thư mục | Đường dẫn file `session.json` để đối chiếu |
| `--reencode` | | Tự động | Bắt buộc mã hóa lại sang H.265 (tự động bật nếu video là H.264) |
| `--trim-start-frame` | | `0` | Số lượng frame bị cắt ở đầu video |

### Tham số `merge_mcap.py`
| Tham số | Viết tắt | Mặc định | Mô tả |
| :--- | :---: | :---: | :--- |
| `inputs` | | *Bắt buộc* | Một hoặc nhiều thư mục session, hoặc 1 thư mục cha chứa các session con |
| `--output` | `-o` | Tự động sinh theo tên session | Đường dẫn file `.mcap` đầu ra |
| `--output-dir` | | Cùng thư mục nguồn | Thư mục lưu file đầu ra nếu không chỉ định `-o` |
| `--compression` | | `zstd` | Thuật toán nén chunk: `zstd`, `lz4`, hoặc `none` |
| `--chunk-size` | | `4` | Kích thước mỗi chunk (MB) |
| `--part-range` | | `None` | Giới hạn khoảng part cần gộp cho từng session (vd: `0-10`) |
| `--no-shift-timeline` | | `False` | Tắt chế độ tịnh tiến timeline nối tiếp (giữ nguyên timestamp gốc) |
| `--dry-run` | | `False` | Chỉ kiểm tra danh sách session, file và timeline mà không ghi file |

---

## 🧠 Đặc Tả Kỹ Thuật (Data Specifications)

### 1. Cấu trúc Topic & Schema Protobuf
Dữ liệu trong các file MCAP thuộc bộ dataset này sử dụng mã hóa **Protobuf** (KHÔNG PHẢI ROS2 / CDR):
- **Schema**: `foxglove.CompressedVideo` (Protobuf)
  - `field 1` (`wire=2`): `timestamp` (`google.protobuf.Timestamp`: field 1: `seconds`, field 2: `nanos`)
  - `field 2` (`wire=2`): `frame_id` (`string`)
  - `field 3` (`wire=2`): `data` (`bytes` - chứa chuỗi byte nén Annex-B của video)
  - `field 4` (`wire=2`): `format` (`string` - giá trị: `"h265"`)

### 2. Danh sách Channels trong MCAP
1. `/top-left-camera/image-raw`: Luồng video camera mắt trái (H.265)
2. `/top-right-camera/image-raw`: Luồng video camera mắt phải (H.265)
3. `/top-left-camera/camera-info`: Thông số nội quan (intrinsics) camera trái
4. `/top-right-camera/camera-info`: Thông số nội quan camera phải
5. `/ego/imu`: Dữ liệu cảm biến đo quán tính IMU
6. `/tf_static`: Tọa độ các khớp và camera
7. `/camera/exposure_diagnostics`: Chẩn đoán độ phơi sáng camera

### 3. Định dạng Video Stream
- **Codec**: **H.265 / HEVC** (Annex-B stream, mỗi NAL bắt đầu bằng `00 00 00 01`)
- **Độ phân giải**: **1920 × 1200**
- **Frame Rate**: **~30.106 FPS** (Khoảng cách giữa các frame là `0.033216s`, tính từ timestamp thực tế)
- **Đặc tính phân mảnh**:
  - Mỗi file `.mcap` đại diện cho một part dài xấp xỉ **1 phút** (~1,827 - 1,830 frames).
  - Đầu mỗi part đều chứa NAL units: VPS (`0x40`), SPS (`0x42`), PPS, và IDR Keyframe, cho phép nối chuỗi (concatenate) bitstream trực tiếp ở mức lossless mà không bị lỗi giải mã.

---

## ⚠️ Các Vấn Đề Kỹ Thuật Quan Trọng Cần Tránh (Critical Pitfalls)

| Vấn đề | Chi tiết & Nguyên nhân | Giải pháp chuẩn |
| :--- | :--- | :--- |
| **Không dùng ROS2 Decoder** | File MCAP dùng protobuf `foxglove.CompressedVideo`. Thư viện `mcap_ros2` với `DecoderFactory` sẽ báo lỗi hoặc không decode được schema. | Dùng parser varint/protobuf nhẹ tự viết (`parse_compressed_video`) hoặc `mcap.protobuf`. |
| **cv2.imdecode thất bại trên raw H.265** | `cv2.imdecode` chỉ hỗ trợ container image (JPEG/PNG/WebP), không thể decode trực tiếp raw Annex-B H.265 NAL stream. | Sử dụng **FFmpeg** để remux hoặc decode. |
| **Tràn bộ nhớ RAM (OOM)** | Đọc cả mảng frame uncompressed của 1 file vào RAM (1,830 frame × 1920 × 1200 × 3 = ~12.6 GB/part) sẽ gây tràn RAM khi chạy batch. | Dùng cơ chế **streaming trực tiếp** (pipe vào stdin của FFmpeg) không lưu mảng frame trong RAM. |
| **Deadlock pipe FFmpeg** | Nếu bắt `stderr=subprocess.PIPE` của FFmpeg mà không đọc bất đồng bộ, bộ đệm pipe hệ thống bị đầy sẽ gây treo tiến trình (deadlock). | Sử dụng daemon thread đọc `stderr` liên tục hoặc redirect log. |
| **Thiếu Part do Google Drive Zip** | Khi tải từ Google Drive, dữ liệu lớn bị tách thành nhiều file zip (`-001.zip`, `-002.zip`). Một thư mục con có thể chỉ chứa một vài part (vd: part 0, 10, 13). | Script có tính năng **Gap Detection** để tự động cảnh báo phần nào bị thiếu. |
| **Windows Console Encoding** | Mặc định PowerShell/cmd có thể dùng `cp1252` gây lỗi `UnicodeEncodeError` khi in tiếng Việt. | Cần cấu hình `sys.stdout.reconfigure(encoding="utf-8")`. |

---

## 📈 Nhật Ký Kiểm Nghiệm & Hiệu Năng Thực Tế (Execution Log & Benchmarks)

### 1. Trích xuất video (`convert_mcap.py`)
- **Tốc độ xử lý**: **~10,000 - 11,000 FPS**.
- **Hiệu quả I/O**: Đọc đồng thời cả 2 camera trong 1 pass, 1 session 3 phút (~5,487 frames/camera) trích xuất hoàn tất trong chưa đầy **2 giây**.

### 2. Nạp ngược video (`inject_video_to_mcap.py`)
- **Trường hợp Lossless Copy (CapCut xuất HEVC)**:
  - Tốc độ xử lý: **~19,100 messages/giây**.
  - Đóng gói hoàn tất 71,319 messages vào 3 file part mới trong **3.73s**.
  - Khớp 100% schemas, channels, số frame và dữ liệu cảm biến (IMU: 18,293 msgs/part, camera-info: 1 msg/part, tf_static: 1 msg/part).
- **Trường hợp Re-encode (Video đầu vào là H.264)**:
  - Với CPU `libx265`: Tốn ~45-50s/part.
  - Với GPU NVENC (`hevc_nvenc`): Rút ngắn xuống **~3-5s/part**.

### 3. Gộp file MCAP (`merge_mcap.py`)
- **Tốc độ xử lý**: **~31,000 - 33,000 messages/giây** (~108 MB/s).
- **Kết quả nén chunk (ZSTD 4MB)**: Giảm dung lượng file gộp từ 165.65 MB xuống còn 163.49 MB trong khi bảo toàn 100% metadata và bảng chỉ mục (index) giúp Foxglove Studio tìm kiếm khung hình tức thì.
