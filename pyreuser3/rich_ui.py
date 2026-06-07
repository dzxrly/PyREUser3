"""基于 Rich 的批处理进度条和日志输出工具。

提供一个全局共享的 Rich 控制台，以及把进度条固定在底部、日志滚动输出到上方的
:class:`BatchProgress` 上下文管理器，供导出/封包批处理复用。
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

# 全局唯一的 Rich 控制台，确保进度条与日志共享同一渲染区域。
_CONSOLE = Console()


def get_console() -> Console:
    """返回命令行批处理共用的 Rich 控制台。

    返回：
        Console: 模块级单例 :class:`rich.console.Console` 实例。
    """
    return _CONSOLE


class BatchProgress:
    """让 Rich 进度条固定在底部，并把日志滚动输出到上方。

    作为上下文管理器使用：进入时启动进度条并创建任务，退出时关闭进度条。
    期间可通过 :meth:`log` 输出滚动日志、:meth:`update` 推进进度。
    """

    def __init__(self, description: str, total: int, unit: str = "file") -> None:
        """初始化批处理进度条配置。

        参数：
            description (str): 进度条左侧显示的任务描述。
            total (int): 任务总量，用于计算完成度和预计剩余时间。
            unit (str): 计量单位文本（如 ``"file"``），仅用于展示。

        返回：
            None: 构造函数，仅准备 Rich 进度条对象（尚未启动）。
        """
        self.description = description
        self.total = total
        self.unit = unit
        self.console = get_console()
        # 预先组装进度条的各列：转轮、描述、进度条、计数、已用时和预计剩余时间。
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn(unit),
            TextColumn("elapsed"),
            TimeElapsedColumn(),
            TextColumn("eta"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
            transient=False,
        )
        self._task_id: TaskID | None = None

    def __enter__(self) -> "BatchProgress":
        """进入上下文：启动进度条并创建任务。

        返回：
            BatchProgress: 自身，便于 ``with ... as progress`` 语法使用。
        """
        self._progress.__enter__()
        self._task_id = self._progress.add_task(self.description, total=self.total)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """退出上下文：关闭进度条。

        参数：
            exc_type (Any): 异常类型（无异常时为 ``None``）。
            exc (Any): 异常实例（无异常时为 ``None``）。
            tb (Any): 异常回溯对象（无异常时为 ``None``）。

        返回：
            bool: 始终返回 ``False``，表示不吞掉上下文内发生的异常。
        """
        self._progress.__exit__(exc_type, exc, tb)
        return False

    def log(self, message: str, style: str | None = None) -> None:
        """在实时进度条上方输出一行日志。

        参数：
            message (str): 日志文本。
            style (str | None): 可选的 Rich 样式名（如 ``"green"`` / ``"red"``）。

        返回：
            None: 直接输出到共享控制台。
        """
        self.console.log(message, style=style)

    def update(self, advance: int = 1, description: str | None = None) -> None:
        """推进当前任务，并可同时更新底部进度条标签。

        参数：
            advance (int): 本次推进的进度量；传 0 可只更新描述不推进进度。
            description (str | None): 可选的新任务描述；为 ``None`` 时保持不变。

        返回：
            None: 更新内部进度状态；尚未创建任务时直接返回。
        """
        if self._task_id is None:
            return
        kwargs: dict[str, Any] = {"advance": advance}
        if description is not None:
            kwargs["description"] = description
        self._progress.update(self._task_id, **kwargs)
