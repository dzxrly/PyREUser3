"""对外使用的高层 API。

`REUser3Converter` 是推荐给其他项目调用的门面类。它把底层的
`User3Exporter` 和 `User3Packer` 包装成更稳定的工作流：
解析、导出、封包，以及“解析后交给 callback 修改再自动封包”。
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from .core import RSZ_MAGIC, USR_MAGIC
from .export import User3Exporter
from .pack import User3Packer

# 导出/封包过程中流转的 JSON 树，结构随文件而异，故用 Any 表示。
JsonTree = Any
# 用户提供的修补回调：接收 (data) 或 (data, source_path)，可返回新树或就地修改后返回 None。
PatchCallback = Callable[..., Optional[JsonTree]]


class REUser3Converter:
    """RE Engine `.user.3` 与 JSON 互转的可复用门面类。

    封装解析、导出、封包以及“解析→回调修改→封包”的完整工作流，并统一处理
    模板路径、il2cpp dump、magic 等配置，让外部调用方无需直接接触底层
    导出器/封包器。
    """

    def __init__(
        self,
        schema_path: str | Path | None = None,
        il2cpp_dump_path: str | Path | None = None,
        tree_depth: int | str = "auto",
        schema_dir: str | Path | None = None,
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
    ) -> None:
        """初始化转换器。

        参数：
            schema_path (str | Path | None): 必填，RE_RSZ 模板 JSON 文件路径。
            il2cpp_dump_path (str | Path | None): ``il2cpp_dump.json`` 路径；解析和导出时必填，
                封包时可选但建议传入，用于枚举名反查。
            tree_depth (int | str): 对象引用树展开深度，支持非负整数或 ``"auto"``。
            schema_dir (str | Path | None): 旧参数名兼容入口，实际含义仍是模板 JSON 文件。
            user_magic (int): ``.user.3`` 文件头 magic，默认沿用当前项目值。
            rsz_magic (int): RSZ 数据块 magic，默认沿用当前项目值。

        返回：
            None: 构造函数，仅初始化实例属性。

        异常：
            TypeError: 当 ``schema_path`` 和 ``schema_dir`` 都缺失时抛出。
        """
        # 兼容旧调用方的 `schema_dir=` 写法，但内部统一使用 schema_path。
        if schema_path is None:
            schema_path = schema_dir
        if schema_path is None:
            raise TypeError("schema_path is required")
        self.schema_path = Path(schema_path)
        self.il2cpp_dump_path = Path(il2cpp_dump_path) if il2cpp_dump_path else None
        self.tree_depth = tree_depth
        self.user_magic = int(user_magic)
        self.rsz_magic = int(rsz_magic)

    def export_directory(
        self,
        user3_root: str | Path,
        output_root: str | Path,
        exclude_regexes: list[str] | None = None,
    ) -> dict[str, int]:
        """批量导出目录或单文件下的 `.user.3`。

        参数：
            user3_root (str | Path): ``.user.3`` 根目录或单个 ``.user.3`` 文件。
            output_root (str | Path): JSON 输出根目录。
            exclude_regexes (list[str] | None): 用于排除相对路径的正则表达式列表。

        返回：
            dict[str, int]: 统计字典，含 ``total``、``success``、``failed`` 三个计数。
        """
        exporter = self._new_exporter(user3_root, output_root, exclude_regexes)
        return exporter.run()

    def export_file(
        self,
        user3_path: str | Path,
        json_path: str | Path,
    ) -> Path:
        """导出单个 `.user.3` 文件到指定 JSON 路径。

        参数：
            user3_path (str | Path): 源 ``.user.3`` 文件。
            json_path (str | Path): 目标 JSON 文件。

        返回：
            Path: 实际写入的 JSON 文件路径。
        """
        # 单文件导出复用 parse_file，确保 API 直接解析和批量导出的
        # JSON 形状一致，减少后续封包时的分支差异。
        tree = self.parse_file(user3_path, round_floats=True)
        target = Path(json_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with target.open("w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        return target

    def parse_file(self, user3_path: str | Path, round_floats: bool = True) -> JsonTree:
        """把单个 `.user.3` 解析成导出器使用的紧凑 JSON 树。

        参数：
            user3_path (str | Path): 源 ``.user.3`` 文件。
            round_floats (bool): 是否把浮点数四舍五入到 4 位，方便人工阅读。

        返回：
            JsonTree: 可直接修改或传给 :meth:`pack` 的紧凑 JSON 树。
        """
        exporter = self._new_exporter(user3_path, Path.cwd(), [])
        # 单文件解析不写 Enums_Internal.json，但仍需要从 il2cpp_dump.json
        # 构建枚举表和枚举上下文，否则固定枚举值无法转换成可读标签。
        self._prepare_exporter_metadata(exporter)
        tree = exporter._parse_user3(Path(user3_path))
        tree = exporter._postprocess_enum_nodes(tree)
        tree = exporter._finalize_export_tree(tree)
        if round_floats:
            return exporter._round_export_floats(tree)
        return tree

    def parse_pack_file(self, user3_path: str | Path) -> JsonTree:
        """把单个 `.user.3` 解析成适合修改后稳定封包的实例表 JSON。

        普通导出和 :meth:`parse_file` 仍然返回 readable JSON；只有需要封回
        ``.user.3`` 的流程才应使用这个完整实例表结构。

        参数：
            user3_path (str | Path): 源 ``.user.3`` 文件。

        返回：
            JsonTree: 含完整实例表（``_instances`` 等键）的封包格式 JSON。
        """
        exporter = self._new_exporter(user3_path, Path.cwd(), [])
        self._prepare_exporter_metadata(exporter)
        return exporter._parse_user3_pack(Path(user3_path))

    def pack_directory(
        self,
        json_root: str | Path,
        output_root: str | Path,
        exclude_regexes: list[str] | None = None,
    ) -> dict[str, int]:
        """批量将 JSON 文件封回 `.user.3`。

        参数：
            json_root (str | Path): JSON 文件或 JSON 根目录。
            output_root (str | Path): ``.user.3`` 输出根目录。
            exclude_regexes (list[str] | None): 用于排除 JSON 相对路径的正则表达式列表。

        返回：
            dict[str, int]: 统计字典，含 ``total``、``success``、``failed`` 三个计数。
        """
        packer = self._new_packer(output_root)
        return packer.pack_directory(json_root, output_root, exclude_regexes)

    def pack_file(self, json_path: str | Path, user3_path: str | Path) -> Path:
        """把单个 JSON 文件封包到指定 `.user.3` 路径。

        参数：
            json_path (str | Path): 源 JSON 文件。
            user3_path (str | Path): 输出 ``.user.3`` 文件路径。

        返回：
            Path: 实际写入的 ``.user.3`` 文件路径。
        """
        packer = self._new_packer(Path(user3_path).parent)
        return packer.pack_json_file(json_path, user3_path)

    def pack(self, data: Any) -> bytes:
        """把内存中的 JSON 树直接编码为 `.user.3` 二进制。

        参数：
            data (Any): readable JSON 对象/数组，或 :meth:`parse_pack_file` 返回的实例表 JSON。

        返回：
            bytes: 可直接写入文件的 ``.user.3`` 字节串。
        """
        return self._new_packer(None).pack(data)

    def patch_file(
        self,
        user3_path: str | Path,
        output_path: str | Path,
        callback: PatchCallback,
    ) -> Path:
        """解析、交给 callback 修改、封包并写出单个 `.user.3`。

        callback 可以接收 ``(data)`` 或 ``(data, source_path)``。这里的 ``data``
        是完整实例表 JSON。callback 既可以返回一个新的 JSON 树，也可以
        原地修改 ``data`` 后返回 ``None``。

        参数：
            user3_path (str | Path): 源 ``.user.3`` 文件。
            output_path (str | Path): 修改后 ``.user.3`` 的写入路径。
            callback (PatchCallback): 用户提供的 JSON 修改函数。

        返回：
            Path: 实际写入的 ``.user.3`` 文件路径。
        """
        source = Path(user3_path)
        # 修改并封回时使用完整实例表格式，避免 readable 树里的旧引用编号
        # 在重建实例表时变成悬空引用。
        data = self.parse_pack_file(source)
        modified = self._run_callback(callback, data, source)
        if modified is None:
            modified = data
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.pack(modified))
        return target

    def patch_directory(
        self,
        user3_root: str | Path,
        output_root: str | Path,
        callback: PatchCallback,
        include_regexes: list[str] | None = None,
        exclude_regexes: list[str] | None = None,
    ) -> dict[str, int]:
        """批量查找匹配的 `.user.3`，用 callback 修改后自动封包。

        ``include_regexes`` 和 ``exclude_regexes`` 都匹配相对 ``user3_root`` 的
        路径，并统一使用 ``/`` 作为路径分隔符，避免 Windows 与类 Unix
        路径差异影响正则。

        参数：
            user3_root (str | Path): ``.user.3`` 根目录或单个文件。
            output_root (str | Path): 修改后文件的输出根目录。
            callback (PatchCallback): 用户提供的 JSON 修改函数。
            include_regexes (list[str] | None): 只处理匹配这些正则的相对路径。
            exclude_regexes (list[str] | None): 跳过匹配这些正则的相对路径。

        返回：
            dict[str, int]: 统计字典，含 ``total``、``success``、``failed``、``skipped`` 四个计数。
        """
        source_root = Path(user3_root)
        target_root = Path(output_root)
        files = self._discover_user3_files(source_root)
        include_patterns = [re.compile(p) for p in (include_regexes or [])]
        exclude_patterns = [re.compile(p) for p in (exclude_regexes or [])]

        total = success = failed = skipped = 0
        for file_path in files:
            # 单文件模式使用文件名；目录模式使用相对路径，以便输出时还原目录。
            rel = (
                file_path.name
                if source_root.is_file()
                else file_path.relative_to(source_root).as_posix()
            )
            if include_patterns and not any(
                pattern.search(rel) for pattern in include_patterns
            ):
                skipped += 1
                continue
            if any(pattern.search(rel) for pattern in exclude_patterns):
                skipped += 1
                continue

            total += 1
            output_path = target_root / (
                file_path.name
                if source_root.is_file()
                else file_path.relative_to(source_root)
            )
            try:
                # 每个文件独立处理，单个文件失败不会影响整个目录批处理。
                self.patch_file(file_path, output_path, callback)
                success += 1
            except Exception:
                failed += 1
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
        }

    def _new_exporter(
        self,
        user3_root: str | Path,
        output_root: str | Path,
        exclude_regexes: list[str] | None,
    ) -> User3Exporter:
        """按当前配置创建导出器实例。

        参数：
            user3_root (str | Path): ``.user.3`` 输入根目录或单个文件。
            output_root (str | Path): JSON 输出根目录。
            exclude_regexes (list[str] | None): 排除相对路径的正则表达式列表。

        返回：
            User3Exporter: 已用当前模板、dump、magic 等配置初始化的导出器。

        异常：
            FileNotFoundError: 当导出所需的 ``il2cpp_dump_path`` 未配置时抛出。
        """
        if self.il2cpp_dump_path is None:
            raise FileNotFoundError("il2cpp_dump_path is required for exporting JSON")
        return User3Exporter(
            user3_root=user3_root,
            schema_dir=self.schema_path,
            output_root=output_root,
            tree_depth=self.tree_depth,
            exclude_regexes=exclude_regexes or [],
            il2cpp_dump_path=self.il2cpp_dump_path,
            user_magic=self.user_magic,
            rsz_magic=self.rsz_magic,
        )

    def _new_packer(self, output_root: str | Path | None) -> User3Packer:
        """按当前配置创建封包器实例。

        参数：
            output_root (str | Path | None): 默认输出根目录，可为 ``None``。

        返回：
            User3Packer: 已用当前模板、dump、magic 等配置初始化的封包器。
        """
        return User3Packer(
            schema_dir=self.schema_path,
            il2cpp_dump_path=self.il2cpp_dump_path,
            output_root=output_root,
            user_magic=self.user_magic,
            rsz_magic=self.rsz_magic,
        )

    def _prepare_exporter_metadata(self, exporter: User3Exporter) -> None:
        """为单文件解析准备枚举表和枚举上下文。

        参数：
            exporter (User3Exporter): 待填充枚举索引的导出器实例。

        返回：
            None: 直接在 ``exporter`` 上设置枚举查找表与上下文。

        异常：
            FileNotFoundError: 当 ``il2cpp_dump_path`` 缺失或不是文件时抛出。
        """
        if self.il2cpp_dump_path is None or not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError("il2cpp_dump_path is required for parsing JSON")
        with self.il2cpp_dump_path.open("r", encoding="utf-8") as f:
            il2cpp_dump = json.load(f)
        # 导出器批处理时会写出 Enums_Internal.json；这里是内存解析，
        # 因此只构建运行时索引，不产生额外文件。
        enums_internal = exporter.export_enums_internal(il2cpp_dump)
        exporter.enum_lookup = exporter._build_enum_lookup_from_enums_internal(
            enums_internal
        )
        enum_context = exporter.export_enum_context_internal(il2cpp_dump)
        exporter._apply_enum_context(enum_context)
        exporter._ensure_enum_lookup()

    @staticmethod
    def _discover_user3_files(user3_root: Path) -> list[Path]:
        """发现单文件或目录下的 `.user.3` 文件。

        参数：
            user3_root (Path): ``.user.3`` 根目录或单个文件路径。

        返回：
            list[Path]: 排序后的 ``.user.3`` 文件路径列表（单文件时只含一项）。

        异常：
            FileNotFoundError: 当路径不存在或目录下没有 ``.user.3`` 时抛出。
        """
        if user3_root.is_file():
            return [user3_root]
        if not user3_root.is_dir():
            raise FileNotFoundError(f"user3 root not found: {user3_root}")
        files = sorted(user3_root.rglob("*.user.3"))
        if not files:
            raise FileNotFoundError(f"no *.user.3 found under: {user3_root}")
        return files

    @staticmethod
    def _run_callback(
        callback: PatchCallback, data: JsonTree, source_path: Path
    ) -> JsonTree | None:
        """根据 callback 参数个数自动决定是否传入源路径。

        参数：
            callback (PatchCallback): 用户提供的修改函数。
            data (JsonTree): 待修改的完整实例表 JSON。
            source_path (Path): 源 ``.user.3`` 文件路径。

        返回：
            JsonTree | None: callback 返回的新树，或 ``None``（表示就地修改）。
        """
        try:
            param_count = len(inspect.signature(callback).parameters)
        except (TypeError, ValueError):
            # 某些可调用对象可能无法通过 inspect 取得签名，默认按完整参数调用。
            param_count = 2
        if param_count <= 1:
            return callback(data)
        return callback(data, source_path)
