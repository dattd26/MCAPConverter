import asyncio
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union


def pick_directory(title: str = "Chọn Thư Mục") -> Optional[str]:
    """Bật cửa sổ Windows Explorer chọn thư mục trực tiếp qua Tkinter."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.focus_force()
        folder = filedialog.askdirectory(title=title)
        root.destroy()
        if folder:
            return str(Path(folder).resolve())
        return None
    except Exception as e:
        print(f"Lỗi khi mở Folder Dialog: {e}")
        return None


def pick_file(title: str = "Chọn Tập Tin", filetypes: Optional[List[Tuple[str, str]]] = None) -> Optional[str]:
    """Bật cửa sổ Windows Explorer chọn file trực tiếp qua Tkinter."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        if filetypes is None:
            filetypes = [("Tất cả tập tin", "*.*")]

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.focus_force()
        file_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        root.destroy()
        if file_path:
            return str(Path(file_path).resolve())
        return None
    except Exception as e:
        print(f"Lỗi khi mở File Dialog: {e}")
        return None


def find_foxglove_bin() -> Optional[str]:
    """Dò tìm đường dẫn file thực thi Foxglove Studio trên Windows."""
    # 1. Thử qua PATH
    bin_path = shutil.which("foxglove") or shutil.which("foxglove-studio")
    if bin_path:
        return bin_path

    # 2. Các vị trí cài đặt phổ biến trên Windows
    search_paths = []
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    prog_files = os.environ.get("ProgramFiles", "")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "")

    if local_app_data:
        search_paths.append(Path(local_app_data) / "Programs" / "desktop" / "Foxglove.exe")
        search_paths.append(Path(local_app_data) / "Programs" / "foxglove-studio" / "Foxglove Studio.exe")
        search_paths.append(Path(local_app_data) / "Programs" / "Foxglove" / "Foxglove.exe")
        search_paths.append(Path(local_app_data) / "foxglove-studio" / "Foxglove Studio.exe")
    if prog_files:
        search_paths.append(Path(prog_files) / "Foxglove Studio" / "Foxglove Studio.exe")
        search_paths.append(Path(prog_files) / "Foxglove" / "Foxglove.exe")
    if prog_files_x86:
        search_paths.append(Path(prog_files_x86) / "Foxglove Studio" / "Foxglove Studio.exe")

    for p in search_paths:
        if p.exists():
            return str(p.resolve())

    # 3. Tìm nhanh trong LOCALAPPDATA
    if local_app_data:
        matches = glob.glob(os.path.join(local_app_data, "Programs", "**", "*foxglove*.exe"), recursive=True)
        if matches:
            return matches[0]

    return None


def launch_foxglove(target_paths: Union[str, List[str]]) -> bool:
    """Mở một hoặc nhiều file / thư mục trên Foxglove Studio."""
    if isinstance(target_paths, str):
        paths = [target_paths]
    else:
        paths = target_paths

    resolved_paths: List[Path] = []
    for p_str in paths:
        p = Path(p_str).resolve()
        if p.exists():
            resolved_paths.append(p)

    if not resolved_paths:
        return False

    foxglove_bin = find_foxglove_bin()
    try:
        if foxglove_bin:
            cmd = [foxglove_bin] + [str(p) for p in resolved_paths]
            subprocess.Popen(cmd)
            return True
        elif sys.platform == "win32":
            for p in resolved_paths:
                os.startfile(str(p))
            return True
        else:
            for p in resolved_paths:
                subprocess.Popen(["xdg-open", str(p)])
            return True
    except Exception as e:
        print(f"Lỗi khi mở Foxglove: {e}")
        return False


def open_in_explorer(target_path: str) -> bool:
    """Mở thư mục trong Windows Explorer."""
    p = Path(target_path).resolve()
    if not p.exists():
        return False

    try:
        if sys.platform == "win32":
            if p.is_file():
                subprocess.Popen(["explorer", f"/select,{str(p)}"])
            else:
                subprocess.Popen(["explorer", str(p)])
            return True
        else:
            subprocess.Popen(["xdg-open", str(p)])
            return True
    except Exception as e:
        print(f"Lỗi khi mở Explorer: {e}")
        return False
