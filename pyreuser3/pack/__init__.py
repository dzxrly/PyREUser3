"""封包功能子包。

这个子包负责把项目导出的 JSON 数据重新写回 `.user.3` 二进制格式。
内部会先规划实例表、字符串表和资源引用，再按 RE_RSZ 模板写入字段。
"""

from .base import User3Packer
from .models import PackError

__all__ = ["PackError", "User3Packer"]
