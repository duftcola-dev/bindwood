"""DDL parsing — sqlglot-based table and enum extraction."""

from __future__ import annotations

import hashlib
import re

import sqlglot
from sqlglot import exp, ErrorLevel


PREVIEW_LEN = 250


def _find_statement_end(text: str, start: int) -> int:
    """Walk forward from `start` until the first top-level `;` outside any
    parens or single-quoted string. Returns the offset of the `;`."""
    depth = 0
    in_string = False
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if in_string:
            if c == "'":
                # Doubled-up '' inside a string is an escaped apostrophe.
                if i + 1 < n and text[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if c == "'":
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            if depth > 0:
                depth -= 1
        elif c == ";" and depth == 0:
            return i
        i += 1
    return n - 1


def _line_of(text: str, offset: int) -> int:
    """Return the 1-based line number at a byte offset."""
    return text.count("\n", 0, offset) + 1


def _hash_and_preview(text: str) -> tuple[str, str]:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    preview = text[:PREVIEW_LEN]
    if len(text) > PREVIEW_LEN:
        preview = preview.rstrip() + "..."
    return h, preview


def locate_spans(ddl_text: str) -> dict:
    """Locate CREATE statements in the raw DDL text and return a map of
    coordinate metadata keyed by kind and name.

    Returns:
      {
        "tables": { name: {line, end_line, byte_start, byte_end, content_hash, source_preview, raw_source}, ... },
        "views":  { name: {...} },
        "enums":  { name: {...} },
      }
    """
    result: dict[str, dict[str, dict]] = {"tables": {}, "views": {}, "enums": {}}

    # The identifier may be bare, schema-qualified (Postgres ``public.``,
    # MySQL ``dbname.``), or wrapped in backticks (MySQL) / double quotes
    # (standard SQL / Postgres quoted identifiers).
    qualified_ident = r"(?:[`\"]?\w+[`\"]?\.)?[`\"]?(\w+)[`\"]?"
    patterns = [
        ("tables", rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{qualified_ident}\b"),
        ("views", rf"CREATE\s+(?:MATERIALIZED\s+)?VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+{qualified_ident}\b"),
        ("enums", rf"CREATE\s+TYPE\s+{qualified_ident}\s+AS\s+ENUM\b"),
    ]

    for kind, pat in patterns:
        for m in re.finditer(pat, ddl_text, re.IGNORECASE):
            name = m.group(1)
            # Skip duplicates (e.g. ALTER TABLE statements also match a table name
            # regex in principle, but our patterns already anchor to CREATE).
            if name in result[kind]:
                continue
            start = m.start()
            end = _find_statement_end(ddl_text, m.end())
            # Include the terminating ';' in the span when possible.
            byte_end = end + 1 if end < len(ddl_text) and ddl_text[end] == ";" else end
            raw_source = ddl_text[start:byte_end]
            content_hash, source_preview = _hash_and_preview(raw_source)
            result[kind][name] = {
                "line": _line_of(ddl_text, start),
                "end_line": _line_of(ddl_text, byte_end),
                "byte_start": start,
                "byte_end": byte_end,
                "content_hash": content_hash,
                "source_preview": source_preview,
                "raw_source": raw_source,
            }

    return result


def strip_public(name: str) -> str:
    """Normalise a possibly schema-qualified identifier to its bare name.

    Drops any ``<schema>.`` prefix (not just ``public.``) and removes
    surrounding double quotes. Keeping this consistent with the regex
    extractors — which capture only the bare identifier via ``(\\w+)`` —
    ensures ``tables[name]`` keys line up across all code paths.
    """
    name = name.replace('"', '')
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return name


def extract_enums(ddl_text: str) -> dict[str, list[str]]:
    """Extract CREATE TYPE ... AS ENUM via regex (any schema)."""
    enums = {}
    pattern = r'CREATE\s+TYPE\s+(?:"?\w+"?\.)?"?(\w+)"?\s+AS\s+ENUM\s*\(\s*([\s\S]*?)\);'
    for match in re.finditer(pattern, ddl_text, re.IGNORECASE):
        name = match.group(1)
        values = [v.strip().strip("'") for v in match.group(2).split(",") if v.strip()]
        enums[name] = values
    return enums


def _unquote_sql_string(s: str) -> str:
    """Strip surrounding single quotes and unescape doubled single quotes."""
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    return s.replace("''", "'")


def extract_comments(ddl_text: str) -> dict:
    """Extract COMMENT ON statements.

    Returns:
      {
        "tables":  { table_name: comment, ... },
        "columns": { table_name: { column_name: comment, ... }, ... },
        "views":   { view_name: comment, ... },   # views + materialized views
      }
    """
    result = {"tables": {}, "columns": {}, "views": {}}

    qualified = r'(?:"?\w+"?\.)?"?(\w+)"?'

    # COMMENT ON TABLE <schema>.foo IS '...';
    for m in re.finditer(
        rf"COMMENT\s+ON\s+TABLE\s+{qualified}\s+IS\s+('(?:[^']|'')*')\s*;",
        ddl_text,
        re.IGNORECASE,
    ):
        result["tables"][m.group(1)] = _unquote_sql_string(m.group(2))

    # COMMENT ON COLUMN <schema>.foo.bar IS '...';
    for m in re.finditer(
        r'COMMENT\s+ON\s+COLUMN\s+(?:"?\w+"?\.)?"?(\w+)"?\.\s*"?(\w+)"?\s+IS\s+'
        r"('(?:[^']|'')*')\s*;",
        ddl_text,
        re.IGNORECASE,
    ):
        table, column, raw = m.group(1), m.group(2), m.group(3)
        result["columns"].setdefault(table, {})[column] = _unquote_sql_string(raw)

    # COMMENT ON VIEW / MATERIALIZED VIEW <schema>.foo IS '...';
    for m in re.finditer(
        rf"COMMENT\s+ON\s+(?:MATERIALIZED\s+)?VIEW\s+{qualified}\s+IS\s+"
        r"('(?:[^']|'')*')\s*;",
        ddl_text,
        re.IGNORECASE,
    ):
        result["views"][m.group(1)] = _unquote_sql_string(m.group(2))

    return result


def extract_tables(statements: list) -> dict:
    """Extract table definitions from sqlglot CREATE TABLE AST nodes."""
    tables = {}

    for stmt in statements:
        if not isinstance(stmt, exp.Create):
            continue
        if stmt.args.get("kind") != "TABLE":
            continue

        schema_node = stmt.find(exp.Schema)
        if not schema_node:
            continue

        table_expr = schema_node.find(exp.Table)
        if not table_expr:
            continue

        table_name = strip_public(table_expr.sql(dialect="postgres"))

        columns = []
        for col_def in schema_node.find_all(exp.ColumnDef):
            col_name = col_def.alias_or_name.replace('"', '')

            col_kind = col_def.args.get("kind")
            col_type = col_kind.sql(dialect="postgres") if col_kind else "unknown"

            nullable = True
            default = None
            generated = False

            for constraint in col_def.find_all(exp.ColumnConstraint):
                kind = constraint.args.get("kind")
                if isinstance(kind, exp.NotNullColumnConstraint):
                    nullable = False
                elif isinstance(kind, exp.DefaultColumnConstraint):
                    default = kind.this.sql(dialect="postgres") if kind.this else None
                elif hasattr(exp, "GeneratedAsIdentityColumnConstraint") and isinstance(
                    kind, exp.GeneratedAsIdentityColumnConstraint
                ):
                    generated = True
                elif hasattr(exp, "GeneratedAsRowColumnConstraint") and isinstance(
                    kind, exp.GeneratedAsRowColumnConstraint
                ):
                    generated = True

            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "default": default,
                "generated": generated,
            })

        tables[table_name] = {
            "columns": columns,
            "primary_key": [],
            "unique_constraints": [],
            "indexes": [],
            "foreign_keys_out": [],
            "referenced_by": [],
        }

    return tables


def parse_ddl(ddl_text: str, dialect: str) -> list:
    """Parse DDL text into sqlglot AST statements."""
    return sqlglot.parse(ddl_text, dialect=dialect, error_level=ErrorLevel.WARN)
