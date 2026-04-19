"""Extract function/method/arrow definitions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


MAX_DOCSTRING_LEN = 500
PREVIEW_LEN = 250


@dataclass
class ParamInfo:
    name: str
    type_hint: str | None = None
    default: str | None = None
    optional: bool = False
    kind: str = "positional"  # "positional" | "rest"


@dataclass
class FunctionInfo:
    name: str
    kind: str  # "declaration" | "expression" | "arrow" | "method" | "generator"
    async_: bool = False
    params: list[str] = field(default_factory=list)
    param_types: list[ParamInfo] = field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    visibility: str = "public"  # "public" | "private" | "protected"
    decorators: list[str] = field(default_factory=list)
    line: int = 0
    end_line: int = 0
    byte_start: int = 0
    byte_end: int = 0
    content_hash: str | None = None
    enclosing_class: str | None = None
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


def _truncate(s: str, max_len: int = 120) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_functions(root_node, source: bytes) -> list[FunctionInfo]:
    """Walk the AST and extract all function definitions."""
    functions: list[FunctionInfo] = []
    _walk_functions(root_node, functions, enclosing_class=None)
    return functions


def _walk_functions(node, functions: list[FunctionInfo], enclosing_class: str | None):
    """Recursively walk looking for function definitions."""

    # function foo() {} / async function foo() {}
    if node.type in ("function_declaration", "generator_function_declaration"):
        info = _extract_function_decl(node, enclosing_class)
        if info:
            functions.append(info)
        # Don't recurse into function body for nested function defs
        # (we do want them — they become separate entries)
        for child in node.children:
            if child.type == "statement_block":
                _walk_functions(child, functions, enclosing_class)
        return

    # Arrow function: const foo = () => {} or const foo = async () => {}
    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value and value.type in ("arrow_function", "function_expression"):
            name_node = node.child_by_field_name("name")
            name = _text(name_node) if name_node and name_node.type == "identifier" else "anonymous"
            info = _extract_func_node(value, name, enclosing_class, anchor=node)
            if info:
                functions.append(info)
            # Recurse into body
            body = value.child_by_field_name("body")
            if body:
                _walk_functions(body, functions, enclosing_class)
            return

    # Class method: method_definition inside class body
    if node.type == "method_definition":
        info = _extract_method(node, enclosing_class)
        if info:
            functions.append(info)
        body = node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class)
        return

    # Track class context
    if node.type in ("class_declaration", "class_expression"):
        name_node = node.child_by_field_name("name")
        cls_name = _text(name_node) if name_node else "anonymous"
        body = node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class=cls_name)
        return

    for child in node.children:
        _walk_functions(child, functions, enclosing_class)


def _extract_function_decl(node, enclosing_class: str | None) -> FunctionInfo | None:
    """Extract from function_declaration / generator_function_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    is_async = any(c.type == "async" or _text(c) == "async" for c in node.children if c.type != "statement_block")
    is_generator = node.type == "generator_function_declaration"
    param_infos = _extract_param_infos(node)
    source_text = node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)

    return FunctionInfo(
        name=_text(name_node),
        kind="generator" if is_generator else "declaration",
        async_=is_async,
        params=[p.name for p in param_infos],
        param_types=param_infos,
        return_type=_return_type(node),
        docstring=_leading_jsdoc(node),
        visibility="public",
        decorators=[],
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        content_hash=content_hash,
        enclosing_class=enclosing_class,
        source_text=source_text,
        source_preview=source_preview,
    )


def _extract_func_node(node, name: str, enclosing_class: str | None, anchor=None) -> FunctionInfo:
    """Extract from arrow_function or function_expression.

    `anchor` is the node used to look up a preceding JSDoc comment — for
    arrow assignments this is usually the enclosing variable_declarator.
    """
    is_async = any(_text(c) == "async" for c in node.children if c.type != "statement_block")
    kind = "arrow" if node.type == "arrow_function" else "expression"
    param_infos = _extract_param_infos(node)
    doc_anchor = anchor if anchor is not None else node
    # Walk up one more level for JSDoc on `const foo = () => ...` — the comment
    # precedes the enclosing `lexical_declaration`, not the declarator.
    if doc_anchor.parent and doc_anchor.parent.type in ("lexical_declaration", "variable_declaration"):
        doc_anchor = doc_anchor.parent

    # Span covers the declaration form so line ranges include `const foo = `.
    span_node = anchor if anchor is not None else node
    source_text = span_node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)

    return FunctionInfo(
        name=name,
        kind=kind,
        async_=is_async,
        params=[p.name for p in param_infos],
        param_types=param_infos,
        return_type=_return_type(node),
        docstring=_leading_jsdoc(doc_anchor),
        visibility="public",
        decorators=[],
        line=span_node.start_point[0] + 1,
        end_line=span_node.end_point[0] + 1,
        byte_start=span_node.start_byte,
        byte_end=span_node.end_byte,
        content_hash=content_hash,
        enclosing_class=enclosing_class,
        source_text=source_text,
        source_preview=source_preview,
    )


def _extract_method(node, enclosing_class: str | None) -> FunctionInfo | None:
    """Extract from method_definition."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    is_async = any(_text(c) == "async" for c in node.children if c.type not in ("statement_block", "formal_parameters"))
    param_infos = _extract_param_infos(node)

    # accessibility_modifier child (public/private/protected) in TS
    visibility = "public"
    for child in node.children:
        if child.type == "accessibility_modifier":
            visibility = _text(child).strip()
            break

    source_text = node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)

    return FunctionInfo(
        name=_text(name_node),
        kind="method",
        async_=is_async,
        params=[p.name for p in param_infos],
        param_types=param_infos,
        return_type=_return_type(node),
        docstring=_leading_jsdoc(node),
        visibility=visibility,
        decorators=_preceding_decorators(node),
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        content_hash=content_hash,
        enclosing_class=enclosing_class,
        source_text=source_text,
        source_preview=source_preview,
    )


def _return_type(node) -> str | None:
    """Return text of the `return_type` field if present (TS only)."""
    rt = node.child_by_field_name("return_type")
    if rt is None:
        return None
    text = _text(rt).lstrip(":").strip()
    return _truncate(text) if text else None


def _leading_jsdoc(node) -> str | None:
    """Return the immediately preceding /** ... */ comment text, cleaned up."""
    prev = node.prev_named_sibling if hasattr(node, "prev_named_sibling") else None
    if prev is None:
        prev = node.prev_sibling if hasattr(node, "prev_sibling") else None
    if prev is None or prev.type != "comment":
        return None
    raw = _text(prev).strip()
    if not raw.startswith("/**"):
        return None
    # Strip /** ... */ and leading *'s from each line.
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
    """Collect decorator siblings immediately preceding a method_definition."""
    decorators: list[str] = []
    cur = node.prev_named_sibling if hasattr(node, "prev_named_sibling") else None
    while cur is not None and cur.type == "decorator":
        decorators.append(_text(cur).lstrip("@").strip())
        cur = cur.prev_named_sibling if hasattr(cur, "prev_named_sibling") else None
    decorators.reverse()
    return decorators


def _extract_param_infos(node) -> list[ParamInfo]:
    """Extract rich parameter info from a function/method node.

    Handles both JS (identifier/assignment_pattern/rest_pattern) and TS
    (required_parameter/optional_parameter with type annotations).
    """
    params_node = node.child_by_field_name("parameters")
    if not params_node:
        return []

    infos: list[ParamInfo] = []
    for child in params_node.children:
        if child.type == "identifier":
            infos.append(ParamInfo(name=_text(child)))
        elif child.type in ("required_parameter", "optional_parameter"):
            pattern = child.child_by_field_name("pattern")
            type_node = child.child_by_field_name("type")
            value_node = child.child_by_field_name("value")
            name = _text(pattern) if pattern else "?"
            type_hint = None
            if type_node:
                t = _text(type_node).lstrip(":").strip()
                type_hint = _truncate(t) if t else None
            infos.append(ParamInfo(
                name=name,
                type_hint=type_hint,
                default=_truncate(_text(value_node)) if value_node else None,
                optional=(child.type == "optional_parameter"),
            ))
        elif child.type in ("object_pattern", "array_pattern"):
            infos.append(ParamInfo(name="{...}" if child.type == "object_pattern" else "[...]"))
        elif child.type == "assignment_pattern":
            left = child.child_by_field_name("left")
            right = child.child_by_field_name("right")
            if left:
                infos.append(ParamInfo(
                    name=_text(left),
                    default=_truncate(_text(right)) if right else None,
                ))
        elif child.type == "rest_pattern":
            arg = child.children[1] if len(child.children) > 1 else None
            if arg:
                infos.append(ParamInfo(name=f"...{_text(arg)}", kind="rest"))
    return infos
