#!/usr/bin/env python3
"""MCP server exposing our own harness tools to Codex CLI's native agent
loop — the point is to get OUR tools (not just our prompt) into a session
that still runs on Codex's own execution engine and the existing ChatGPT
subscription billing, rather than being stuck choosing between "Codex's
closed native loop" and "our own loop via metered OpenRouter."

Run via: codex mcp add lean-arena -- <this venv's python> <this file>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

COMPETITION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPETITION))

import arena  # noqa: E402
import verify  # noqa: E402

from mcp.server.mcpserver import MCPServer  # noqa: E402

mcp = MCPServer("lean-arena")

# ARENA_TOOLSET=student: expose exactly the student tool set from
# student_tools.py (bound to ARENA_PROBLEM, every call logged to
# ARENA_TOOL_LOG) instead of the legacy get_target/evaluate_candidate pair
# below. This is the mode collect.py uses — see student_tools.py for why the
# log, not the Codex rollout, is the training trace.
STUDENT = os.environ.get("ARENA_TOOLSET") == "student"

if STUDENT:
    import student_tools  # noqa: E402

    _PROBLEM = os.environ["ARENA_PROBLEM"]
    _EPISODE = os.environ.get("ARENA_EPISODE") or None
    _LOG = Path(os.environ["ARENA_TOOL_LOG"])
    _DESC = {t["function"]["name"]: t["function"]["description"] for t in student_tools.SCHEMA}

    def _call(tool: str, **args: Any) -> str:
        args = {k: v for k, v in args.items() if v is not None}
        return student_tools.call(tool, args, problem=_PROBLEM, episode=_EPISODE, log_path=_LOG)

    @mcp.tool(name="get_target", description=_DESC["get_target"])
    def s_get_target() -> str:
        return _call("get_target")

    @mcp.tool(name="submit_proof", description=_DESC["submit_proof"])
    def s_submit_proof(proof: str, all_versions: bool = False) -> str:
        return _call("submit_proof", proof=proof, all_versions=all_versions)

    @mcp.tool(name="bash", description=_DESC["bash"])
    def s_bash(command: str, timeout: Optional[int] = None) -> str:
        return _call("bash", command=command, timeout=timeout)

    @mcp.tool(name="read_file", description=_DESC["read_file"])
    def s_read_file(path: str) -> str:
        return _call("read_file", path=path)

    @mcp.tool(name="write_file", description=_DESC["write_file"])
    def s_write_file(path: str, content: str) -> str:
        return _call("write_file", path=path, content=content)


def get_target(name: str) -> str:
    """Return the current candidate declaration (statement + proof) for
    problem `name`, exactly as it stands right now, with its file and
    starting line — already isolated from the rest of the file. Use this
    instead of reading the whole work file and searching for the theorem."""
    if name not in verify.BENCHMARK:
        return f"[error] unknown problem: {name}"
    wf = arena.work_file(name)
    if wf is None or not wf.is_file():
        return f"[error] no work file for {name} — has it been prepared?"
    text = wf.read_text()
    start = verify.decl_start(text, verify.BENCHMARK[name])
    if start is None:
        return f"[error] could not locate the {name} declaration in {wf}"
    line_no = text.count("\n", 0, start) + 1
    decl = text[start:].strip()
    return f"Target declaration (from {wf}, starting at line {line_no}):\n{decl}"


def evaluate_candidate(name: str, proof: str, all_versions: bool = False) -> dict[str, Any]:
    """Replace the candidate declaration for `name` with `proof` (the full
    statement + `:=` + proof, byte-identical statement — same contract as
    editing the work file directly) AND compile+score it in one call,
    instead of a separate write-then-check round trip. Set all_versions=True
    for the full cross-toolchain confirmation before finishing; leave it
    False (default, primary toolchain only) for fast iteration. Also reports
    the best validated candidate recorded so far this episode, so you don't
    have to track your own best score across turns."""
    if name not in verify.BENCHMARK:
        return {"error": f"unknown problem: {name}"}
    if not proof.strip():
        return {"error": "empty proof"}
    arena.write_candidate(name, proof)
    out = arena.check(name, all_versions=all_versions, timeout=900)
    # This MCP server is a separate long-lived process from the one that
    # ran run_episode() and set arena.CURRENT_EPISODE — that contextvar is
    # always None here, same reason record_trial() itself falls back to the
    # ARENA_EPISODE env var. Whether this actually gets tagged to the right
    # episode depends on Codex propagating its own env to this subprocess —
    # verify that empirically before trusting best_so_far's results.
    episode = os.environ.get("ARENA_EPISODE") or None
    best = arena.best_so_far(name, episode)
    out["best_validated_so_far_this_episode"] = (
        {"objective_sum_pct": best["objective_sum_pct"], "hash": best.get("hash")}
        if best else None
    )
    return out


if not STUDENT:
    mcp.tool()(get_target)
    mcp.tool()(evaluate_candidate)


if __name__ == "__main__":
    mcp.run(transport="stdio")
