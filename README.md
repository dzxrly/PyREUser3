<h1 align="center">PyREUser3</h1>

<p align="center">
  English | <a href="https://github.com/dzxrly/PyREUser3/blob/main/docs/README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/PyREUser3/"><img alt="PyPI Project" src="https://img.shields.io/badge/PyPI-PyREUser3-blue"></a>
  <a href="https://pypi.org/project/PyREUser3/"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/PyREUser3"></a>
  <a href="https://pepy.tech/project/PyREUser3"><img alt="Downloads" src="https://static.pepy.tech/badge/PyREUser3"></a>
  <a href="https://github.com/dzxrly/PyREUser3/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/pypi/l/PyREUser3"></a>
</p>

PyREUser3 is a pure Python package for converting RE Engine `.user.3` database files to JSON and packing compatible JSON back to `.user.3`.

Install it with:

```bash
pip install pyreuser3
```

Import it with the same normalized package name:

```python
from pyreuser3 import REUser3Converter
```

## What Is Included

- `.user.3 -> JSON` export.
- `JSON -> .user.3` packing.
- A reusable Python API through `REUser3Converter`.
- CLI commands through `pyreuser3`.
- A local `.user.3` export Web UI through `pyreuser3-web`.

This PyPI package intentionally does not include game resources, dumped game data, RE_RSZ templates, `il2cpp_dump.json`, `.msg.23` conversion tools, or repository-specific helper scripts.

## Requirements

- Python 3.9 or newer.
- A RE_RSZ schema JSON file for the target game/version.
- An `il2cpp_dump.json` file when exporting readable enum labels.
- One or more unpacked `.user.3` files.

## Command Line

Export `.user.3` files to JSON:

```bash
pyreuser3 export \
  -i <input-user3-file-or-directory> \
  -s <RE_RSZ-schema.json> \
  -o <json-output-directory> \
  -p <il2cpp_dump.json>
```

Pack JSON back to `.user.3`:

```bash
pyreuser3 pack \
  -j <input-json-file-or-directory> \
  -s <RE_RSZ-schema.json> \
  -o <user3-output-directory> \
  -p <il2cpp_dump.json>
```

The `-p/--il2cpp-dump-path` option is required for export and optional for pack. Passing it during pack is recommended when enum names need to be resolved back to numeric values.

Start the local `.user.3` export Web UI:

```bash
pyreuser3-web --port 8765
```

The Web UI only handles `.user.3` export. It does not pack files and does not provide `.msg.23` conversion.

## Python API

```python
from pyreuser3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_game.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)

converter.export_file(
    "input/OtomonData.user.3",
    "json/OtomonData.user.3.json",
)

converter.pack_file(
    "json/OtomonData.user.3.json",
    "mod/OtomonData.user.3",
)
```

Convert a `.user.3` file to an in-memory JSON-compatible Python object without writing a JSON file:

```python
readable_data = converter.user3_to_json(
    "input/OtomonData.user.3",
    json_format="readable",
)

repack_data = converter.user3_to_json(
    "input/OtomonData.user.3",
    json_format="repack",
)
```

Use `json_format="readable"` for the same shape produced by `export_file()`, or `json_format="repack"` for the full instance-table document accepted by `pack()`.

For stable patch-and-repack workflows, use `patch_file()` or `parse_pack_file()`:

```python
from pyreuser3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_game.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)

def patch(data, source_path):
    # Modify the full instance-table JSON in place.
    return None

converter.patch_file(
    "input/example.user.3",
    "output/example.user.3",
    patch,
)
```

## Build From Source

```bash
python -m pip install -U build twine
python -m build
python -m twine check dist/*
```

Upload to TestPyPI first:

```bash
python -m twine upload -r testpypi dist/*
```

Then upload the same checked distribution files to PyPI:

```bash
python -m twine upload dist/*
```

## License

MIT License.
