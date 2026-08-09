"""Serialize planned RSZ instances into the binary .user.3 format.

The writer handles USR and RSZ headers, object and instance tables, field alignment,
strings, arrays, structs, enum values, and raw byte preservation.
"""

from __future__ import annotations

import uuid
from typing import Any

from .models import (
    BinaryWriter,
    ExternalUserdataSpec,
    InstanceRef,
    InstanceSpec,
    PackError,
    StructValue,
)
from ..core import align, enum_storage_type_from_size
from ..enum_codec import ENUM_LABEL_RE
from ..schema import FieldDef
from ..usr_layouts import (
    DEFAULT_RSZ_HEADER_LAYOUT_ID,
    DEFAULT_USR_LAYOUT_ID,
    get_rsz_header_layout,
    get_usr_layout,
)

class PackerWriterMixin:
    """Serialize planned instances, tables, headers, and field values into the binary .user.3
    layout.
    """

    def _build_binary(self, root_ids: list[int]) -> bytes:
        """Build binary.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            root_ids (list[int]): Collection of identifiers used for validation.

        Returns:
            bytes: Encoded binary data ready to write to disk.
        """
        layout = getattr(self, "usr_layout", None)
        if layout is None:
            layout = get_usr_layout(DEFAULT_USR_LAYOUT_ID)
        if layout is None:
            raise PackError(f"default USR layout is not registered: {DEFAULT_USR_LAYOUT_ID}")
        rsz_layout = getattr(self, "rsz_header_layout", None)
        if rsz_layout is None:
            rsz_layout = get_rsz_header_layout(DEFAULT_RSZ_HEADER_LAYOUT_ID)
        if rsz_layout is None:
            raise PackError(
                "default RSZ header layout is not registered: "
                f"{DEFAULT_RSZ_HEADER_LAYOUT_ID}"
            )
        if not layout.repack_supported:
            raise PackError(f"USR layout {layout.identifier} is read-only")
        if not rsz_layout.repack_supported:
            raise PackError(f"RSZ header layout {rsz_layout.identifier} is read-only")
        usr_resources = list(getattr(self, "usr_resources", []))
        usr_userdata = list(getattr(self, "usr_userdata", []))
        rsz_userdata = list(getattr(self, "rsz_userdata", []))
        raw_rsz_version = getattr(self, "rsz_version", None)
        if not isinstance(raw_rsz_version, int):
            raise PackError("RSZ version must come from repack layout metadata")
        rsz_version = raw_rsz_version
        if not rsz_layout.supports_version(rsz_version):
            raise PackError(
                f"RSZ version {rsz_version} is not supported by header layout "
                f"{rsz_layout.identifier}"
            )
        rsz_reserved = int(getattr(self, "rsz_reserved", 0))
        header_padding = bytes(
            getattr(
                self,
                "usr_header_padding",
                b"\x00" * layout.header_padding_size,
            )
        )
        if len(header_padding) != layout.header_padding_size:
            raise PackError(
                f"layout {layout.identifier} requires {layout.header_padding_size} "
                f"header padding bytes, got {len(header_padding)}"
            )

        data_writer = BinaryWriter()
        for spec in self.instances[1:]:
            if spec is None:
                raise PackError("instance table contains an unexpected empty slot")
            if isinstance(spec, ExternalUserdataSpec):
                continue
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            self._write_instance(data_writer, spec)

        writer = BinaryWriter()
        writer.write(b"\x00" * layout.semantic_header_size)
        writer.write(header_padding)
        writer.pad_to(layout.header_size)

        writer.align(layout.table_alignment)
        resource_info_tbl = writer.tell()
        resource_entry_offsets: list[int] = []
        for _item in usr_resources:
            resource_entry_offsets.append(writer.tell())
            writer.write(b"\x00" * layout.resource_entry_size)

        writer.align(layout.table_alignment)
        userdata_info_tbl = writer.tell()
        usr_userdata_entry_offsets: list[int] = []
        for _item in usr_userdata:
            usr_userdata_entry_offsets.append(writer.tell())
            writer.write(b"\x00" * layout.userdata_entry_size)

        resource_path_offsets: list[int] = []
        for item in usr_resources:
            resource_path_offsets.append(writer.tell())
            self._write_usr_path(writer, item.path, layout.path_encoding)
        usr_userdata_path_offsets: list[int] = []
        for item in usr_userdata:
            usr_userdata_path_offsets.append(writer.tell())
            self._write_usr_path(writer, item.path, layout.path_encoding)

        for entry_offset, item, path_offset in zip(
            resource_entry_offsets, usr_resources, resource_path_offsets
        ):
            self._patch_named_struct(
                writer,
                entry_offset,
                layout.resource_entry_struct,
                layout.resource_entry_fields,
                {"path_offset": path_offset, "reserved": item.reserved},
            )
        for entry_offset, item, path_offset in zip(
            usr_userdata_entry_offsets, usr_userdata, usr_userdata_path_offsets
        ):
            self._patch_named_struct(
                writer,
                entry_offset,
                layout.userdata_entry_struct,
                layout.userdata_entry_fields,
                {
                    "class_hash": item.class_hash,
                    "crc": item.crc,
                    "path_offset": path_offset,
                },
            )

        rsz_start = writer.tell()
        rsz_header_offset = writer.tell()
        writer.write(b"\x00" * rsz_layout.header_size)
        for root_id in root_ids:
            writer.write_struct("<i", root_id)
        instance_offset = writer.tell() - rsz_start

        null_entry_offset = writer.tell()
        writer.write(b"\x00" * rsz_layout.instance_entry_size)
        self._patch_named_struct(
            writer,
            null_entry_offset,
            rsz_layout.instance_entry_struct,
            rsz_layout.instance_entry_fields,
            {"type_hash": 0, "crc": 0, "reserved": 0},
        )
        for spec in self.instances[1:]:
            if spec is None:
                raise PackError("instance table contains an unexpected empty slot")
            crc = spec.crc if isinstance(spec, ExternalUserdataSpec) else spec.class_def.crc
            entry_offset = writer.tell()
            writer.write(b"\x00" * rsz_layout.instance_entry_size)
            self._patch_named_struct(
                writer,
                entry_offset,
                rsz_layout.instance_entry_struct,
                rsz_layout.instance_entry_fields,
                {"type_hash": spec.class_hash, "crc": crc, "reserved": 0},
            )

        if rsz_userdata:
            self._align_from_base(
                writer,
                rsz_layout.rsz_userdata_alignment,
                rsz_layout.rsz_userdata_alignment_base,
                rsz_start,
            )
            userdata_offset = writer.tell() - rsz_start
            rsz_userdata_entry_offsets: list[int] = []
            for _item in rsz_userdata:
                rsz_userdata_entry_offsets.append(writer.tell())
                writer.write(b"\x00" * rsz_layout.rsz_userdata_entry_size)
            rsz_userdata_path_offsets: list[int] = []
            for item in rsz_userdata:
                rsz_userdata_path_offsets.append(writer.tell() - rsz_start)
                self._write_usr_path(writer, item.path, layout.path_encoding)
            for entry_offset, item, path_offset in zip(
                rsz_userdata_entry_offsets,
                rsz_userdata,
                rsz_userdata_path_offsets,
            ):
                self._patch_named_struct(
                    writer,
                    entry_offset,
                    rsz_layout.rsz_userdata_entry_struct,
                    rsz_layout.rsz_userdata_entry_fields,
                    {
                        "instance_id": item.instance_id,
                        "type_hash": item.type_hash,
                        "path_offset": path_offset,
                    },
                )
        else:
            userdata_offset = -1

        self._align_from_base(
            writer,
            rsz_layout.rsz_data_alignment,
            rsz_layout.rsz_data_alignment_base,
            rsz_start,
        )
        data_offset = writer.tell() - rsz_start
        if userdata_offset < 0:
            userdata_offset = data_offset
        writer.write(bytes(data_writer.data))

        self._patch_named_struct(
            writer,
            rsz_header_offset,
            rsz_layout.header_struct,
            rsz_layout.header_fields,
            {
                "magic": self.rsz_magic,
                "version": rsz_version,
                "object_count": len(root_ids),
                "instance_count": len(self.instances),
                "userdata_count": len(rsz_userdata),
                "reserved": rsz_reserved,
                "instance_offset": instance_offset,
                "data_offset": data_offset,
                "userdata_offset": userdata_offset,
            },
        )
        self._patch_named_struct(
            writer,
            0,
            layout.header_struct,
            layout.header_fields,
            {
                "signature": self.user_magic,
                "resource_count": len(usr_resources),
                "userdata_count": len(usr_userdata),
                "info_count": 0,
                "resource_info_tbl": resource_info_tbl,
                "userdata_info_tbl": userdata_info_tbl,
                "data_offset": rsz_start,
            },
        )
        return bytes(writer.data)

    @staticmethod
    def _patch_named_struct(
        writer: BinaryWriter,
        offset: int,
        fmt: str,
        fields: tuple[str, ...],
        values: dict[str, int],
    ) -> None:
        """Patch a declarative layout structure from its named values."""

        try:
            ordered = [values[field] for field in fields]
        except KeyError as exc:
            raise PackError(f"missing layout field value: {exc.args[0]}") from exc
        writer.patch_struct(offset, fmt, *ordered)

    @staticmethod
    def _write_usr_path(writer: BinaryWriter, path: str, encoding: str) -> None:
        if encoding != "utf-16-le-z":
            raise PackError(f"unsupported USR path encoding: {encoding}")
        writer.write(f"{path}\x00".encode("utf-16-le"))

    @staticmethod
    def _align_from_base(
        writer: BinaryWriter,
        alignment: int,
        base_kind: str,
        rsz_start: int,
    ) -> None:
        if base_kind == "file":
            writer.align(alignment)
            return
        if base_kind == "rsz":
            relative = writer.tell() - rsz_start
            writer.pad_to(rsz_start + align(relative, alignment))
            return
        raise PackError(f"unsupported alignment base: {base_kind}")

    def _write_instance(self, writer: BinaryWriter, spec: InstanceSpec) -> None:
        """Write instance.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            spec (InstanceSpec): Planned instance specification used by the binary writer.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        for field_def in spec.class_def.fields:
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            writer.align(4 if field_def.is_array else max(field_def.align, 1))
            key = field_def.name or "unnamed"
            self._write_field(writer, field_def, spec.fields.get(key))

    def _write_field(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Write field.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            field_def (FieldDef): Schema field definition for the value being parsed or written.
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        if field_def.is_array:
            items = value if isinstance(value, list) else []
            writer.write_struct("<I", len(items))
            non_array = FieldDef(
                name=field_def.name,
                field_type=field_def.field_type,
                original_type=field_def.original_type,
                size=field_def.size,
                align=field_def.align,
                is_array=False,
            )
            for item in items:
                writer.align(max(field_def.align, 1))
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
                self._write_scalar(writer, non_array, item)
            return
        self._write_scalar(writer, field_def, value)

    def _write_scalar(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Write scalar.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            field_def (FieldDef): Schema field definition for the value being parsed or written.
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        t = field_def.field_type
        if t == "Bool":
            writer.write_struct("<B", 1 if bool(value) else 0)
            return
        if t == "S8":
            writer.write_struct("<b", self._coerce_int(value, field_def))
            return
        if t == "U8":
            writer.write_struct("<B", self._coerce_int(value, field_def) & 0xFF)
            return
        if t == "S16":
            writer.write_struct("<h", self._coerce_int(value, field_def))
            return
        if t == "U16":
            writer.write_struct("<H", self._coerce_int(value, field_def) & 0xFFFF)
            return
        if t in {"S32", "Sfix"}:
            writer.write_struct("<i", self._to_s32(self._coerce_int(value, field_def)))
            return
        if t == "Enum":
            self._write_enum_value(writer, field_def, value)
            return
        if t == "U32":
            writer.write_struct("<I", self._coerce_int(value, field_def) & 0xFFFFFFFF)
            return
        if t == "S64":
            writer.write_struct("<q", self._coerce_int(value, field_def))
            return
        if t == "U64":
            writer.write_struct(
                "<Q", self._coerce_int(value, field_def) & 0xFFFFFFFFFFFFFFFF
            )
            return
        if t == "F32":
            writer.write_struct("<f", float(value or 0.0))
            return
        if t == "F64":
            writer.write_struct("<d", float(value or 0.0))
            return
        if t in {"Object", "UserData"}:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            ref_id = (
                value.index
                if isinstance(value, InstanceRef)
                else self._coerce_int(value, field_def)
            )
            writer.write_struct("<i", ref_id)
            return
        if t in {"String", "Resource"}:
            # Decode strings and GUID-like values conservatively so invalid data does
            # not corrupt subsequent parsing.
            writer.align(4)
            if value is None or value == "":
                writer.write_struct("<I", 0)
                return
            raw = f"{value or ''}\x00".encode("utf-16-le")
            writer.write_struct("<I", len(raw) // 2)
            writer.write(raw)
            return
        if t in {"C8", "RuntimeType"}:
            # C8-style strings store UTF-8 byte length and keep a trailing null byte in the binary stream.
            writer.align(4)
            if value is None or value == "":
                writer.write_struct("<I", 0)
                return
            raw = f"{value or ''}\x00".encode("utf-8")
            writer.write_struct("<I", len(raw))
            writer.write(raw)
            return
        if t in {"Guid", "GameObjectRef", "Uri"}:
            writer.write(uuid.UUID(str(value)).bytes_le)
            return
        if t == "Struct":
            self._write_struct(writer, value)
            return
        if t in {
            "Float2",
            "Float3",
            "Float4",
            "Vec2",
            "Vec3",
            "Vec4",
            "Quaternion",
            "Color",
            "AABB",
            "Capsule",
            "OBB",
            "Mat3",
            "Mat4",
            "Position",
        }:
            # Vector and matrix fields write float32 components and pad missing values with zero.
            values = value if isinstance(value, list) else []
            count = max(field_def.size // 4, 1)
            for i in range(count):
                writer.write_struct("<f", float(values[i]) if i < len(values) else 0.0)
            return
        if isinstance(value, dict) and isinstance(value.get("raw"), str):
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            writer.write(bytes.fromhex(value["raw"]))
            return
        # Follow schema field layout exactly so alignment, padding, and unknown data
        # remain binary-compatible.
        writer.write(b"\x00" * max(field_def.size, 0))

    def _enum_type_candidates_for_field(self, field_def: FieldDef) -> list[str]:
        """Yield enum metadata candidates for one schema field."""
        original = field_def.original_type
        candidates = [original] if isinstance(original, str) and original else []
        if isinstance(original, str) and original.endswith("_Serializable"):
            candidates.append(f"{original[:-13]}_Fixed")
        if isinstance(original, str) and "Serializable" in original:
            candidates.append(original.replace("Serializable", "Fixed"))
        if isinstance(original, str) and original.endswith("_Fixed"):
            candidates.append(original)
        return list(dict.fromkeys(candidates))

    def _enum_storage_type_for_field(self, field_def: FieldDef) -> str:
        """Resolve enum storage type from il2cpp metadata or schema size."""
        for candidate in self._enum_type_candidates_for_field(field_def):
            storage_type = self.enum_underlying_types.get(candidate)
            if storage_type is not None:
                return storage_type
        return enum_storage_type_from_size(field_def.size)

    def _write_enum_value(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Write an enum using its il2cpp underlying type or schema width."""
        int_value = self._coerce_int(value, field_def)
        storage_type = self._enum_storage_type_for_field(field_def)
        if storage_type == "S8":
            writer.write_struct("<b", int_value)
            return
        if storage_type == "U8":
            writer.write_struct("<B", int_value & 0xFF)
            return
        if storage_type == "S16":
            writer.write_struct("<h", int_value)
            return
        if storage_type == "U16":
            writer.write_struct("<H", int_value & 0xFFFF)
            return
        if storage_type == "U32":
            writer.write_struct("<I", int_value & 0xFFFFFFFF)
            return
        if storage_type == "S64":
            writer.write_struct("<q", int_value)
            return
        if storage_type == "U64":
            writer.write_struct("<Q", int_value & 0xFFFFFFFFFFFFFFFF)
            return
        writer.write_struct("<i", self._to_s32(int_value))

    def _write_struct(self, writer: BinaryWriter, value: Any) -> None:
        """Write struct.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        if not isinstance(value, StructValue):
            raw = value.get("raw") if isinstance(value, dict) else None
            if isinstance(raw, str):
                writer.write(bytes.fromhex(raw))
            return
        start = writer.tell()
        for field_def in value.class_def.fields:
            writer.align(4 if field_def.is_array else max(field_def.align, 1))
            key = field_def.name or "unnamed"
            self._write_field(writer, field_def, value.fields.get(key))
        consumed = writer.tell() - start
        if value.declared_size > consumed:
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            writer.write(b"\x00" * (value.declared_size - consumed))

    def _coerce_int(self, value: Any, field_def: FieldDef) -> int:
        """Coerce int.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            field_def (FieldDef): Schema field definition for the value being parsed or written.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            match = ENUM_LABEL_RE.match(text)
            if match:
                # Prefer the numeric value inside "[123] Name" labels when present
                # so enum text can round-trip to binary.
                return int(match.group(1))
            try:
                return int(text, 0)
            except ValueError:
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                enum_value = self._resolve_enum_member(text, field_def)
                if enum_value is not None:
                    return enum_value
        raise PackError(f"cannot convert {value!r} to int for field {field_def.name}")

    def _resolve_enum_member(self, text: str, field_def: FieldDef) -> int | None:
        """Resolve enum member.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            text (str): Text to normalize or parse.
            field_def (FieldDef): Schema field definition for the value being parsed or written.

        Returns:
            int | None: Resolved numeric value, or None when the source cannot be mapped.
        """
        for enum_type in self._enum_type_candidates_for_field(field_def):
            member_map = self.member_lookup.get(enum_type)
            if member_map and text in member_map:
                return member_map[text]
        return None
