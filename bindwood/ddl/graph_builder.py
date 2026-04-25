"""Assemble the complete DDL graph from extracted components."""

from __future__ import annotations

from datetime import datetime

from .parser import parse_ddl, extract_tables, extract_enums, extract_comments, locate_spans
from .constraints import (
    extract_primary_keys,
    extract_unique_constraints,
    extract_foreign_keys,
    extract_indexes,
)
from .views import extract_views
from .mysql import extract_mysql_inline, extract_mysql_views
from .inline import extract_postgres_inline


def _table_source_text(name: str, table: dict) -> str:
    """Generate a structured text description of a table for embeddings."""
    lines = [f"Table: {name}"]
    if table.get("docstring"):
        lines.append(f"Description: {table['docstring']}")
    lines.append("Columns:")
    for col in table["columns"]:
        parts = [f"  - {col['name']}: {col['type']}"]
        if not col["nullable"]:
            parts.append("NOT NULL")
        if col["default"]:
            parts.append(f"DEFAULT {col['default']}")
        if col["generated"]:
            parts.append("GENERATED")
        if col.get("docstring"):
            parts.append(f"-- {col['docstring']}")
        lines.append(" ".join(parts))
    if table["primary_key"]:
        lines.append(f"Primary key: {', '.join(table['primary_key'])}")
    for fk in table["foreign_keys_out"]:
        lines.append(
            f"FK: {', '.join(fk['columns'])} -> {fk['references_table']}({', '.join(fk['references_columns'])})"
        )
    for uc in table["unique_constraints"]:
        lines.append(f"Unique: {', '.join(uc['columns'])}")
    return "\n".join(lines)


def _view_source_text(name: str, view: dict) -> str:
    """Generate a structured text description of a view for embeddings."""
    kind = "Materialized view" if view["materialized"] else "View"
    lines = [f"{kind}: {name}"]
    if view.get("docstring"):
        lines.append(f"Description: {view['docstring']}")
    if view.get("columns"):
        lines.append("Columns:")
        for col in view["columns"]:
            lines.append(f"  - {col['name']}: {col.get('type', 'unknown')}")
    if view.get("source_tables"):
        lines.append(f"Sources: {', '.join(view['source_tables'])}")
    if view.get("definition"):
        defn = view["definition"][:500]
        lines.append(f"Definition: {defn}")
    return "\n".join(lines)


def build_graph(ddl_text: str, dialect: str, source_path: str) -> dict:
    """Build the complete database graph from DDL text."""
    dialect_lc = (dialect or "").lower()
    is_mysql = dialect_lc == "mysql"

    # Phase 1a: sqlglot AST for CREATE TABLE (column definitions)
    statements = parse_ddl(ddl_text, dialect)
    tables = extract_tables(statements)

    # Phase 1b: locate CREATE statement spans. We run this before
    # constraint extraction because the MySQL path needs each table's
    # raw_source to parse inline PK/UK/KEY/FK rows.
    spans = locate_spans(ddl_text)
    for table_name, table_data in tables.items():
        span = spans["tables"].get(table_name, {})
        for key in ("line", "end_line", "byte_start", "byte_end", "content_hash", "source_preview", "raw_source"):
            if key in span:
                table_data[key] = span[key]

    # Phase 1c: constraints, enums, views, indexes — dialect-specific
    if is_mysql:
        enums: dict = {}  # MySQL declares enums inline as column types, not CREATE TYPE
        extract_mysql_inline(tables)
        # Views need to know all table/view names to resolve FROM/JOIN refs.
        known_names = set(tables.keys()) | set(spans["views"].keys())
        views = extract_mysql_views(ddl_text, known_names)
    else:
        # Postgres — supports both external ``ALTER TABLE ... ADD
        # CONSTRAINT`` form (pg_dump) and inline ``CREATE TABLE`` body
        # constraints (pgModeler output, hand-written DDL). Run both;
        # the inline extractor deduplicates against what ALTER TABLE
        # already added.
        enums = extract_enums(ddl_text)
        extract_primary_keys(ddl_text, tables)
        extract_unique_constraints(ddl_text, tables)
        extract_foreign_keys(ddl_text, tables)
        extract_postgres_inline(tables)

        # Known names come from our own span locator so any schema (public,
        # iam, stealthis, …) and any quoting style is handled uniformly.
        all_known_names = set(tables.keys()) | set(spans["views"].keys())
        views = extract_views(ddl_text, all_known_names)

        extract_indexes(ddl_text, tables, views)

    # Phase 1e: COMMENT ON statements -> docstrings on tables/columns/views.
    # Postgres-only syntax; MySQL docstrings come from inline COMMENT clauses
    # handled by extract_mysql_inline above.
    if not is_mysql:
        comments = extract_comments(ddl_text)
        for table_name, table_data in tables.items():
            table_data["docstring"] = comments["tables"].get(table_name)
            column_comments = comments["columns"].get(table_name, {})
            for col in table_data["columns"]:
                col["docstring"] = column_comments.get(col["name"])
        for view_name, view_data in views.items():
            view_data["docstring"] = comments["views"].get(view_name)
    else:
        # Ensure every column has a docstring key (None if MySQL didn't
        # annotate it) so downstream code can assume the field exists.
        for table_data in tables.values():
            table_data.setdefault("docstring", None)
            for col in table_data["columns"]:
                col.setdefault("docstring", None)
            # Normalise constraint list keys — extract_mysql_inline only
            # appends when there's a match, so tables without e.g. FKs
            # still need the empty list here for graph_builder's downstream
            # iteration over ``foreign_keys_out`` / ``referenced_by``.
            table_data.setdefault("primary_key", [])
            table_data.setdefault("unique_constraints", [])
            table_data.setdefault("indexes", [])
            table_data.setdefault("foreign_keys_out", [])
            table_data.setdefault("referenced_by", [])
        for view_data in views.values():
            view_data.setdefault("docstring", None)
    for view_name, view_data in views.items():
        span = spans["views"].get(view_name, {})
        for key in ("line", "end_line", "byte_start", "byte_end", "content_hash", "source_preview", "raw_source"):
            if key in span:
                view_data[key] = span[key]

    # Enums: promote from {name: [values]} to {name: {values, ...span}} so
    # coordinate fields travel with the enum.
    enums_enriched: dict[str, dict] = {}
    for enum_name, enum_values in enums.items():
        entry = {"values": enum_values}
        span = spans["enums"].get(enum_name, {})
        for key in ("line", "end_line", "byte_start", "byte_end", "content_hash", "source_preview", "raw_source"):
            if key in span:
                entry[key] = span[key]
        enums_enriched[enum_name] = entry
    enums = enums_enriched

    # Phase 2: generate source_text for embeddings
    for table_name, table_data in tables.items():
        table_data["source_text"] = _table_source_text(table_name, table_data)
    for view_name, view_data in views.items():
        view_data["source_text"] = _view_source_text(view_name, view_data)

    # Flat FK relationship list for graph traversal
    relationships = []
    for table_name, table_data in tables.items():
        for fk in table_data["foreign_keys_out"]:
            relationships.append({
                "from_table": table_name,
                "from_columns": fk["columns"],
                "to_table": fk["references_table"],
                "to_columns": fk["references_columns"],
                "constraint": fk["constraint"],
            })

    # View-to-table dependency edges
    view_dependencies = []
    for view_name, view_data in views.items():
        for source_table in view_data["source_tables"]:
            view_dependencies.append({
                "view": view_name,
                "depends_on": source_table,
                "materialized": view_data["materialized"],
            })

    mat_count = sum(1 for v in views.values() if v["materialized"])
    reg_count = len(views) - mat_count
    total_indexes = (
        sum(len(t["indexes"]) for t in tables.values())
        + sum(len(v["indexes"]) for v in views.values())
    )

    return {
        "metadata": {
            "extracted_at": datetime.now().isoformat(),
            "source": source_path,
            "total_tables": len(tables),
            "total_views": len(views),
            "total_materialized_views": mat_count,
            "total_regular_views": reg_count,
            "total_enums": len(enums),
            "total_foreign_keys": len(relationships),
            "total_indexes": total_indexes,
        },
        "enums": enums,
        "tables": tables,
        "views": views,
        "relationships": relationships,
        "view_dependencies": view_dependencies,
    }
