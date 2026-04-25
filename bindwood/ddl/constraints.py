"""Regex-based constraint extractors for DDL (PKs, UKs, FKs, indexes).

Handles the ``ALTER TABLE ... ADD CONSTRAINT`` form that ``pg_dump``
produces. Inline table-body constraints (``CONSTRAINT pk ... PRIMARY KEY``,
column-level ``REFERENCES``, etc.) are handled by ``inline.py`` — both
paths populate the same ``tables[name]`` dicts.
"""

from __future__ import annotations

import re


# Identifier fragment: optional schema prefix + optional double-quote wrapping.
# Captures the bare name as ``(\w+)``. Use this anywhere a schema-qualified
# table reference appears in raw DDL text.
_QUALIFIED = r'(?:"?\w+"?\.)?"?(\w+)"?'


def extract_primary_keys(ddl_text: str, tables: dict):
    """Extract PRIMARY KEY constraints from ALTER TABLE statements."""
    pattern = (
        rf'ALTER\s+TABLE\s+(?:ONLY\s+)?{_QUALIFIED}\s+'
        rf'ADD\s+CONSTRAINT\s+"?\w+"?\s+PRIMARY\s+KEY\s*\(([^)]+)\);'
    )
    for match in re.finditer(pattern, ddl_text, re.IGNORECASE):
        table = match.group(1)
        cols = [c.strip().strip('"') for c in match.group(2).split(",")]
        if table in tables:
            tables[table]["primary_key"] = cols


def extract_unique_constraints(ddl_text: str, tables: dict):
    """Extract UNIQUE constraints from ALTER TABLE statements."""
    pattern = (
        rf'ALTER\s+TABLE\s+(?:ONLY\s+)?{_QUALIFIED}\s+'
        rf'ADD\s+CONSTRAINT\s+"?(\w+)"?\s+UNIQUE\s*\(([^)]+)\);'
    )
    for match in re.finditer(pattern, ddl_text, re.IGNORECASE):
        table = match.group(1)
        name = match.group(2)
        cols = [c.strip().strip('"') for c in match.group(3).split(",")]
        if table in tables:
            tables[table]["unique_constraints"].append({"name": name, "columns": cols})


def extract_foreign_keys(ddl_text: str, tables: dict):
    """Extract FOREIGN KEY constraints from ALTER TABLE statements."""
    pattern = (
        rf'ALTER\s+TABLE\s+(?:ONLY\s+)?{_QUALIFIED}\s+'
        rf'ADD\s+CONSTRAINT\s+"?(\w+)"?\s+FOREIGN\s+KEY\s*\(([^)]+)\)\s+'
        rf'REFERENCES\s+{_QUALIFIED}\s*\(([^)]+)\)'
        r"([^;]*);"
    )
    for match in re.finditer(pattern, ddl_text, re.IGNORECASE):
        from_table = match.group(1)
        constraint_name = match.group(2)
        from_cols = [c.strip().strip('"') for c in match.group(3).split(",")]
        to_table = match.group(4)
        to_cols = [c.strip().strip('"') for c in match.group(5).split(",")]
        trailer = match.group(6)

        fk = {
            "constraint": constraint_name,
            "columns": from_cols,
            "references_table": to_table,
            "references_columns": to_cols,
        }

        action = r"(?:NO\s+ACTION|SET\s+NULL|SET\s+DEFAULT|CASCADE|RESTRICT)"
        on_delete = re.search(rf"ON\s+DELETE\s+({action})", trailer, re.IGNORECASE)
        on_update = re.search(rf"ON\s+UPDATE\s+({action})", trailer, re.IGNORECASE)
        if on_delete:
            fk["on_delete"] = re.sub(r"\s+", " ", on_delete.group(1)).upper()
        if on_update:
            fk["on_update"] = re.sub(r"\s+", " ", on_update.group(1)).upper()

        if from_table in tables:
            tables[from_table]["foreign_keys_out"].append(fk)
        if to_table in tables:
            tables[to_table]["referenced_by"].append({
                "constraint": constraint_name,
                "from_table": from_table,
                "from_columns": from_cols,
            })


def _extract_balanced_parens(text: str, start: int) -> str:
    """Extract content between balanced parentheses starting at position start."""
    if start >= len(text) or text[start] != '(':
        return ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return ""


def _split_top_level(expr: str) -> list[str]:
    """Split expression on commas that are not inside parentheses."""
    parts = []
    depth = 0
    current = []
    for char in expr:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append(''.join(current).strip())
    return parts


def extract_indexes(ddl_text: str, tables: dict, views: dict):
    """Extract CREATE [UNIQUE] INDEX statements for tables and materialized views.

    Accepts any schema prefix and makes the ``USING <method>`` clause
    optional (Postgres defaults to btree when omitted).
    """
    pattern = (
        rf'CREATE\s+(UNIQUE\s+)?INDEX\s+"?(\w+)"?\s+ON\s+{_QUALIFIED}'
        r'(?:\s+USING\s+(\w+))?\s*(?=\()'
    )
    for match in re.finditer(pattern, ddl_text, re.IGNORECASE):
        unique = bool(match.group(1))
        name = match.group(2)
        target = match.group(3)
        method = match.group(4) or "btree"

        paren_start = match.end()
        col_expr = _extract_balanced_parens(ddl_text, paren_start)
        if not col_expr:
            continue

        cols = _split_top_level(col_expr)

        index_entry = {
            "name": name,
            "columns": cols,
            "unique": unique,
            "method": method,
        }

        if target in tables:
            tables[target]["indexes"].append(index_entry)
        elif target in views:
            views[target].setdefault("indexes", []).append(index_entry)
