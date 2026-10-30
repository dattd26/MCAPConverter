import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Thêm thư mục gốc vào sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gui.backend.batch_merger import run_batch_merge, scan_merge_targets
from gui.backend.splitter import execute_split, scan_parts
from gui.backend.system_utils import (
    find_foxglove_bin,
    launch_foxglove,
    open_in_explorer,
    pick_directory,
    pick_file,
)

app = FastAPI(title="MCAPConverter Studio", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = ROOT_DIR / "gui" / "frontend"

# Quản lý WebSocket clients và logs
connected_websockets: Set[WebSocket] = set()
log_history: List[str] = []
MAX_LOG_HISTORY = 3000
current_running_process: Optional[subprocess.Popen] = None
is_task_running = False
current_task_name = ""


MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
async def startup_event():
    global MAIN_EVENT_LOOP
    MAIN_EVENT_LOOP = asyncio.get_running_loop()


async def broadcast_log(line: str):
    """Gửi một dòng log tới toàn bộ WebSockets và lưu vào lịch sử."""
    global log_history
    log_history.append(line)
    if len(log_history) > MAX_LOG_HISTORY:
        log_history = log_history[-MAX_LOG_HISTORY:]

    dead_clients = set()
    for ws in list(connected_websockets):
        try:
            await ws.send_text(json.dumps({"type": "log", "data": line}))
        except Exception:
            dead_clients.add(ws)
    for ws in dead_clients:
        connected_websockets.discard(ws)


def sync_broadcast_log(line: str):
    """Bọc đồng bộ cho callback gọi từ thread khác để gửi về WebSocket."""
    global MAIN_EVENT_LOOP
    print(line)
    try:
        if MAIN_EVENT_LOOP and MAIN_EVENT_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_log(line), MAIN_EVENT_LOOP)
        else:
            try:
                loop = asyncio.get_running_loop()
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(broadcast_log(line), loop)
            except Exception:
                pass
    except Exception:
        pass


# ==========================================
# WEBSOCKET LOGS
# ==========================================
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    global MAIN_EVENT_LOOP
    if MAIN_EVENT_LOOP is None or not MAIN_EVENT_LOOP.is_running():
        MAIN_EVENT_LOOP = asyncio.get_running_loop()
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        # Gửi lại 200 dòng log gần nhất khi mới kết nối
        recent = log_history[-200:] if len(log_history) > 200 else log_history
        await websocket.send_text(json.dumps({
            "type": "init",
            "history": recent,
            "is_running": is_task_running,
            "task_name": current_task_name,
        }))
        while True:
            # Giữ kết nối
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_websockets.discard(websocket)
    except Exception:
        connected_websockets.discard(websocket)


# ==========================================
# SYSTEM & DIALOG APIs
# ==========================================
class PickDialogRequest(BaseModel):
    title: Optional[str] = "Chọn Thư Mục"


class PickFileDialogRequest(BaseModel):
    title: Optional[str] = "Chọn Tập Tin"
    file_type: Optional[str] = "video"  # "video" hoặc "mcap"


class PathRequest(BaseModel):
    path: Optional[str] = None
    paths: Optional[List[str]] = None


@app.post("/api/pick-folder")
def api_pick_folder(req: PickDialogRequest):
    folder = pick_directory(title=req.title or "Chọn Thư Mục")
    return {"path": folder}


@app.post("/api/pick-file")
def api_pick_file(req: PickFileDialogRequest):
    if req.file_type == "video":
        ft = [("Video MP4", "*.mp4;*.mov;*.mkv"), ("Tất cả tập tin", "*.*")]
    elif req.file_type == "mcap":
        ft = [("MCAP Files", "*.mcap"), ("Tất cả tập tin", "*.*")]
    else:
        ft = [("Tất cả tập tin", "*.*")]
    file_path = pick_file(title=req.title or "Chọn Tập Tin", filetypes=ft)
    return {"path": file_path}


@app.post("/api/open-foxglove")
def api_open_foxglove(req: PathRequest):
    target = req.paths if req.paths else req.path
    if not target:
        raise HTTPException(status_code=400, detail="Không có đường dẫn file nào được cung cấp.")
    success = launch_foxglove(target)
    return {"success": success, "foxglove_bin": find_foxglove_bin()}


@app.post("/api/open-explorer")
def api_open_explorer(req: PathRequest):
    success = open_in_explorer(req.path)
    return {"success": success}


@app.get("/api/detect-encoders")
def api_detect_encoders():
    """Kiểm tra danh sách encoder phần cứng có sẵn qua ffmpeg."""
    encoders = [
        {"id": "auto", "label": "Tự động phát hiện (Ưu tiên GPU)"},
        {"id": "hevc_nvenc", "label": "NVIDIA NVENC (hevc_nvenc)"},
        {"id": "hevc_qsv", "label": "Intel Quick Sync (hevc_qsv)"},
        {"id": "hevc_amf", "label": "AMD AMF (hevc_amf)"},
        {"id": "libx265", "label": "CPU libx265 (Chậm hơn, tương thích 100%)"},
    ]
    foxglove_bin = find_foxglove_bin()
    return {"encoders": encoders, "foxglove_found": foxglove_bin is not None, "foxglove_path": foxglove_bin}


@app.get("/api/status")
def api_status():
    return {
        "is_running": is_task_running,
        "current_task": current_task_name,
    }


@app.post("/api/cancel-task")
async def api_cancel_task():
    global current_running_process, is_task_running, current_task_name
    if current_running_process and current_running_process.poll() is None:
        try:
            current_running_process.terminate()
            await broadcast_log("[HỦY BỎ] Đã gửi tín hiệu dừng tiến trình đang chạy.")
        except Exception as e:
            await broadcast_log(f"[LỖI HỦY] Không thể dừng tiến trình: {e}")
    is_task_running = False
    current_task_name = ""
    return {"success": True}


# ==========================================
# PROCESS RUNNER HELPER
# ==========================================
def run_command_in_background(cmd: List[str], task_name: str, on_complete: Optional[Callable[[bool], None]] = None):
    """Chạy kịch bản Python trong luồng riêng và stream log ra WebSocket."""
    global current_running_process, is_task_running, current_task_name

    def worker():
        global current_running_process, is_task_running, current_task_name
        is_task_running = True
        current_task_name = task_name

        sync_broadcast_log(f"\n{'='*70}\n[BẮT ĐẦU TÁC VỤ] {task_name}\nLệnh: {' '.join(cmd)}\n{'='*70}\n")
        try:
            # Tạo môi trường UTF-8 cho subprocess
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(ROOT_DIR),
                env=env,
            )
            current_running_process = proc

            for line in proc.stdout:
                line_str = line.rstrip()
                if line_str:
                    sync_broadcast_log(line_str)

            proc.wait()
            success = (proc.returncode == 0)
            if success:
                sync_broadcast_log(f"\n[HOÀN THÀNH THÀNH CÔNG] Tác vụ: {task_name}\n")
            else:
                sync_broadcast_log(f"\n[KẾT THÚC CÓ LỖI] Mã lỗi: {proc.returncode} cho tác vụ: {task_name}\n")

            if on_complete:
                on_complete(success)

        except Exception as e:
            sync_broadcast_log(f"\n[LỖI THỰC THI] {e}\n")
            if on_complete:
                on_complete(False)
        finally:
            is_task_running = False
            current_task_name = ""
            current_running_process = None

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


# ==========================================
# STEP 1: CONVERT MCAP TO MP4
# ==========================================
class Step1Request(BaseModel):
    mcap_dir: str
    camera: str = "both"  # "both", "left", "right"
    output_dir: Optional[str] = None
    h264: bool = False


@app.post("/api/step1/run")
async def api_step1_run(req: Step1Request):
    global is_task_running
    if is_task_running:
        raise HTTPException(status_code=400, detail="Một tác vụ khác đang chạy. Vui lòng đợi hoặc bấm Hủy.")

    src = Path(req.mcap_dir).resolve()
    if not src.exists():
        raise HTTPException(status_code=400, detail="Thư mục MCAP nguồn không tồn tại.")

    py_bin = sys.executable
    script = str(ROOT_DIR / "convert_mcap.py")

    cmd = [py_bin, script, str(src), "--camera", req.camera]
    if req.output_dir:
        cmd.extend(["--output-dir", str(Path(req.output_dir).resolve())])
    if req.h264:
        cmd.append("--h264")

    run_command_in_background(cmd, f"Trích xuất MP4 từ {src.name}")
    return {"started": True, "task": f"Trích xuất MP4 ({src.name})"}


# ==========================================
# STEP 2: INJECT CAPCUT VIDEO TO MCAP
# ==========================================
class Step2Request(BaseModel):
    original_mcap_dir: str
    video_left: Optional[str] = None
    video_right: Optional[str] = None
    output_dir: Optional[str] = None
    encoder: Optional[str] = "auto"
    reencode: bool = False


@app.post("/api/step2/run")
async def api_step2_run(req: Step2Request):
    global is_task_running
    if is_task_running:
        raise HTTPException(status_code=400, detail="Một tác vụ khác đang chạy. Vui lòng đợi hoặc bấm Hủy.")

    src = Path(req.original_mcap_dir).resolve()
    if not src.exists():
        raise HTTPException(status_code=400, detail="Thư mục MCAP gốc không tồn tại.")

    py_bin = sys.executable
    script = str(ROOT_DIR / "inject_video_to_mcap_v2.py")

    cmd = [py_bin, script, str(src)]
    if req.video_left:
        cmd.extend(["--video-left", str(Path(req.video_left).resolve())])
    if req.video_right:
        cmd.extend(["--video-right", str(Path(req.video_right).resolve())])
    if req.output_dir:
        cmd.extend(["--output-dir", str(Path(req.output_dir).resolve())])
    if req.encoder and req.encoder != "auto":
        cmd.extend(["--encoder", req.encoder])
    if req.reencode:
        cmd.append("--reencode")

    run_command_in_background(cmd, f"Nạp ngược Video CapCut vào MCAP ({src.name})")
    return {"started": True, "task": f"Nạp Video vào MCAP ({src.name})"}


# ==========================================
# STEP 3: FOXGLOVE & PART SPLITTER
# ==========================================
class Step3ScanRequest(BaseModel):
    dir_path: str


class Step3Segment(BaseModel):
    name: str
    start_part: int
    end_part: int


class Step3ExecuteRequest(BaseModel):
    dir_path: str
    segments: List[Step3Segment]


@app.post("/api/step3/scan")
def api_step3_scan(req: Step3ScanRequest):
    res = scan_parts(req.dir_path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/step3/execute")
async def api_step3_execute(req: Step3ExecuteRequest):
    segments_dict = [s.model_dump() for s in req.segments]
    res = execute_split(req.dir_path, segments_dict)
    if not res.get("success"):
        error_msg = "; ".join(res.get("errors", ["Lỗi không xác định"]))
        await broadcast_log(f"[LỖI TÁCH PART] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

    await broadcast_log(f"[TÁCH THÀNH CÔNG] Đã di chuyển {res['total_moved']} parts vào {len(res['created_subfolders'])} thư mục con.")
    return res


# ==========================================
# STEP 4: BATCH MERGE MCAP
# ==========================================
class Step4ScanRequest(BaseModel):
    paths: List[str]


class Step4Target(BaseModel):
    name: str
    folder: str
    parts_count: int
    total_size_mb: float
    expected_output: str
    already_merged: bool


class Step4ExecuteRequest(BaseModel):
    targets: List[Step4Target]
    compression: str = "zstd"
    chunk_size_mb: int = 4


@app.post("/api/step4/scan")
def api_step4_scan(req: Step4ScanRequest):
    targets = scan_merge_targets(req.paths)
    return {"targets": targets, "count": len(targets)}


@app.post("/api/step4/run")
async def api_step4_run(req: Step4ExecuteRequest):
    global is_task_running, current_task_name
    if is_task_running:
        raise HTTPException(status_code=400, detail="Một tác vụ khác đang chạy. Vui lòng đợi hoặc bấm Hủy.")

    targets_dict = [t.model_dump() for t in req.targets]
    if not targets_dict:
        raise HTTPException(status_code=400, detail="Không có thư mục nào để gộp.")

    def worker():
        global is_task_running, current_task_name
        is_task_running = True
        current_task_name = f"Gộp {len(targets_dict)} thư mục MCAP"
        try:
            run_batch_merge(
                targets=targets_dict,
                compression=req.compression,
                chunk_size_mb=req.chunk_size_mb,
                log_callback=sync_broadcast_log,
            )
        finally:
            is_task_running = False
            current_task_name = ""

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    return {"started": True, "targets_count": len(targets_dict)}


# ==========================================
# STATIC FILES SERVING
# ==========================================
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
def get_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"message": "MCAPConverter API Server is running. Frontend not found."})

@app.get("/{file_name}")
def get_root_file(file_name: str):
    target = FRONTEND_DIR / file_name
    if target.exists() and target.is_file():
        return FileResponse(str(target))
    raise HTTPException(status_code=404, detail="File not found")
