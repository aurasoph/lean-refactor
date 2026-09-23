#!/usr/bin/env python3
"""The student tool set: one schema, one implementation, one prompt addendum.

Everything that trains or serves the open-track model goes through this file:

- the MCP server (`mcp_server/server.py`, `ARENA_TOOLSET=student`) exposes
  these tools to the Codex teacher during collection;
- `training/build_sft.py` renders traces against `SCHEMA` and `SYSTEM_PROMPT`;
- the Qwen serving loop imports `SCHEMA` / `call()` directly.

So train and serve share code, not just a spec. Changing a tool's name,
arguments, or output shape is a schema change: bump `TOOLSET_ID`, and never
mix two TOOLSET_IDs in one SFT mixture.

Codex runs its models in code mode (the model writes JavaScript that calls
tools), and cells carry state (`load("statement") + ...`), so the resolved
arguments are not recoverable from the rollout. Every call made through
`call()` is therefore logged, with resolved args and full output, to
`$ARENA_TOOL_LOG` — that log, not the rollout, is the training trace.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

COMPETITION = Path(__file__).resolve().parent
sys.path.insert(0, str(COMPETITION))

import arena  # noqa: E402
import verify  # noqa: E402

TOOLSET_ID = "student-v1"

SYSTEM_PROMPT = (
    "You are an expert Lean 4 proof engineer working autonomously on one task. "
    "Use the provided tools. When you are completely done, reply with plain "
    "text and no tool call, summarizing as the task instructs."
)

SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_target",
            "description": (
                "Return the current candidate declaration (statement + proof), "
                "already isolated from the rest of the work file, with its line number."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_proof",
            "description": (
                "Replace the candidate declaration (full statement + `:=` + proof; "
                "statement byte-identical) and compile + score it. Returns the score "
                "vector, errors, and the best validated candidate so far this episode. "
                "Call it as often as you like. all_versions=true additionally checks "
                "survival on every listed toolchain — do that before finishing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proof": {"type": "string", "description": "The full replacement declaration, verbatim."},
                    "all_versions": {"type": "boolean", "description": "Default false (primary toolchain only)."},
                },
                "required": ["proof"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command via `bash -lc` (cwd: the competition directory). "
                "Use for `lake env lean` and rg/sed over .lake/packages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "description": "Seconds, default 300, max 1200."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file under the competition directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write a scratch file under the competition directory. Not for the "
                "work file — use submit_proof for that."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
]

TOOL_NAMES = tuple(t["function"]["name"] for t in SCHEMA)


def prompt_for(name: str) -> str:
    """The user turn, identical for teacher collection and student serving."""
    return arena.build_prompt(name) + (
        "\n\n---\nTools: `get_target` returns your current candidate declaration. "
        "`submit_proof` replaces it AND compiles + scores it in one call — this is "
        "how you edit the work file and how you run `check` (pass "
        "all_versions=true for the cross-toolchain confirmation). `bash` is for "
        "`lake env lean` and searching the corpus; `read_file`/`write_file` for "
        "anything else under the competition directory."
    )


def _impl(tool: str, args: dict[str, Any], problem: str, episode: Optional[str]) -> str:
    if tool == "get_target":
        wf = arena.work_file(problem)
        if wf is None or not wf.is_file():
            return "[tool error] no work file — has this episode been prepared?"
        text = wf.read_text()
        start = verify.decl_start(text, verify.BENCHMARK[problem])
        if start is None:
            return f"[tool error] could not locate the {problem} declaration"
        line_no = text.count("\n", 0, start) + 1
        return f"Target declaration (from {wf}, line {line_no}):\n{text[start:].strip()}"

    if tool == "submit_proof":
        proof = args.get("proof") or ""
        if not proof.strip():
            return "[tool error] empty proof"
        arena.write_candidate(problem, proof)
        out = arena.check(problem, all_versions=bool(args.get("all_versions")), timeout=900)
        best = arena.best_so_far(problem, episode)
        out["best_validated_so_far_this_episode"] = (
            {"objective_sum_pct": best["objective_sum_pct"], "hash": best.get("hash")} if best else None
        )
        return json.dumps(out, indent=1)

    if tool == "bash":
        command = args.get("command") or ""
        hit = arena._bash_leak_check(command)
        if hit:
            return (
                f"[tool error] refused: command references prior-episode data ({hit!r}). "
                "Solve this from the corpus, not from past attempts."
            )
        timeout = min(int(args.get("timeout") or 300), 1200)
        env = {**os.environ, "ARENA_EPISODE": episode or ""}
        # Own process group, killed as a group on timeout: subprocess.run's
        # timeout kills only `bash`, leaving any `lake env lean` it forked
        # running orphaned (same failure verify.run_one guards against).
        proc = subprocess.Popen(
            ["bash", "-lc", command], cwd=arena.ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            return f"[timed out after {timeout}s]"
        return arena._truncate(f"[exit {proc.returncode}]\n{stdout}{stderr}")

    if tool == "read_file":
        return arena._truncate(arena._safe_path(args.get("path") or "").read_text())

    if tool == "write_file":
        path = arena._safe_path(args.get("path") or "")
        wf = arena.work_file(problem)
        if wf is not None and path == wf.resolve():
            return "[tool error] use submit_proof for the work file"
        content = args.get("content") or ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"wrote {len(content)} bytes to {path}"

    return f"[tool error] unknown tool: {tool}"


def call(tool: str, args: dict[str, Any], *, problem: str, episode: Optional[str] = None,
         log_path: Optional[Path] = None) -> str:
    """Run one tool call and (if log_path) append the resolved call to the trace log."""
    t0 = time.time()
    try:
        out = _impl(tool, args, problem, episode)
    except subprocess.TimeoutExpired:
        out = "[timed out]"
    except Exception as e:  # tool errors are observations, not crashes
        out = f"[tool error] {type(e).__name__}: {e}"
    if log_path is not None:
        with Path(log_path).open("a") as fh:
            fh.write(json.dumps({
                "t0": t0, "t1": time.time(), "toolset": TOOLSET_ID,
                "tool": tool, "args": args, "output": out,
            }) + "\n")
    return out
