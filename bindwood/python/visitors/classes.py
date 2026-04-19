"""Extract class definitions from Python AST."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


MAX_DOCSTRING_LEN = 500
PREVIEW_LEN = 250


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
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    methods: list[MethodBrief] = field(default_factory=list)
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


def _clean_docstring(raw: str) -> str | None:
    s = raw.strip()
    for prefix in ('r"""', "r'''", 'b"""', "b'''", 'rb"""', "rb'''", 'br"""', "br'''"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    else:
        for prefix in ('"""', "'''", '"', "'"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
    for suffix in ('"""', "'''", '"', "'"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    s = s.strip()
    if len(s) > MAX_DOCSTRING_LEN:
        s = s[:MAX_DOCSTRING_LEN].rstrip() + "..."
    return s or None


def _extract_docstring(body_node) -> str | None:
    if not body_node:
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            inner = child.children[0] if child.children else None
            if inner and inner.type == "string":
                return _clean_docstring(_text(inner))
            return None
    return None


def _visibility(name: str) -> str:
    return "private" if name.startswith("_") and not (name.startswith("__") and name.endswith("__")) else "public"


def extract_classes(root_node, source: bytes) -> list[ClassInfo]:
    """Walk the AST and extract class definitions."""
    classes: list[ClassInfo] = []
    _walk_classes(root_node, classes)
    return classes


def _walk_classes(node, classes: list[ClassInfo]):
    """Recursively walk looking for class definitions."""
    if node.type == "class_definition":
        info = _extract_class(node, decorators=[])
        if info:
            classes.append(info)
        return

    if node.type == "decorated_definition":
        decorators: list[str] = []
        class_node = None
        for child in node.children:
            if child.type == "decorator":
                decorators.append(_text(child).lstrip("@").strip())
            elif child.type == "class_definition":
                class_node = child
        if class_node:
            info = _extract_class(class_node, decorators)
            if info:
                classes.append(info)
            return

    for child in node.children:
        _walk_classes(child, classes)


def _extract_class(node, decorators: list[str]) -> ClassInfo | None:
    """Parse a class_definition node."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    name = _text(name_node)

    # Extract base classes
    bases: list[str] = []
    superclasses = node.child_by_field_name("superclasses")
    if superclasses:
        for child in superclasses.children:
            if child.type in ("identifier", "attribute"):
                bases.append(_text(child))
            elif child.type == "keyword_argument":
                # metaclass=ABCMeta etc.
                bases.append(_text(child))

    # Extract method briefs from class body
    methods: list[MethodBrief] = []
    body = node.child_by_field_name("body")
    docstring = _extract_docstring(body)

    if body:
        for member in body.children:
            func_node = member
            method_decorators: list[str] = []
            if member.type == "decorated_definition":
                for child in member.children:
                    if child.type == "decorator":
                        method_decorators.append(_text(child).lstrip("@").strip())
                    elif child.type == "function_definition":
                        func_node = child
                        break
                else:
                    continue
            if func_node.type == "function_definition":
                m_name = func_node.child_by_field_name("name")
                if m_name:
                    is_async = any(
                        _text(c) == "async"
                        for c in func_node.children
                        if c.type not in ("block", "parameters")
                    )
                    m_name_text = _text(m_name)
                    # Use `member` as the anchor so that decorated methods report
                    # the full span including their decorator lines.
                    methods.append(MethodBrief(
                        name=m_name_text,
                        async_=is_async,
                        line=member.start_point[0] + 1,
                        end_line=member.end_point[0] + 1,
                        visibility=_visibility(m_name_text),
                        decorators=method_decorators,
                    ))

    source_text = node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)

    return ClassInfo(
        name=name,
        bases=bases,
        decorators=decorators,
        methods=methods,
        docstring=docstring,
        visibility=_visibility(name),
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        content_hash=content_hash,
        source_text=source_text,
        source_preview=source_preview,
    )
