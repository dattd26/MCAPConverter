import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Thêm thư mục gốc vào sys.path để import merge_mcap
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from merge_mcap import SessionInfo, find_mcap_parts, merge_sessions


def scan_merge_targets(parent_or_subdirs: List[str]) -> List[Dict[str, Any]]:
    """
    Quét danh sách các thư mục con có chứa part MCAP cần gộp.
    Hỗ trợ truyền vào 1 thư mục cha (sẽ tự động tìm các folder con _P1, _P2...)
    hoặc danh sách các thư mục con trực tiếp.
    """
    folders_to_check: List[Path] = []

    for item in parent_or_subdirs:
        p = Path(item).resolve()
        if not p.exists() or not p.is_dir():
            continue

        # Kiểm tra nếu thư mục chứa trực tiếp part_*.mcap
        parts_here = [f for f in p.glob("*.mcap") if not f.name.endswith("_merged.mcap") and not f.name.endswith(".tmp.mcap")]
        if parts_here:
            folders_to_check.append(p)
            continue

        # Nếu không có part trực tiếp, tìm các thư mục con bên trong
        subdirs = [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
        # Sắp xếp tự nhiên
        subdirs.sort(key=lambda d: [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", d.name)])
        for sd in subdirs:
            sd_parts = [f for f in sd.glob("*.mcap") if not f.name.endswith("_merged.mcap") and not f.name.endswith(".tmp.mcap")]
            if sd_parts:
                folders_to_check.append(sd)

    targets = []
    for fld in folders_to_check:
        parts = find_mcap_parts(fld)
        # Loại trừ các file merged đã tạo trước đó
        valid_parts = [f for f in parts if f.name != f"{fld.name}.mcap" and not f.name.endswith("_merged.mcap")]
        expected_output = fld / f"{fld.name}.mcap"
        total_size = sum(f.stat().st_size for f in valid_parts)

        targets.append({
            "name": fld.name,
            "folder": str(fld.resolve()),
            "parts_count": len(valid_parts),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "expected_output": str(expected_output.resolve()),
            "already_merged": expected_output.exists(),
        })

    return targets


def run_batch_merge(
    targets: List[Dict[str, Any]],
    compression: str = "zstd",
    chunk_size_mb: int = 4,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Thực hiện gộp tuần tự từng thư mục con thành 1 file .mcap trùng tên thư mục.
    """
    def log(msg: str):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    results = []
    success_count = 0
    fail_count = 0

    log("\n" + "=" * 70)
    log(f" BẮT ĐẦU QUY TRÌNH GỘP BATCH CHO {len(targets)} THƯ MỤC CON")
    log("=" * 70)

    for idx, t in enumerate(targets, 1):
        fld_path = Path(t["folder"])
        out_file = Path(t["expected_output"])
        parts = find_mcap_parts(fld_path)
        valid_parts = [f for f in parts if f.name != out_file.name and not f.name.endswith("_merged.mcap")]

        if not valid_parts:
            log(f"[{idx}/{len(targets)}] Bỏ qua {t['name']}: Không tìm thấy file part hợp lệ.")
            continue

        log(f"\n[{idx}/{len(targets)}] Đang gộp {t['name']} ({len(valid_parts)} parts)...")
        log(f" -> File kết quả: {out_file.name}")

        session_info = SessionInfo(name=t["name"], folder=fld_path, files=valid_parts)
        t_start = time.perf_counter()

        try:
            ok = merge_sessions(
                sessions=[session_info],
                output_file=out_file,
                compression=compression,
                chunk_size_mb=chunk_size_mb,
                shift_timeline=False,  # Trong 1 session con không cần shift timeline
                deep_timestamp_sync=True,
            )
            elapsed = time.perf_counter() - t_start

            if ok and out_file.exists():
                size_mb = out_file.stat().st_size / (1024 * 1024)
                log(f" HOÀN TẤT: {out_file.name} ({size_mb:.2f} MB, {elapsed:.2f}s)")
                success_count += 1
                results.append({
                    "folder": t["name"],
                    "output_file": str(out_file),
                    "size_mb": round(size_mb, 2),
                    "success": True,
                })
            else:
                log(f" THẤT BẠI khi gộp {t['name']}")
                fail_count += 1
                results.append({
                    "folder": t["name"],
                    "success": False,
                    "error": "Quá trình gộp trả về lỗi.",
                })
        except Exception as e:
            log(f" LỖI NGOẠI LỆ ({t['name']}): {e}")
            fail_count += 1
            results.append({
                "folder": t["name"],
                "success": False,
                "error": str(e),
            })

    log("\n" + "=" * 70)
    log(f" TỔNG KẾT GỘP BATCH: Thành công {success_count}/{len(targets)} | Thất bại {fail_count}")
    log("=" * 70 + "\n")

    return {
        "total": len(targets),
        "success_count": success_count,
        "fail_count": fail_count,
        "details": results,
    }
