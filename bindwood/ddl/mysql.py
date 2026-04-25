"""MySQL-specific DDL extractors.

The Postgres path (``constraints.py``, ``views.py``) keys off
``ALTER TABLE ONLY public.<name> ADD CONSTRAINT ...``, which MySQL dumps
never emit. MySQL declares PK/UK/KEY/FK **inline** inside the
``CREATE TABLE`` block, and uses backtick-quoted identifiers. This
module parses those inline constraint rows out of the raw CREATE TABLE
text stored in ``table["raw_source"]`` by ``locate_spans`` and fills
the same dict shape the Postgres extractors produce.

Column definitions themselves are already extracted via the sqlglot AST
in ``parser.extract_tables`` — this module only handles the bits the
AST path doesn't cover cleanly (docstrings on columns, table comments,
and the constraint/index rows that follow the column list).
"""

from __future__ import annotations

import re


# Matches an inline COMMENT 'xxx' clause (MySQL allows doubled '' to
# escape an apostrophe inside the string).
_COMMENT_CLAUSE = re.compile(r"COMMENT\s+'((?:[^']|'')*)'", re.IGNORECASE)


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("`", '"'):
        s = s[1:-1]
    return s


def _split_columns(col_expr: str) -> list[str]:
    """Split a column list on top-level commas (ignoring commas inside ())."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for c in col_expr:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(c)
    if buf:
        parts.append("".join(buf).strip())
    # strip backtick/double-quote wrappers and any trailing index-prefix
    # length (``col(255)``), which MySQL allows on KEY definitions.
    out = []
    for p in parts:
        p = re.sub(r"\(\d+\)\s*$", "", p).strip()
        out.append(_unquote(p))
    return [p for p in out if p]


def _split_body_lines(body: str) -> list[str]:
    """Split the inside of a CREATE TABLE on top-level commas.

    Preserves content inside parens (for KEY ``(col1, col2)``) and inside
    single-quoted strings (for COMMENT 'has, a comma').
    """
    parts: list[str] = []
    depth = 0
    in_string = False
    buf: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
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


def _extract_body_and_trailer(raw: str) -> tuple[str, str] | None:
    """Return the inside of ``CREATE TABLE ... ( ... ) trailer;``.

    Finds the first ``(`` and its matching ``)``; ``trailer`` is the text
    after that ``)`` (where MySQL puts ``ENGINE=InnoDB COMMENT='x'`` etc.)
    """
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
                return raw[start + 1 : i], raw[i + 1 :]
    return None


_PK_RE = re.compile(r"^PRIMARY\s+KEY\s*\(([^)]*)\)", re.IGNORECASE)
_UNIQUE_RE = re.compile(
    r"^(?:UNIQUE\s+(?:KEY|INDEX)?\s*)(?:`([^`]+)`|\"([^\"]+)\"|(\w+))?\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_KEY_RE = re.compile(
    r"^(?:KEY|INDEX)\s+(?:`([^`]+)`|\"([^\"]+)\"|(\w+))\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_FK_RE = re.compile(
    r"^(?:CONSTRAINT\s+(?:`([^`]+)`|\"([^\"]+)\"|(\w+))\s+)?"
    r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*"
    r"REFERENCES\s+(?:(?:`[^`]+`|\"[^\"]+\"|\w+)\.)?"
    r"(?:`([^`]+)`|\"([^\"]+)\"|(\w+))\s*\(([^)]*)\)"
    r"(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def extract_mysql_inline(tables: dict) -> None:
    """Populate PK / unique / index / FK and column docstrings for MySQL tables.

    Expects each entry in ``tables`` to have ``raw_source`` already
    populated by ``locate_spans`` — that is the text of the full
    ``CREATE TABLE ... ;`` statement.
    """
    for name, table in tables.items():
        raw = table.get("raw_source") or ""
        parts = _extract_body_and_trailer(raw)
        if not parts:
            continue
        body, trailer = parts

        # Table-level COMMENT='...' in the trailer (after the closing paren).
        m = _COMMENT_CLAUSE.search(trailer)
        if m:
            table["docstring"] = m.group(1).replace("''", "'")

        # Build a lookup of existing column dicts so we can annotate them
        # with inline COMMENT clauses without depending on line order.
        col_by_name = {c["name"]: c for c in table.get("columns", [])}

        for line in _split_body_lines(body):
            upper = line.upper().lstrip()

            if upper.startswith("PRIMARY KEY"):
                mm = _PK_RE.match(line)
                if mm:
                    table["primary_key"] = _split_columns(mm.group(1))
                continue

            if upper.startswith("UNIQUE"):
                mm = _UNIQUE_RE.match(line)
                if mm:
                    uname = mm.group(1) or mm.group(2) or mm.group(3) or ""
                    cols = _split_columns(mm.group(4))
                    table.setdefault("unique_constraints", []).append(
                        {"name": uname, "columns": cols}
                    )
                continue

            if upper.startswith("CONSTRAINT") or upper.startswith("FOREIGN KEY"):
                mm = _FK_RE.match(line)
                if mm:
                    cname = mm.group(1) or mm.group(2) or mm.group(3) or ""
                    from_cols = _split_columns(mm.group(4))
                    ref_table = mm.group(5) or mm.group(6) or mm.group(7) or ""
                    ref_cols = _split_columns(mm.group(8))
                    trailer_text = mm.group(9) or ""
                    fk: dict = {
                        "constraint": cname,
                        "columns": from_cols,
                        "references_table": ref_table,
                        "references_columns": ref_cols,
                    }
                    on_delete = re.search(
                        r"ON\s+DELETE\s+((?:NO\s+ACTION|SET\s+NULL|SET\s+DEFAULT|CASCADE|RESTRICT))",
                        trailer_text,
                        re.IGNORECASE,
                    )
                    on_update = re.search(
                        r"ON\s+UPDATE\s+((?:NO\s+ACTION|SET\s+NULL|SET\s+DEFAULT|CASCADE|RESTRICT))",
                        trailer_text,
                        re.IGNORECASE,
                    )
                    if on_delete:
                        fk["on_delete"] = re.sub(r"\s+", " ", on_delete.group(1)).upper()
                    if on_update:
                        fk["on_update"] = re.sub(r"\s+", " ", on_update.group(1)).upper()
                    table.setdefault("foreign_keys_out", []).append(fk)
                    if ref_table in tables:
                        tables[ref_table].setdefault("referenced_by", []).append({
                            "constraint": cname,
                            "from_table": name,
                            "from_columns": from_cols,
                        })
                continue

            if upper.startswith("KEY") or upper.startswith("INDEX"):
                mm = _KEY_RE.match(line)
                if mm:
                    kname = mm.group(1) or mm.group(2) or mm.group(3) or ""
                    cols = _split_columns(mm.group(4))
                    table.setdefault("indexes", []).append({
                        "name": kname,
                        "columns": cols,
                        "unique": False,
                        "method": "btree",
                    })
                continue

            # Column definition — pull inline COMMENT onto the matching col.
            cm = _COMMENT_CLAUSE.search(line)
            if cm:
                head = line.strip().split(None, 1)[0]
                col_name = _unquote(head)
                if col_name in col_by_name:
                    col_by_name[col_name]["docstring"] = cm.group(1).replace("''", "'")


# ── Views ────────────────────────────────────────────────────

_VIEW_HEADER_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:ALGORITHM\s*=\s*\w+\s+)?"
    r"(?:DEFINER\s*=\s*[^\s]+\s+)?"
    r"(?:SQL\s+SECURITY\s+(?:DEFINER|INVOKER)\s+)?"
    r"VIEW\s+(?:`([^`]+)`|\"([^\"]+)\"|(\w+))\.(?:`([^`]+)`|\"([^\"]+)\"|(\w+))"
    r"|CREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:ALGORITHM\s*=\s*\w+\s+)?"
    r"(?:DEFINER\s*=\s*[^\s]+\s+)?"
    r"(?:SQL\s+SECURITY\s+(?:DEFINER|INVOKER)\s+)?"
    r"VIEW\s+(?:`([^`]+)`|\"([^\"]+)\"|(\w+))",
    re.IGNORECASE,
)


def extract_mysql_views(ddl_text: str, known_names: set[str]) -> dict:
    """Extract MySQL ``CREATE VIEW`` definitions.

    Returns a dict of the same shape ``bindwood.ddl.views.extract_views``
    produces so graph_builder can consume either.
    """
    views: dict[str, dict] = {}

    # Walk each ``CREATE VIEW`` header, then grab up to the next top-level ``;``.
    for m in _VIEW_HEADER_RE.finditer(ddl_text):
        # Header regex has two alternates (schema-qualified and bare);
        # groups 4-6 are the bare-identifier variant of the second alternate.
        groups = m.groups()
        name = (
            groups[3] or groups[4] or groups[5]   # schema.viewname variant
            or groups[6] or groups[7] or groups[8]  # bare viewname variant
        )
        if not name:
            continue

        # Find the end of this view statement (first top-level ``;``).
        end = ddl_text.find(";", m.end())
        if end < 0:
            continue
        body = ddl_text[m.end(): end]

        source_tables = set()
        # Match bare, backticked, and double-quoted references.
        for ref in re.findall(r"(?:`([^`]+)`|\"([^\"]+)\"|(\w+))", body):
            candidate = next((r for r in ref if r), "")
            if candidate in known_names:
                source_tables.add(candidate)
        source_tables.discard(name)

        views[name] = {
            "materialized": False,  # MySQL has no materialized views
            "columns": [],           # MySQL dumps don't annotate view columns; leave empty
            "source_tables": sorted(source_tables),
            "indexes": [],
        }

    return views
