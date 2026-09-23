#!/usr/bin/env python3
"""Collect Codex rollouts for recorded episodes into `traces/`.

Raw rollouts are copied verbatim (`traces/raw/`) and a distilled view is
written alongside (`traces/distilled/`) holding just the turn-by-turn
prompt / reasoning / tool-call / result sequence plus the episode's score, which
is the part that is useful as training data.

  python3 training/harvest_traces.py            # every episode in runs/episodes.jsonl
  python3 training/harvest_traces.py --name N    # one problem
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "competition"))
from arena import slug  # noqa: E402 — reuse arena.py's exact directory-naming convention

# runs/ and traces/ live outside competition/ on purpose — see arena.py's RUNS.
RUNS = REPO / "runs"
EPISODES = RUNS / "episodes.jsonl"
SESSIONS = Path.home() / ".codex" / "sessions"
TRACES = REPO / "traces"

TRUNC = 4000


def episodes(name: Optional[str] = None) -> Iterator[dict[str, Any]]:
    if not EPISODES.exists():
        return
    for line in EPISODES.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if name is None or rec.get("name") == name:
            yield rec


def find_rollout(rec: dict[str, Any]) -> Optional[Path]:
    codex = rec.get("codex") or {}
    for key in ("session_id", "thread_id", "conversation_id"):
        ident = codex.get(key)
        if ident:
            hits = list(SESSIONS.rglob(f"rollout-*{ident}*.jsonl"))
            if hits:
                return hits[0]
    explicit = codex.get("rollout_path")
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
    return None


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            if isinstance(chunk, dict):
                parts.append(chunk.get("text") or chunk.get("summary") or "")
        return "\n".join(p for p in parts if p)
    return ""


def distill(rollout: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in rollout.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "response_item":
            continue
        payload = event.get("payload") or {}
        kind = payload.get("type")
        stamp = event.get("timestamp")
        if kind == "message":
            body = text_of(payload.get("content"))
            if body and payload.get("role") != "developer":
                items.append({"t": stamp, "kind": payload.get("role"), "text": body[:TRUNC]})
        elif kind == "reasoning":
            body = text_of(payload.get("summary") or payload.get("content"))
            if body:
                items.append({"t": stamp, "kind": "reasoning", "text": body[:TRUNC]})
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            items.append({
                "t": stamp,
                "kind": "tool_call",
                "tool": payload.get("name") or kind,
                "args": str(payload.get("arguments") or payload.get("input") or "")[:TRUNC],
            })
        elif kind in ("function_call_output", "custom_tool_call_output"):
            items.append({
                "t": stamp,
                "kind": "tool_result",
                "text": str(payload.get("output") or "")[:TRUNC],
            })
    return items


def find_openrouter_trace(rec: dict[str, Any]) -> Optional[Path]:
    run_dir = rec.get("run_dir")
    if run_dir:
        p = Path(run_dir) / "openrouter.jsonl"
        if p.is_file():
            return p
    # `run_dir` is recorded at episode time and goes stale if RUNS ever moves
    # (as it did on 2026-08-24) — reconstruct from the current RUNS location.
    stamp, name = rec.get("timestamp"), rec.get("name")
    if not stamp or not name:
        return None
    p = RUNS / f"{stamp}-{slug(name)}" / "openrouter.jsonl"
    return p if p.is_file() else None


def distill_openrouter(trace_path: Path) -> list[dict[str, Any]]:
    """Same item shape as `distill()` (t/kind/text[/tool/args]) so downstream
    tooling doesn't need to special-case backends. `harness` items (nudges,
    retries) are kept but distinctly tagged — never mask/train on them as if
    they were model output."""
    items: list[dict[str, Any]] = []
    for line in trace_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        turn = rec.get("turn")
        if rec.get("harness") or rec.get("harness_error"):
            items.append({
                "t": turn, "kind": "harness",
                "text": str(rec.get("harness") or rec.get("harness_error") or "")[:TRUNC],
            })
            continue
        role = rec.get("role")
        if role == "assistant":
            msg = rec.get("message") or {}
            reasoning = msg.get("reasoning")
            if reasoning:
                items.append({"t": turn, "kind": "reasoning", "text": str(reasoning)[:TRUNC]})
            content = msg.get("content")
            if content:
                items.append({"t": turn, "kind": "assistant", "text": str(content)[:TRUNC]})
        elif role == "tool":
            items.append({
                "t": turn, "kind": "tool_call",
                "tool": rec.get("name"),
                "args": json.dumps(rec.get("args") or {})[:TRUNC],
            })
            items.append({
                "t": turn, "kind": "tool_result",
                "text": str(rec.get("result") or "")[:TRUNC],
            })
    return items


def harvest(name: Optional[str] = None) -> None:
    (TRACES / "raw").mkdir(parents=True, exist_ok=True)
    (TRACES / "distilled").mkdir(parents=True, exist_ok=True)
    for rec in episodes(name):
        backend = rec.get("backend", "codex")
        slug = rec["name"].replace(".", "_")

        if backend == "openrouter":
            trace_path = find_openrouter_trace(rec)
            if trace_path is None:
                print(f"no openrouter trace found for {rec['name']} @ {rec.get('timestamp')}")
                continue
            raw_dest = TRACES / "raw" / f"openrouter-{rec.get('timestamp')}-{slug}.jsonl"
            shutil.copy2(trace_path, raw_dest)
            items = distill_openrouter(trace_path)
            rollout_repr = str(trace_path)
        elif backend == "claude":
            print(f"no Claude trace ingestion yet for {rec['name']} @ {rec.get('timestamp')} (~/.claude sessions not read)")
            continue
        else:
            rollout = find_rollout(rec)
            if rollout is None:
                print(f"no rollout found for {rec['name']} @ {rec.get('timestamp')}")
                continue
            raw_dest = TRACES / "raw" / rollout.name
            shutil.copy2(rollout, raw_dest)
            items = distill(rollout)
            rollout_repr = str(rollout)

        # `run_episode` always stores teacher metadata under the "codex" key,
        # regardless of which backend actually ran (pre-existing naming quirk).
        meta = rec.get("codex") or {}
        stem = f"{rec.get('timestamp')}-{slug}.jsonl"
        dest = TRACES / "distilled" / stem
        after = rec.get("after") or {}
        with dest.open("w") as fh:
            fh.write(json.dumps({
                "kind": "episode",
                "name": rec["name"],
                "backend": backend,
                "model": meta.get("model"),
                "effort": meta.get("effort"),
                "wrapper": meta.get("wrapper") or rec.get("wrapper"),
                "wall_seconds": meta.get("wall_seconds"),
                "turns": meta.get("turns"),
                "stop_reason": meta.get("stop_reason"),
                "compiled": after.get("compiled"),
                "length": after.get("length"),
                "length_reduction_pct": after.get("length_reduction_pct"),
                "heartbeats": after.get("heartbeats"),
                "heartbeat_reduction_pct": after.get("heartbeat_reduction_pct"),
                "objective_sum_pct": after.get("objective_sum_pct"),
                "survival_pct": after.get("survival_pct"),
                "agent_final": rec.get("agent_final"),
                "checkpoint_promotions": rec.get("checkpoint_promotions"),
                "compat": after.get("compat"),
                "rollout": rollout_repr,
            }) + "\n")
            for item in items:
                fh.write(json.dumps(item) + "\n")
        print(f"{rec['name']} [{backend}]: {len(items)} items → {dest.relative_to(REPO)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name")
    args = ap.parse_args()
    harvest(args.name)


if __name__ == "__main__":
    main()
