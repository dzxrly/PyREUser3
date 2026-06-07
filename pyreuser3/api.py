"""High-level API facade for RE Engine .user.3 JSON workflows."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from .core import RSZ_MAGIC, USR_MAGIC
from .export import User3Exporter
from .pack import User3Packer

# Keep the JSON shape stable for callers and editors.
JsonTree = Any
# Keep this implementation detail explicit.
PatchCallback = Callable[..., Optional[JsonTree]]


class REUser3Converter:
    """Reusable facade for exporting, parsing, patching, and packing .user.3 data."""

    def __init__(
        self,
        schema_path: str | Path | None = None,
        il2cpp_dump_path: str | Path | None = None,
        tree_depth: int | str = "auto",
        schema_dir: str | Path | None = None,
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
    ) -> None:
        """Initialize the instance."""
        # Keep this implementation detail explicit.
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
        """Export directory."""
        exporter = self._new_exporter(user3_root, output_root, exclude_regexes)
        return exporter.run()

    def export_file(
        self,
        user3_path: str | Path,
        json_path: str | Path,
    ) -> Path:
        """Export file."""
        # Keep this implementation detail explicit.
        # Keep the JSON shape stable for callers and editors.
        tree = self.parse_file(user3_path, round_floats=True)
        target = Path(json_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with target.open("w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        return target

    def parse_file(self, user3_path: str | Path, round_floats: bool = True) -> JsonTree:
        """Parse file."""
        exporter = self._new_exporter(user3_path, Path.cwd(), [])
        # Keep this implementation detail explicit.
        # Keep enum metadata consistent while converting values.
        self._prepare_exporter_metadata(exporter)
        tree = exporter._parse_user3(Path(user3_path))
        tree = exporter._postprocess_enum_nodes(tree)
        tree = exporter._finalize_export_tree(tree)
        if round_floats:
            return exporter._round_export_floats(tree)
        return tree

    def parse_pack_file(self, user3_path: str | Path) -> JsonTree:
        """Parse pack file."""
        exporter = self._new_exporter(user3_path, Path.cwd(), [])
        self._prepare_exporter_metadata(exporter)
        return exporter._parse_user3_pack(Path(user3_path))

    def pack_directory(
        self,
        json_root: str | Path,
        output_root: str | Path,
        exclude_regexes: list[str] | None = None,
    ) -> dict[str, int]:
        """Pack directory."""
        packer = self._new_packer(output_root)
        return packer.pack_directory(json_root, output_root, exclude_regexes)

    def pack_file(self, json_path: str | Path, user3_path: str | Path) -> Path:
        """Pack file."""
        packer = self._new_packer(Path(user3_path).parent)
        return packer.pack_json_file(json_path, user3_path)

    def pack(self, data: Any) -> bytes:
        """Pack pack."""
        return self._new_packer(None).pack(data)

    def patch_file(
        self,
        user3_path: str | Path,
        output_path: str | Path,
        callback: PatchCallback,
    ) -> Path:
        """Handle patch file."""
        source = Path(user3_path)
        # Keep instance references stable while parsing or packing data.
        # Keep instance references stable while parsing or packing data.
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
        """Handle patch directory."""
        source_root = Path(user3_root)
        target_root = Path(output_root)
        files = self._discover_user3_files(source_root)
        include_patterns = [re.compile(p) for p in (include_regexes or [])]
        exclude_patterns = [re.compile(p) for p in (exclude_regexes or [])]

        total = success = failed = skipped = 0
        for file_path in files:
            # Keep path handling explicit to avoid ambiguous working directories.
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
                # Record per-file failures without stopping the whole batch.
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
        """Internal helper for new exporter."""
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
        """Internal helper for new packer."""
        return User3Packer(
            schema_dir=self.schema_path,
            il2cpp_dump_path=self.il2cpp_dump_path,
            output_root=output_root,
            user_magic=self.user_magic,
            rsz_magic=self.rsz_magic,
        )

    def _prepare_exporter_metadata(self, exporter: User3Exporter) -> None:
        """Internal helper for prepare exporter metadata."""
        if self.il2cpp_dump_path is None or not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError("il2cpp_dump_path is required for parsing JSON")
        with self.il2cpp_dump_path.open("r", encoding="utf-8") as f:
            il2cpp_dump = json.load(f)
        # Keep this implementation detail explicit.
        # Keep this implementation detail explicit.
        enums_internal = exporter.export_enums_internal(il2cpp_dump)
        exporter.enum_lookup = exporter._build_enum_lookup_from_enums_internal(
            enums_internal
        )
        enum_context = exporter.export_enum_context_internal(il2cpp_dump)
        exporter._apply_enum_context(enum_context)
        exporter._ensure_enum_lookup()

    @staticmethod
    def _discover_user3_files(user3_root: Path) -> list[Path]:
        """Internal helper for discover user3 files."""
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
        """Internal helper for run callback."""
        try:
            param_count = len(inspect.signature(callback).parameters)
        except (TypeError, ValueError):
            # Keep this implementation detail explicit.
            param_count = 2
        if param_count <= 1:
            return callback(data)
        return callback(data, source_path)
