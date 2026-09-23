#!/usr/bin/env python3
"""Build a versioned multi-turn SFT mixture from student-toolset Codex episodes.

  python3 training/build_sft.py --mixture astra-student --version v1
  python3 training/build_sft.py --mixture astra-student --version v1 --model gpt-6-astra --dry-run

Input: runs/episodes.jsonl records collected with `arena.py run --toolset
student` (see competition/collect.py). For each episode:

  - the tool calls come from runs/<ep>/tools.jsonl: resolved args and full
    outputs, logged by our MCP server. Codex runs its models in code mode
    (JavaScript cells that call tools, with state carried between cells),
    so the rollout alone does not contain the arguments that actually ran.
  - the visible assistant text and the user prompt come from the Codex
    rollout in ~/.codex/sessions. Reasoning is encrypted there and is not
    used; we train with thinking off.

The two are interleaved by timestamp into the student's chat format:
system (student_tools.SYSTEM_PROMPT) → user → [assistant (+tool_calls) →
tool…]* → final assistant. Tool calls that ran concurrently share one
assistant turn; sequential calls from one JS cell become consecutive turns.

Drop rules (every drop is counted by reason in manifest.json):
  wrong backend / wrapper / toolset / model; held-out test split; missing
  tools.jsonl or rollout; teacher's own final not eligible, not above
  --min-objective, or rolled back by checkpoint recovery; rollout used a
  tool outside the student set (apply_patch, subagents, ...); path audit
  (any call that references prior-episode data or an absolute path outside
  the allowed roots).

Output: training/data/<mixture>/<version>/{train,val}.jsonl + manifest.json
(written last). An existing version directory is never overwritten.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "competition"))
sys.path.insert(0, str(REPO / "training"))

import arena  # noqa: E402
import student_tools  # noqa: E402
from splits import SPLIT_ID, split_of  # noqa: E402

SESSIONS = Path.home() / ".codex" / "sessions"
DATA = REPO / "training" / "data"

# Paths a legitimate call may name. Anything else absolute is a drop.
ALLOWED_ROOTS = (str(arena.ROOT), str(Path.home() / ".elan"), "/tmp", "/dev/null", "/usr", "/bin")
ABS_PATH_RE = re.compile(r"(?<![\w.])(/[\w.@+-]+(?:/[\w.@+-]*)*)")
JS_TOOL_RE = re.compile(r"tools\.(\w+)\s*\(")
STUDENT_MCP = {f"mcp__lean_arena__{t}" for t in student_tools.TOOL_NAMES}
CODE_MODE_CALLS = {"exec", "wait"}  # Codex's own code-mode plumbing, not model tools


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def find_rollout(info: dict[str, Any]) -> Optional[Path]:
    for key in ("session_id", "thread_id", "conversation_id"):
        ident = info.get(key)
        if ident:
            hits = sorted(SESSIONS.rglob(f"rollout-*{ident}*.jsonl"))
            if hits:
                return hits[0]
    return None


def read_rollout(path: Path) -> tuple[Optional[str], list[tuple[float, str]], set[str]]:
    """(task prompt, [(time, visible assistant text)], names of every tool the model invoked)."""
    prompt: Optional[str] = None
    texts: list[tuple[float, str]] = []
    used: set[str] = set()
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "response_item":
            continue
        p = event.get("payload") or {}
        kind = p.get("type")
        if kind == "message":
            body = "\n".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict)).strip()
            if p.get("role") == "user" and prompt is None and body.startswith("You are refactoring"):
                prompt = body
            elif p.get("role") == "assistant" and body:
                texts.append((ts(event["timestamp"]), body))
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            name = p.get("name") or kind
            used.add(name)
            if name == "exec":
                used.update(JS_TOOL_RE.findall(p.get("input") or ""))
    return prompt, texts, used


CLAUDE_PREFIX = "mcp__lean-arena__"


def claude_messages(stream: Path, calls: list[dict[str, Any]]) -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
    """Chat messages from a Claude Code stream-json log.

    Claude calls tools directly (no code mode), so the stream is already in
    order with resolved arguments. Tool outputs come from tools.jsonl, the
    same full strings the student is served, matched one-to-one in order.
    Thinking blocks are dropped (we train with thinking off).
    """
    msgs: list[dict[str, Any]] = []
    uses: list[tuple[str, dict[str, Any]]] = []
    for line in stream.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "assistant":
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            kind = block.get("type")
            if kind not in ("text", "tool_use"):
                continue
            if not msgs or msgs[-1]["role"] != "assistant" or (kind == "text" and msgs[-1].get("tool_calls")):
                msgs.append({"role": "assistant", "content": ""})
            cur = msgs[-1]
            if kind == "text":
                cur["content"] = (cur["content"] + "\n\n" + block["text"]).strip()
            else:
                name = block.get("name", "")
                if not name.startswith(CLAUDE_PREFIX) or name[len(CLAUDE_PREFIX):] not in student_tools.TOOL_NAMES:
                    return None, f"non-student tool: {name}"
                cur.setdefault("tool_calls", []).append({"id": block["id"], "type": "function", "function": {
                    "name": name[len(CLAUDE_PREFIX):], "arguments": block.get("input") or {}}})
                uses.append((block["id"], name[len(CLAUDE_PREFIX):]))
    if len(uses) != len(calls) or any(u[1] != c["tool"] for u, c in zip(uses, calls)):
        return None, "tool log does not match the stream"
    out: list[dict[str, Any]] = []
    k = 0
    for m in msgs:
        out.append(m)
        for tc in m.get("tool_calls", []):
            out.append({"role": "tool", "tool_call_id": tc["id"], "name": tc["function"]["name"],
                        "content": calls[k]["output"]})
            k += 1
    return out, None


def path_audit(calls: list[dict[str, Any]]) -> Optional[str]:
    for c in calls:
        args = c.get("args") or {}
        blob = args.get("command") or args.get("path") or ""
        if c["tool"] == "bash":
            hit = arena._bash_leak_check(blob)
            if hit:
                return f"leak marker {hit!r}"
        for p in ABS_PATH_RE.findall(blob):
            if not any(p == r or p.startswith(r.rstrip("/") + "/") for r in ALLOWED_ROOTS):
                return f"path outside allowed roots: {p}"
        if ".." in blob and c["tool"] in ("bash", "read_file", "write_file"):
            if re.search(r"(^|[\s/'\"])\.\.(/|$|[\s'\"])", blob):
                return "relative path escaping cwd ('..')"
    return None


def interleave(texts: list[tuple[float, str]], calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chat messages (assistant/tool) from timestamped text and tool-call records."""
    events = [(t, 0, "text", s) for t, s in texts] + [(c["t0"], 1, "call", c) for c in calls]
    events.sort(key=lambda e: (e[0], e[1]))
    turns: list[dict[str, Any]] = []  # {"text": str, "calls": [record]}
    for _, _, kind, item in events:
        last = turns[-1] if turns else None
        if kind == "text":
            if last is not None and not last["calls"]:
                last["text"] += "\n\n" + item
            else:
                turns.append({"text": item, "calls": []})
        else:
            concurrent = last is not None and last["calls"] and item["t0"] < max(c["t1"] for c in last["calls"])
            if last is not None and (not last["calls"] or concurrent):
                last["calls"].append(item)
            else:
                turns.append({"text": "", "calls": [item]})
    msgs: list[dict[str, Any]] = []
    n = 0
    for turn in turns:
        msg: dict[str, Any] = {"role": "assistant", "content": turn["text"]}
        if turn["calls"]:
            msg["tool_calls"] = []
            for c in turn["calls"]:
                n += 1
                c["_id"] = f"call_{n}"
                msg["tool_calls"].append({"id": c["_id"], "type": "function",
                                          "function": {"name": c["tool"], "arguments": c["args"]}})
        msgs.append(msg)
        for c in turn["calls"]:
            msgs.append({"role": "tool", "tool_call_id": c["_id"], "name": c["tool"], "content": c["output"]})
    return msgs


def normalize(obj: Any, old: str, new: str) -> Any:
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, list):
        return [normalize(x, old, new) for x in obj]
    if isinstance(obj, dict):
        return {k: normalize(v, old, new) for k, v in obj.items()}
    return obj


def build_one(rec: dict[str, Any], args: argparse.Namespace) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    info = rec.get("codex") or {}  # teacher metadata, whatever the backend (legacy key name)
    backend = rec.get("backend")
    if backend not in ("codex", "claude"):
        return None, "backend"
    if rec.get("wrapper") != args.wrapper:
        return None, "wrapper"
    if info.get("toolset") != student_tools.TOOLSET_ID:
        return None, "toolset"
    if args.model and info.get("model") not in args.model:
        return None, "model"
    split = split_of(rec["name"])
    if split == "test":
        return None, "test split"
    final = rec.get("agent_final") or {}
    if not final.get("eligible") or (final.get("survival_pct") or 0) < 100:
        return None, "final not eligible"
    if (final.get("objective_sum_pct") or 0) <= args.min_objective:
        return None, "final below min objective"
    if rec.get("checkpoint_promotions"):
        return None, "final rolled back"
    run_dir = arena.RUNS / Path(rec.get("run_dir", "")).name
    tool_log = run_dir / "tools.jsonl"
    if not tool_log.is_file():
        return None, "no tools.jsonl"
    calls = [json.loads(l) for l in tool_log.read_text().splitlines() if l.strip()]
    if not calls:
        return None, "no tool calls"
    reason = path_audit(calls)
    if reason:
        return None, f"path audit: {reason}"
    if backend == "claude":
        prompt_file = run_dir / "prompt.txt"
        if not prompt_file.is_file() or not (run_dir / "claude.jsonl").is_file():
            return None, "no claude stream or prompt.txt"
        prompt = prompt_file.read_text()
        turns, why = claude_messages(run_dir / "claude.jsonl", calls)
        if turns is None:
            return None, why
    else:
        rollout = find_rollout(info)
        if rollout is None:
            return None, "no rollout"
        prompt, texts, used = read_rollout(rollout)
        if prompt is None:
            return None, "no task prompt in rollout"
        foreign = used - CODE_MODE_CALLS - STUDENT_MCP
        if foreign:
            return None, f"non-student tool: {sorted(foreign)[0]}"
        turns = interleave(texts, calls)

    messages = [{"role": "system", "content": student_tools.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}] + turns
    if messages[-1]["role"] != "assistant" or messages[-1].get("tool_calls"):
        return None, "no final assistant message"
    if args.normalize_root:
        messages = normalize(messages, str(arena.ROOT), args.normalize_root)
    return {
        "name": rec["name"], "episode": rec["timestamp"], "split": split, "backend": backend,
        "model": info.get("model"), "effort": info.get("effort"),
        "objective_sum_pct": final.get("objective_sum_pct"),
        "messages": messages,
    }, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mixture", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--model", nargs="*", help="keep only these teacher models")
    ap.add_argument("--wrapper", default=arena.WRAPPER_ID)
    ap.add_argument("--min-objective", type=float, default=0.0)
    ap.add_argument("--normalize-root", help="replace the competition/ absolute path with this (e.g. /arena)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out_dir = DATA / args.mixture / args.version
    if out_dir.exists() and not args.dry_run:
        sys.exit(f"{out_dir} exists — mixtures are immutable, pick a new --version")

    kept: dict[str, list[dict[str, Any]]] = {"train": [], "val": []}
    drops: Counter = Counter()
    for line in arena.EPISODES.read_text().splitlines():
        if not line.strip():
            continue
        ex, reason = build_one(json.loads(line), args)
        if ex is None:
            drops[reason] += 1
        else:
            kept[ex["split"]].append(ex)

    for split, rows in kept.items():
        print(f"{split}: {len(rows)} episodes over {len({r['name'] for r in rows})} problems")
    for reason, n in drops.most_common():
        print(f"  drop {n:4d}  {reason}")
    if args.dry_run:
        return

    out_dir.mkdir(parents=True)
    for split, rows in kept.items():
        with (out_dir / f"{split}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "manifest.json").write_text(json.dumps({
        "mixture": args.mixture, "version": args.version,
        "created": datetime.now().isoformat(timespec="seconds"),
        "wrapper": args.wrapper, "toolset": student_tools.TOOLSET_ID, "split": SPLIT_ID,
        "models": args.model, "min_objective": args.min_objective,
        "normalize_root": args.normalize_root,
        "counts": {s: len(r) for s, r in kept.items()},
        "problems": {s: sorted({r["name"] for r in rows}) for s, rows in kept.items()},
        "drops": dict(drops),
        "tools": student_tools.SCHEMA,
        "system_prompt": student_tools.SYSTEM_PROMPT,
    }, indent=1))
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
