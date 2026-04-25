"""Report generator — per-type, per-fixture token tables + judge verdicts."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _fmt_delta(base: float, bw: float) -> str:
    if base == 0:
        return "n/a"
    delta = bw - base
    pct = delta / base * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:,.0f} ({sign}{pct:.1f}%)"


def _tool_summary(tool_calls: list[dict[str, Any]]) -> str:
    counts: Counter[str] = Counter(tc.get("name", "?") for tc in tool_calls)
    return " ".join(f"{name}×{cnt}" for name, cnt in counts.most_common())


def _winner_label(judge: dict[str, Any] | None) -> str:
    if not judge:
        return "-"
    if judge.get("error"):
        return "err"
    w = judge.get("winner", "tie")
    return {"baseline": "base", "bindwood": "bw", "tie": "tie", "error": "err"}.get(w, w)


def _print_fixture_table(
    *,
    header: str,
    rows: list[dict[str, Any]],
) -> tuple[int, int, Counter[str]]:
    """Print one fixture's table; return (base_sum, bw_sum, win_counter)."""
    try:
        from tabulate import tabulate  # type: ignore[import]
    except ImportError:
        print("Install tabulate: pip install tabulate")
        return 0, 0, Counter()

    table: list[list[Any]] = []
    base_sum = 0.0
    bw_sum = 0.0
    wins: Counter[str] = Counter()

    for r in rows:
        base = r["baseline"]
        bw = r["bindwood"]
        judge = r.get("judge")

        # Effective tokens weights cache creation (1.25×) and cache read (0.1×)
        # against raw input+output, giving one cost-accurate number.
        base_tok = float(base["usage"].get("effective_tokens") or base["usage"]["total_tokens"])
        bw_tok = float(bw["usage"].get("effective_tokens") or bw["usage"]["total_tokens"])
        base_sum += base_tok
        bw_sum += bw_tok

        winner = _winner_label(judge)
        if winner in ("base", "bw", "tie"):
            wins[winner] += 1

        table.append([
            r["question"]["id"],
            f"{base_tok:,.0f}",
            f"{bw_tok:,.0f}",
            _fmt_delta(base_tok, bw_tok),
            _tool_summary(base["tool_calls"]) or "-",
            _tool_summary(bw["tool_calls"]) or "-",
            f"{base['elapsed_seconds']:.0f}/{bw['elapsed_seconds']:.0f}s",
            winner,
        ])

    table.append([
        "SUBTOTAL",
        f"{base_sum:,.0f}",
        f"{bw_sum:,.0f}",
        _fmt_delta(base_sum, bw_sum),
        "",
        "",
        "",
        f"b={wins['base']} w={wins['bw']} t={wins['tie']}",
    ])

    print("\n" + "─" * 100)
    print(header)
    print("─" * 100)
    print(tabulate(
        table,
        headers=["Q", "Base eff", "BW eff", "Δ", "Base tools", "BW tools", "Wall", "Judge"],
        tablefmt="rounded_outline",
    ))
    return base_sum, bw_sum, wins


def print_full_report(all_results: list[dict[str, Any]]) -> None:
    if not all_results:
        print("No results to report.")
        return

    # Group: type → fixture name → rows
    by_type: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in all_results:
        by_type.setdefault(r["type"], {}).setdefault(r["repo"], []).append(r)

    overall_base = 0.0
    overall_bw = 0.0
    overall_wins: Counter[str] = Counter()
    per_type_totals: dict[str, tuple[float, float, Counter[str]]] = {}

    for rtype in sorted(by_type):
        print("\n" + "=" * 100)
        print(f"TYPE: {rtype.upper()}")
        print("=" * 100)

        type_base = 0.0
        type_bw = 0.0
        type_wins: Counter[str] = Counter()

        for repo_name in sorted(by_type[rtype]):
            rows = by_type[rtype][repo_name]
            base, bw, wins = _print_fixture_table(
                header=f"Fixture: {repo_name}  ({len(rows)} question(s))",
                rows=rows,
            )
            type_base += base
            type_bw += bw
            type_wins.update(wins)

        per_type_totals[rtype] = (type_base, type_bw, type_wins)
        overall_base += type_base
        overall_bw += type_bw
        overall_wins.update(type_wins)

    # Per-type rollup.
    print("\n" + "=" * 100)
    print("PER-TYPE ROLLUP")
    print("=" * 100)
    try:
        from tabulate import tabulate  # type: ignore[import]
        rollup: list[list[Any]] = []
        for rtype, (b, w, wc) in per_type_totals.items():
            rollup.append([
                rtype,
                f"{b:,.0f}",
                f"{w:,.0f}",
                _fmt_delta(b, w),
                f"base={wc['base']} bw={wc['bw']} tie={wc['tie']}",
            ])
        rollup.append([
            "OVERALL",
            f"{overall_base:,.0f}",
            f"{overall_bw:,.0f}",
            _fmt_delta(overall_base, overall_bw),
            f"base={overall_wins['base']} bw={overall_wins['bw']} tie={overall_wins['tie']}",
        ])
        print(tabulate(
            rollup,
            headers=["Type", "Base eff", "BW eff", "Δ", "Judge"],
            tablefmt="rounded_outline",
        ))
    except ImportError:
        print(f"Baseline total: {overall_base:,.0f}  Bindwood total: {overall_bw:,.0f}")


def save_results(
    all_results: list[dict[str, Any]],
    output_path: Path,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    def _raw(r: dict[str, Any], cond: str) -> int:
        return r[cond]["usage"]["total_tokens"]

    def _eff(r: dict[str, Any], cond: str) -> float:
        u = r[cond]["usage"]
        return float(u.get("effective_tokens") or u["total_tokens"])

    total_base_raw = sum(_raw(r, "baseline") for r in all_results)
    total_bw_raw = sum(_raw(r, "bindwood") for r in all_results)
    total_base_eff = sum(_eff(r, "baseline") for r in all_results)
    total_bw_eff = sum(_eff(r, "bindwood") for r in all_results)

    wins: Counter[str] = Counter()
    for r in all_results:
        j = r.get("judge")
        if j and not j.get("error"):
            wins[j.get("winner", "tie")] += 1

    by_type: Counter[str] = Counter(r["type"] for r in all_results)

    duration_s: float | None = None
    if started_at and finished_at:
        duration_s = round((finished_at - started_at).total_seconds(), 2)

    data = {
        "run_metadata": {
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "duration_seconds": duration_s,
        },
        "runs": all_results,
        "summary": {
            "baseline_total_tokens": total_base_raw,
            "bindwood_total_tokens": total_bw_raw,
            "baseline_effective_tokens": round(total_base_eff, 1),
            "bindwood_effective_tokens": round(total_bw_eff, 1),
            "tokens_delta": total_bw_raw - total_base_raw,
            "effective_tokens_delta": round(total_bw_eff - total_base_eff, 1),
            "savings_pct": round((total_base_raw - total_bw_raw) / total_base_raw * 100, 2)
            if total_base_raw
            else 0,
            "effective_savings_pct": round(
                (total_base_eff - total_bw_eff) / total_base_eff * 100, 2
            )
            if total_base_eff
            else 0,
            "judge_wins": dict(wins),
            "runs_count": len(all_results),
            "runs_by_type": dict(by_type),
        },
    }
    output_path.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved to {output_path}")
