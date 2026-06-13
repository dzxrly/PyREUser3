<h1 align="center">PyREUser3</h1>

<p align="center">
  <a href="https://github.com/dzxrly/PyREUser3/blob/main/README.md">English</a> | 简体中文
</p>

<p align="center">
  <a href="https://pypi.org/project/PyREUser3/"><img alt="PyPI 项目" src="https://img.shields.io/badge/PyPI-PyREUser3-blue"></a>
  <a href="https://pypi.org/project/PyREUser3/"><img alt="PyPI 版本" src="https://img.shields.io/pypi/v/PyREUser3"></a>
  <a href="https://pepy.tech/project/PyREUser3"><img alt="下载量" src="https://static.pepy.tech/badge/PyREUser3"></a>
  <a href="https://github.com/dzxrly/PyREUser3/blob/main/LICENSE"><img alt="许可证" src="https://img.shields.io/pypi/l/PyREUser3"></a>
</p>

PyREUser3 是一个纯 Python 包，用于在 RE Engine 的 `.user.3` 数据库文件和 JSON 之间进行双向转换。

它的发布包名是 `PyREUser3`，安装时可以使用规范化后的名称：

```bash
pip install pyreuser3
```

安装后使用同名 Python 包导入：

```python
from pyreuser3 import REUser3Converter
```

## 功能范围

PyREUser3 当前提供：

- `.user.3 -> JSON` 导出；
- `JSON -> .user.3` 封包；
- 面向其他项目调用的 `REUser3Converter` Python API；
- `pyreuser3` 命令行工具；
- `pyreuser3-web` 本地 Web 导出界面。

PyPI 包不会包含游戏资源、游戏 dump、RE_RSZ 模板、`il2cpp_dump.json`、`.msg.23` 转换工具或特定仓库脚本。调用方需要自己准备与目标游戏版本匹配的数据文件。

## 环境要求

- Python 3.9 或更高版本；
- 与目标游戏和版本匹配的 RE_RSZ schema JSON；
- 导出可读枚举标签时需要 `il2cpp_dump.json`；
- 一个或多个已解包的 `.user.3` 文件。

## 命令行使用

导出 `.user.3` 为 JSON：

```bash
pyreuser3 export \
  -i <输入的-user3-文件或目录> \
  -s <RE_RSZ-schema.json> \
  -o <JSON-输出目录> \
  -p <il2cpp_dump.json>
```

将 JSON 封回 `.user.3`：

```bash
pyreuser3 pack \
  -j <输入的-JSON-文件或目录> \
  -s <RE_RSZ-schema.json> \
  -o <user3-输出目录> \
  -p <il2cpp_dump.json>
```

说明：

- `export` 时 `-p/--il2cpp-dump-path` 是必填项，用于生成可读枚举标签；
- `pack` 时 `-p/--il2cpp-dump-path` 是可选项，但如果 JSON 中包含枚举名称，建议传入；
- `-s/--schema-path` 必须指向具体 schema JSON 文件，不应传目录；
- `-i`、`-j` 都可以传单个文件或目录，目录会递归处理。

可用 `--user-magic` 和 `--rsz-magic` 覆盖默认 magic，例如：

```bash
pyreuser3 export \
  -i input \
  -s schema.json \
  -o output \
  -p il2cpp_dump.json \
  --user-magic 0x00525355 \
  --rsz-magic 0x005A5352
```

## 本地 Web 界面

启动本地 `.user.3` 导出 Web UI：

```bash
pyreuser3-web --port 8765
```

默认地址：

```text
http://127.0.0.1:8765/
```

Web UI 只提供 `.user.3` 导出，不提供 JSON 封包，也不提供 `.msg.23` 转换。

## Python API

基本导出和封包：

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

不写入 JSON 文件，直接把 `.user.3` 转成内存中的 JSON 兼容 Python 对象：

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

使用 `json_format="readable"` 时返回与 `export_file()` 一致的可读导出结构；使用 `json_format="repack"` 时返回可传给 `pack()` 的完整实例表结构。

批量处理目录：

```python
from pyreuser3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_game.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)

export_result = converter.export_directory(
    "D:/game/unpacked",
    "D:/game/json",
)

pack_result = converter.pack_directory(
    "D:/game/json",
    "D:/game/mod",
)

print(export_result)
print(pack_result)
```

修改后稳定封回时，建议使用 `patch_file()` 或 `parse_pack_file()`。这类流程使用完整实例表 JSON，能减少引用关系丢失的风险：

```python
from pyreuser3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_game.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)

def patch(data, source_path):
    # data 是完整实例表结构。可以原地修改，也可以返回新的 JSON 树。
    return None

converter.patch_file(
    "input/example.user.3",
    "output/example.user.3",
    patch,
)
```

## 常见注意事项

- schema JSON、`il2cpp_dump.json` 和 `.user.3` 文件应来自同一个游戏版本；
- PyREUser3 不负责生成 RE_RSZ 模板，也不负责解包游戏 pak；
- 不要在公开 issue 中上传受版权保护的原始游戏文件；
- 如果遇到转换失败，请保留完整命令、Python 版本、PyREUser3 版本和异常堆栈。

## 从源码构建

安装构建工具：

```bash
python -m pip install -U build twine
```

生成源码包和 wheel：

```bash
python -m build
```

检查发布文件：

```bash
python -m twine check dist/*
```

先上传到 TestPyPI：

```bash
python -m twine upload -r testpypi dist/*
```

确认无误后上传到 PyPI：

```bash
python -m twine upload dist/*
```

## 许可证

MIT License。
