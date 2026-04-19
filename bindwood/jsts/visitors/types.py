"""Extract TypeScript interfaces, type aliases, and enums."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


PREVIEW_LEN = 250


@dataclass
class TypeMember:
    name: str
    type_hint: str | None = None


@dataclass
class TypeInfo:
    name: str
    kind: str  # "interface" | "type_alias" | "enum"
    members: list[TypeMember] = field(default_factory=list)
    extends: list[str] = field(default_factory=list)
    line: int = 0
    end_line: int = 0
    byte_start: int = 0
    byte_end: int = 0
    content_hash: str | None = None
    source_text: str | None = None
    source_preview: str | None = None


def _hash_and_preview(text: str) -> tuple[str, str]:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    preview = text[:PREVIEW_LEN]
    if len(text) > PREVIEW_LEN:
        preview = preview.rstrip() + "..."
    return h, preview


def _build_type_info(node, name: str, kind: str, members: list[TypeMember], extends: list[str]) -> TypeInfo:
    source_text = node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)
    return TypeInfo(
        name=name,
        kind=kind,
        members=members,
        extends=extends,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        content_hash=content_hash,
        source_text=source_text,
        source_preview=source_preview,
    )


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_types(root_node, source: bytes) -> list[TypeInfo]:
    """Walk the AST and extract TypeScript type definitions."""
    types: list[TypeInfo] = []
    _walk_types(root_node, types)
    return types


def _walk_types(node, types: list[TypeInfo]):
    """Recursively walk looking for type definitions."""
    if node.type == "interface_declaration":
        info = _extract_interface(node)
        if info:
            types.append(info)
        return

    if node.type == "type_alias_declaration":
        info = _extract_type_alias(node)
        if info:
            types.append(info)
        return

    if node.type == "enum_declaration":
        info = _extract_enum(node)
        if info:
            types.append(info)
        return

    # Handle exported types: export interface/type/enum
    if node.type == "export_statement":
        for child in node.children:
            _walk_types(child, types)
        return

    for child in node.children:
        _walk_types(child, types)


def _extract_interface(node) -> TypeInfo | None:
    """Parse an interface_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    extends = []
    for child in node.children:
        if child.type == "extends_type_clause":
            for ext_child in child.children:
                if ext_child.type in ("type_identifier", "generic_type"):
                    extends.append(_text(ext_child))

    members = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type in ("property_signature", "method_signature"):
                m_name = member.child_by_field_name("name")
                m_type = member.child_by_field_name("type")
                if m_name:
                    members.append(TypeMember(
                        name=_text(m_name),
                        type_hint=_truncate(_text(m_type)) if m_type else None,
                    ))

    return _build_type_info(node, _text(name_node), "interface", members, extends)


def _extract_type_alias(node) -> TypeInfo | None:
    """Parse a type_alias_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    return _build_type_info(node, _text(name_node), "type_alias", [], [])


def _extract_enum(node) -> TypeInfo | None:
    """Parse an enum_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    members = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type == "enum_member":
                m_name = member.child_by_field_name("name")
                if m_name:
                    members.append(TypeMember(name=_text(m_name)))

    return _build_type_info(node, _text(name_node), "enum", members, [])
