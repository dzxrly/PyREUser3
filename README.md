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

This PyPI package intentionally does not include game resources, dumped game data, RE_RSZ templates, `il2cpp_dump.json`,
or repository-specific helper scripts.

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

Export full repack JSON, then pack it back to `.user.3`:

```bash
pyreuser3 export \
  -i <input-user3-file-or-directory> \
  -s <RE_RSZ-schema.json> \
  -o <repack-json-output-directory> \
  -p <il2cpp_dump.json> \
  --json-format repack
```

```bash
pyreuser3 pack \
  -j <input-repack-json-file-or-directory> \
  -s <RE_RSZ-schema.json> \
  -o <user3-output-directory> \
  -p <il2cpp_dump.json>
```

The `-p/--il2cpp-dump-path` option is required for export and optional for pack. Passing it during pack is recommended when enum names need to be resolved back to numeric values.

Start the local `.user.3` export Web UI:

```bash
pyreuser3-web --port 8765
```

The Web UI only handles `.user.3` export. It does not pack files.

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

# Packing only accepts the full repack document. Readable exports are read-only.
converter.export_file(
    "input/OtomonData.user.3",
    "json/OtomonData.user.3.pack.json",
    json_format="repack",
)
converter.pack_file(
    "json/OtomonData.user.3.pack.json",
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

Use `json_format="readable"` for the same shape produced by `export_file()`. This
shape is read-only. Use `json_format="repack"` for the full document accepted by
`pack()`; the packer rejects readable JSON.

Enum fields are rendered as `[numeric] Name` labels using the enum's actual storage
width. Scalar flag enums are rendered as arrays of labels. ``ace.Bitset`1<T>`` values are
rendered as enum-index labels together with `_MaxElement` and `_WordCount`, so unknown
bits and padded word arrays remain reversible. Repack exports use
`re_user3_pack_v3`, which records the independently detected USR outer layout, RSZ
header family, and numeric RSZ version while preserving resource and userdata
dependency tables. Layout candidates and their read/repack capability status are
declared in `pyreuser3/usr_layouts.py`; RSZ field definitions still come from the
supplied REFramework-compatible schema. The verified modern header family accepts
structurally valid RSZ v4+ files and preserves their original version instead of
forcing MHWS version 16. Experimental physical H28 and legacy RSZ v3 candidates are
read-only until real fixtures validate byte-for-byte repacking. V1 and v2 documents
are recognized for diagnostics but must be re-exported as v3 before packing because
they do not record the required layout metadata.

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
