"""A/B judge for answer quality — Claude Code subprocess, no tools.

Spawns ``claude -p`` with ``--tools ""`` (no built-in tools) and no MCP
config, so the judge can only reason from the prompt text. Keeps the
benchmark on one transport (Claude Code for everything) and avoids a
parallel Anthropic SDK dependency.

A/B labels are randomized per call to avoid position bias, then mapped back
to ``baseline`` / ``bindwood`` on return.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any


_JUDGE_MODEL = "sonnet"  # Claude Code model alias; set to None to use the user default
_JUDGE_TIMEOUT_S = 120


_PROMPT = """\
You are an impartial judge comparing two answers (A and B) to the same question \
about the same codebase. You do not have access to the codebase — reason only \
from the answer text.

Score each answer 1-5 on:
  - completeness : does it cover what the question asked for?
  - accuracy     : are the specific claims (names, paths, numbers) internally consistent and plausible?
  - specificity  : does it give concrete identifiers and locations, not vague summaries?

Then pick a winner: "A", "B", or "tie".

Respond with ONLY a JSON object of this exact shape (no prose, no code fences):
{{"a": {{"completeness": <1-5>, "accuracy": <1-5>, "specificity": <1-5>}}, \
"b": {{"completeness": <1-5>, "accuracy": <1-5>, "specificity": <1-5>}}, \
"winner": "A" | "B" | "tie", "reasoning": "<one short sentence>"}}

Repo: {repo}
Question: {question}

--- Answer A ---
{answer_a}

--- Answer B ---
{answer_b}
"""


@dataclass
class JudgeScore:
    completeness: int
    accuracy: int
    specificity: int

    @property
    def total(self) -> int:
        return self.completeness + self.accuracy + self.specificity

    def to_dict(self) -> dict[str, int]:
        return {
            "completeness": self.completeness,
            "accuracy": self.accuracy,
            "specificity": self.specificity,
            "total": self.total,
        }


@dataclass
class JudgeResult:
    winner: str  # "baseline" | "bindwood" | "tie" | "error"
    reasoning: str
    baseline_score: JudgeScore | None = None
    bindwood_score: JudgeScore | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "reasoning": self.reasoning,
            "baseline_score": self.baseline_score.to_dict() if self.baseline_score else None,
            "bindwood_score": self.bindwood_score.to_dict() if self.bindwood_score else None,
            "error": self.error,
        }


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of the model's reply, being forgiving."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def _score_from(obj: dict[str, Any] | None) -> JudgeScore | None:
    if not obj:
        return None
    try:
        return JudgeScore(
            completeness=int(obj["completeness"]),
            accuracy=int(obj["accuracy"]),
            specificity=int(obj["specificity"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _run_judge_subprocess(prompt: str, timeout_s: int) -> tuple[str, str | None]:
    """Run `claude -p` for one judge call. Returns (answer_text, error)."""
    cmd: list[str] = [
        "claude",
        "-p",
        prompt,
        "--output-format", "json",
        "--tools", "",            # no built-in tools, no tool use at all
        "--no-session-persistence",
        "--permission-mode", "bypassPermissions",
        "--dangerously-skip-permissions",
    ]
    if _JUDGE_MODEL:
        cmd += ["--model", _JUDGE_MODEL]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return "", "claude CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return "", f"judge timed out after {timeout_s}s"

    if proc.returncode != 0:
        return "", f"claude exited {proc.returncode}: {(proc.stderr or '')[:300]}"

    # `--output-format json` emits a single JSON envelope with a `result` field
    # containing the model's answer text.
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return "", f"could not parse claude envelope: {e}"

    if envelope.get("is_error"):
        return "", f"claude reported is_error: {envelope.get('error') or envelope.get('subtype')}"

    return str(envelope.get("result", "")), None


def judge_ab(
    *,
    repo: str,
    question: str,
    baseline_answer: str,
    bindwood_answer: str,
    rng: random.Random | None = None,
    timeout_s: int = _JUDGE_TIMEOUT_S,
) -> JudgeResult:
    """Ask the judge to compare the two answers.

    A/B position is randomized so the judge can't anchor on "always pick A".
    """
    rng = rng or random.Random()

    swap = rng.random() < 0.5
    if swap:
        answer_a, answer_b = bindwood_answer, baseline_answer
        label_a, label_b = "bindwood", "baseline"
    else:
        answer_a, answer_b = baseline_answer, bindwood_answer
        label_a, label_b = "baseline", "bindwood"

    prompt = _PROMPT.format(
        repo=repo,
        question=question,
        answer_a=answer_a or "(empty)",
        answer_b=answer_b or "(empty)",
    )

    raw_text, err = _run_judge_subprocess(prompt, timeout_s)
    if err:
        return JudgeResult(winner="error", reasoning="", error=err)

    try:
        parsed = _extract_json(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        return JudgeResult(
            winner="error",
            reasoning="",
            error=f"judge returned unparseable JSON: {e}",
            raw={"text": raw_text[:500]},
        )

    winner_raw = str(parsed.get("winner", "tie")).strip().lower()
    if winner_raw == "a":
        winner = label_a
    elif winner_raw == "b":
        winner = label_b
    else:
        winner = "tie"

    score_a = _score_from(parsed.get("a"))
    score_b = _score_from(parsed.get("b"))
    if swap:
        bindwood_score, baseline_score = score_a, score_b
    else:
        baseline_score, bindwood_score = score_a, score_b

    return JudgeResult(
        winner=winner,
        reasoning=str(parsed.get("reasoning", ""))[:500],
        baseline_score=baseline_score,
        bindwood_score=bindwood_score,
        raw={"swapped": swap},
    )
