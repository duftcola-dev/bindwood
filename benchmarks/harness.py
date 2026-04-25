"""Headless Claude Code driver.

Spawns ``claude -p`` with stream-json output, parses events defensively, and
returns a RunResult with usage, tool calls, timing, and the final answer text.

Two conditions are supported:

- baseline : Claude Code with built-in filesystem tools only, no MCP.
- bindwood : Claude Code with built-ins disabled and the bindwood MCP server
             loaded exclusively (``--strict-mcp-config``). Server startup cost
             is included in the measurement on purpose — it's a real-world
             component of the user-facing latency.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Built-in tools the baseline condition is allowed to use. Everything else is
# blocked by passing this list to --tools (a positive allowlist).
BASELINE_TOOLS = "Read,Grep,Glob,Bash"

# In the bindwood condition we disable ALL built-ins (including Bash), so the
# model has to route every question through the bindwood MCP tools. An empty
# string to --tools means "no built-in tools"; MCP tools remain available.
BINDWOOD_TOOLS = ""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def effective_tokens(self) -> float:
        # Cache creation is 1.25× the price of regular input tokens; cache read
        # is 0.1×. Weighting them this way gives a single workload number that
        # reflects real cost, since in Claude Code most tokens flow through the
        # cache and raw input+output drastically undercounts.
        return (
            self.input_tokens
            + self.output_tokens
            + 1.25 * self.cache_creation_input_tokens
            + 0.1 * self.cache_read_input_tokens
        )

    def add_from(self, u: dict[str, Any] | None) -> None:
        if not u:
            return
        self.input_tokens += int(u.get("input_tokens", 0) or 0)
        self.output_tokens += int(u.get("output_tokens", 0) or 0)
        self.cache_creation_input_tokens += int(u.get("cache_creation_input_tokens", 0) or 0)
        self.cache_read_input_tokens += int(u.get("cache_read_input_tokens", 0) or 0)

    def to_dict(self) -> dict[str, float | int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "total_tokens": self.total_tokens,
            "effective_tokens": round(self.effective_tokens, 1),
        }


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]


@dataclass
class RunResult:
    condition: str  # "baseline" | "bindwood"
    repo: str
    question_id: str
    question: str
    answer: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    turns: int = 0
    usage: Usage = field(default_factory=Usage)
    result_usage: Usage | None = None  # usage reported by the final `result` event
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    elapsed_seconds: float = 0.0
    error: str | None = None
    unknown_event_types: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "repo": self.repo,
            "question_id": self.question_id,
            "question": self.question,
            "answer": self.answer,
            "turns": self.turns,
            "usage": self.usage.to_dict(),
            "result_usage": self.result_usage.to_dict() if self.result_usage else None,
            "total_cost_usd": self.total_cost_usd,
            "duration_ms": self.duration_ms,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "tool_calls": [{"name": tc.name, "input": tc.input} for tc in self.tool_calls],
            "error": self.error,
            "unknown_event_types": self.unknown_event_types,
        }


def _build_command(
    *,
    question: str,
    repo_path: Path,
    mcp_config: Path | None,
    tools: str,
    model: str | None,
    timeout_s: int,
) -> list[str]:
    cmd: list[str] = [
        "claude",
        "-p",
        question,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--dangerously-skip-permissions",
        # Note: --bare would give a more hermetic run (no hooks, memory, CLAUDE.md)
        # but it also disables OAuth, which breaks auth for users without
        # ANTHROPIC_API_KEY set. We rely on cwd pointing at the fixture repo
        # (not bindwood) so CLAUDE.md auto-discovery finds nothing.
        "--no-session-persistence",
        "--add-dir",
        str(repo_path),
        "--tools",
        tools,
    ]
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
    if model:
        cmd += ["--model", model]
    return cmd


def _parse_event(
    event: dict[str, Any],
    result: RunResult,
) -> None:
    """Update result state from one stream-json event. Defensive: skips unknowns."""
    etype = event.get("type")

    if etype == "assistant":
        msg = event.get("message") or {}
        usage = msg.get("usage") or {}
        result.usage.add_from(usage)
        result.turns += 1

        text_parts: list[str] = []
        for block in msg.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
            elif btype == "tool_use":
                result.tool_calls.append(
                    ToolCall(
                        name=block.get("name") or "?",
                        input=block.get("input") or {},
                    )
                )
        if text_parts:
            # Keep overwriting with the latest assistant text; the last one
            # before stop is usually the final answer. The `result` event
            # below authoritatively overwrites this if present.
            result.answer = "\n".join(p for p in text_parts if p).strip()

    elif etype == "user":
        # Tool results come back as user messages. We don't accumulate their
        # content (they can be huge and we already have the tool_use records).
        return

    elif etype == "system":
        # init event — no measurements on our side, but useful for debugging.
        return

    elif etype == "result":
        if event.get("result"):
            result.answer = str(event["result"]).strip()
        if "total_cost_usd" in event:
            try:
                result.total_cost_usd = float(event["total_cost_usd"])
            except (TypeError, ValueError):
                pass
        if "duration_ms" in event:
            try:
                result.duration_ms = int(event["duration_ms"])
            except (TypeError, ValueError):
                pass
        if "num_turns" in event:
            try:
                result.turns = max(result.turns, int(event["num_turns"]))
            except (TypeError, ValueError):
                pass
        if event.get("is_error"):
            # Keep any prior error text; append result-event detail.
            detail = event.get("error") or event.get("subtype") or "unknown"
            result.error = (
                f"{result.error}; result.is_error={detail}" if result.error else f"result.is_error={detail}"
            )
        # The result event often reports its own aggregated usage; capture it
        # so we can sanity-check against our per-turn sum.
        if "usage" in event:
            ru = Usage()
            ru.add_from(event.get("usage"))
            result.result_usage = ru

    elif etype is None:
        result.unknown_event_types["<missing type>"] = (
            result.unknown_event_types.get("<missing type>", 0) + 1
        )
    else:
        result.unknown_event_types[etype] = result.unknown_event_types.get(etype, 0) + 1


def run_claude_code(
    *,
    condition: str,
    repo: str,
    question_id: str,
    question: str,
    repo_path: Path,
    mcp_config: Path | None,
    tools: str,
    model: str | None = None,
    timeout_s: int = 900,
    env: dict[str, str] | None = None,
) -> RunResult:
    """Run one headless Claude Code session and return a RunResult.

    The subprocess is given ``timeout_s`` seconds to finish; if it hangs past
    that, it's killed and the partial result is returned with an error set.
    """
    result = RunResult(
        condition=condition,
        repo=repo,
        question_id=question_id,
        question=question,
    )

    cmd = _build_command(
        question=question,
        repo_path=repo_path,
        mcp_config=mcp_config,
        tools=tools,
        model=model,
        timeout_s=timeout_s,
    )

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(repo_path),  # run as if the user were in the repo
        )
    except FileNotFoundError as e:
        result.error = f"claude CLI not found: {e}"
        result.elapsed_seconds = time.monotonic() - t0
        return result

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON line — log it but don't crash.
                result.unknown_event_types["<non-json>"] = (
                    result.unknown_event_types.get("<non-json>", 0) + 1
                )
                continue
            _parse_event(event, result)

        rc = proc.wait(timeout=timeout_s)
        if rc != 0 and not result.error:
            stderr = proc.stderr.read() if proc.stderr else ""
            result.error = f"claude exited with code {rc}: {stderr[:500]}"
    except subprocess.TimeoutExpired:
        proc.kill()
        result.error = f"timeout after {timeout_s}s"
    except Exception as e:  # pragma: no cover
        proc.kill()
        result.error = f"unexpected harness error: {e}"
    finally:
        result.elapsed_seconds = time.monotonic() - t0

    return result
