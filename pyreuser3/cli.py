"""Command line interface for the PyREUser3 package."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from typing import Sequence

from .core import RSZ_MAGIC, USR_MAGIC
from .export import User3Exporter
from .pack import User3Packer
from .rich_ui import get_console


def parse_int_arg(value: str) -> int:
    """Parse decimal or 0x-prefixed integer command line values."""
    return int(value, 0)


def package_version() -> str:
    """Return installed package version, with a source-tree fallback."""
    try:
        return version("PyREUser3")
    except PackageNotFoundError:
        return "0.1.0"


def normalize_tree_depth(value: str) -> int | str:
    """Normalize tree depth argument to an integer or the string 'auto'."""
    text = value.strip().lower()
    if text == "auto":
        return "auto"
    depth = int(text)
    if depth < 0:
        raise argparse.ArgumentTypeError("tree depth must be non-negative or 'auto'")
    return depth


def add_magic_args(parser: argparse.ArgumentParser) -> None:
    """Add common .user.3 and RSZ magic options to a subparser."""
    parser.add_argument(
        "--user-magic",
        type=parse_int_arg,
        default=USR_MAGIC,
        help=f"USR file magic as decimal or hex (default: 0x{USR_MAGIC:08x}).",
    )
    parser.add_argument(
        "--rsz-magic",
        type=parse_int_arg,
        default=RSZ_MAGIC,
        help=f"RSZ block magic as decimal or hex (default: 0x{RSZ_MAGIC:08x}).",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="pyreuser3",
        description="Convert RE Engine .user.3 files to JSON and pack them back.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {package_version()}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser(
        "export",
        help="Export .user.3 files to JSON.",
    )
    export_parser.add_argument(
        "--input-dir",
        "-i",
        required=True,
        help="Root directory or single .user.3 file to export.",
    )
    export_parser.add_argument(
        "--schema-path",
        "--schema-dir",
        "-s",
        dest="schema_path",
        required=True,
        help="Explicit RE_RSZ schema JSON file path.",
    )
    export_parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Root output directory for exported JSON files.",
    )
    export_parser.add_argument(
        "--tree-depth",
        "-d",
        type=normalize_tree_depth,
        default="auto",
        help="Tree depth as a non-negative integer or 'auto' (default: auto).",
    )
    export_parser.add_argument(
        "--exclude-regex",
        "-x",
        action="append",
        default=[],
        help="Regex to exclude matching relative file paths. Can be used multiple times.",
    )
    export_parser.add_argument(
        "--il2cpp-dump-path",
        "-p",
        required=True,
        help="Path to il2cpp_dump.json, used to generate enum labels.",
    )
    add_magic_args(export_parser)
    export_parser.set_defaults(func=run_export)

    pack_parser = subparsers.add_parser(
        "pack",
        help="Pack .user.3 JSON files back to .user.3.",
    )
    pack_parser.add_argument(
        "--input-json",
        "-j",
        required=True,
        help="JSON file or root directory that contains .user.3.json files.",
    )
    pack_parser.add_argument(
        "--schema-path",
        "--schema-dir",
        "-s",
        dest="schema_path",
        required=True,
        help="Explicit RE_RSZ schema JSON file path.",
    )
    pack_parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Root output directory for packed .user.3 files.",
    )
    pack_parser.add_argument(
        "--il2cpp-dump-path",
        "-p",
        default="",
        help="Optional il2cpp_dump.json path, used for enum name lookup.",
    )
    pack_parser.add_argument(
        "--exclude-regex",
        "-x",
        action="append",
        default=[],
        help="Regex to exclude matching relative JSON paths. Can be used multiple times.",
    )
    add_magic_args(pack_parser)
    pack_parser.set_defaults(func=run_pack)

    return parser


def run_export(args: argparse.Namespace) -> int:
    """Run the export subcommand."""
    console = get_console()
    console.log("Exporting .user.3 files to JSON...")
    exporter = User3Exporter(
        user3_root=args.input_dir,
        schema_dir=args.schema_path,
        output_root=args.output_dir,
        tree_depth=args.tree_depth,
        exclude_regexes=args.exclude_regex,
        il2cpp_dump_path=args.il2cpp_dump_path,
        user_magic=args.user_magic,
        rsz_magic=args.rsz_magic,
    )
    result = exporter.run()
    console.log("Export complete:", json.dumps(result, ensure_ascii=False))
    return 1 if result.get("failed", 0) else 0


def run_pack(args: argparse.Namespace) -> int:
    """Run the pack subcommand."""
    console = get_console()
    console.log("Packing JSON files to .user.3...")
    packer = User3Packer(
        schema_dir=args.schema_path,
        il2cpp_dump_path=args.il2cpp_dump_path or None,
        output_root=args.output_dir,
        user_magic=args.user_magic,
        rsz_magic=args.rsz_magic,
    )
    result = packer.pack_directory(
        json_root=args.input_json,
        output_root=args.output_dir,
        exclude_regexes=args.exclude_regex,
    )
    console.log("Pack complete:", json.dumps(result, ensure_ascii=False))
    return 1 if result.get("failed", 0) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point used by the pyreuser3 console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
