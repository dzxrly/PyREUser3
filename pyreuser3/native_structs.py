"""Validate and encode fixed-width RE Engine value types.

The registry in this module is deliberately game-agnostic.  A codec is enabled only
when the active il2cpp dump proves the expected value-type layout; schema matching then
checks the original type name and byte width before binary data is decoded.
"""

from __future__ import annotations

import math
import numbers
import struct
from dataclasses import dataclass
from typing import Any

from .schema import FieldDef


class NativeStructValueError(ValueError):
    """Signal that a native structure value cannot be represented losslessly."""


@dataclass(frozen=True)
class NativeLayoutMember:
    """Describe one instance field observed in il2cpp value-type metadata."""

    name: str
    type_name: str
    offset: int


@dataclass(frozen=True)
class NativeJsonMember:
    """Describe one JSON property and its consecutive binary component count."""

    name: str
    component_count: int = 1


@dataclass(frozen=True)
class NativeStructCodec:
    """Declare one verified schema/il2cpp/binary/JSON structure mapping."""

    codec_id: str
    schema_types: tuple[str, ...]
    il2cpp_type: str
    payload_size: int
    boxed_size: int
    layout_members: tuple[NativeLayoutMember, ...]
    binary_format: str
    json_members: tuple[NativeJsonMember, ...]

    def descriptor(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible validated-layout descriptor."""

        return {
            "codec": self.codec_id,
            "il2cpp_type": self.il2cpp_type,
            "payload_size": self.payload_size,
            "boxed_size": self.boxed_size,
            "fields": [
                {
                    "name": member.name,
                    "type": member.type_name,
                    "offset": member.offset,
                }
                for member in self.layout_members
            ],
        }


NATIVE_STRUCT_CODECS: tuple[NativeStructCodec, ...] = (
    NativeStructCodec(
        codec_id="via.Int2.v1",
        schema_types=("Int2",),
        il2cpp_type="via.Int2",
        payload_size=8,
        boxed_size=0x18,
        layout_members=(
            NativeLayoutMember("x", "System.Int32", 0),
            NativeLayoutMember("y", "System.Int32", 4),
        ),
        binary_format="<ii",
        json_members=(NativeJsonMember("x"), NativeJsonMember("y")),
    ),
    NativeStructCodec(
        codec_id="via.Uint2.v1",
        schema_types=("Uint2",),
        il2cpp_type="via.Uint2",
        payload_size=8,
        boxed_size=0x18,
        layout_members=(
            NativeLayoutMember("x", "System.UInt32", 0),
            NativeLayoutMember("y", "System.UInt32", 4),
        ),
        binary_format="<II",
        json_members=(NativeJsonMember("x"), NativeJsonMember("y")),
    ),
    NativeStructCodec(
        codec_id="via.Range.v1",
        schema_types=("Range",),
        il2cpp_type="via.Range",
        payload_size=8,
        boxed_size=0x18,
        layout_members=(
            NativeLayoutMember("s", "System.Single", 0),
            NativeLayoutMember("r", "System.Single", 4),
        ),
        binary_format="<ff",
        json_members=(NativeJsonMember("s"), NativeJsonMember("r")),
    ),
    NativeStructCodec(
        codec_id="via.RangeI.v1",
        schema_types=("RangeI",),
        il2cpp_type="via.RangeI",
        payload_size=8,
        boxed_size=0x18,
        layout_members=(
            NativeLayoutMember("s", "System.Int32", 0),
            NativeLayoutMember("r", "System.Int32", 4),
        ),
        binary_format="<ii",
        json_members=(NativeJsonMember("s"), NativeJsonMember("r")),
    ),
    NativeStructCodec(
        codec_id="via.Sphere.v1",
        schema_types=("Sphere",),
        il2cpp_type="via.Sphere",
        payload_size=16,
        boxed_size=0x20,
        layout_members=(
            NativeLayoutMember("pos", "via.Float3", 0),
            NativeLayoutMember("r", "System.Single", 12),
        ),
        binary_format="<ffff",
        json_members=(NativeJsonMember("pos", 3), NativeJsonMember("r")),
    ),
)

_CODECS_BY_IL2CPP_TYPE = {
    codec.il2cpp_type: codec for codec in NATIVE_STRUCT_CODECS
}
_CODECS_BY_SCHEMA_TYPE = {
    schema_type: codec
    for codec in NATIVE_STRUCT_CODECS
    for schema_type in codec.schema_types
}


def _validate_registry() -> None:
    for codec in NATIVE_STRUCT_CODECS:
        if struct.calcsize(codec.binary_format) != codec.payload_size:
            raise RuntimeError(f"invalid native codec payload size: {codec.codec_id}")
        component_count = sum(
            member.component_count for member in codec.json_members
        )
        unpacked_count = len(
            struct.unpack(codec.binary_format, bytes(codec.payload_size))
        )
        format_codes = codec.binary_format.lstrip("@=<>!")
        if component_count != unpacked_count or len(format_codes) != component_count:
            raise RuntimeError(f"invalid native codec JSON shape: {codec.codec_id}")


_validate_registry()


def _parse_metadata_integer(value: Any) -> int | None:
    """Parse hexadecimal il2cpp metadata integers without guessing decimal strings."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def _flag_is_set(value: Any, flag: str) -> bool:
    if not isinstance(value, str):
        return False
    return flag in {item.strip() for item in value.split("|")}


def collect_validated_native_struct_layout(
    class_name: Any, obj: Any
) -> tuple[str, dict[str, Any]] | None:
    """Validate one il2cpp entry and return a canonical capability descriptor.

    Some dump generators omit type and field flag strings.  In that format, extra
    self-typed fields are accepted as static constants; all other fields must match the
    declared instance layout exactly.
    """

    if not isinstance(class_name, str) or not isinstance(obj, dict):
        return None
    codec = _CODECS_BY_IL2CPP_TYPE.get(class_name)
    if codec is None or obj.get("parent") != "System.ValueType":
        return None
    type_flags = obj.get("flags")
    if type_flags is not None and not _flag_is_set(type_flags, "SequentialLayout"):
        return None
    if _parse_metadata_integer(obj.get("size")) != codec.boxed_size:
        return None

    fields = obj.get("fields")
    if not isinstance(fields, dict):
        return None
    expected_names = {member.name for member in codec.layout_members}
    for member in codec.layout_members:
        field = fields.get(member.name)
        if not isinstance(field, dict):
            return None
        if field.get("type") != member.type_name:
            return None
        if (
            _parse_metadata_integer(field.get("offset_from_fieldptr"))
            != member.offset
        ):
            return None
        if _flag_is_set(field.get("flags"), "Static"):
            return None

    for field_name, field in fields.items():
        if field_name in expected_names:
            continue
        if not isinstance(field_name, str) or not isinstance(field, dict):
            return None
        field_flags = field.get("flags")
        if isinstance(field_flags, str):
            if not _flag_is_set(field_flags, "Static"):
                return None
        elif field.get("type") != class_name:
            return None

    return class_name, codec.descriptor()


def normalize_native_struct_layouts(raw: Any) -> dict[str, dict[str, Any]]:
    """Keep only descriptors that exactly match the local codec registry."""

    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for type_name, descriptor in raw.items():
        codec = _CODECS_BY_IL2CPP_TYPE.get(type_name)
        if codec is None:
            continue
        expected = codec.descriptor()
        if descriptor == expected:
            normalized[type_name] = expected
    return normalized


def registered_native_struct_codec(field: FieldDef) -> NativeStructCodec | None:
    """Resolve a declared codec from an exact schema type/name/size signature."""

    codec = _CODECS_BY_SCHEMA_TYPE.get(field.field_type)
    if codec is None:
        return None
    if field.original_type != codec.il2cpp_type:
        return None
    if field.size != codec.payload_size:
        return None
    return codec


def resolve_native_struct_codec(
    field: FieldDef, validated_layouts: Any
) -> NativeStructCodec | None:
    """Resolve a codec only when schema and active il2cpp metadata both agree."""

    codec = registered_native_struct_codec(field)
    if codec is None or not isinstance(validated_layouts, dict):
        return None
    if validated_layouts.get(codec.il2cpp_type) != codec.descriptor():
        return None
    return codec


def decode_native_struct(codec: NativeStructCodec, payload: bytes) -> dict[str, Any]:
    """Decode one fixed-width payload into its declared JSON object shape."""

    if len(payload) != codec.payload_size:
        raise NativeStructValueError(
            f"{codec.il2cpp_type} payload has {len(payload)} bytes, "
            f"expected {codec.payload_size}"
        )
    values = struct.unpack(codec.binary_format, payload)
    if any(isinstance(value, float) and not math.isfinite(value) for value in values):
        raise NativeStructValueError(
            f"{codec.il2cpp_type} contains a non-finite float; preserve it as raw bytes"
        )

    result: dict[str, Any] = {}
    offset = 0
    for member in codec.json_members:
        end = offset + member.component_count
        components = values[offset:end]
        result[member.name] = (
            components[0] if member.component_count == 1 else list(components)
        )
        offset = end
    return result


def encode_native_struct(codec: NativeStructCodec, value: Any) -> bytes:
    """Validate and encode one declared JSON object shape into native bytes."""

    if not isinstance(value, dict):
        raise NativeStructValueError(f"{codec.il2cpp_type} value must be an object")
    expected_keys = {member.name for member in codec.json_members}
    if set(value) != expected_keys:
        raise NativeStructValueError(
            f"{codec.il2cpp_type} value must contain exactly {sorted(expected_keys)}"
        )

    flat_values: list[int | float] = []
    for member in codec.json_members:
        member_value = value[member.name]
        if member.component_count == 1:
            components = [member_value]
        else:
            if (
                not isinstance(member_value, list)
                or len(member_value) != member.component_count
            ):
                raise NativeStructValueError(
                    f"{codec.il2cpp_type}.{member.name} must contain exactly "
                    f"{member.component_count} components"
                )
            components = member_value
        flat_values.extend(components)

    format_codes = codec.binary_format.lstrip("@=<>!")
    for index, (component, format_code) in enumerate(zip(flat_values, format_codes)):
        if isinstance(component, bool):
            raise NativeStructValueError(
                f"{codec.il2cpp_type} component {index} must be numeric, not bool"
            )
        if format_code in "bBhHiIlLqQ":
            if not isinstance(component, numbers.Integral):
                raise NativeStructValueError(
                    f"{codec.il2cpp_type} component {index} must be an integer"
                )
        elif not isinstance(component, numbers.Real) or not math.isfinite(
            float(component)
        ):
            raise NativeStructValueError(
                f"{codec.il2cpp_type} component {index} must be a finite number"
            )

    try:
        payload = struct.pack(codec.binary_format, *flat_values)
    except (OverflowError, struct.error, TypeError, ValueError) as exc:
        raise NativeStructValueError(
            f"{codec.il2cpp_type} value is outside its binary range"
        ) from exc
    if len(payload) != codec.payload_size:
        raise NativeStructValueError(f"invalid encoded size for {codec.il2cpp_type}")
    return payload
