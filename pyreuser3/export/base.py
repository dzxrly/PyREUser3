"""Compose exporter mixins into the concrete User3Exporter class and coordinate batch export work.

The class validates inputs, discovers files, prepares enum metadata, writes JSON output,
and reports per-file progress without stopping the whole batch on one failure.
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
    """Coordinate file discovery, enum preparation, parsing, post-processing, and JSON writing
    for .user.3 export.
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
        """Initialize User3Exporter with validated configuration and state.

        Args:
            user3_root (str | Path): Source .user.3 file or directory root.
            schema_dir (str | Path): Compatibility schema argument that must resolve to a schema
            JSON file.
            output_root (str | Path): Directory where generated output is written.
            tree_depth (int | str): Requested reference-tree expansion depth or auto mode.
            exclude_regexes (list[str] | None): Regular expressions used to skip matching
            relative paths.
            il2cpp_dump_path (str | Path): Path to il2cpp_dump.json for enum metadata.
            user_magic (int): Expected magic value for the outer .user.3 container header.
            rsz_magic (int): Expected magic value for embedded RSZ blocks.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            FileNotFoundError: A required file or directory was missing.
        """
        # Resolve and validate paths at the boundary so later code never guesses
        # relative to a surprising working directory.
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
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        self.enum_lookup: dict[str, dict[int, tuple[str, int]]] = {}
        self.class_field_fixed_types: dict[str, dict[str, str]] = {}
        self.serializable_to_fixed: dict[str, str] = {}
        self.generic_container_rules: dict[str, tuple[str, str]] = {}
        self.param_type_default_enum: dict[str, str] = {}
        self.enum_underlying_types: dict[str, str] = {}
        self.enum_member_to_types: dict[str, list[str]] = {}
        self._pending_enum_context: dict | None = None

    def run(self) -> dict[str, int]:
        """Run the batch exporter and return conversion counters.


        Returns:
            dict[str, int]: Counters describing total, successful, and failed items.
        """
        files = self._discover_user3_files()
        self.output_root.mkdir(parents=True, exist_ok=True)
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        # Rebuild enum metadata from the explicit il2cpp dump on every export to
        # avoid cross-game or cross-version contamination.
        enums_internal = self._ensure_internal_metadata_files()
        self.enum_lookup = self._build_enum_lookup_from_enums_internal(enums_internal)
        self._load_enum_context_from_il2cpp_dump()
        self._ensure_enum_lookup()

        success = 0
        failed = 0
        # Treat each file independently so one malformed resource is reported but does
        # not stop the rest of the batch.
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
        """Export one file.

        Args:
            user3_file (Path): Specific .user.3 file currently being processed.

        Returns:
            tuple[bool, Path | None, str | None]: Success flag, written path when
            available, and error text when conversion fails.
        """
        try:
            # Register enum values through the shared lookup tables so readable labels
            # and numeric packing stay reversible.
            # Preserve the exported JSON structure so external scripts and hand-edited
            # files remain compatible across workflows.
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
            # Convert per-file exceptions into result tuples so batch processing can
            # continue and report each failed source.
            return False, None, f"{exc.__class__.__name__}: {exc}"

    def _resolve_schema_path(self, schema_dir: Path) -> Path:
        """Resolve schema path.

        Args:
            schema_dir (Path): Compatibility schema argument that must resolve to a schema JSON
            file.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        return resolve_schema_path(schema_dir)

    def _normalize_tree_depth(self, tree_depth: int | str) -> int | str:
        """Normalize tree depth.

        Args:
            tree_depth (int | str): Requested reference-tree expansion depth or auto mode.

        Returns:
            int | str: Parsed integer value or the literal auto mode.

        Raises:
            TypeError: The caller supplied a value of an unsupported type.
            ValueError: The caller supplied a missing, malformed, or out-of-range value.
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
        """Discover user3 files.


        Returns:
            list[Path]: Filesystem paths selected for batch processing after suffix and exclusion checks.

        Raises:
            FileNotFoundError: A required file or directory was missing.
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
            # Resolve and validate paths at the boundary so later code never guesses
            # relative to a surprising working directory.
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
        """Compute the output path for path for.

        Args:
            user3_file (Path): Specific .user.3 file currently being processed.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        if self.user3_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = user3_file.relative_to(self.user3_root).parent
        output_name = f"{user3_file.name}.json"
        return self.output_root / relative_parent / output_name
