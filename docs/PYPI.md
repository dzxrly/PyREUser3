# PyREUser3

PyREUser3 is a pure Python package for converting RE Engine `.user.3` database files to JSON and packing compatible JSON back to `.user.3`.

## Installation

```bash
pip install pyreuser3
```

## What Is Included

- `.user.3 -> JSON` export.
- `JSON -> .user.3` packing.
- A reusable Python API through `REUser3Converter`.
- CLI commands through `pyreuser3`.
- A local `.user.3` export Web UI through `pyreuser3-web`.

The published package intentionally does not include game resources, dumped game data, RE_RSZ templates,
`il2cpp_dump.json`, or repository-specific helper scripts. You need to provide data files that match the target game and
version.

## Requirements

- Python 3.9 or newer.
- A RE_RSZ schema JSON file for the target game/version.
- An `il2cpp_dump.json` file when exporting readable enum labels.
- One or more unpacked `.user.3` files.

## Usage

Usage details may change as the package evolves. For the latest command-line and Python API examples, read the GitHub README:

https://github.com/dzxrly/PyREUser3#readme

## Links

- Homepage: https://github.com/dzxrly/PyREUser3
- Issues: https://github.com/dzxrly/PyREUser3/issues
- License: MIT License
