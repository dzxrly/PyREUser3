"""Main packer that rebuilds .user.3 files from JSON input."""

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
    """Packer for rebuilding RE Engine .user.3 binaries from JSON."""

    def __init__(
        self,
        schema_dir: str | Path,
        il2cpp_dump_path: str | Path | None = None,
        output_root: str | Path | None = None,
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
    ) -> None:
        """Initialize the instance."""
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
        # Keep enum metadata consistent while converting values.
        # Keep enum metadata consistent while converting values.
        self.enum_lookup = self._load_enum_lookup()
        self.member_lookup = self._build_member_lookup()
        self.instances: list[InstanceSpec | None] = []

    def pack_json_file(self, json_path: str | Path, output_path: str | Path) -> Path:
        """Pack json file."""
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
        """Pack directory."""
        source_root = Path(json_root)
        target_root = Path(output_root)
        patterns = [re.compile(p) for p in (exclude_regexes or [])]
        if source_root.is_file():
            files = [source_root]
        else:
            if not source_root.is_dir():
                raise FileNotFoundError(f"json root not found: {source_root}")
            # Keep the JSON shape stable for callers and editors.
            # Keep the JSON shape stable for callers and editors.
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
                    # Record per-file failures without stopping the whole batch.
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
        """Pack pack."""
        # Keep instance references stable while parsing or packing data.
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
        """Handle output path for."""
        relative_parent = (
            Path() if json_root.is_file() else json_file.relative_to(json_root).parent
        )
        name = json_file.name
        # Keep the JSON shape stable for callers and editors.
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
        """Internal helper for resolve schema path."""
        return resolve_schema_path(schema_dir)

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """Internal helper for load enum lookup."""
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
                # Keep the JSON shape stable for callers and editors.
                value_map[self._to_s32(raw_value)] = entry
                value_map[self._to_u32(raw_value)] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _build_member_lookup(self) -> dict[str, dict[str, int]]:
        """Internal helper for build member lookup."""
        out: dict[str, dict[str, int]] = {}
        for enum_type, value_map in self.enum_lookup.items():
            members = out.setdefault(enum_type, {})
            for member_name, fixed_value in value_map.values():
                members.setdefault(member_name, fixed_value)
        return out

    @staticmethod
    def _to_u32(value: int) -> int:
        """Internal helper for to u32."""
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """Internal helper for to s32."""
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000
