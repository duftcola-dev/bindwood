"""Extract function and method definitions from Python AST."""

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
    kind: str = "positional"  # "positional" | "vararg" | "kwarg"


@dataclass
class FunctionInfo:
    name: str
    kind: str  # "function" | "method" | "staticmethod" | "classmethod" | "property"
    async_: bool = False
    params: list[str] = field(default_factory=list)
    param_types: list[ParamInfo] = field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    visibility: str = "public"  # "public" | "private"
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
    """Compute content hash and short preview for a source text block."""
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


def extract_functions(root_node, source: bytes) -> list[FunctionInfo]:
    """Walk the AST and extract all function definitions."""
    functions: list[FunctionInfo] = []
    _walk_functions(root_node, functions, enclosing_class=None)
    return functions


def _walk_functions(node, functions: list[FunctionInfo], enclosing_class: str | None):
    """Recursively walk looking for function definitions."""
    if node.type in ("function_definition", "decorated_definition"):
        info = _extract_function(node, enclosing_class)
        if info:
            functions.append(info)
        # Recurse into the function body for nested functions
        func_node = node
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    func_node = child
                    break
        body = func_node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class)
        return

    # Track class context
    if node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        cls_name = _text(name_node) if name_node else "anonymous"
        body = node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class=cls_name)
        return

    for child in node.children:
        _walk_functions(child, functions, enclosing_class)


def _extract_function(node, enclosing_class: str | None) -> FunctionInfo | None:
    """Extract from function_definition or decorated_definition."""
    decorators: list[str] = []
    func_node = node

    if node.type == "decorated_definition":
        for child in node.children:
            if child.type == "decorator":
                dec_text = _text(child).lstrip("@").strip()
                decorators.append(dec_text)
            elif child.type == "function_definition":
                func_node = child
                break
            elif child.type == "class_definition":
                # This is a decorated class, not a function
                return None

    name_node = func_node.child_by_field_name("name")
    if not name_node:
        return None

    is_async = any(
        child.type == "async" or _text(child) == "async"
        for child in func_node.children
        if child.type not in ("block", "parameters")
    )

    # Determine kind based on decorators and context
    kind = "function"
    if enclosing_class:
        kind = "method"
        for dec in decorators:
            if dec == "staticmethod":
                kind = "staticmethod"
                break
            elif dec == "classmethod":
                kind = "classmethod"
                break
            elif dec == "property" or dec.endswith(".setter") or dec.endswith(".getter") or dec.endswith(".deleter"):
                kind = "property"
                break

    name = _text(name_node)
    param_infos = _extract_param_infos(func_node)

    # Return type from `-> X` annotation
    return_type_node = func_node.child_by_field_name("return_type")
    return_type = _truncate(_text(return_type_node), max_len=120) if return_type_node else None

    # Docstring: first statement in body if it's a string expression
    body = func_node.child_by_field_name("body")
    docstring = _extract_docstring(body)

    # Python convention: leading underscore => private
    visibility = "private" if name.startswith("_") and not (name.startswith("__") and name.endswith("__")) else "public"

    source_text = func_node.text.decode("utf-8")
    content_hash, source_preview = _hash_and_preview(source_text)

    return FunctionInfo(
        name=name,
        kind=kind,
        async_=is_async,
        params=[p.name for p in param_infos],
        param_types=param_infos,
        return_type=return_type,
        docstring=docstring,
        visibility=visibility,
        decorators=decorators,
        line=node.start_point[0] + 1,
        end_line=func_node.end_point[0] + 1,
        byte_start=func_node.start_byte,
        byte_end=func_node.end_byte,
        content_hash=content_hash,
        enclosing_class=enclosing_class,
        source_text=source_text,
        source_preview=source_preview,
    )


def _extract_docstring(body_node) -> str | None:
    """Return the first string-literal statement in a block, cleaned up."""
    if not body_node:
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            inner = child.children[0] if child.children else None
            if inner and inner.type == "string":
                raw = _text(inner)
                return _clean_docstring(raw)
            return None  # first real statement wasn't a string
    return None


def _clean_docstring(raw: str) -> str:
    """Strip Python string quoting and truncate."""
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


def _extract_param_infos(node) -> list[ParamInfo]:
    """Extract rich parameter info (name, type_hint, default, kind) from a function node."""
    params_node = node.child_by_field_name("parameters")
    if not params_node:
        return []

    infos: list[ParamInfo] = []
    for child in params_node.children:
        if child.type == "identifier":
            infos.append(ParamInfo(name=_text(child)))
        elif child.type == "typed_parameter":
            # children: identifier, ":", type
            name_node = child.children[0] if child.children else None
            type_node = child.child_by_field_name("type")
            if name_node:
                infos.append(ParamInfo(
                    name=_text(name_node),
                    type_hint=_truncate(_text(type_node), max_len=120) if type_node else None,
                ))
        elif child.type == "default_parameter":
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if name_node:
                infos.append(ParamInfo(
                    name=_text(name_node),
                    default=_truncate(_text(value_node)) if value_node else None,
                ))
        elif child.type == "typed_default_parameter":
            name_node = child.child_by_field_name("name")
            type_node = child.child_by_field_name("type")
            value_node = child.child_by_field_name("value")
            if name_node:
                infos.append(ParamInfo(
                    name=_text(name_node),
                    type_hint=_truncate(_text(type_node), max_len=120) if type_node else None,
                    default=_truncate(_text(value_node)) if value_node else None,
                ))
        elif child.type == "list_splat_pattern":
            arg = child.children[0] if child.children else None
            # In tree-sitter-python, list_splat_pattern wraps a plain identifier; for typed *args
            # the AST uses a different shape, but this handles the common case.
            if arg:
                infos.append(ParamInfo(name=f"*{_text(arg)}", kind="vararg"))
        elif child.type == "dictionary_splat_pattern":
            arg = child.children[0] if child.children else None
            if arg:
                infos.append(ParamInfo(name=f"**{_text(arg)}", kind="kwarg"))
    return infos
