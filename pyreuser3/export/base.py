"""`.user.3` 到 JSON 的导出器入口。

`User3Exporter` 通过多个 Mixin 组合出完整的解析链路：读取 USR/RSZ 结构、
解析字段、构建对象引用树、应用枚举元数据并做后处理。本文件只负责装配
这些能力、管理批处理流程，以及处理文件发现与输出路径计算。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .enums import ExporterEnumSourceMixin
from .fields import ExporterFieldParserMixin
from .metadata import ExporterMetadataMixin
from .postprocess import ExporterPostprocessMixin
from .tree import ExporterTreeMixin
from .user3 import ExporterUser3ParserMixin
from ..core import RSZ_MAGIC, USR_MAGIC, resolve_schema_path
from ..rich_ui import BatchProgress
from ..schema import TypeDB


class User3Exporter(
    ExporterEnumSourceMixin,
    ExporterMetadataMixin,
    ExporterPostprocessMixin,
    ExporterTreeMixin,
    ExporterFieldParserMixin,
    ExporterUser3ParserMixin,
):
    """把 RE Engine `.user.3` 二进制文件导出为紧凑 JSON。

    通过组合枚举源、元数据、后处理、对象树、字段解析和 USR/RSZ 解析等
    Mixin，提供从单文件解析到批量导出的完整能力。
    """

    def __init__(
        self,
        user3_root: str | Path,
        schema_dir: str | Path,
        output_root: str | Path,
        tree_depth: int | str = "auto",
        exclude_regexes: list[str] | None = None,
        il2cpp_dump_path: str | Path = "",
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
    ):
        """初始化导出器配置和运行期索引。

        参数：
            user3_root (str | Path): 输入根目录或单个 ``.user.3`` 文件。
            schema_dir (str | Path): 显式传入的 RE_RSZ 模板 JSON 文件路径。
            output_root (str | Path): JSON 输出根目录。
            tree_depth (int | str): 对象引用树展开深度，支持非负整数或 ``"auto"``。
            exclude_regexes (list[str] | None): 用于排除相对路径的正则表达式列表。
            il2cpp_dump_path (str | Path): 必填的 ``il2cpp_dump.json`` 文件路径。
            user_magic (int): 期望读取到的 USR 文件 magic。
            rsz_magic (int): 期望读取到的 RSZ 块 magic。

        返回：
            None: 构造函数，仅初始化实例属性。

        异常：
            FileNotFoundError: 当 ``il2cpp_dump.json`` 不存在时抛出。
        """
        # 路径在入口处统一转为 Path，后续模块只处理 Path 对象。
        self.user3_root = Path(user3_root)
        self.schema_dir = Path(schema_dir)
        self.output_root = Path(output_root)
        self.il2cpp_dump_path = Path(il2cpp_dump_path)
        if not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        self.tree_depth = self._normalize_tree_depth(tree_depth)
        self.user_magic = int(user_magic)
        self.rsz_magic = int(rsz_magic)
        self.exclude_regexes = exclude_regexes or []
        self._exclude_patterns = [re.compile(p) for p in self.exclude_regexes]
        self.schema_path = self._resolve_schema_path(self.schema_dir)
        self.typedb = TypeDB.load(self.schema_path)
        # 下面这些索引在导出前由 il2cpp_dump.json 构建，用于把固定枚举值
        # 转成 `[数值] 成员名`，并在泛型容器中推断字段对应的枚举类型。
        self.enum_lookup: dict[str, dict[int, tuple[str, int]]] = {}
        self.class_field_fixed_types: dict[str, dict[str, str]] = {}
        self.serializable_to_fixed: dict[str, str] = {}
        self.generic_container_rules: dict[str, tuple[str, str]] = {}
        self.param_type_default_enum: dict[str, str] = {}
        self.enum_member_to_types: dict[str, list[str]] = {}

    def run(self) -> dict[str, int]:
        """执行批量导出流程。

        发现输入文件、构建枚举索引，然后逐个导出并通过 Rich 进度条反馈进度。

        返回：
            dict[str, int]: 统计字典，含 ``total``、``success``、``failed`` 三个计数。
        """
        files = self._discover_user3_files()
        self.output_root.mkdir(parents=True, exist_ok=True)
        # 每次导出都根据显式传入的 il2cpp_dump.json 重新生成枚举表，
        # 不复用旧目录中的 Enums_Internal.json，避免跨游戏或跨版本污染。
        enums_internal = self._ensure_internal_metadata_files()
        self.enum_lookup = self._build_enum_lookup_from_enums_internal(enums_internal)
        self._load_enum_context_from_il2cpp_dump()
        self._ensure_enum_lookup()

        success = 0
        failed = 0
        # 单文件失败只计入失败数量，不中断整批导出；这样大批量资源更容易排查。
        with BatchProgress(
            "Exporting user3", total=len(files), unit="file"
        ) as progress:
            progress.log(f"发现 {len(files)} 个 .user.3 文件。")
            progress.log(f"使用模板: {self.schema_path}")
            progress.log(f"输出目录: {self.output_root}")
            for user3_file in files:
                label = user3_file.name.replace(".user.3", "")
                progress.update(advance=0, description=label)
                progress.log(f"开始导出 user3: {user3_file}")
                ok, output_path, error = self._export_one_file(user3_file)
                if ok:
                    success += 1
                    progress.log(f"user3 导出完成: {output_path}", style="green")
                else:
                    failed += 1
                    progress.log(f"user3 导出失败: {user3_file} ({error})", style="red")
                progress.update(1)

        return {"total": len(files), "success": success, "failed": failed}

    def _export_one_file(
        self, user3_file: Path
    ) -> tuple[bool, Path | None, str | None]:
        """导出单个 `.user.3` 文件。

        参数：
            user3_file (Path): 源 ``.user.3`` 文件路径。

        返回：
            tuple[bool, Path | None, str | None]: 三元组 ``(是否成功, 输出路径, 错误信息)``；
            成功时输出路径有效、错误信息为 ``None``，失败时反之。
        """
        try:
            # 解析出的原始树先经过枚举后处理，再移除内部索引和值包装，
            # 最后对展示用浮点数做轻微圆整，生成更适合人工编辑的 JSON。
            tree = self._parse_user3(user3_file)
            tree = self._postprocess_enum_nodes(tree)
            tree = self._finalize_export_tree(tree)
            tree = self._round_export_floats(tree)
            output_path = self._output_path_for(user3_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2)
            return True, output_path, None
        except Exception as exc:
            # 把异常转成简短文本返回给批处理统计，不向上抛出以免中断整批。
            return False, None, f"{exc.__class__.__name__}: {exc}"

    def _resolve_schema_path(self, schema_dir: Path) -> Path:
        """校验并返回模板文件路径。

        参数：
            schema_dir (Path): 历史参数名，实际必须是具体模板 JSON 文件。

        返回：
            Path: 校验后的模板文件路径。
        """
        return resolve_schema_path(schema_dir)

    def _normalize_tree_depth(self, tree_depth: int | str) -> int | str:
        """规范化对象树展开深度。

        参数：
            tree_depth (int | str): 用户传入的深度设置，整数或字符串 ``"auto"``。

        返回：
            int | str: 非负整数或字符串 ``"auto"``。

        异常：
            ValueError: 字符串非 ``"auto"`` 或整数为负时抛出。
            TypeError: 类型既不是 ``int`` 也不是 ``str`` 时抛出。
        """
        if isinstance(tree_depth, str):
            value = tree_depth.strip().lower()
            if value != "auto":
                raise ValueError("tree_depth must be a non-negative integer or 'auto'")
            return "auto"
        if isinstance(tree_depth, int):
            if tree_depth < 0:
                raise ValueError("tree_depth must be >= 0")
            return tree_depth
        raise TypeError("tree_depth must be int or str")

    def _discover_user3_files(self) -> list[Path]:
        """发现输入 `.user.3` 文件并应用排除规则。

        返回：
            list[Path]: 过滤后的 ``.user.3`` 文件路径列表。

        异常：
            FileNotFoundError: 路径不存在、目录下无文件，或全部被排除时抛出。
        """
        if self.user3_root.is_file():
            files = [self.user3_root]
        else:
            if not self.user3_root.is_dir():
                raise FileNotFoundError(f"user3 root not found: {self.user3_root}")
            files = sorted(self.user3_root.rglob("*.user.3"))
            if not files:
                raise FileNotFoundError(f"no *.user.3 found under: {self.user3_root}")
        if not self._exclude_patterns:
            return files

        kept: list[Path] = []
        for file_path in files:
            # 目录模式下按相对路径匹配排除正则，便于排除整类子目录。
            if self.user3_root.is_file():
                rel_path = file_path.name
            else:
                rel_path = file_path.relative_to(self.user3_root).as_posix()
            if any(pattern.search(rel_path) for pattern in self._exclude_patterns):
                continue
            kept.append(file_path)
        if not kept:
            raise FileNotFoundError("all *.user.3 files were excluded by regex filters")
        return kept

    def _output_path_for(self, user3_file: Path) -> Path:
        """计算单个源文件对应的 JSON 输出路径。

        参数：
            user3_file (Path): 源 ``.user.3`` 文件。

        返回：
            Path: 输出 JSON 文件路径（目录模式下会还原相对子目录结构）。
        """
        if self.user3_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = user3_file.relative_to(self.user3_root).parent
        output_name = f"{user3_file.name}.json"
        return self.output_root / relative_parent / output_name
