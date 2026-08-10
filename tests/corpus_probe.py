"""Run schema-free layout regression checks against a local .user.3 corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Direct execution puts tests/ ahead of the repository root.  Pin imports to the
# source tree so an older installed wheel cannot silently invalidate the result.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyreuser3.usr_container import probe_usr_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="File or directory containing .user.3 files.")
    parser.add_argument("--expected-total", type=int)
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--report", default="")
    parser.add_argument("--include-successes", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = probe_usr_path(
        args.root,
        policy="strict_probe",
        include_successes=args.include_successes,
    )
    failures: list[str] = []
    if args.expected_total is not None and result["total"] != args.expected_total:
        failures.append(
            f"expected {args.expected_total} files, found {result['total']}"
        )
    if result["failed"]:
        failures.append(f"{result['failed']} file(s) failed strict layout validation")
    if args.expected_version is not None:
        observed = result["rsz_versions"]
        expected = {str(args.expected_version): result["total"]}
        if observed != expected:
            failures.append(
                f"expected only RSZ version {args.expected_version}, found {observed}"
            )
    result["acceptance_failures"] = failures
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
