"""Web 表单任务到核心转换器的桥接逻辑。

负责把浏览器提交的字符串参数解析、校验并转换成 :class:`User3Exporter` 的构造
参数，再调用其批量导出。所有路径都要求用户通过选择按钮提供绝对路径，避免在
不同工作目录下产生歧义。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..core import RSZ_MAGIC, USR_MAGIC

# 日志回调函数签名：接收一行文本并写回任务日志。
LogFn = Callable[[str], None]


class ConversionRunners:
    """把浏览器提交的参数转换为 `User3Exporter` 调用。"""

    def __init__(self, root_dir: str | Path) -> None:
        """保存 Web 服务配置中的根目录。

        参数：
            root_dir (str | Path): 服务根目录（兼容用途），会被展开并解析为绝对路径。

        返回：
            None: 构造函数，仅初始化实例属性。
        """
        # 这里保留 root_dir 仅用于服务配置兼容。实际 Web 表单路径要求
        # 用户通过选择按钮提供绝对路径，不再自动拼接项目根目录。
        self.root_dir = Path(root_dir).expanduser().resolve()

    def run_export(self, payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
        """执行 Web 导出任务，只处理 `.user.3` 文件。

        参数：
            payload (dict[str, Any]): 浏览器提交的导出表单参数。
            log (LogFn): 日志回调，用于把阶段信息写回任务。

        返回：
            dict[str, Any]: 含 ``user3``（导出统计）和 ``outputDir``（输出目录）的结果字典。

        异常：
            ValueError: 当必填参数缺失或路径不是绝对路径时抛出。
            FileNotFoundError: 当输入路径、模板或 dump 文件不存在时抛出。
        """
        # 先做参数解析和路径校验，保证常见输入错误能尽早以清晰文本返回。
        input_dir = self._path_value(payload, "inputDir", "输入目录")
        schema_path = self._path_value(payload, "schemaPath", "RE_RSZ 模板")
        output_dir = self._path_value(payload, "outputDir", "JSON 输出目录")
        il2cpp_dump_path = self._path_value(
            payload,
            "il2cppDumpPath",
            "il2cpp_dump.json",
        )
        exclude_regexes = self._exclude_regexes(payload)
        tree_depth = self._tree_depth(payload)
        user_magic = self._magic(payload, "userMagic", USR_MAGIC)
        rsz_magic = self._magic(payload, "rszMagic", RSZ_MAGIC)

        # 输入文件或目录必须已存在；输出目录由底层导出器按需创建。
        self._ensure_existing_path(input_dir, "输入目录或文件")
        self._ensure_existing_file(schema_path, "RE_RSZ 模板")
        self._ensure_existing_file(il2cpp_dump_path, "il2cpp_dump.json")

        log(f"输入：{input_dir}")
        log(f"模板：{schema_path}")
        log(f"输出：{output_dir}")
        if exclude_regexes:
            log(f"排除规则：{len(exclude_regexes)} 条")

        # 延迟导入核心导出器，避免仅启动 Web 服务或查看 --help 时加载 Rich。
        from ..export import User3Exporter

        log("开始导出 .user.3 文件。")
        exporter = User3Exporter(
            user3_root=input_dir,
            schema_dir=schema_path,
            output_root=output_dir,
            tree_depth=tree_depth,
            exclude_regexes=exclude_regexes,
            il2cpp_dump_path=il2cpp_dump_path,
            user_magic=user_magic,
            rsz_magic=rsz_magic,
        )
        user3_result = exporter.run()
        log(f".user.3 导出完成：{json.dumps(user3_result, ensure_ascii=False)}")

        # 结果结构保持简单，前端会自动汇总其中的 total/success/failed。
        return {"user3": user3_result, "outputDir": str(output_dir)}

    def _path_value(self, payload: dict[str, Any], key: str, label: str) -> Path:
        """读取必填路径，并要求路径来自用户选择的绝对路径。

        参数：
            payload (dict[str, Any]): 表单参数。
            key (str): 参数键名。
            label (str): 用于错误信息的人类可读名称。

        返回：
            Path: 展开用户目录后的绝对路径。

        异常：
            ValueError: 当参数缺失，或路径不是绝对路径时抛出。
        """
        path = Path(self._text_value(payload, key, label)).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{label}必须通过选择按钮提供绝对路径")
        return path

    @staticmethod
    def _text_value(payload: dict[str, Any], key: str, label: str) -> str:
        """读取必填文本参数，并去掉常见的外层双引号。

        参数：
            payload (dict[str, Any]): 表单参数。
            key (str): 参数键名。
            label (str): 用于错误信息的人类可读名称。

        返回：
            str: 去除空白与外层引号后的非空文本。

        异常：
            ValueError: 当参数缺失或为空时抛出。
        """
        value = payload.get(key)
        if value is None:
            raise ValueError(f"缺少参数：{label}")
        text = str(value).strip().strip('"')
        if not text:
            raise ValueError(f"缺少参数：{label}")
        return text

    @staticmethod
    def _optional_text(payload: dict[str, Any], key: str) -> str:
        """读取可选文本参数，缺失或空值时返回空字符串。

        参数：
            payload (dict[str, Any]): 表单参数。
            key (str): 参数键名。

        返回：
            str: 去除空白与外层引号后的文本；缺失时返回空字符串。
        """
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip().strip('"')

    @staticmethod
    def _ensure_existing_path(path: Path, label: str) -> None:
        """校验输入路径存在，可以是文件也可以是目录。

        参数：
            path (Path): 待校验的路径。
            label (str): 用于错误信息的人类可读名称。

        返回：
            None: 仅做校验；不存在时抛出异常。

        异常：
            FileNotFoundError: 当路径不存在时抛出。
        """
        if not path.exists():
            raise FileNotFoundError(f"{label}不存在：{path}")

    @staticmethod
    def _ensure_existing_file(path: Path, label: str) -> None:
        """校验输入路径存在且必须是文件。

        参数：
            path (Path): 待校验的路径。
            label (str): 用于错误信息的人类可读名称。

        返回：
            None: 仅做校验；不是文件时抛出异常。

        异常：
            FileNotFoundError: 当路径不存在或不是文件时抛出。
        """
        if not path.is_file():
            raise FileNotFoundError(f"{label}不存在或不是文件：{path}")

    @staticmethod
    def _exclude_regexes(payload: dict[str, Any]) -> list[str]:
        """解析排除正则，支持文本域逐行填写或 JSON 数组。

        参数：
            payload (dict[str, Any]): 表单参数，``excludeRegexes`` 可为列表或多行文本。

        返回：
            list[str]: 去除空白、过滤空行后的正则字符串列表。
        """
        raw = payload.get("excludeRegexes", "")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [line.strip() for line in str(raw).splitlines() if line.strip()]

    @staticmethod
    def _tree_depth(payload: dict[str, Any]) -> int | str:
        """解析导出树深度，支持 `auto`、十进制和 `0x` 十六进制整数。

        参数：
            payload (dict[str, Any]): 表单参数，``treeDepth`` 为文本。

        返回：
            int | str: 非负整数，或字符串 ``"auto"``。

        异常：
            ValueError: 当解析出的整数为负时抛出。
        """
        raw = ConversionRunners._optional_text(payload, "treeDepth")
        if not raw or raw.lower() == "auto":
            return "auto"
        value = int(raw, 0)
        if value < 0:
            raise ValueError("tree-depth 必须为非负整数或 auto")
        return value

    @staticmethod
    def _magic(payload: dict[str, Any], key: str, default: int) -> int:
        """解析 magic 参数，未填写时使用核心库默认值。

        参数：
            payload (dict[str, Any]): 表单参数。
            key (str): 参数键名（如 ``"userMagic"``）。
            default (int): 未填写时使用的默认 magic。

        返回：
            int: 解析出的 magic 整数（支持 ``0x`` 前缀）。
        """
        raw = ConversionRunners._optional_text(payload, key)
        if not raw:
            return default
        return int(raw, 0)
