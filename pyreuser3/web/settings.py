"""本地 Web UI 的运行配置。

集中保存 HTTP 服务和转换任务共享的少量配置项，使用 frozen dataclass 避免运行
过程中被意外修改。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebSettings:
    """HTTP 服务和转换任务共享的配置。

    属性：
        host (str): 监听主机地址，默认仅本机回环 ``127.0.0.1``。
        port (int): 监听端口，默认 ``8765``。
        root_dir (Path): 服务根目录（兼容用途），默认当前工作目录。
        max_jobs (int): 内存中保留的最大任务数量，默认 ``50``。
    """

    host: str = "127.0.0.1"
    port: int = 8765
    root_dir: Path = Path.cwd()
    max_jobs: int = 50

    def with_resolved_root(self) -> "WebSettings":
        """返回根目录已解析为绝对路径的新配置对象。

        返回：
            WebSettings: 一个 ``root_dir`` 展开用户目录并解析为绝对路径的新实例，
            其余字段保持不变。
        """
        # dataclass 设置为 frozen，使用新对象可以避免运行中误改配置。
        return WebSettings(
            host=self.host,
            port=self.port,
            root_dir=self.root_dir.expanduser().resolve(),
            max_jobs=self.max_jobs,
        )
