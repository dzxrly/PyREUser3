"""Compose packer mixins into User3Packer and provide file, directory, and in-memory packing entry points.

The class loads schema metadata, optional enum reverse lookups, discovers JSON
candidates, and writes rebuilt .user.3 files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import (
    ExternalUserdataSpec,
    InstanceSpec,
    RszUserdataSpec,
    UsrResourceSpec,
    UsrUserdataSpec,
)
from .plan import PackerPlanMixin
from .writer import PackerWriterMixin
from ..core import PACK_JSON_FORMATS, RSZ_MAGIC, USR_MAGIC, resolve_schema_path
from ..enum_codec import is_probable_flags_enum
from ..export import User3Exporter
from ..rich_ui import BatchProgress
from ..schema import TypeDB
from ..usr_layouts import (
    DEFAULT_RSZ_HEADER_LAYOUT_ID,
    DEFAULT_USR_LAYOUT_ID,
    get_rsz_header_layout,
    get_usr_layout,
)


class User3Packer(PackerPlanMixin, PackerWriterMixin):
    """Coordinate schema loading, enum reverse lookup, JSON discovery, planning, and binary
    writing for .user.3 packing.
    """

    def __init__(
        self,
        schema_dir: str | Path,
        il2cpp_dump_path: str | Path | None = None,
        output_root: str | Path | None = None,
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
        preloaded_typedb: TypeDB | None = None,
        preloaded_il2cpp_metadata: tuple[dict, dict] | None = None,
    ) -> None:
        """Initialize User3Packer with validated configuration and state.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            schema_dir (str | Path): Compatibility schema argument that must resolve to a schema
            JSON file.
            il2cpp_dump_path (str | Path | None): Path to il2cpp_dump.json for enum metadata.
            output_root (str | Path | None): Directory where generated output is written.
            user_magic (int): Expected magic value for the outer .user.3 container header.
            rsz_magic (int): Expected magic value for embedded RSZ blocks.
            preloaded_typedb (TypeDB | None): Optional schema cache supplied by the
            high-level converter.
            preloaded_il2cpp_metadata (tuple[dict, dict] | None): Optional enum tables
            and context supplied by the high-level converter.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            FileNotFoundError: A required file or directory was missing.
        """
        self.schema_path = self._resolve_schema_path(Path(schema_dir))
        self.typedb = preloaded_typedb or TypeDB.load(self.schema_path)
        self.il2cpp_dump_path = Path(il2cpp_dump_path) if il2cpp_dump_path else None
        if self.il2cpp_dump_path is not None and not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        self._preloaded_il2cpp_metadata = preloaded_il2cpp_metadata
        self.output_root = Path(output_root) if output_root else Path.cwd()
        self.user_magic = int(user_magic)
        self.rsz_magic = int(rsz_magic)
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        self.enum_underlying_types: dict[str, str] = {}
        self.bitset_rules: dict[str, str] = {}
        self.class_default_enums: dict[str, str] = {}
        self.enum_lookup = self._load_enum_lookup()
        self.member_lookup = self._build_member_lookup()
        self.enum_flags = {
            enum_type
            for enum_type, value_map in self.enum_lookup.items()
            if is_probable_flags_enum(
                enum_type, value_map, self.enum_underlying_types.get(enum_type)
            )
        }
        self.instances: list[InstanceSpec | ExternalUserdataSpec | None] = []
        self.usr_layout = get_usr_layout(DEFAULT_USR_LAYOUT_ID)
        if self.usr_layout is None:
            raise RuntimeError(f"default USR layout is not registered: {DEFAULT_USR_LAYOUT_ID}")
        self.rsz_header_layout = get_rsz_header_layout(
            DEFAULT_RSZ_HEADER_LAYOUT_ID
        )
        if self.rsz_header_layout is None:
            raise RuntimeError(
                "default RSZ header layout is not registered: "
                f"{DEFAULT_RSZ_HEADER_LAYOUT_ID}"
            )
        self.usr_header_padding = b"\x00" * self.usr_layout.header_padding_size
        self.usr_resources: list[UsrResourceSpec] = []
        self.usr_userdata: list[UsrUserdataSpec] = []
        # A numeric RSZ version must be loaded from repack metadata.  The modern
        # header family is shared across games and must not imply MHWS version 16.
        self.rsz_version: int | None = None
        self.rsz_reserved = 0
        self.rsz_userdata: list[RszUserdataSpec] = []

    def pack_json_file(self, json_path: str | Path, output_path: str | Path) -> Path:
        """Pack json file.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            json_path (str | Path): Path to the JSON document read from or written by this workflow.
            output_path (str | Path): Destination path where the generated file is written.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
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
        """Pack every selected JSON file under a directory or single-file root.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            json_root (str | Path): JSON file or directory root to process.
            output_root (str | Path): Directory where generated output is written.
            exclude_regexes (list[str] | None): Regular expressions used to skip matching
            relative paths.

        Returns:
            dict[str, int]: Counters describing total, successful, and failed items.

        Raises:
            FileNotFoundError: A required file or directory was missing.
        """
        source_root = Path(json_root)
        target_root = Path(output_root)
        patterns = [re.compile(p) for p in (exclude_regexes or [])]
        if source_root.is_file():
            files = [source_root]
        else:
            if not source_root.is_dir():
                raise FileNotFoundError(f"json root not found: {source_root}")
            # Only documents that explicitly identify themselves as repack JSON are
            # candidates. Readable exports are never sent to the packer.
            named_pack_files = set(source_root.rglob("*.user.3.pack.json"))
            files = sorted(
                named_pack_files
                | {
                    path
                    for path in source_root.rglob("*.json")
                    if path not in named_pack_files and self._is_repack_json_file(path)
                }
            )
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
                    # Treat each file independently so one malformed resource is
                    # reported but does not stop the rest of the batch.
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

    @staticmethod
    def _is_repack_json_file(path: Path) -> bool:
        """Return whether a directory candidate declares a supported repack format."""

        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(data, dict)
            and data.get("_format") in PACK_JSON_FORMATS
            and isinstance(data.get("_instances"), dict)
        )

    def pack(self, data: Any) -> bytes:
        """Encode an in-memory JSON tree as .user.3 bytes.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            data (Any): JSON tree or binary payload consumed by this conversion step.

        Returns:
            bytes: Encoded binary data ready to write to disk.
        """
        # Readable trees deliberately omit physical container metadata and are therefore
        # never accepted as pack input.
        roots = self._plan_repack_input(data)
        return self._build_binary(roots)

    def output_path_for(
        self, json_file: Path, json_root: Path, output_root: Path
    ) -> Path:
        """Compute the output path for path for.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            json_file (Path): JSON file currently being packed into .user.3 output.
            json_root (Path): JSON file or directory root to process.
            output_root (Path): Directory where generated output is written.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        relative_parent = (
            Path() if json_root.is_file() else json_file.relative_to(json_root).parent
        )
        name = json_file.name
        # Preserve the exported JSON structure so external scripts and hand-edited files
        # remain compatible across workflows.
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
        """Resolve schema path.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            schema_dir (Path): Compatibility schema argument that must resolve to a schema JSON
            file.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        return resolve_schema_path(schema_dir)

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """Load enum lookup.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Returns:
            dict[str, dict[int, tuple[str, int]]]: Enum lookup table keyed by type name and numeric value.
        """
        raw: dict[str, Any] | None = None
        preloaded = self._preloaded_il2cpp_metadata
        if preloaded is not None:
            raw, enum_context = preloaded
        elif self.il2cpp_dump_path is not None:
            raw, enum_context = User3Exporter.export_il2cpp_metadata_from_path(
                self.il2cpp_dump_path
            )
        else:
            enum_context = {}
        if isinstance(raw, dict):
            enum_underlying_types = enum_context.get("enum_underlying_types")
            if isinstance(enum_underlying_types, dict):
                for enum_name, storage_type in enum_underlying_types.items():
                    if isinstance(enum_name, str) and isinstance(storage_type, str):
                        self.enum_underlying_types[enum_name] = storage_type
            bitset_rules = enum_context.get("bitset_rules")
            if isinstance(bitset_rules, dict):
                self.bitset_rules = {
                    class_name: enum_type
                    for class_name, enum_type in bitset_rules.items()
                    if isinstance(class_name, str) and isinstance(enum_type, str)
                }
            generic_scalar_rules = enum_context.get("generic_scalar_rules")
            if isinstance(generic_scalar_rules, dict):
                for class_name, enum_type in generic_scalar_rules.items():
                    if isinstance(class_name, str) and isinstance(enum_type, str):
                        self.class_default_enums[class_name] = enum_type
            generic_container_rules = enum_context.get("generic_container_rules")
            param_enums: dict[str, set[str]] = {}
            if isinstance(generic_container_rules, dict):
                for rule in generic_container_rules.values():
                    if not isinstance(rule, dict):
                        continue
                    param_type = rule.get("param_type")
                    enum_type = rule.get("enum_type")
                    if isinstance(param_type, str) and isinstance(enum_type, str):
                        param_enums.setdefault(param_type, set()).add(enum_type)
            for param_type, enum_types in param_enums.items():
                if len(enum_types) == 1:
                    self.class_default_enums[param_type] = next(iter(enum_types))
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
                # Preserve the exported JSON structure so external scripts and hand-
                # edited files remain compatible across workflows.
                value_map[raw_value] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _build_member_lookup(self) -> dict[str, dict[str, int]]:
        """Build member lookup.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Returns:
            dict[str, dict[str, int]]: Reverse enum lookup keyed by type name and member label.
        """
        out: dict[str, dict[str, int]] = {}
        for enum_type, value_map in self.enum_lookup.items():
            members = out.setdefault(enum_type, {})
            for member_name, fixed_value in value_map.values():
                members.setdefault(member_name, fixed_value)
        return out

    @staticmethod
    def _to_u32(value: int) -> int:
        """Normalize an integer-like value into an unsigned 32-bit integer.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """Normalize an integer-like value into a signed 32-bit integer.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000
