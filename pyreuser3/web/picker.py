"""本地路径选择对话框。

借助标准库 tkinter，在本机弹出原生的文件/目录选择框，把用户选中的绝对路径
回传给前端表单。GUI 相关导入均延迟到调用时进行，避免无界面环境仅启动服务时
就尝试初始化 tkinter。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# 串行化选择框，避免多个浏览器请求同时弹出对话框造成混乱。
_PICKER_LOCK = threading.Lock()


def pick_path(payload: dict[str, Any]) -> dict[str, str]:
    """根据前端请求打开文件或目录选择对话框。

    参数：
        payload (dict[str, Any]): 前端参数，含 ``kind``（``file`` 或 ``directory``）、
            ``title``（对话框标题）和可选的 ``filetypes``（文件过滤器）。

    返回：
        dict[str, str]: 形如 ``{"path": "..."}``；用户取消选择时 ``path`` 为空字符串。

    异常：
        ValueError: 当 ``kind`` 既不是 ``file`` 也不是 ``directory`` 时抛出。
    """
    # tkinter 是 Python 标准库，适合在本地工具里弹出原生选择框。
    # 这里延迟导入，避免无界面环境仅启动服务时就尝试初始化 GUI。
    import tkinter as tk
    from tkinter import filedialog

    kind = str(payload.get("kind", "file")).strip().lower()
    title = str(payload.get("title", "Select a path")).strip() or "Select a path"
    filetypes = _normalize_filetypes(payload.get("filetypes"))

    with _PICKER_LOCK:
        # 多个浏览器请求同时打开文件框会非常混乱，因此用锁串行化。
        root = tk.Tk()
        root.withdraw()
        try:
            # 尽量把对话框放到最前面，避免用户以为网页没有响应。
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            if kind == "directory":
                selected = filedialog.askdirectory(
                    parent=root,
                    title=title,
                    mustexist=False,
                )
            elif kind == "file":
                selected = filedialog.askopenfilename(
                    parent=root,
                    title=title,
                    filetypes=filetypes,
                )
            else:
                raise ValueError("path picker kind must be file or directory")
        finally:
            # 无论是否选择成功，都销毁临时根窗口，释放 GUI 资源。
            root.destroy()

    # 用户取消选择时返回空字符串，前端保持原字段不变。
    return {"path": str(Path(selected)) if selected else ""}


def _normalize_filetypes(raw: Any) -> list[tuple[str, str]]:
    """把前端传来的文件过滤器整理成 tkinter 接受的格式。

    参数：
        raw (Any): 前端传入的过滤器，期望是 ``[[标签, 通配符], ...]`` 形状的列表。

    返回：
        list[tuple[str, str]]: ``(标签, 通配符)`` 元组列表；输入非法时退回 ``[("所有文件", "*.*")]``。
    """
    if not isinstance(raw, list):
        return [("All files", "*.*")]

    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        label = str(item[0]).strip()
        pattern = str(item[1]).strip()
        if label and pattern:
            out.append((label, pattern))
    return out or [("All files", "*.*")]
