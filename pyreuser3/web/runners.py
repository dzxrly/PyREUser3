"""Validate Web form payloads and bridge them to User3Exporter calls.

The runner requires absolute user-selected paths, parses numeric form fields, forwards
progress messages to the job log, and returns simple result dictionaries for the
frontend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..core import RSZ_MAGIC, USR_MAGIC

# Log callbacks append one human-readable line to the Web job log.
LogFn = Callable[[str], None]


class ConversionRunners:
    """Validate Web UI form payloads and execute conversion tasks through the core exporter.
    """

    def __init__(self, root_dir: str | Path) -> None:
        """Initialize ConversionRunners with validated configuration and state.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            root_dir (str | Path): Compatibility root directory for Web settings.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        # Resolve and validate paths at the boundary so later code never guesses
        # relative to a surprising working directory.
        self.root_dir = Path(root_dir).expanduser().resolve()

    def run_export(self, payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
        """Run the CLI export subcommand.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.
            log (LogFn): Callback used to append progress messages.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.
        """
        # Resolve and validate paths at the boundary so later code never guesses
        # relative to a surprising working directory.
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

        # root_dir is retained only for compatibility; submitted form paths must be absolute picker selections.
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

        # Keep the local HTTP and frontend behavior explicit because the Web UI runs
        # without a separate framework.
        return {"user3": user3_result, "outputDir": str(output_dir)}

    def _path_value(self, payload: dict[str, Any], key: str, label: str) -> Path:
        """Read and validate an absolute filesystem path from a Web form payload.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.
            key (str): Payload key, metadata key, or enum key being read.
            label (str): Human-readable field name used in validation errors and logs.

        Returns:
            Path: Concrete filesystem path returned after the read, write, or resolution step finishes.

        Raises:
            ValueError: The caller supplied a missing, malformed, or out-of-range value.
        """
        path = Path(self._text_value(payload, key, label)).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{label} must be selected as an absolute path")
        return path

    @staticmethod
    def _text_value(payload: dict[str, Any], key: str, label: str) -> str:
        """Read a required non-empty string from a Web form payload.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.
            key (str): Payload key, metadata key, or enum key being read.
            label (str): Human-readable field name used in validation errors and logs.

        Returns:
            str: Normalized or formatted text.

        Raises:
            ValueError: The caller supplied a missing, malformed, or out-of-range value.
        """
        value = payload.get(key)
        if value is None:
            raise ValueError(f"missing required value: {label}")
        text = str(value).strip().strip('"')
        if not text:
            raise ValueError(f"missing required value: {label}")
        return text

    @staticmethod
    def _optional_text(payload: dict[str, Any], key: str) -> str:
        """Read an optional string from a Web form payload and normalize blanks to None.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.
            key (str): Payload key, metadata key, or enum key being read.

        Returns:
            str: Normalized or formatted text.
        """
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip().strip('"')

    @staticmethod
    def _ensure_existing_path(path: Path, label: str) -> None:
        """Ensure existing path.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            path (Path): Filesystem path to validate or use.
            label (str): Human-readable field name used in validation errors and logs.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            FileNotFoundError: A required file or directory was missing.
        """
        if not path.exists():
            raise FileNotFoundError(f"{label} does not exist: {path}")

    @staticmethod
    def _ensure_existing_file(path: Path, label: str) -> None:
        """Ensure existing file.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            path (Path): Filesystem path to validate or use.
            label (str): Human-readable field name used in validation errors and logs.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            FileNotFoundError: A required file or directory was missing.
        """
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist or is not a file: {path}")

    @staticmethod
    def _exclude_regexes(payload: dict[str, Any]) -> list[str]:
        """Split newline-separated exclusion patterns into a clean regex list.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.

        Returns:
            list[str]: Normalized string candidates or exclusion patterns.
        """
        raw = payload.get("excludeRegexes", "")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [line.strip() for line in str(raw).splitlines() if line.strip()]

    @staticmethod
    def _tree_depth(payload: dict[str, Any]) -> int | str:
        """Parse the Web form tree-depth field as a non-negative integer or auto mode.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.

        Returns:
            int | str: Parsed integer value or the literal auto mode.

        Raises:
            ValueError: The caller supplied a missing, malformed, or out-of-range value.
        """
        raw = ConversionRunners._optional_text(payload, "treeDepth")
        if not raw or raw.lower() == "auto":
            return "auto"
        value = int(raw, 0)
        if value < 0:
            raise ValueError("tree-depth must be a non-negative integer or auto")
        return value

    @staticmethod
    def _magic(payload: dict[str, Any], key: str, default: int) -> int:
        """Parse an optional decimal or hexadecimal magic value from the Web form.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            payload (dict[str, Any]): JSON request body or Web form payload.
            key (str): Payload key, metadata key, or enum key being read.
            default (int): Fallback value used when the caller omits an optional setting.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        raw = ConversionRunners._optional_text(payload, key)
        if not raw:
            return default
        return int(raw, 0)
