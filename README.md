# PyREUser3

PyREUser3 is a pure Python package for converting RE Engine `.user.3` database files to JSON and packing compatible JSON back to `.user.3`.

Simplified Chinese documentation is available at [docs/README.zh-CN.md](docs/README.zh-CN.md).

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
