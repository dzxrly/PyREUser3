"""Provide the REUser3Converter facade used by downstream Python code.

The facade hides exporter and packer construction details, keeps schema and il2cpp dump
configuration in one place, and offers convenient single-file, batch, and patch-and-
repack workflows.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from .core import RSZ_MAGIC, USR_MAGIC
from .export import User3Exporter
from .pack import User3Packer

# Preserve the exported JSON structure so external scripts and hand-edited files remain
# compatible across workflows.
JsonTree = Any
JsonFormat = Literal["readable", "repack"]
# Patch callbacks may accept only the parsed data or both the data and source
# path; returning None means the callback mutated in place.
PatchCallback = Callable[..., Optional[JsonTree]]


class REUser3Converter:
    """Store shared conversion configuration and expose high-level export, parse, patch, and
    pack workflows.
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
        """Initialize REUser3Converter with validated configuration and state.

        Args:
            schema_path (str | Path | None): Explicit RE_RSZ schema JSON file path.
            il2cpp_dump_path (str | Path | None): Path to il2cpp_dump.json for enum metadata.
            tree_depth (int | str): Requested reference-tree expansion depth or auto mode.
            schema_dir (str | Path | None): Compatibility schema argument that must resolve to a
            schema JSON file.
            user_magic (int): Expected magic value for the outer .user.3 container header.
            rsz_magic (int): Expected magic value for embedded RSZ blocks.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            TypeError: The caller supplied a value of an unsupported type.
        """
        # Accept the legacy schema_dir alias from older callers, but normalize all internal state to schema_path.
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
        """Export every selected .user.3 file under a directory or single-file root.

        Args:
            user3_root (str | Path): Source .user.3 file or directory root.
            output_root (str | Path): Directory where generated output is written.
            exclude_regexes (list[str] | None): Regular expressions used to skip matching
            relative paths.

        Returns:
            dict[str, int]: Counters describing total, successful, and failed items.
        """
        exporter = self._new_exporter(user3_root, output_root, exclude_regexes)
        return exporter.run()

    def export_file(
        self,
        user3_path: str | Path,
        json_path: str | Path,
    ) -> Path:
        """Export one .user.3 file to the requested JSON path.

        Args:
            user3_path (str | Path): Path to the .user.3 file being parsed, exported, patched, or packed.
            json_path (str | Path): Path to the JSON document read from or written by this workflow.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        # Reuse parse_file so single-file and batch exports keep the same parsed JSON shape and metadata handling.
        # Preserve the exported JSON structure so external scripts and hand-edited files
        # remain compatible across workflows.
        tree = self.user3_to_json(
            user3_path,
            json_format="readable",
            round_floats=True,
        )
        target = Path(json_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with target.open("w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        return target

    def user3_to_json(
        self,
        user3_path: str | Path,
        json_format: JsonFormat = "readable",
        round_floats: bool = True,
    ) -> JsonTree:
        """Convert one .user.3 file to an in-memory JSON-compatible tree.

        Args:
            user3_path (str | Path): Path to the .user.3 file being parsed.
            json_format (JsonFormat): Return "readable" for the same shape written by
            export_file(), or "repack" for the full instance-table document accepted by
            pack().
            round_floats (bool): Whether readable-format floats should be rounded to four
            decimal places.

        Returns:
            JsonTree: JSON-compatible Python data. The readable format preserves the
            existing export shape; the repack format returns a dictionary with pack
            metadata and instance tables.

        Raises:
            ValueError: json_format was not "readable" or "repack".
        """
        normalized_format = self._normalize_json_format(json_format)
        if normalized_format == "readable":
            return self.parse_file(user3_path, round_floats=round_floats)
        if normalized_format == "repack":
            return self.parse_pack_file(user3_path)
        raise ValueError("json_format must be 'readable' or 'repack'")

    def parse_file(self, user3_path: str | Path, round_floats: bool = True) -> JsonTree:
        """Parse one .user.3 file into the compact exported JSON tree.

        Args:
            user3_path (str | Path): Path to the .user.3 file being parsed, exported, patched, or packed.
            round_floats (bool): Whether exported floats should be rounded to four decimal places for readability.

        Returns:
            JsonTree: JSON-compatible tree used by export, editing, or packing workflows.
        """
        exporter = self._new_exporter(user3_path, Path.cwd(), [])
        # Build enum lookup and context metadata in memory; single-file parsing should not create Enums_Internal.json.
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        self._prepare_exporter_metadata(exporter)
        tree = exporter._parse_user3(Path(user3_path))
        tree = exporter._postprocess_enum_nodes(tree)
        tree = exporter._finalize_export_tree(tree)
        if round_floats:
            return exporter._round_export_floats(tree)
        return tree

    def parse_pack_file(self, user3_path: str | Path) -> JsonTree:
        """Parse one .user.3 file into the full instance-table JSON used for stable repacking.

        Args:
            user3_path (str | Path): Path to the .user.3 file being parsed, exported, patched, or packed.

        Returns:
            JsonTree: JSON-compatible tree used by export, editing, or packing workflows.
        """
        exporter = self._new_exporter(user3_path, Path.cwd(), [])
        self._prepare_exporter_metadata(exporter)
        return exporter._parse_user3_pack(Path(user3_path))

    @staticmethod
    def _normalize_json_format(json_format: str) -> str:
        """Normalize the public in-memory JSON format selector.

        Args:
            json_format (str): Requested JSON output shape.

        Returns:
            str: Normalized format name.

        Raises:
            TypeError: The caller supplied a non-string format selector.
        """
        if not isinstance(json_format, str):
            raise TypeError("json_format must be a string")
        return json_format.strip().lower().replace("-", "_")

    def pack_directory(
        self,
        json_root: str | Path,
        output_root: str | Path,
        exclude_regexes: list[str] | None = None,
    ) -> dict[str, int]:
        """Pack every selected JSON file under a directory or single-file root.

        Args:
            json_root (str | Path): JSON file or directory root to process.
            output_root (str | Path): Directory where generated output is written.
            exclude_regexes (list[str] | None): Regular expressions used to skip matching
            relative paths.

        Returns:
            dict[str, int]: Counters describing total, successful, and failed items.
        """
        packer = self._new_packer(output_root)
        return packer.pack_directory(json_root, output_root, exclude_regexes)

    def pack_file(self, json_path: str | Path, user3_path: str | Path) -> Path:
        """Pack one JSON document to the requested .user.3 path.

        Args:
            json_path (str | Path): Path to the JSON document read from or written by this workflow.
            user3_path (str | Path): Path to the .user.3 file being parsed, exported, patched, or packed.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        packer = self._new_packer(Path(user3_path).parent)
        return packer.pack_json_file(json_path, user3_path)

    def pack(self, data: Any) -> bytes:
        """Encode an in-memory JSON tree as .user.3 bytes.

        Args:
            data (Any): JSON tree or binary payload consumed by this conversion step.

        Returns:
            bytes: Encoded binary data ready to write to disk.
        """
        return self._new_packer(None).pack(data)

    def patch_file(
        self,
        user3_path: str | Path,
        output_path: str | Path,
        callback: PatchCallback,
    ) -> Path:
        """Patch one .user.3 file through a callback and write the packed result.

        Args:
            user3_path (str | Path): Path to the .user.3 file being parsed, exported, patched, or packed.
            output_path (str | Path): Destination path where the generated file is written.
            callback (PatchCallback): User callback that may inspect or modify parsed JSON.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.
        """
        source = Path(user3_path)
        # Preserve instance numbering and reference identity; RSZ object links depend on
        # these indexes remaining stable.
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
        """Patch every selected .user.3 file under a root directory.

        Args:
            user3_root (str | Path): Source .user.3 file or directory root.
            output_root (str | Path): Directory where generated output is written.
            callback (PatchCallback): User callback that may inspect or modify parsed JSON.
            include_regexes (list[str] | None): Regular expressions used to include matching
            relative paths.
            exclude_regexes (list[str] | None): Regular expressions used to skip matching
            relative paths.

        Returns:
            dict[str, int]: Counters describing total, successful, and failed items.
        """
        source_root = Path(user3_root)
        target_root = Path(output_root)
        files = self._discover_user3_files(source_root)
        include_patterns = [re.compile(p) for p in (include_regexes or [])]
        exclude_patterns = [re.compile(p) for p in (exclude_regexes or [])]

        total = success = failed = skipped = 0
        for file_path in files:
            # Resolve and validate paths at the boundary so later code never guesses
            # relative to a surprising working directory.
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
                # Treat each file independently so one malformed resource is reported
                # but does not stop the rest of the batch.
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
        """Create an exporter with this facade's schema, enum metadata, and magic values.

        Args:
            user3_root (str | Path): Source .user.3 file or directory root.
            output_root (str | Path): Directory where generated output is written.
            exclude_regexes (list[str] | None): Regular expressions used to skip matching
            relative paths.

        Returns:
            User3Exporter: Configured object or normalized value returned for the caller to use directly.

        Raises:
            FileNotFoundError: A required file or directory was missing.
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
        """Create a packer with this facade's schema, enum metadata, and magic values.

        Args:
            output_root (str | Path | None): Directory where generated output is written.

        Returns:
            User3Packer: Configured object or normalized value returned for the caller to use directly.
        """
        return User3Packer(
            schema_dir=self.schema_path,
            il2cpp_dump_path=self.il2cpp_dump_path,
            output_root=output_root,
            user_magic=self.user_magic,
            rsz_magic=self.rsz_magic,
        )

    def _prepare_exporter_metadata(self, exporter: User3Exporter) -> None:
        """Prepare exporter metadata.

        Args:
            exporter (User3Exporter): Exporter instance whose metadata caches are being prepared.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            FileNotFoundError: A required file or directory was missing.
        """
        if self.il2cpp_dump_path is None or not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError("il2cpp_dump_path is required for parsing JSON")
        with self.il2cpp_dump_path.open("r", encoding="utf-8") as f:
            il2cpp_dump = json.load(f)
        # Batch export writes Enums_Internal.json for downstream tools; direct
        # parsing keeps the same lookup only in memory.
        # Keep the generated metadata attached to the exporter so field parsing can
        # format enum names consistently.
        enums_internal = exporter.export_enums_internal(il2cpp_dump)
        exporter.enum_lookup = exporter._build_enum_lookup_from_enums_internal(
            enums_internal
        )
        enum_context = exporter.export_enum_context_internal(il2cpp_dump)
        exporter._apply_enum_context(enum_context)
        exporter._ensure_enum_lookup()

    @staticmethod
    def _discover_user3_files(user3_root: Path) -> list[Path]:
        """Discover user3 files.

        Args:
            user3_root (Path): Source .user.3 file or directory root.

        Returns:
            list[Path]: Filesystem paths selected for batch processing after suffix and exclusion checks.

        Raises:
            FileNotFoundError: A required file or directory was missing.
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
        """Run callback.

        Args:
            callback (PatchCallback): User callback that may inspect or modify parsed JSON.
            data (JsonTree): JSON tree or binary payload consumed by this conversion step.
            source_path (Path): Original source path associated with a patch callback or output
            path.

        Returns:
            JsonTree | None: Configured object or normalized value returned for the caller to use directly.
        """
        try:
            param_count = len(inspect.signature(callback).parameters)
        except (TypeError, ValueError):
            # Some callables do not expose inspectable signatures, so fall back to
            # the full callback signature when introspection fails.
            param_count = 2
        if param_count <= 1:
            return callback(data)
        return callback(data, source_path)
