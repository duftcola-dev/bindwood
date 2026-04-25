"""Question bank for the benchmark.

Questions are tagged with ``applies_to`` — the fixture types they're meant
for. The code-oriented bank (Python / JS / TS) reuses one shared set of
structural questions; DDL fixtures get their own SQL-schema bank since
"call chain", "imports", etc. don't apply.

Tiers:
  - orientation   : "what is in this codebase/schema?"
  - lookup        : "where is X?"
  - structural    : "how does X connect to Y?"
  - cross_cutting : "find everything that does X"
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Canonical fixture types recognized by the harness.
CODE_TYPES = ("python", "javascript", "typescript")
DDL_TYPES = ("ddl",)
ALL_TYPES = CODE_TYPES + DDL_TYPES


@dataclass
class Question:
    id: str
    tier: str
    text: str
    applies_to: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
# Code question bank (Python / JavaScript / TypeScript)
# ────────────────────────────────────────────────────────────────────────────

_CODE: list[Question] = [
    # Orientation
    Question(
        id="orient_1",
        tier="orientation",
        text=(
            "Give me an overview of this codebase: what are the main modules or packages, "
            "roughly how many files are there, and what does each top-level directory contain?"
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="orient_2",
        tier="orientation",
        text="List every public class defined in this project along with the file it lives in.",
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="orient_3",
        tier="orientation",
        text=(
            "What entry points does this project expose? "
            "Look for CLI commands, HTTP routes, public module-level functions, or __main__ blocks."
        ),
        applies_to=list(CODE_TYPES),
    ),
    # Lookup
    Question(
        id="lookup_1",
        tier="lookup",
        text=(
            "Find every function whose name contains 'parse'. "
            "For each match, show the function name, file, and line number."
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="lookup_2",
        tier="lookup",
        text=(
            "Find the module that exposes this project's main public API to end users. "
            "Show its path and list the top-level public names it exports."
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="lookup_3",
        tier="lookup",
        text=(
            "List all functions or methods related to configuration management "
            "(loading, saving, validating, or resetting configuration)."
        ),
        applies_to=list(CODE_TYPES),
    ),
    # Structural
    Question(
        id="struct_1",
        tier="structural",
        text=(
            "Pick the most central module in this project — the one most other modules "
            "depend on. What does it import, and which modules import it?"
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="struct_2",
        tier="structural",
        text=(
            "Trace the call chain from a top-level public API function down to low-level I/O "
            "(network, file, or database). What are the intermediate layers?"
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="struct_3",
        tier="structural",
        text=(
            "Which functions are responsible for low-level I/O — executing network requests, "
            "reading/writing files, or running database queries? Show their names and files."
        ),
        applies_to=list(CODE_TYPES),
    ),
    # Cross-cutting
    Question(
        id="cross_1",
        tier="cross_cutting",
        text=(
            "Find all places where error handling occurs (try/except blocks or explicit error "
            "returns). List the file, function, and a one-line description of what each handles."
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="cross_2",
        tier="cross_cutting",
        text=(
            "Identify all external dependencies this project calls at runtime "
            "(third-party libraries, network endpoints, subprocesses). "
            "Which parts of the codebase are responsible for each?"
        ),
        applies_to=list(CODE_TYPES),
    ),
    Question(
        id="cross_3",
        tier="cross_cutting",
        text=(
            "Find every public API surface: exported functions, classes, or constants intended "
            "for external consumers. Where are they defined and how are they re-exported?"
        ),
        applies_to=list(CODE_TYPES),
    ),
]


# ────────────────────────────────────────────────────────────────────────────
# DDL / SQL-schema question bank
# ────────────────────────────────────────────────────────────────────────────

_DDL: list[Question] = [
    # Orientation
    Question(
        id="ddl_orient_1",
        tier="orientation",
        text=(
            "Give me an overview of this database schema: how many tables are there, and what "
            "are the major entity groups or domains (e.g. users, orders, billing)? Group the "
            "tables by purpose."
        ),
        applies_to=list(DDL_TYPES),
    ),
    Question(
        id="ddl_orient_2",
        tier="orientation",
        text=(
            "List every table in this schema along with its primary key column(s). "
            "Flag any tables that have no primary key."
        ),
        applies_to=list(DDL_TYPES),
    ),
    # Lookup
    Question(
        id="ddl_lookup_1",
        tier="lookup",
        text=(
            "List every foreign-key relationship in this schema. "
            "For each FK, show source_table.column → target_table.column."
        ),
        applies_to=list(DDL_TYPES),
    ),
    Question(
        id="ddl_lookup_2",
        tier="lookup",
        text=(
            "Find all tables that contain a column whose name ends in '_id' or is named 'id'. "
            "For each, show the column name and type."
        ),
        applies_to=list(DDL_TYPES),
    ),
    # Structural
    Question(
        id="ddl_struct_1",
        tier="structural",
        text=(
            "Pick the most central table in this schema — the one with the most incoming "
            "foreign keys. List the tables that reference it and the tables it references."
        ),
        applies_to=list(DDL_TYPES),
    ),
    # Cross-cutting
    Question(
        id="ddl_cross_1",
        tier="cross_cutting",
        text=(
            "Pick one foreign key in this schema. If that FK column were dropped, which tables "
            "and queries would be affected? Describe the impact in terms of which relationships "
            "break and which orphan rows become possible."
        ),
        applies_to=list(DDL_TYPES),
    ),
]


DEFAULT_QUESTIONS: list[Question] = _CODE + _DDL


def questions_by_tier(tier: str) -> list[Question]:
    return [q for q in DEFAULT_QUESTIONS if q.tier == tier]


def questions_by_ids(ids: list[str]) -> list[Question]:
    index = {q.id: q for q in DEFAULT_QUESTIONS}
    return [index[i] for i in ids if i in index]


def questions_for_type(fixture_type: str) -> list[Question]:
    """Return the questions that apply to a fixture of the given type."""
    return [q for q in DEFAULT_QUESTIONS if fixture_type in q.applies_to]
