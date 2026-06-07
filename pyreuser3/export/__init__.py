"""导出功能子包。

这个子包负责把 RE Engine 的 `.user.3` 二进制数据库解析成 JSON。
外部调用通常不需要关心内部拆分，直接从 `pyreuser3` 导入
`User3Exporter` 即可；保留这个子包入口是为了方便后续继续扩展
解析链路。
"""

from .base import User3Exporter

__all__ = ["User3Exporter"]
