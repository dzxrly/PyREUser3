"""Bridge from Web form payloads to core converter calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..core import RSZ_MAGIC, USR_MAGIC

# Keep this implementation detail explicit.
LogFn = Callable[[str], None]


class ConversionRunners:
    """Implementation for ConversionRunners."""

    def __init__(self, root_dir: str | Path) -> None:
        """Initialize the instance."""
        # Keep path handling explicit to avoid ambiguous working directories.
        # Keep path handling explicit to avoid ambiguous working directories.
        self.root_dir = Path(root_dir).expanduser().resolve()

    def run_export(self, payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
        """Run the export command."""
        # Keep path handling explicit to avoid ambiguous working directories.
        input_dir = self._path_value(payload, "inputDir", "input path")
        schema_path = self._path_value(payload, "schema path")
        output_dir = self._path_value(payload, "output directory")
        il2cpp_dump_path = self._path_value(
            payload,
            "il2cppDumpPath",
            "il2cpp_dump.json",
        )
        exclude_regexes = self._exclude_regexes(payload)
        tree_depth = self._tree_depth(payload)
        user_magic = self._magic(payload, "userMagic", USR_MAGIC)
        rsz_magic = self._magic(payload, "rszMagic", RSZ_MAGIC)

        # Keep this implementation detail explicit.
        self._ensure_existing_path(input_dir, "input path")
        self._ensure_existing_file(schema_path, "schema path")
        self._ensure_existing_file(il2cpp_dump_path, "il2cpp_dump.json")

        log(f"Input: {input_dir}")
        log(f"Schema: {schema_path}")
        log(f"Output: {output_dir}")
        if exclude_regexes:
            log(f"Exclude regexes: {len(exclude_regexes)}")

        # Delay the import so lightweight commands do not load heavy dependencies.
        from ..export import User3Exporter

        log("Starting .user.3 export.")
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
        log(f".user.3 export complete: {json.dumps(user3_result, ensure_ascii=False)}")

        # Keep Web UI behavior explicit and predictable.
        return {"user3": user3_result, "outputDir": str(output_dir)}

    def _path_value(self, payload: dict[str, Any], key: str, label: str) -> Path:
        """Internal helper for path value."""
        path = Path(self._text_value(payload, key, label)).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{label} must be selected as an absolute path")
        return path

    @staticmethod
    def _text_value(payload: dict[str, Any], key: str, label: str) -> str:
        """Internal helper for text value."""
        value = payload.get(key)
        if value is None:
            raise ValueError(f"missing required value: {label}")
        text = str(value).strip().strip('"')
        if not text:
            raise ValueError(f"missing required value: {label}")
        return text

    @staticmethod
    def _optional_text(payload: dict[str, Any], key: str) -> str:
        """Internal helper for optional text."""
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip().strip('"')

    @staticmethod
    def _ensure_existing_path(path: Path, label: str) -> None:
        """Internal helper for ensure existing path."""
        if not path.exists():
            raise FileNotFoundError(f"{label} does not exist: {path}")

    @staticmethod
    def _ensure_existing_file(path: Path, label: str) -> None:
        """Internal helper for ensure existing file."""
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist or is not a file: {path}")

    @staticmethod
    def _exclude_regexes(payload: dict[str, Any]) -> list[str]:
        """Internal helper for exclude regexes."""
        raw = payload.get("excludeRegexes", "")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [line.strip() for line in str(raw).splitlines() if line.strip()]

    @staticmethod
    def _tree_depth(payload: dict[str, Any]) -> int | str:
        """Internal helper for tree depth."""
        raw = ConversionRunners._optional_text(payload, "treeDepth")
        if not raw or raw.lower() == "auto":
            return "auto"
        value = int(raw, 0)
        if value < 0:
            raise ValueError("tree-depth must be a non-negative integer or auto")
        return value

    @staticmethod
    def _magic(payload: dict[str, Any], key: str, default: int) -> int:
        """Internal helper for magic."""
        raw = ConversionRunners._optional_text(payload, key)
        if not raw:
            return default
        return int(raw, 0)
