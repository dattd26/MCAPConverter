import math
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def natural_sort_key(path: Path) -> List[object]:
    """Sắp xếp tự nhiên theo số hiệu file."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", path.name)]


def extract_part_number(filename: str) -> Optional[int]:
    """Trích xuất số part từ tên file (ví dụ: part_00012.mcap -> 12)."""
    m = re.search(r"part_(\d+)", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def scan_parts(dir_path: str) -> Dict[str, Any]:
    """Quét và phân tích chi tiết các file part .mcap trong thư mục."""
    folder = Path(dir_path).resolve()
    if not folder.exists() or not folder.is_dir():
        return {"error": f"Thư mục không tồn tại: {dir_path}"}

    # Tìm tất cả file .mcap không phải file merged
    all_mcap = [
        f for f in folder.glob("*.mcap")
        if not f.name.endswith("_merged.mcap") and not f.name.endswith(".tmp.mcap")
    ]
    all_mcap.sort(key=natural_sort_key)

    if not all_mcap:
        return {
            "folder": str(folder),
            "folder_name": folder.name,
            "parts": [],
            "total_parts": 0,
            "total_size_mb": 0,
            "gaps": [],
            "suggested_segments": [],
        }

    parts_list = []
    indexed_parts = []
    total_bytes = 0

    for f in all_mcap:
        size = f.stat().st_size
        total_bytes += size
        p_num = extract_part_number(f.name)
        if p_num is not None:
            indexed_parts.append((p_num, f))

        parts_list.append({
            "filename": f.name,
            "path": str(f.resolve()),
            "part_number": p_num,
            "size_bytes": size,
            "size_mb": round(size / (1024 * 1024), 2),
            "est_duration_min": 1.0,
        })

    # Kiểm tra gián đoạn (Gaps)
    gaps = []
    if indexed_parts:
        indexed_parts.sort(key=lambda x: x[0])
        for i in range(len(indexed_parts) - 1):
            curr_idx = indexed_parts[i][0]
            next_idx = indexed_parts[i + 1][0]
            if next_idx > curr_idx + 1:
                gaps.append({"start_missing": curr_idx + 1, "end_missing": next_idx - 1})

    # Tính toán gợi ý phân nhóm tự động (quy tắc <= 30 part / segment)
    suggested_segments = generate_suggested_segments(folder.name, indexed_parts)

    return {
        "folder": str(folder),
        "folder_name": folder.name,
        "parts": parts_list,
        "total_parts": len(parts_list),
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "gaps": gaps,
        "suggested_segments": suggested_segments,
    }


def generate_suggested_segments(folder_name: str, indexed_parts: List[Tuple[int, Path]]) -> List[Dict[str, Any]]:
    """Tự động phân bổ các part thành các nhóm <= 30 part, theo chuẩn tên ..._P1, ..._P2."""
    if not indexed_parts:
        return []

    min_part = indexed_parts[0][0]
    max_part = indexed_parts[-1][0]
    total_count = len(indexed_parts)

    # Nếu tổng số part <= 30: 1 nhóm duy nhất
    if total_count <= 30:
        return [{
            "name": f"{folder_name}_P1",
            "start_part": min_part,
            "end_part": max_part,
            "count": total_count,
            "warning": False,
        }]

    # Số nhóm tối thiểu cần thiết để mỗi nhóm <= 30
    num_groups = math.ceil(total_count / 30)
    # Phân chia đều giữa các nhóm
    base_size = total_count // num_groups
    remainder = total_count % num_groups

    segments = []
    curr_idx = 0
    for g_idx in range(1, num_groups + 1):
        group_size = base_size + (1 if g_idx <= remainder else 0)
        start_item = indexed_parts[curr_idx]
        end_item = indexed_parts[min(curr_idx + group_size - 1, total_count - 1)]

        seg_name = f"{folder_name}_P{g_idx}"
        segments.append({
            "name": seg_name,
            "start_part": start_item[0],
            "end_part": end_item[0],
            "count": group_size,
            "warning": group_size > 30,
        })
        curr_idx += group_size
        if curr_idx >= total_count:
            break

    return segments


def execute_split(dir_path: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Di chuyển (Move) các file part vào các thư mục con theo dải phân nhóm.
    segments: [{"name": "DIENTHOAI_P1", "start_part": 0, "end_part": 24}, ...]
    """
    folder = Path(dir_path).resolve()
    if not folder.exists() or not folder.is_dir():
        return {"success": False, "error": f"Thư mục nguồn không tồn tại: {dir_path}"}

    # Quét tất cả part hiện có
    all_mcap = [
        f for f in folder.glob("*.mcap")
        if not f.name.endswith("_merged.mcap") and not f.name.endswith(".tmp.mcap")
    ]
    part_map: Dict[int, Path] = {}
    for f in all_mcap:
        p_num = extract_part_number(f.name)
        if p_num is not None:
            part_map[p_num] = f

    created_subfolders = []
    total_moved = 0
    errors = []

    for seg in segments:
        seg_name = seg.get("name", "").strip()
        if not seg_name:
            continue
        start_p = int(seg.get("start_part", 0))
        end_p = int(seg.get("end_part", 0))

        subfolder = folder / seg_name
        subfolder.mkdir(parents=True, exist_ok=True)
        subfolder_moved = 0

        # Di chuyển các part nằm trong khoảng [start_p, end_p]
        for p_idx in range(start_p, end_p + 1):
            if p_idx in part_map:
                src_file = part_map[p_idx]
                dest_file = subfolder / src_file.name
                try:
                    shutil.move(str(src_file), str(dest_file))
                    subfolder_moved += 1
                    total_moved += 1
                except Exception as e:
                    errors.append(f"Không thể di chuyển {src_file.name} tới {subfolder.name}: {e}")

        created_subfolders.append({
            "name": seg_name,
            "path": str(subfolder.resolve()),
            "moved_parts": subfolder_moved,
            "start_part": start_p,
            "end_part": end_p,
        })

    return {
        "success": len(errors) == 0,
        "total_moved": total_moved,
        "created_subfolders": created_subfolders,
        "errors": errors,
    }
