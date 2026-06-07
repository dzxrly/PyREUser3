"""JSON 到 `.user.3` 的封包器入口。

`User3Packer` 通过组合规划（plan）与写入（writer）两个 Mixin，把项目导出的
JSON 重新编码成 ``.user.3`` 二进制。本文件负责装配能力、加载枚举反查表，并
提供单文件、目录批量以及内存对象三种封包入口。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import InstanceSpec
from .plan import PackerPlanMixin
from .writer import PackerWriterMixin
from ..core import RSZ_MAGIC, USR_MAGIC, resolve_schema_path
from ..export import User3Exporter
from ..rich_ui import BatchProgress
from ..schema import TypeDB


class User3Packer(PackerPlanMixin, PackerWriterMixin):
    """根据导出的 JSON 树重新构造 `.user.3` 二进制文件。

    组合实例规划与二进制写入能力，支持 readable JSON、完整实例表 JSON 以及
    手写 JSON 三种输入，并在配置 il2cpp dump 时支持枚举名/标签反查。
    """

    def __init__(
        self,
        schema_dir: str | Path,
        il2cpp_dump_path: str | Path | None = None,
        output_root: str | Path | None = None,
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
    ) -> None:
        """初始化封包器。

        参数：
            schema_dir (str | Path): 历史参数名，实际必须是 RE_RSZ 模板 JSON 文件路径。
            il2cpp_dump_path (str | Path | None): 可选的 ``il2cpp_dump.json``，用于枚举名反查。
            output_root (str | Path | None): 默认输出根目录；为 ``None`` 时使用当前工作目录。
            user_magic (int): 写入 USR 头的 magic。
            rsz_magic (int): 写入 RSZ 块的 magic。

        返回：
            None: 构造函数，仅初始化实例属性。

        异常：
            FileNotFoundError: 当传入的 ``il2cpp_dump.json`` 路径不是文件时抛出。
        """
        self.schema_path = self._resolve_schema_path(Path(schema_dir))
        self.typedb = TypeDB.load(self.schema_path)
        self.il2cpp_dump_path = Path(il2cpp_dump_path) if il2cpp_dump_path else None
        if self.il2cpp_dump_path is not None and not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        self.output_root = Path(output_root) if output_root else Path.cwd()
        self.user_magic = int(user_magic)
        self.rsz_magic = int(rsz_magic)
        # 枚举查找表用于把 `[值] 名称` 或成员名还原为整数；没有 dump 时
        # 封包器仍可处理已经是数字的枚举字段。
        self.enum_lookup = self._load_enum_lookup()
        self.member_lookup = self._build_member_lookup()
        self.instances: list[InstanceSpec | None] = []

    def pack_json_file(self, json_path: str | Path, output_path: str | Path) -> Path:
        """读取一个 JSON 文件并写出 `.user.3`。

        参数：
            json_path (str | Path): 源 JSON 文件。
            output_path (str | Path): 目标 ``.user.3`` 路径。

        返回：
            Path: 实际写入的 ``.user.3`` 文件路径。
        """
        source = Path(json_path)
        target = Path(output_path)
        with source.open("r", encoding="utf-8") as f:
            data = json.load(f)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.pack(data))
        return target

    def pack_directory(
        self,
        json_root: str | Path,
        output_root: str | Path,
        exclude_regexes: list[str] | None = None,
    ) -> dict[str, int]:
        """批量封包目录或单个 JSON 文件。

        参数：
            json_root (str | Path): JSON 文件或根目录。
            output_root (str | Path): ``.user.3`` 输出根目录。
            exclude_regexes (list[str] | None): 排除相对路径的正则表达式列表。

        返回：
            dict[str, int]: 统计字典，含 ``total``、``success``、``failed`` 三个计数。

        异常：
            FileNotFoundError: 当 ``json_root`` 既不是文件也不是存在的目录时抛出。
        """
        source_root = Path(json_root)
        target_root = Path(output_root)
        patterns = [re.compile(p) for p in (exclude_regexes or [])]
        if source_root.is_file():
            files = [source_root]
        else:
            if not source_root.is_dir():
                raise FileNotFoundError(f"json root not found: {source_root}")
            # 优先处理稳定封包格式；没有时再处理 readable JSON，
            # 最后退回普通 JSON，方便用户手写输入。
            files = sorted(source_root.rglob("*.user.3.pack.json"))
            if not files:
                files = sorted(source_root.rglob("*.user.3.json"))
            if not files:
                files = sorted(source_root.rglob("*.json"))
        candidates: list[tuple[Path, str]] = []
        for json_file in files:
            rel = (
                json_file.name
                if source_root.is_file()
                else json_file.relative_to(source_root).as_posix()
            )
            if any(pattern.search(rel) for pattern in patterns):
                continue
            candidates.append((json_file, rel))

        total = success = failed = 0
        with BatchProgress(
            "Packing user3", total=len(candidates), unit="file"
        ) as progress:
            progress.log(f"Found {len(candidates)} JSON file(s).")
            progress.log(f"Schema: {self.schema_path}")
            progress.log(f"Output directory: {target_root}")
            for json_file, rel in candidates:
                total += 1
                progress.update(advance=0, description=json_file.stem)
                progress.log(f"Packing JSON: {rel}")
                try:
                    # 单个文件失败不会终止整批任务，便于批量模组输出时逐个排查。
                    out_path = self.output_path_for(json_file, source_root, target_root)
                    self.pack_json_file(json_file, out_path)
                    success += 1
                    progress.log(f"user3 pack complete: {out_path}", style="green")
                except Exception as exc:
                    failed += 1
                    error = f"{exc.__class__.__name__}: {exc}"
                    progress.log(f"user3 pack failed: {json_file} ({error})", style="red")
                progress.update(1)
        return {"total": total, "success": success, "failed": failed}

    def pack(self, data: Any) -> bytes:
        """把内存中的 JSON 对象编码为 `.user.3` 字节。

        参数：
            data (Any): 类名包裹对象、这类对象组成的列表，或完整实例表封包文档。

        返回：
            bytes: 可直接写入文件的 ``.user.3`` 二进制字节。
        """
        # 实例 0 固定保留为空引用槽，所有真实对象从 1 开始。
        if self._is_pack_document(data):
            roots = self._plan_pack_document(data)
        else:
            self.instances = [None]
            roots: list[int] = []
            for node in self._normalize_roots(data):
                roots.append(self._plan_node(node))
        return self._build_binary(roots)

    def output_path_for(
        self, json_file: Path, json_root: Path, output_root: Path
    ) -> Path:
        """根据输入 JSON 路径计算输出 `.user.3` 路径。

        参数：
            json_file (Path): 单个源 JSON 文件路径。
            json_root (Path): 输入根（文件或目录），用于还原相对子目录。
            output_root (Path): 输出根目录。

        返回：
            Path: 去掉 JSON 后缀、还原 ``.user.3`` 扩展名后的输出文件路径。
        """
        relative_parent = (
            Path() if json_root.is_file() else json_file.relative_to(json_root).parent
        )
        name = json_file.name
        # 按输入命名约定剥离不同层级的 JSON 后缀，得到目标 .user.3 文件名。
        if name.endswith(".user.3.pack.json"):
            output_name = name[: -len(".pack.json")]
        elif name.endswith(".user.3.json"):
            output_name = name[: -len(".json")]
        elif name.endswith(".json"):
            output_name = f"{name[: -len('.json')]}.user.3"
        else:
            output_name = f"{name}.user.3"
        return output_root / relative_parent / output_name

    def _resolve_schema_path(self, schema_dir: Path) -> Path:
        """校验模板路径并拒绝目录输入。

        参数：
            schema_dir (Path): 历史参数名，实际必须是具体模板 JSON 文件。

        返回：
            Path: 校验后的模板文件路径。
        """
        return resolve_schema_path(schema_dir)

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """从显式 il2cpp dump 构建枚举数值查找表。

        返回：
            dict[str, dict[int, tuple[str, int]]]: ``枚举类型 -> {数值 -> (成员名, 原始值)}``
            的查找表；未配置 dump 时返回空映射。
        """
        raw: dict[str, Any] | None = None
        if self.il2cpp_dump_path is not None:
            with self.il2cpp_dump_path.open("r", encoding="utf-8") as f:
                raw = User3Exporter.export_enums_internal(json.load(f))
        if not isinstance(raw, dict):
            return {}

        lookup: dict[str, dict[int, tuple[str, int]]] = {}
        for enum_type, members in raw.items():
            if not isinstance(enum_type, str) or not isinstance(members, dict):
                continue
            value_map: dict[int, tuple[str, int]] = {}
            for member_name, raw_value in members.items():
                if not isinstance(member_name, str) or not isinstance(raw_value, int):
                    continue
                entry = (member_name, raw_value)
                # 同时登记有符号和无符号 32 位形式，兼容 JSON 中的不同写法。
                value_map[self._to_s32(raw_value)] = entry
                value_map[self._to_u32(raw_value)] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _build_member_lookup(self) -> dict[str, dict[str, int]]:
        """建立 `枚举类型 -> 成员名 -> 数值` 的反查表。

        返回：
            dict[str, dict[str, int]]: 用于把枚举成员名还原成整数值的反查表。
        """
        out: dict[str, dict[str, int]] = {}
        for enum_type, value_map in self.enum_lookup.items():
            members = out.setdefault(enum_type, {})
            for member_name, fixed_value in value_map.values():
                members.setdefault(member_name, fixed_value)
        return out

    @staticmethod
    def _to_u32(value: int) -> int:
        """转换为无符号 32 位整数。

        参数：
            value (int): 输入整数。

        返回：
            int: 无符号 32 位值（0 ~ 0xFFFFFFFF）。
        """
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """转换为有符号 32 位整数。

        参数：
            value (int): 输入整数。

        返回：
            int: 有符号 32 位值（-0x80000000 ~ 0x7FFFFFFF）。
        """
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000
