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
- Schema-free layout probing through `pyreuser3 probe` and the public probe API.
- A local `.user.3` export Web UI through `pyreuser3-web`.
- Automatic separation of the USR outer layout from the embedded RSZ header family;
  modern RSZ v4+ files preserve their original numeric version during repack.

The published package intentionally does not include game resources, dumped game data, RE_RSZ templates,
`il2cpp_dump.json`, or repository-specific helper scripts. You need to provide data files that match the target game and
version.

Verified H30/modern layouts support repacking. Experimental physical H28 and legacy
RSZ v3 layouts are readable for analysis but intentionally blocked from repacking
until real fixtures provide byte-for-byte validation.

Version 0.7.1 fixes the 0.7.0 modern RSZ alignment regression. Modern userdata and
data targets use absolute 16-byte file alignment even though their stored offsets
remain RSZ-relative. Readable parsing accepts alignment-only deviations without
hiding structural corruption, while the probe API reports them explicitly. Repack
output blocks layouts carrying unverified diagnostics. The strict schema-free
probe can validate large local corpora.

Repeated operations on one `REUser3Converter` reuse schema and il2cpp metadata,
with automatic file-signature invalidation and an explicit
`clear_metadata_cache()` escape hatch. Batch patching reuses one exporter and
packer. Signed `-1` null object references and very large fixed-width arrays are
preserved losslessly; large arrays use a compact raw payload instead of millions
of Python scalar objects.

## Requirements

- Python 3.9 or newer.
- A RE_RSZ schema JSON file for the target game/version.
- An `il2cpp_dump.json` file when exporting readable enum labels.
- One or more unpacked `.user.3` files.

`pyreuser3 probe` does not require a schema or `il2cpp_dump.json`.

## Usage

Usage details may change as the package evolves. For the latest command-line and Python API examples, read the GitHub README:

https://github.com/dzxrly/PyREUser3#readme

## Links

- Homepage: https://github.com/dzxrly/PyREUser3
- Issues: https://github.com/dzxrly/PyREUser3/issues
- License: MIT License
