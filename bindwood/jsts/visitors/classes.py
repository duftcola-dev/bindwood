"""Extract class declarations with methods and properties."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


MAX_DOCSTRING_LEN = 500
PREVIEW_LEN = 250


@dataclass
class PropertyInfo:
    name: str
    value_hint: str | None = None
    type_hint: str | None = None
    visibility: str = "public"
    line: int = 0
    end_line: int = 0


@dataclass
class MethodBrief:
    name: str
    async_: bool = False
    line: int = 0
    end_line: int = 0
    visibility: str = "public"
    decorators: list[str] = field(default_factory=list)


@dataclass
class ClassInfo:
    name: str
    extends: str | None = None
    methods: list[MethodBrief] = field(default_factory=list)
    properties: list[PropertyInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    docstring: str | None = None
    visibility: str = "public"
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


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def _leading_jsdoc(node) -> str | None:
    """Return the immediately preceding /** ... */ comment text, cleaned up."""
    prev = node.prev_named_sibling if hasattr(node, "prev_named_sibling") else None
    if prev is None:
        prev = node.prev_sibling if hasattr(node, "prev_sibling") else None
    # Skip over decorator siblings to find the JSDoc
    while prev is not None and prev.type == "decorator":
        prev = prev.prev_named_sibling if hasattr(prev, "prev_named_sibling") else None
    if prev is None or prev.type != "comment":
        return None
    raw = _text(prev).strip()
    if not raw.startswith("/**"):
        return None
    inner = raw[3:]
    if inner.endswith("*/"):
        inner = inner[:-2]
    lines = []
    for line in inner.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        lines.append(line)
    cleaned = "\n".join(l for l in lines if l).strip()
    if len(cleaned) > MAX_DOCSTRING_LEN:
        cleaned = cleaned[:MAX_DOCSTRING_LEN].rstrip() + "..."
    return cleaned or None


def _preceding_decorators(node) -> list[str]:
    """Collect decorator siblings immediately preceding a node."""
    decorators: list[str] = []
    cur = node.prev_named_sibling if hasattr(node, "prev_named_sibling") else None
    while cur is not None and cur.type == "decorator":
        decorators.append(_text(cur).lstrip("@").strip())
        cur = cur.prev_named_sibling if hasattr(cur, "prev_named_sibling") else None
    decorators.reverse()
    return decorators


def extract_classes(root_node, source: bytes) -> list[ClassInfo]:
    """Walk the AST and extract class declarations."""
    classes: list[ClassInfo] = []
    _walk_classes(root_node, classes)
    return classes


def _walk_classes(node, classes: list[ClassInfo]):
    """Recursively walk looking for class definitions."""
    if node.type in ("class_declaration", "class_expression"):
        info = _extract_class(node)
        if info:
            classes.append(info)
        return  # don't recurse into class body (methods handled above)

    # Also catch: const X = class { ... }
    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value and value.type == "class_expression":
            name_node = node.child_by_field_name("name")
            info = _extract_class(value)
            if info and name_node:
                info.name = _text(name_node)
                classes.append(info)
            return

    for child in node.children:
        _walk_classes(child, classes)


def _extract_class(node) -> ClassInfo | None:
    """Parse a class_declaration or class_expression."""
    name_node = node.child_by_field_name("name")
    name = _text(name_node) if name_node else "anonymous"

    # extends clause
    extends = None
    for child in node.children:
        if child.type == "class_heritage":
            for heritage_child in child.children:
                if heritage_child.type == "extends_clause":
                    for ext_child in heritage_child.children:
                        if ext_child.type in ("identifier", "member_expression"):
                            extends = _text(ext_child)

    # Methods and properties from class body
    methods: list[MethodBrief] = []
    properties: list[PropertyInfo] = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type == "method_definition":
                m_name_node = member.child_by_field_name("name")
                if m_name_node:
                    is_async = any(_text(c) == "async" for c in member.children if c.type not in ("statement_block", "formal_parameters"))
                    m_visibility = "public"
                    for c in member.children:
                        if c.type == "accessibility_modifier":
                            m_visibility = _text(c).strip()
                            break
                    methods.append(MethodBrief(
                        name=_text(m_name_node),
                        async_=is_async,
                        line=member.start_point[0] + 1,
                        end_line=member.end_point[0] + 1,
                        visibility=m_visibility,
                        decorators=_preceding_decorators(member),
                    ))
            elif member.type in ("public_field_definition", "field_definition", "property_definition"):
                p_name_node = member.child_by_field_name("name")
                p_value_node = member.child_by_field_name("value")
                p_type_node = member.child_by_field_name("type")
                p_visibility = "public"
                for c in member.children:
                    if c.type == "accessibility_modifier":
                        p_visibility = _text(c).strip()
                        break
                if p_name_node:
                    t_hint = None
                    if p_type_node:
                        t = _text(p_type_node).lstrip(":").strip()
                        t_hint = _truncate(t, max_len=120) if t else None
                    properties.append(PropertyInfo(
                        name=_text(p_name_node),
                        value_hint=_truncate(_text(p_value_node)) if p_value_node else None,
                        type_hint=t_hint,
                        visibility=p_visibility,
                        line=member.start_point[0] + 1,
                        end_line=member.end_point[0] + 1,
                    ))

    source_text = node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)

    return ClassInfo(
        name=name,
        extends=extends,
        methods=methods,
        properties=properties,
        decorators=_preceding_decorators(node),
        docstring=_leading_jsdoc(node),
        visibility="public",
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        content_hash=content_hash,
        source_text=source_text,
        source_preview=source_preview,
    )
