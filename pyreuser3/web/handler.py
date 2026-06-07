"""本地 Web UI 的 HTTP 请求处理。

通过工厂函数 :func:`make_handler` 把服务配置、任务仓库和转换桥接器绑定到一个
``BaseHTTPRequestHandler`` 子类上，处理单页应用首页、任务查询 API、路径选择与
导出任务提交等请求。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

from .jobs import JobStore
from .page import INDEX_HTML
from .picker import pick_path
from .runners import ConversionRunners
from .settings import WebSettings


def make_handler(
    settings: WebSettings,
    jobs: JobStore,
    runners: ConversionRunners,
) -> type[BaseHTTPRequestHandler]:
    """创建绑定当前服务状态的请求处理类。

    参数：
        settings (WebSettings): 服务运行配置。
        jobs (JobStore): 后台任务仓库。
        runners (ConversionRunners): 把 Web 表单参数桥接到核心转换器的执行器。

    返回：
        type[BaseHTTPRequestHandler]: 一个已闭包捕获上述依赖的请求处理类，供
        ``ThreadingHTTPServer`` 实例化。
    """

    class WebHandler(BaseHTTPRequestHandler):
        """处理静态首页和本地 JSON API。"""

        def log_message(self, format: str, *args: Any) -> None:
            """输出简洁的请求日志。

            参数：
                format (str): 标准库格式字符串。
                *args (Any): 与 ``format`` 对应的参数。

            返回：
                None: 直接打印到标准输出。
            """
            print(f"{self.address_string()} - {format % args}")

        def do_GET(self) -> None:
            """处理首页、任务列表和任务详情的 GET 请求。

            返回：
                None: 通过写入响应体返回结果；未匹配路径返回 404。
            """
            path = urlparse(self.path).path
            if path == "/":
                # 首页是单页应用，所有前端资源都内嵌在模板里。
                self._send_html(INDEX_HTML)
                return
            if path == "/api/jobs":
                # 任务列表不包含完整日志，避免轮询时响应体过大。
                self._handle_jobs()
                return
            if path.startswith("/api/jobs/"):
                # 任务详情包含日志，用于右侧日志面板刷新。
                self._handle_job(path.rsplit("/", 1)[-1])
                return
            self._send_json(404, {"error": "request path not found"})

        def do_POST(self) -> None:
            """处理路径选择和导出任务提交的 POST 请求。

            返回：
                None: 通过写入响应体返回结果；请求异常时返回 400，未匹配返回 404。
            """
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/pick-path":
                    # 只有用户主动点击选择按钮时才打开本机文件/目录对话框。
                    self._send_json(200, pick_path(payload))
                    return
                if path == "/api/export":
                    # 只提交任务，实际转换由后台线程执行。
                    job = jobs.start("export", payload, runners.run_export)
                    self._send_json(202, {"jobId": job.id})
                    return
                self._send_json(404, {"error": "request path not found"})
            except Exception as exc:
                # 请求体解析失败或参数结构异常时直接返回 400。
                self._send_json(400, {"error": f"{exc.__class__.__name__}: {exc}"})

        def _read_json(self) -> dict[str, Any]:
            """读取并校验 JSON 请求体。

            返回：
                dict[str, Any]: 解析后的请求体对象；无请求体时返回空字典。

            异常：
                ValueError: 当请求体不是 JSON 对象时抛出。
            """
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _handle_jobs(self) -> None:
            """返回当前任务列表和 Web 根目录。

            返回：
                None: 以 JSON 响应输出任务列表（不含日志）和根目录。
            """
            payload = {
                "jobs": [
                    jobs.serialize(job, include_logs=False) for job in jobs.list_jobs()
                ],
                "rootDir": str(settings.root_dir),
            }
            self._send_json(200, payload)

        def _handle_job(self, job_id: str) -> None:
            """返回单个任务详情。

            参数：
                job_id (str): 任务唯一标识。

            返回：
                None: 以 JSON 响应输出含日志的任务详情；不存在时返回 404。
            """
            job = jobs.get(job_id)
            if job is None:
                self._send_json(404, {"error": "job not found"})
                return
            self._send_json(200, {"job": jobs.serialize(job, include_logs=True)})

        def _send_html(self, html: str) -> None:
            """发送 HTML 响应。

            参数：
                html (str): 要返回的 HTML 文本。

            返回：
                None: 写出状态行、响应头和正文。
            """
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            """发送 JSON 响应。

            参数：
                status (int): HTTP 状态码。
                payload (dict[str, Any]): 要序列化为 JSON 的响应体。

            返回：
                None: 写出状态行、响应头和正文。
            """
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return WebHandler
