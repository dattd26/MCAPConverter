# MCAPConverter - Bộ Công Cụ Chuyển Đổi MCAP ⇋ MP4 Hai Chiều

Bộ công cụ xử lý dữ liệu video hai chiều hiệu năng cao chuyên biệt cho các tập tin `.mcap` dạng phân mảnh (multipart) từ hệ thống ghi hình Stereo/Ego-centric (như **HumanEgo**).

---

## 📌 Tính Năng Nổi Bật

- **Chuyển đổi 2 chiều hoàn chỉnh**:
  - **Chiều đi (`convert_mcap.py`)**: Tách xuất đồng thời cả 2 camera (Top-Left & Top-Right) thành các video `.mp4` hoàn chỉnh, kèm file đồng bộ `session.json`.
  - **Chiều về (`inject_video_to_mcap.py`)**: Nhận video `.mp4` đã qua xử lý (làm mờ mặt, gắn nhãn, hậu kỳ...) và nạp ngược lại vào cấu trúc các file `part_xxxxx.mcap` gốc.
- **Bảo toàn dữ liệu cảm biến 100%**:
  - Giữ nguyên vẹn toàn bộ các kênh đo quán tính (`/ego/imu`), thông số nội quan camera (`/top-*-camera/camera-info`), khung tọa độ (`/tf_static`) và phơi sáng (`/camera/exposure_diagnostics`).
- **Hiệu năng xử lý vượt trội**:
  - Áp dụng cơ chế **Lossless Remuxing (Stream Copy)** thông qua stdin pipe của FFmpeg, không sinh file rác tạm thời.
  - Tốc độ trích xuất đạt **~10,000 FPS**.
  - Đọc đồng thời 2 luồng camera trong **1 lần đọc đĩa duy nhất** (tiết kiệm 50% I/O ổ cứng).
- **Tự động hóa thông minh**:
  - Tự động phát hiện part bị thiếu (Gap Detection).
  - Tự động trích xuất và tính toán FPS chính xác từ timestamp phần cứng nanosecond.
  - Tự động nhận diện định dạng video nạp vào (tự động re-encode chuẩn H.265 nếu video đầu vào là H.264/AVC).

---

## 🛠️ Yêu Cầu Hệ Thống & Cài Đặt

### 1. Yêu cầu môi trường
- **Hệ điều hành**: Windows 10/11 (khuyến nghị chạy trên **PowerShell 7 (`pwsh`)**).
- **Python**: Phiên bản `3.10` hoặc `3.11`.
- **FFmpeg**: Bản build đầy đủ hỗ trợ HEVC/H.265 (ví dụ [gyan.dev full build](https://www.gyan.dev/ffmpeg/builds/)) và đã thêm vào biến môi trường `PATH`.

### 2. Cài đặt môi trường ảo (Virtualenv)

Mở **PowerShell 7** tại thư mục dự án:

```powershell
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo
.\.venv\Scripts\Activate.ps1

# Cài đặt các thư viện cần thiết
pip install mcap protobuf opencv-python numpy
```

---

## 🚀 Hướng Dẫn Sử Dụng Chi Tiết

```
                       QUY TRÌNH LÀM VIỆC HAI CHIỀU
                       
  [MCAP Parts Gốc] ───(convert_mcap.py)───► [Video MP4] + [session.json]
                                                  │
                                          (Hậu kỳ / AI / Blur)
                                                  │
                                                  ▼
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

> **Lưu ý quan trọng**: Thư mục đầu ra (`--output-dir`) nên là một thư mục mới riêng biệt để tránh ghi đè làm hỏng các file `.mcap` gốc.

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

---

## 🧠 Đặc Tả Kỹ Thuật (Data Specifications)

- **Mã hóa Payload**: Chuẩn Protobuf `foxglove.CompressedVideo`:
  - `field 1`: `timestamp` (`google.protobuf.Timestamp`)
  - `field 2`: `frame_id` (`string`)
  - `field 3`: `data` (`bytes` - Annex-B stream bắt đầu bằng `00 00 00 01`)
  - `field 4`: `format` (`string: "h265"`)
- **Danh sách Channels bảo toàn**:
  1. `/top-left-camera/image-raw` (HEVC)
  2. `/top-right-camera/image-raw` (HEVC)
  3. `/top-left-camera/camera-info` (Intrinsics)
  4. `/top-right-camera/camera-info` (Intrinsics)
  5. `/ego/imu` (IMU Sensors)
  6. `/tf_static` (Coordinate Transforms)
  7. `/camera/exposure_diagnostics` (Diagnostics)
