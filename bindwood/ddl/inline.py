"""Postgres inline constraint extractor.

Many Postgres dialects / dump tools (pgModeler, raw hand-written DDL,
pg_dump with ``--column-inserts`` etc.) declare PK / UK / FK **inside**
the ``CREATE TABLE`` body rather than via ``ALTER TABLE ... ADD
CONSTRAINT``. Both forms can also coexist in a single file.

``constraints.py`` handles the ``ALTER TABLE`` form. This module walks
each table's raw source (populated by ``locate_spans``) and fills the
same ``tables[name]`` dicts from:

* column-level constraints — ``col type [NOT NULL] PRIMARY KEY``,
  ``UNIQUE``, ``REFERENCES schema.table(col) [ON DELETE …]``.
* table-level constraints — ``[CONSTRAINT name] PRIMARY KEY (…)``,
  ``UNIQUE (…)``, ``FOREIGN KEY (…) REFERENCES …``.

Where an ``ALTER TABLE`` statement elsewhere in the file already set
the same constraint (same column set for a PK, same constraint name
for FK/UK), the inline pass deduplicates so we don't produce two
entries for the same real-world constraint.
"""

from __future__ import annotations

import re


# Reference target: optional schema prefix + optional double-quote wrapping.
_REF_TARGET = r'(?:"?\w+"?\.)?"?(\w+)"?'

_TABLE_PK_RE = re.compile(
    r"^(?:CONSTRAINT\s+\"?(\w+)\"?\s+)?PRIMARY\s+KEY\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_TABLE_UQ_RE = re.compile(
    r"^(?:CONSTRAINT\s+\"?(\w+)\"?\s+)?UNIQUE\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_TABLE_FK_RE = re.compile(
    r"^(?:CONSTRAINT\s+\"?(\w+)\"?\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)\s*"
    rf"REFERENCES\s+{_REF_TARGET}\s*\(([^)]*)\)(.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Column-level references + actions. Applies to a column definition line.
_COL_REF_RE = re.compile(
    rf"REFERENCES\s+{_REF_TARGET}\s*(?:\(([^)]*)\))?(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_ON_DELETE_RE = re.compile(
    r"ON\s+DELETE\s+((?:NO\s+ACTION|SET\s+NULL|SET\s+DEFAULT|CASCADE|RESTRICT))",
    re.IGNORECASE,
)
_ON_UPDATE_RE = re.compile(
    r"ON\s+UPDATE\s+((?:NO\s+ACTION|SET\s+NULL|SET\s+DEFAULT|CASCADE|RESTRICT))",
    re.IGNORECASE,
)


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] == '"':
        s = s[1:-1]
    return s


def _split_columns(col_expr: str) -> list[str]:
    """Split a parenthesised column list on top-level commas."""
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    for c in col_expr:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(c)
    if buf:
        out.append("".join(buf).strip())
    return [_unquote(p) for p in out if p.strip()]


def _split_body_lines(body: str) -> list[str]:
    """Split a CREATE TABLE body on top-level commas, preserving parens and strings."""
    parts: list[str] = []
    depth = 0
    in_string = False
    dollar_tag: str | None = None
    buf: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if dollar_tag is not None:
            # Inside a $tag$ … $tag$ literal — copy verbatim until we see
            # the closing tag.
            buf.append(c)
            if c == "$" and body[i : i + len(dollar_tag)] == dollar_tag:
                buf.append(body[i + 1 : i + len(dollar_tag)])
                i += len(dollar_tag)
                dollar_tag = None
                continue
            i += 1
            continue
        if in_string:
            if c == "'":
                if i + 1 < n and body[i + 1] == "'":
                    buf.append("''")
                    i += 2
                    continue
                in_string = False
            buf.append(c)
            i += 1
            continue
        if c == "'":
            in_string = True
            buf.append(c)
        elif c == "$":
            m = re.match(r"\$\w*\$", body[i:])
            if m:
                dollar_tag = m.group(0)
                buf.append(dollar_tag)
                i += len(dollar_tag)
                continue
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _extract_body(raw: str) -> str | None:
    """Return the inside of ``CREATE TABLE ... ( ... );`` — balanced paren grab."""
    start = raw.find("(")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        c = raw[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return raw[start + 1 : i]
    return None


def _add_fk(
    tables: dict,
    from_table: str,
    to_table: str,
    from_cols: list[str],
    to_cols: list[str],
    constraint_name: str,
    trailer: str,
) -> None:
    """Append an FK to ``foreign_keys_out`` unless an equivalent already exists."""
    fk: dict = {
        "constraint": constraint_name,
        "columns": from_cols,
        "references_table": to_table,
        "references_columns": to_cols,
    }
    on_delete = _ON_DELETE_RE.search(trailer)
    on_update = _ON_UPDATE_RE.search(trailer)
    if on_delete:
        fk["on_delete"] = re.sub(r"\s+", " ", on_delete.group(1)).upper()
    if on_update:
        fk["on_update"] = re.sub(r"\s+", " ", on_update.group(1)).upper()

    existing = tables[from_table].setdefault("foreign_keys_out", [])
    for prior in existing:
        if (
            prior.get("columns") == from_cols
            and prior.get("references_table") == to_table
            and prior.get("references_columns") == to_cols
        ):
            return
    existing.append(fk)
    if to_table in tables:
        ref = tables[to_table].setdefault("referenced_by", [])
        for prior in ref:
            if (
                prior.get("from_table") == from_table
                and prior.get("from_columns") == from_cols
            ):
                return
        ref.append({
            "constraint": constraint_name,
            "from_table": from_table,
            "from_columns": from_cols,
        })


def extract_postgres_inline(tables: dict) -> None:
    """Populate PK / UK / FK from inline constraints in ``CREATE TABLE`` bodies.

    Runs *in addition* to the ALTER TABLE pass in ``constraints.py`` —
    both paths are idempotent and dedupe against what's already there.
    """
    for name, table in tables.items():
        raw = table.get("raw_source") or ""
        body = _extract_body(raw)
        if not body:
            continue

        col_names = {c["name"].lower() for c in table.get("columns", [])}

        for line in _split_body_lines(body):
            stripped = line.strip()
            upper = stripped.upper()

            # Table-level PK
            if upper.startswith("PRIMARY KEY") or (
                upper.startswith("CONSTRAINT") and "PRIMARY KEY" in upper
            ):
                mm = _TABLE_PK_RE.match(stripped)
                if mm:
                    cols = _split_columns(mm.group(2))
                    if cols and not table.get("primary_key"):
                        table["primary_key"] = cols
                    continue

            # Table-level UNIQUE
            if upper.startswith("UNIQUE") or (
                upper.startswith("CONSTRAINT") and re.search(r"\bUNIQUE\b", upper)
                and "FOREIGN KEY" not in upper and "PRIMARY KEY" not in upper
            ):
                mm = _TABLE_UQ_RE.match(stripped)
                if mm:
                    uname = mm.group(1) or ""
                    cols = _split_columns(mm.group(2))
                    existing = table.setdefault("unique_constraints", [])
                    if not any(uc.get("columns") == cols for uc in existing):
                        existing.append({"name": uname, "columns": cols})
                    continue

            # Table-level FK
            if upper.startswith("FOREIGN KEY") or (
                upper.startswith("CONSTRAINT") and "FOREIGN KEY" in upper
            ):
                mm = _TABLE_FK_RE.match(stripped)
                if mm:
                    cname = mm.group(1) or ""
                    from_cols = _split_columns(mm.group(2))
                    ref_table = mm.group(3)
                    ref_cols = _split_columns(mm.group(4))
                    trailer = mm.group(5) or ""
                    _add_fk(tables, name, ref_table, from_cols, ref_cols, cname, trailer)
                    continue

            # CHECK / EXCLUDE / LIKE — skip.
            if upper.startswith("CHECK") or upper.startswith("EXCLUDE") or upper.startswith("LIKE"):
                continue

            # Otherwise: column definition. First token = column name.
            m_head = re.match(r'\s*"?(\w+)"?\s', stripped)
            if not m_head:
                continue
            col_name = m_head.group(1)
            if col_name.lower() not in col_names:
                continue

            # Column-level PRIMARY KEY
            if re.search(r"\bPRIMARY\s+KEY\b", stripped, re.IGNORECASE):
                if not table.get("primary_key"):
                    table["primary_key"] = [col_name]

            # Column-level UNIQUE (but not ``NOT NULL UNIQUE`` on the same
            # line as REFERENCES — still counts as a UNIQUE constraint).
            # Exclude when UNIQUE belongs to a table-level constraint
            # starting the line (handled above).
            if re.search(r"\bUNIQUE\b", stripped, re.IGNORECASE):
                existing = table.setdefault("unique_constraints", [])
                cols = [col_name]
                if not any(uc.get("columns") == cols for uc in existing):
                    existing.append({"name": "", "columns": cols})

            # Column-level REFERENCES
            ref_match = _COL_REF_RE.search(stripped)
            if ref_match:
                ref_table = ref_match.group(1)
                ref_cols_raw = ref_match.group(2)
                trailer = ref_match.group(3) or ""
                # If the REFERENCES clause omits the column list, the
                # target is assumed to be the referenced table's primary
                # key. Record an empty list for now — the graph consumer
                # treats ``[]`` as "PK-of-target".
                ref_cols = _split_columns(ref_cols_raw) if ref_cols_raw else []
                _add_fk(tables, name, ref_table, [col_name], ref_cols, "", trailer)
