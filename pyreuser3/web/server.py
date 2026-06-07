"""本地 Vue Web UI 的服务启动入口。

负责解析命令行参数、装配任务仓库与转换桥接器、构造请求处理类，并启动一个
多线程 HTTP 服务阻塞运行，直到用户按 Ctrl+C 中断。
"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Sequence

from .handler import make_handler
from .jobs import JobStore
from .runners import ConversionRunners
from .settings import WebSettings


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """允许复用刚释放端口的多线程 HTTP 服务。

    通过设置 ``allow_reuse_address``，避免重启服务时因端口处于 TIME_WAIT 而报
    “地址已被占用”。
    """

    allow_reuse_address = True


def run_server(settings: WebSettings) -> None:
    """按给定配置启动本地 Web 服务，并阻塞直到用户中断。

    参数：
        settings (WebSettings): 服务运行配置（主机、端口、根目录、任务上限）。

    返回：
        None: 阻塞运行；收到 ``KeyboardInterrupt`` 后清理并返回。
    """
    # 统一在服务启动前解析配置路径；网页表单仍要求用户选择绝对路径。
    settings = settings.with_resolved_root()

    # 三个对象分别负责状态、业务和路由；这样 HTTP 层不会掺入转换细节。
    jobs = JobStore(max_jobs=settings.max_jobs)
    runners = ConversionRunners(settings.root_dir)
    handler = make_handler(settings, jobs, runners)

    server = ReusableThreadingHTTPServer((settings.host, settings.port), handler)
    url = f"http://{settings.host}:{settings.port}/"
    print(f"RE User3 JSON Web 正在运行：{url}")
    print("网页路径不会自动使用项目根目录，请在页面中手动选择。")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        # 无论正常退出还是异常中断，都关闭服务释放端口。
        server.server_close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析 Web 服务命令行参数。

    参数：
        argv (Sequence[str] | None): 命令行参数序列；为 ``None`` 时使用 ``sys.argv``。

    返回：
        argparse.Namespace: 含 ``host``、``port``、``root_dir``、``max_jobs`` 的解析结果。
    """
    parser = argparse.ArgumentParser(description="启动本地 Vue Web UI。")
    parser.add_argument("--host", default="127.0.0.1", help="监听主机。")
    parser.add_argument("--port", type=int, default=8765, help="监听端口。")
    parser.add_argument(
        "--root-dir",
        default=str(Path.cwd()),
        help="兼容配置；网页路径仍需通过选择按钮提供绝对路径。",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=50,
        help="内存中保留的最大任务数量。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """供 `pyreuser3-web` 和 `python -m pyreuser3.web` 调用的入口。

    参数：
        argv (Sequence[str] | None): 命令行参数序列；为 ``None`` 时使用 ``sys.argv``。

    返回：
        None: 解析参数后调用 :func:`run_server` 阻塞运行。
    """
    args = parse_args(argv)
    run_server(
        WebSettings(
            host=args.host,
            port=args.port,
            root_dir=Path(args.root_dir),
            max_jobs=args.max_jobs,
        )
    )
