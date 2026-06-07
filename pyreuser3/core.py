"""`.user.3` 解析与封包共享的基础设施。

这里放置不依赖具体导出器/封包器的通用能力：magic 默认值、二进制读取、
字段与类型定义、RE_RSZ 模板加载、字符串/GUID 规范化等。
"""

from __future__ import annotations

import re
import struct
import uuid
from pathlib import Path
from typing import Any

# `.user.3` 文件最外层 USR 头使用的默认 magic（小端 "USR\0"）。
USR_MAGIC = 5395285
# 内嵌 RSZ 数据块使用的默认 magic（小端 "RSZ\0"）。
RSZ_MAGIC = 5919570
# 完整实例表封包 JSON 的格式标识，用于识别可稳定回封的文档。
PACK_JSON_FORMAT = "re_user3_pack_v1"
# 匹配不含分隔符的 32 位十六进制字符串（用于识别 GUID 文本）。
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
# REFramework dump 中枚举类型里需要忽略的占位字段名。
ENUM_UNUSED_KEY = "value__"


class ParseError(RuntimeError):
    """解析或封包过程中发现二进制结构不符合预期时抛出的异常。

    继承自 :class:`RuntimeError`，用于把“数据格式不对”这类可预期的错误
    与程序自身的逻辑错误区分开，便于上层批处理捕获并单独统计失败文件。
    """

    pass


def align(value: int, alignment: int) -> int:
    """把整数偏移向上对齐到指定边界。

    参数：
        value (int): 当前偏移。
        alignment (int): 对齐粒度；小于等于 1 时不做处理。

    返回：
        int: 对齐后的偏移（大于等于 ``value`` 的最小满足边界的值）。
    """
    if alignment <= 1:
        return value
    # 经典的二进制向上取整：先加 (alignment-1)，再用位与清除低位。
    return (value + (alignment - 1)) & ~(alignment - 1)


def format_guid_text_from_hex32(hex32: str) -> str:
    """把 32 位十六进制文本格式化为标准 GUID 文本。

    参数：
        hex32 (str): 不带分隔符的 32 位十六进制字符串。

    返回：
        str: 形如 ``xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`` 的 GUID 文本。
    """
    h = hex32.lower()
    # 按 8-4-4-4-12 的标准分组插入连字符。
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def normalize_guid_candidate_text(text: str) -> str:
    """在字符串看起来像 GUID 时进行规范化。

    参数：
        text (str): 原始字符串，可能包含 ``{}`` 包裹或 ``-`` 分隔符。

    返回：
        str: 可识别为 GUID 时返回标准 GUID 文本，否则原样返回输入。
    """
    # 去掉首尾空白与花括号，再剥离连字符，得到纯十六进制候选。
    stripped = text.strip().strip("{}")
    compact = stripped.replace("-", "")
    if HEX32_RE.fullmatch(compact):
        return format_guid_text_from_hex32(compact)
    return text


def resolve_schema_path(schema_path_or_dir: str | Path) -> Path:
    """校验并返回用户显式提供的 RE_RSZ 模板文件路径。

    新逻辑要求依赖文件全部显式传入，因此这里故意拒绝目录路径，
    避免在多个游戏模板共存时自动匹配到错误文件。

    参数：
        schema_path_or_dir (str | Path): 期望指向具体模板 JSON 文件的路径。

    返回：
        Path: 校验通过的模板文件路径。

    异常：
        FileNotFoundError: 当路径是目录或不存在时抛出。
    """
    path = Path(schema_path_or_dir)
    if path.is_file():
        return path
    if path.is_dir():
        raise FileNotFoundError(
            f"schema must be an explicit RE RSZ json file, not a directory: {path}"
        )
    raise FileNotFoundError(f"schema file not found: {path}")


class BinaryReader:
    """带边界检查的小端二进制读取器。

    封装一个只读字节缓冲区和读取游标，提供各种定宽整数/浮点数以及
    字符串的读取方法，并在越界时抛出 :class:`ParseError`，避免错误模板
    导致越界访问破坏后续解析。
    """

    def __init__(self, data: bytes):
        """初始化读取器。

        参数：
            data (bytes): 源字节缓冲区，读取过程中不会被修改。
        """
        self.data = data
        # pos 是相对缓冲区起点的绝对读取游标，初始指向开头。
        self.pos = 0

    @property
    def size(self) -> int:
        """缓冲区总长度。

        返回：
            int: 源字节缓冲区的字节数。
        """

        return len(self.data)

    def tell(self) -> int:
        """返回当前读取游标。

        返回：
            int: 当前相对缓冲区起点的绝对偏移。
        """

        return self.pos

    def seek(self, pos: int) -> None:
        """把游标移动到绝对偏移。

        参数：
            pos (int): 目标绝对偏移，必须落在 ``[0, size]`` 区间内。

        返回：
            None: 仅更新内部游标。

        异常：
            ParseError: 当目标偏移越界时抛出。
        """
        if pos < 0 or pos > self.size:
            raise ParseError(f"seek out of range: {pos}")
        self.pos = pos

    def read(self, n: int) -> bytes:
        """读取指定长度的字节并推进游标。

        参数：
            n (int): 要读取的字节数。

        返回：
            bytes: 读取出的字节序列，长度为 ``n``。

        异常：
            ParseError: 当剩余字节不足 ``n`` 时抛出。
        """
        end = self.pos + n
        if end > self.size:
            raise ParseError(f"read out of range: {self.pos}+{n}")
        out = self.data[self.pos : end]
        self.pos = end
        return out

    def read_struct(self, fmt: str) -> Any:
        """按 ``struct`` 格式读取并解包一个值。

        参数：
            fmt (str): :func:`struct.unpack` 使用的格式字符串，应只描述单个值。

        返回：
            Any: 解包后的单个值，具体类型取决于 ``fmt``。
        """
        size = struct.calcsize(fmt)
        raw = self.read(size)
        return struct.unpack(fmt, raw)[0]

    def read_u8(self) -> int:
        """读取一个无符号 8 位整数（1 字节）。

        返回：
            int: 取值范围 0-255 的无符号整数。
        """
        return self.read_struct("<B")

    def read_s8(self) -> int:
        """读取一个有符号 8 位整数（1 字节）。

        返回：
            int: 取值范围 -128~127 的有符号整数。
        """
        return self.read_struct("<b")

    def read_u16(self) -> int:
        """读取一个无符号 16 位整数（2 字节，小端）。

        返回：
            int: 取值范围 0-65535 的无符号整数。
        """
        return self.read_struct("<H")

    def read_s16(self) -> int:
        """读取一个有符号 16 位整数（2 字节，小端）。

        返回：
            int: 取值范围 -32768~32767 的有符号整数。
        """
        return self.read_struct("<h")

    def read_u32(self) -> int:
        """读取一个无符号 32 位整数（4 字节，小端）。

        返回：
            int: 无符号 32 位整数。
        """
        return self.read_struct("<I")

    def read_s32(self) -> int:
        """读取一个有符号 32 位整数（4 字节，小端）。

        返回：
            int: 有符号 32 位整数。
        """
        return self.read_struct("<i")

    def read_u64(self) -> int:
        """读取一个无符号 64 位整数（8 字节，小端）。

        返回：
            int: 无符号 64 位整数。
        """
        return self.read_struct("<Q")

    def read_s64(self) -> int:
        """读取一个有符号 64 位整数（8 字节，小端）。

        返回：
            int: 有符号 64 位整数。
        """
        return self.read_struct("<q")

    def read_f32(self) -> float:
        """读取一个 32 位单精度浮点数（4 字节，小端）。

        返回：
            float: 解析出的单精度浮点数。
        """
        return self.read_struct("<f")

    def read_f64(self) -> float:
        """读取一个 64 位双精度浮点数（8 字节，小端）。

        返回：
            float: 解析出的双精度浮点数。
        """
        return self.read_struct("<d")

    def read_wstring_null(self, offset: int) -> str:
        """从绝对偏移读取以空字符结尾的 UTF-16LE 字符串。

        与游标无关：本方法直接按给定偏移读取，不改变 ``self.pos``，
        适合解析头部路径表这类“偏移指向别处”的字符串。

        参数：
            offset (int): 字符串起始的绝对偏移。

        返回：
            str: 解码并规范化后的字符串；偏移越界时返回空字符串。
        """
        if offset < 0 or offset >= self.size:
            return ""
        out: list[int] = []
        i = offset
        # RE Engine 路径表常以 UTF-16LE 存储，并由 0 结束。
        while i + 1 < self.size:
            ch = struct.unpack_from("<H", self.data, i)[0]
            i += 2
            if ch == 0:
                break
            out.append(ch)
        return normalize_guid_candidate_text("".join(chr(c) for c in out))


def read_len_utf16(reader: BinaryReader) -> str:
    """读取带 4 字节长度前缀的 UTF-16LE 字符串。

    参数：
        reader (BinaryReader): 二进制读取器，会从其当前游标处读取。

    返回：
        str: 解码并去掉结尾空字符、规范化后的字符串；长度异常时返回空字符串。
    """
    # 字符串前的长度字段按 4 字节对齐。
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining_chars = (reader.size - reader.tell()) // 2
    # 长度异常时返回空字符串，而不是继续越界读取破坏后续解析。
    if length > remaining_chars or length > 2_000_000:
        return ""
    raw = reader.read(length * 2)
    decoded = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_len_c8(reader: BinaryReader) -> str:
    """读取带 4 字节长度前缀的 UTF-8/C8 字符串。

    参数：
        reader (BinaryReader): 二进制读取器，会从其当前游标处读取。

    返回：
        str: 解码并去掉结尾空字符、规范化后的字符串；长度异常时返回空字符串。
    """
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining = reader.size - reader.tell()
    if length > remaining or length > 2_000_000:
        return ""
    raw = reader.read(length)
    decoded = raw.decode("utf-8", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_guid_like(reader: BinaryReader) -> str:
    """读取 16 字节 GUID 数据并规范化为标准文本。

    参数：
        reader (BinaryReader): 二进制读取器，会从其当前游标处读取 16 字节。

    返回：
        str: 标准 GUID 文本；无法按 UUID 解析时退回十六进制格式化结果。
    """
    raw = reader.read(16)
    try:
        # RE Engine 的 GUID 以小端字节序存储，使用 bytes_le 还原。
        return str(uuid.UUID(bytes_le=raw))
    except Exception:
        return format_guid_text_from_hex32(raw.hex())
