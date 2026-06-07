"""Main exporter that converts .user.3 files into compact JSON."""

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
    """Exporter for converting RE Engine .user.3 binaries into compact JSON."""

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
        """Initialize the instance."""
        # Keep path handling explicit to avoid ambiguous working directories.
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
        # Keep enum metadata consistent while converting values.
        # Keep enum metadata consistent while converting values.
        self.enum_lookup: dict[str, dict[int, tuple[str, int]]] = {}
        self.class_field_fixed_types: dict[str, dict[str, str]] = {}
        self.serializable_to_fixed: dict[str, str] = {}
        self.generic_container_rules: dict[str, tuple[str, str]] = {}
        self.param_type_default_enum: dict[str, str] = {}
        self.enum_member_to_types: dict[str, list[str]] = {}

    def run(self) -> dict[str, int]:
        """Run the configured workflow."""
        files = self._discover_user3_files()
        self.output_root.mkdir(parents=True, exist_ok=True)
        # Keep enum metadata consistent while converting values.
        # Keep this implementation detail explicit.
        enums_internal = self._ensure_internal_metadata_files()
        self.enum_lookup = self._build_enum_lookup_from_enums_internal(enums_internal)
        self._load_enum_context_from_il2cpp_dump()
        self._ensure_enum_lookup()

        success = 0
        failed = 0
        # Record per-file failures without stopping the whole batch.
        with BatchProgress(
            "Exporting user3", total=len(files), unit="file"
        ) as progress:
            progress.log(f"Found {len(files)} .user.3 file(s).")
            progress.log(f"Schema: {self.schema_path}")
            progress.log(f"Output directory: {self.output_root}")
            for user3_file in files:
                label = user3_file.name.replace(".user.3", "")
                progress.update(advance=0, description=label)
                progress.log(f"Exporting user3: {user3_file}")
                ok, output_path, error = self._export_one_file(user3_file)
                if ok:
                    success += 1
                    progress.log(f"user3 export complete: {output_path}", style="green")
                else:
                    failed += 1
                    progress.log(f"user3 export failed: {user3_file} ({error})", style="red")
                progress.update(1)

        return {"total": len(files), "success": success, "failed": failed}

    def _export_one_file(
        self, user3_file: Path
    ) -> tuple[bool, Path | None, str | None]:
        """Internal helper for export one file."""
        try:
            # Keep enum metadata consistent while converting values.
            # Keep the JSON shape stable for callers and editors.
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
            # Keep this implementation detail explicit.
            return False, None, f"{exc.__class__.__name__}: {exc}"

    def _resolve_schema_path(self, schema_dir: Path) -> Path:
        """Internal helper for resolve schema path."""
        return resolve_schema_path(schema_dir)

    def _normalize_tree_depth(self, tree_depth: int | str) -> int | str:
        """Internal helper for normalize tree depth."""
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
        """Internal helper for discover user3 files."""
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
            # Keep path handling explicit to avoid ambiguous working directories.
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
        """Internal helper for output path for."""
        if self.user3_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = user3_file.relative_to(self.user3_root).parent
        output_name = f"{user3_file.name}.json"
        return self.output_root / relative_parent / output_name
