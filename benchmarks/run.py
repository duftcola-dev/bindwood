"""CLI entry point: iterate (fixture, question) × {baseline, bindwood}, judge, report.

Example
-------
Full matrix (all fixtures, all applicable questions, with judging):

    python -m benchmarks.run --fixtures benchmarks/fixtures.toml

Subset:

    python -m benchmarks.run --fixtures benchmarks/fixtures.toml \
        --types python --repos p-example-1 --questions lookup_1,struct_2 --no-judge
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.harness import (
    BASELINE_TOOLS,
    BINDWOOD_TOOLS,
    RunResult,
    run_claude_code,
)
from benchmarks.questions import (
    ALL_TYPES,
    DEFAULT_QUESTIONS,
    Question,
    questions_by_ids,
    questions_by_tier,
    questions_for_type,
)
from benchmarks.repos import (
    FixtureConfig,
    Repo,
    allowed_dirs,
    load_fixtures,
    write_shared_mcp_config,
)  # noqa: F401 — FixtureConfig kept for downstream typing
from benchmarks.report import print_full_report, save_results
from benchmarks.rubric import JudgeResult, judge_ab


def _select_questions(
    all_for_type: list[Question],
    tiers: list[str] | None,
    ids: list[str] | None,
) -> list[Question]:
    """Filter a per-type question list by tier and/or id."""
    out = all_for_type
    if tiers:
        out = [q for q in out if q.tier in tiers]
    if ids:
        id_set = set(ids)
        out = [q for q in out if q.id in id_set]
    return out


def _select_repos(
    cfg: FixtureConfig,
    wanted_names: list[str] | None,
    wanted_types: list[str] | None,
) -> list[Repo]:
    repos = cfg.repos
    if wanted_types:
        bad = [t for t in wanted_types if t not in ALL_TYPES]
        if bad:
            print(
                f"Error: unknown type(s): {bad}. Expected one of {list(ALL_TYPES)}",
                file=sys.stderr,
            )
            sys.exit(1)
        repos = [r for r in repos if r.type in wanted_types]
    if wanted_names:
        by_name = {r.name: r for r in repos}
        missing = [n for n in wanted_names if n not in by_name]
        if missing:
            print(
                f"Error: repos not found after type filter: {missing}. "
                f"Available: {list(by_name)}",
                file=sys.stderr,
            )
            sys.exit(1)
        repos = [by_name[n] for n in wanted_names]
    if not repos:
        print("Error: repo filters left nothing to run.", file=sys.stderr)
        sys.exit(1)
    return repos


def _build_context_prompt(repo: Repo, question_text: str) -> str:
    """Prepend a small context line identical to both conditions.

    Naming the path (not bindwood's target) keeps the hint symmetric — the
    baseline can Read it, and bindwood can match it to a target via
    graph_overview. No bindwood-specific terminology leaks to the baseline.
    """
    if repo.type == "ddl":
        context = f"Context: SQL schema file at {repo.path}"
    else:
        context = f"Context: {repo.type} project rooted at {repo.path}"
    return f"{context}\n\n{question_text}"


def _run_one_condition(
    *,
    condition: str,
    repo: Repo,
    question: Question,
    mcp_config: Path | None,
    tools: str,
    model: str | None,
    timeout_s: int,
) -> RunResult:
    prompt = _build_context_prompt(repo, question.text)
    cwd_like = allowed_dirs(repo)[0]
    r = run_claude_code(
        condition=condition,
        repo=repo.name,
        question_id=question.id,
        question=prompt,
        repo_path=cwd_like,
        mcp_config=mcp_config,
        tools=tools,
        model=model,
        timeout_s=timeout_s,
    )
    _echo_run(r)
    return r


def _echo_run(r: RunResult) -> None:
    if r.error:
        print(f"      ERROR: {r.error}")
        return
    print(
        f"      turns={r.turns}  tool_calls={len(r.tool_calls)}  "
        f"tokens={r.usage.total_tokens:,}  elapsed={r.elapsed_seconds:.1f}s"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Headless Claude Code benchmark: baseline vs bindwood MCP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("benchmarks/fixtures.toml"),
        help="Path to the fixtures TOML file (default: benchmarks/fixtures.toml).",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        choices=list(ALL_TYPES),
        default=None,
        help="Only run fixtures of these types (ddl/python/javascript/typescript).",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=None,
        help="Only run these fixture names (applied after --types filter).",
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=["orientation", "lookup", "structural", "cross_cutting"],
        default=None,
        help="Only run questions from these tiers.",
    )
    parser.add_argument(
        "--questions",
        type=lambda s: s.split(","),
        default=None,
        help="Comma-separated question IDs (e.g. lookup_1,ddl_struct_1).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the Claude model (passed through to `claude --model`).",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=900,
        help="Per-run subprocess timeout, seconds (default: 900).",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the A/B judge LLM call.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Where to write the JSON results file. "
            "Default: benchmark_results.<UTC-timestamp>.json so successive runs "
            "don't overwrite each other."
        ),
    )
    parser.add_argument(
        "--mcp-cache-dir",
        type=Path,
        default=Path("benchmarks/.mcp_configs"),
        help="Where to write the shared .mcp.json (auto-created).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the runs that would happen without executing them.",
    )

    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc)
    # File-safe UTC stamp, e.g. 20260425T141233Z. If the user passed --output
    # explicitly, we honor it as-is; otherwise auto-suffix so back-to-back runs
    # don't clobber each other.
    if args.output is None:
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        args.output = Path(f"benchmark_results.{stamp}.json")

    cfg = load_fixtures(args.fixtures.resolve())
    repos = _select_repos(cfg, args.repos, args.types)

    # Resolve per-fixture question sets up front so --dry-run shows the truth.
    planned: list[tuple[Repo, list[Question]]] = []
    for r in repos:
        per_type = questions_for_type(r.type)
        selected = _select_questions(per_type, args.tiers, args.questions)
        if selected:
            planned.append((r, selected))

    if not planned:
        print("Nothing to run — filters eliminated every (fixture, question) pair.", file=sys.stderr)
        sys.exit(1)

    total_runs = sum(len(qs) for _, qs in planned)
    print(
        f"\nPlan: {len(planned)} fixture(s), {total_runs} question(s) total "
        f"→ {total_runs * 2} Claude Code runs"
        + ("" if args.no_judge else f" + {total_runs} judge calls"),
    )

    if args.dry_run:
        for r, qs in planned:
            for q in qs:
                print(f"  {r.type:10s} {r.name:15s} :: {q.id} ({q.tier})")
        return

    mcp_config = write_shared_mcp_config(args.mcp_cache_dir.resolve())
    print(f"Using shared MCP config: {mcp_config}")

    all_results: list[dict] = []

    for repo, questions in planned:
        print(f"\n=== Fixture: {repo.name} [{repo.type}] ({repo.path}) ===")
        for q in questions:
            print(f"  [{q.id}] baseline …", flush=True)
            baseline = _run_one_condition(
                condition="baseline",
                repo=repo,
                question=q,
                mcp_config=None,
                tools=BASELINE_TOOLS,
                model=args.model,
                timeout_s=args.timeout_s,
            )
            print(f"  [{q.id}] bindwood …", flush=True)
            bindwood = _run_one_condition(
                condition="bindwood",
                repo=repo,
                question=q,
                mcp_config=mcp_config,
                tools=BINDWOOD_TOOLS,
                model=args.model,
                timeout_s=args.timeout_s,
            )

            judge: JudgeResult | None = None
            if not args.no_judge and not baseline.error and not bindwood.error:
                print(f"  [{q.id}] judging …", flush=True)
                judge = judge_ab(
                    repo=repo.name,
                    question=q.text,
                    baseline_answer=baseline.answer,
                    bindwood_answer=bindwood.answer,
                )
                if judge.error:
                    print(f"      judge error: {judge.error}")
                else:
                    print(f"      winner={judge.winner}  — {judge.reasoning[:100]}")

            all_results.append({
                "repo": repo.name,
                "type": repo.type,
                "target": repo.target,
                "path": str(repo.path),
                "question": {"id": q.id, "tier": q.tier, "text": q.text},
                "baseline": baseline.to_dict(),
                "bindwood": bindwood.to_dict(),
                "judge": judge.to_dict() if judge else None,
            })

    finished_at = datetime.now(timezone.utc)
    print_full_report(all_results)
    save_results(
        all_results,
        args.output,
        started_at=started_at,
        finished_at=finished_at,
    )


if __name__ == "__main__":
    main()
