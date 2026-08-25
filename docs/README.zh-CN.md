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
- 无需 schema 的单文件与整批布局探测；
- `pyreuser3-web` 本地 Web 导出界面。

PyPI 包不会包含游戏资源、游戏 dump、RE_RSZ 模板、`il2cpp_dump.json`、或特定仓库脚本。调用方需要自己准备与目标游戏版本匹配的数据文件。

## 环境要求

- Python 3.9 或更高版本；
- 与目标游戏和版本匹配的 RE_RSZ schema JSON；
- 导出可读枚举标签时需要 `il2cpp_dump.json`；
- 一个或多个已解包的 `.user.3` 文件。

布局探测是例外：`pyreuser3 probe` 只检查 USR/RSZ 容器，不需要 schema 或
`il2cpp_dump.json`。

## 命令行使用

导出 `.user.3` 为 JSON：

```bash
pyreuser3 export \
  -i <输入的-user3-文件或目录> \
  -s <RE_RSZ-schema.json> \
  -o <JSON-输出目录> \
  -p <il2cpp_dump.json>
```

导出完整 repack JSON，然后封回 `.user.3`：

```bash
pyreuser3 export \
  -i <输入的-user3-文件或目录> \
  -s <RE_RSZ-schema.json> \
  -o <repack-JSON-输出目录> \
  -p <il2cpp_dump.json> \
  --json-format repack
```

```bash
pyreuser3 pack \
  -j <输入的-repack-JSON-文件或目录> \
  -s <RE_RSZ-schema.json> \
  -o <user3-输出目录> \
  -p <il2cpp_dump.json>
```

说明：

- `export` 时 `-p/--il2cpp-dump-path` 是必填项，用于生成可读枚举标签；
- `pack` 时 `-p/--il2cpp-dump-path` 是可选项，但如果 JSON 中包含枚举名称，建议传入；
- `-s/--schema-path` 必须指向具体 schema JSON 文件，不应传目录；
- `-i`、`-j` 都可以传单个文件或目录，目录会递归处理。

无需加载游戏元数据即可探测单个文件或整个目录：

```bash
pyreuser3 probe -i <输入的-user3-文件或目录>
pyreuser3 probe -i <输入的-user3-文件或目录> --strict -o layout-report.json
```

默认探测采用与 readable 导出相同的安全策略：结构损坏仍会直接失败，只有非规范对齐会记录为
警告。`--strict` 会拒绝任何布局偏差，适合整批语料验证。可选的 JSON 报告会按布局、RSZ
版本和诊断代码汇总结果。

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

Web UI 只提供 `.user.3` 导出，不提供 JSON 封包。

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

# 封包只接受完整 repack 文档；readable 导出仅供读取。
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

`REUser3Converter` 会延迟加载 schema 和 il2cpp metadata，并在该 converter 的生命周期内复用。
连续执行 readable、repack、pack 或 patch 时，不再反复扫描大型 metadata 文件。源文件的绝对
路径、大小或纳秒修改时间变化后缓存会自动失效；如果调用方以特殊方式原地替换文件，也可以强制
清理：

```python
converter.clear_metadata_cache()
```

`patch_directory()` 现在也会让整批文件复用同一个已准备好的 exporter 和 packer，不再为每个
文件重复构造。

也可以不创建 converter、不加载 schema，直接调用容器布局探测 API：

```python
from pyreuser3 import probe_usr_file, probe_usr_path

one_file = probe_usr_file("input/example.user.3")
whole_tree = probe_usr_path("input/natives", policy="strict_probe")
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

使用 `json_format="readable"` 时返回与 `export_file()` 一致的只读导出结构；使用
`json_format="repack"` 时返回可传给 `pack()` 的完整实例表结构。封回器会拒绝 readable JSON。

枚举字段会按照真实底层存储宽度输出为 `[数值] 名称`。标量位标志枚举输出为标签数组；
``ace.Bitset`1<T>`` 输出为枚举索引标签，并保留 `_MaxElement` 与 `_WordCount`，因此未知位和
填充词也可以无损封回。新的 repack 文档格式为 `re_user3_pack_v3`，它会分别记录自动探测到的
USR 外层布局、RSZ 头族和文件中的真实 RSZ 版本，并保留 resource 与 userdata 依赖表。布局
候选及其读取/回封能力状态集中声明在 `pyreuser3/usr_layouts.py`，RSZ 字段定义仍来自传入的
REFramework 兼容模板。已验证的现代头族接受通过完整结构校验的 RSZ v4+ 文件，并原样保留
版本号，不再固定为 MHWS 的版本 16。这个头族中的 offset 数值仍以 RSZ 段为基准，但 userdata
与 data 的目标位置按整个文件的绝对 16 字节边界对齐。readable 导出会接受仅对齐偏差，probe
API 则把它们报告为结构化警告；repack 导出会把同一诊断写入 `_warnings`，并通过
`_unsupported` 阻止未经验证的布局被封回。实验性的物理 H28 与 legacy RSZ v3 候选暂时只读，
获得真实样本并完成逐字节回封验证后才能启用 repack。v1 和 v2 文档仍可识别以便诊断，但由于
缺少必要的布局元数据，封回前必须从源文件重新导出为 v3。

部分现代文件会用有符号 `-1` 明确表示空 `Object` 引用；repack 会原样保留这个哨兵，同时继续
拒绝其他不存在的实例 ID。超过一百万项的定长数组会紧凑保存为 `_raw_array_count` 和
`_raw_array_hex`。这种表示不提供逐项可读性，但能够无损回封、避免展开数百万个 Python 整数，
并会在封包前校验 count 与 payload 长度是否匹配。

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
    json_format="repack",
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

## 兼容性验证

仓库内提供无需 schema 的语料测试脚本。游戏文件不会提交到仓库，请让脚本指向本地已解包的
`natives` 目录：

```bash
python tests/corpus_probe.py D:/game/natives \
  --expected-total 62768 \
  --expected-version 16 \
  --report layout-report.json
```

0.7.2 在 0.7.1 的现代 RSZ 对齐修复基础上，改为先原子化验证 repack 容器元数据再写入二进制，
并在拆解未命名 flags 组合前优先保留精确枚举成员。该版本继续提供分阶段布局探测、结构化诊断、
安全 readable 解析、仅验证布局可 repack，以及无需 schema 的 probe 命令。新的现代布局规则已用
62,768 个 MHWS `.user.3` 文件验证；其中四个 SystemSetting 样本还完成了 readable 导出、
repack 导出、逐字节一致回封和二次解析验证。

另外还验证了 Monster Hunter Stories 3 语料：42,945 个文件全部通过严格 layout 探测和
schema 驱动的 repack 导出；42,945 个文件全部能够无异常地重新构建，其中 38,548 个逐字节
一致。其余 4,397 个可以成功重建但并非逐字节一致；已观察到的原因包括非零 padding、空字符串
的另一种物理编码，因此不把它们宣称为逐字节 fixture。两个使用紧凑超大数组表示的 voxel 文件
都能逐字节一致回封，其中包括 6.55 MB 的 `dg100_Root` payload。

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
