#!/usr/bin/env python3
"""Episode harness for the Lean Refactor Arena.

  arena.py prepare --name N        materialise the work file inside its project
  arena.py check   --name N        extract, compile, measure, score
  arena.py run     --name N        prepare → run teacher → check → record episode
  arena.py list                    problems, toolchains, local readiness

`check` is what the agent calls while it works; `run` is the outer loop that
produces a trace + JSONL episode record.
"""

from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import local_score
import verify

ROOT = Path(__file__).resolve().parent
# Deliberately OUTSIDE ROOT: ROOT is the teacher's working directory
# (Codex `-C ROOT`, Claude `--add-dir ROOT`, our own openrouter tool guard).
# That is cwd / default search path, not a read sandbox — Codex's sandbox
# restricts writes, not reads (`head ../README.md` works; ~/.codex/sessions
# is readable). runs/ holds every prior episode's transcript and winning
# proof; keeping it off the default search path still matters. Confirmed
# 2026-08-24: a v2-tight-loop Codex episode on Core.InitsUpdatesComm read a
# prior episode's codex.jsonl and reproduced its proof byte-for-byte.
RUNS = ROOT.parent / "runs"
TRIALS = RUNS / "trials"
PROMPT = ROOT / "prompts" / "refactor.md"
EPISODES = RUNS / "episodes.jsonl"

DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "high"  # `max`/`ultra` exist; every A/B so far used `high`
# Prompt + tool profile id; bump when iterating the wrapper.
WRAPPER_ID = "v4.2-minimal"
CURRENT_EPISODE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "arena_episode", default=None
)


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def primary_version(name: str) -> Optional[str]:
    return verify.newest_version(verify.versions_for(name))


def work_file(name: str, version: Optional[str] = None) -> Optional[Path]:
    version = version or primary_version(name)
    proj = verify.project_dir(version) if version else None
    return proj / "Arena" / f"{slug(name)}.lean" if proj else None


def local_reference() -> dict[str, dict[str, Any]]:
    """Reference measurements taken with *our* method (see verify.py)."""
    return verify.read_references()


def prepare(name: str, version: Optional[str] = None, *, force: bool = False) -> Path:
    row = verify.BENCHMARK[name]
    version = version or primary_version(name)
    proj = verify.project_dir(version)
    if proj is None:
        sys.exit(f"no local project for {version}")
    dest = work_file(name, version)
    assert dest is not None
    if dest.exists() and not force:
        return dest

    rel = row.get("file_path")
    if rel:
        src_file = verify.find_source_file(proj, rel)
        if src_file is None:
            sys.exit(f"source file not found in {proj}: {rel}")
        text = src_file.read_text()
        start = verify.decl_start(text, row)
        if start is None:
            sys.exit("could not locate declaration in source file")
        prefix = verify.trim_decl_modifiers(text[:start])
        body = f"{prefix}\n{row['src'].rstrip()}\n"
    else:
        body = f"{row.get('header', '')}\n{row['src'].rstrip()}\n"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return dest


def extract_candidate(name: str, version: Optional[str] = None) -> Optional[str]:
    path = work_file(name, version)
    if path is None or not path.exists():
        return None
    text = path.read_text()
    start = verify.decl_start(text, verify.BENCHMARK[name])
    if start is None:
        return None
    return text[start:].strip()


def check(
    name: str,
    *,
    all_versions: bool = False,
    timeout: int = 1800,
    candidate: Optional[str] = None,
) -> dict[str, Any]:
    row = verify.BENCHMARK[name]
    if candidate is None:
        candidate = extract_candidate(name)
    if not candidate:
        return {"name": name, "error": "no work file — run `arena.py prepare` first"}

    versions = verify.versions_for(name)
    if not all_versions:
        top = primary_version(name)
        versions = [top] if top else []

    res = verify.verify(name, candidate, versions=versions, timeout=timeout)
    length = local_score.proof_length(candidate, row["statement"], name=name)
    ref_len = local_score.original_length(name) or 0
    published_hb = local_score.original_heartbeats(name) or 0
    local_ref = local_reference().get(name, {})
    ref_hb = local_ref.get("heartbeats") or published_hb

    hb = res["heartbeats"]
    forbidden = local_score.forbidden_hit(candidate)
    extra = [f"{kind} {n}" for kind, n in local_score.count_toplevel_decls(candidate)
             if n != name and n.split(".")[-1] != name.split(".")[-1]]

    len_pct = (
        round((ref_len - length) / ref_len * 100, 2)
        if (ref_len and length is not None)
        else None
    )
    hb_pct = (
        round((ref_hb - hb) / ref_hb * 100, 2)
        if (ref_hb and hb)
        else None
    )
    compat = res["compat"]
    untested = res.get("untested") or []
    tested_compat = {v: ok for v, ok in compat.items() if v not in untested}
    survival_pct = (
        round(sum(bool(ok) for ok in tested_compat.values()) / len(tested_compat) * 100, 2)
        if tested_compat
        else 0.0
    )
    objective_sum = (
        round(len_pct + hb_pct, 2)
        if len_pct is not None and hb_pct is not None
        else None
    )
    combined_pct = (
        round((objective_sum + survival_pct) / 3, 2)
        if objective_sum is not None
        else None
    )

    # A candidate that fails to compile can still report low heartbeats
    # (elaboration that never finished isn't "cheap") and a nonzero
    # objective_sum_pct — visually indistinguishable from a real score unless
    # this is checked explicitly. Confirmed as a real confusion source in a
    # live episode (Astra trace review, 2026-09-07): interleaved_affine_gaps'
    # last submission showed objective_sum_pct=150.49 right next to
    # compiled=false, on all-versions survival_pct=0.0. The raw numbers are
    # still useful for debugging, so keep them — just tag eligibility
    # explicitly rather than let the caller infer it from compiled+survival.
    eligible = bool(res["compiled"]) and (not all_versions or survival_pct == 100.0)
    out: dict[str, Any] = {
        "name": name,
        "compiled": res["compiled"],
        "length": length,
        "reference_length": ref_len,
        "length_reduction_pct": len_pct,
        "heartbeats": hb,
        "reference_heartbeats": ref_hb,
        "heartbeat_reduction_pct": hb_pct,
        "objective_sum_pct": objective_sum,
        "survival_pct": survival_pct,
        "combined_pct": combined_pct,
        "eligible": eligible,
        "compat": compat,
        "statement_ok": local_score.statements_match(row["statement"], candidate, name=name),
        "per_version": res["per_version"],
    }
    if not eligible:
        out["note"] = (
            "compiled=False or survival<100%: the length/heartbeat/objective "
            "numbers above are raw diagnostic measurements from this failed "
            "attempt, not a valid score — an incomplete elaboration can show "
            "artificially low heartbeats. This candidate would not be accepted."
        )
    if untested:
        out["untested"] = untested
    if forbidden:
        out["forbidden"] = forbidden
    if extra:
        out["extra_toplevel_decls"] = extra
    if published_hb and ref_hb != published_hb:
        out["published_heartbeats"] = published_hb
    record_trial(name, out, candidate, all_versions=all_versions)
    return out


# ── Trial log / best-so-far checkpoint ────────────────────────────────────────
#
# Every `check` the agent runs is logged with its candidate text. The agent is
# free to explore and to end on a worse proof than it once had; the runner
# recovers the best scoring candidate afterwards, so a failed final experiment
# can never cost a result that was already measured.

def trial_log(name: str) -> Path:
    return TRIALS / f"{slug(name)}.jsonl"


def record_trial(name: str, out: dict[str, Any], candidate: str, *, all_versions: bool) -> None:
    try:
        TRIALS.mkdir(parents=True, exist_ok=True)
        with trial_log(name).open("a") as fh:
            fh.write(json.dumps({
                "t": time.time(),
                "episode": CURRENT_EPISODE.get() or os.environ.get("ARENA_EPISODE") or None,
                "name": name,
                "wrapper": WRAPPER_ID,
                "all_versions": all_versions,
                "hash": hashlib.sha1(candidate.encode()).hexdigest()[:12],
                "compiled": out.get("compiled"),
                "length": out.get("length"),
                "length_reduction_pct": out.get("length_reduction_pct"),
                "heartbeats": out.get("heartbeats"),
                "heartbeat_reduction_pct": out.get("heartbeat_reduction_pct"),
                "objective_sum_pct": out.get("objective_sum_pct"),
                "survival_pct": out.get("survival_pct"),
                "compat": out.get("compat"),
                "untested": out.get("untested"),
                "statement_ok": out.get("statement_ok"),
                "forbidden": out.get("forbidden"),
                "extra_toplevel_decls": out.get("extra_toplevel_decls"),
                "candidate": candidate,
            }) + "\n")
    except OSError:
        pass  # never let bookkeeping break a check


def read_trials(
    name: str, *, episode: Optional[str] = None, since: float = 0.0
) -> list[dict[str, Any]]:
    path = trial_log(name)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if episode is not None:
            if rec.get("episode") != episode:
                continue
        elif rec.get("t", 0.0) < since:
            continue
        rows.append(rec)
    return rows


def submittable(trial: dict[str, Any]) -> bool:
    return (
        bool(trial.get("compiled"))
        and bool(trial.get("statement_ok"))
        and not trial.get("forbidden")
        and not trial.get("extra_toplevel_decls")
        and trial.get("objective_sum_pct") is not None
    )


def best_so_far(name: str, episode: Optional[str]) -> Optional[dict[str, Any]]:
    """Best submittable trial recorded so far this episode — used to give the
    openrouter backend a live incumbent to compare against after each edit,
    rather than making the model track its own best score across turns.
    Deliberately uses `submittable` (compiles, statement intact) rather than
    `fully_surviving` — a primary-only checkpoint can't be fully_surviving by
    construction (its compat dict only has one entry), and this is meant as
    a progress signal, not the final acceptance gate."""
    trials = [t for t in read_trials(name, episode=episode) if submittable(t)]
    if not trials:
        return None
    return max(trials, key=lambda t: t["objective_sum_pct"])


def fully_surviving(name: str, trial: dict[str, Any]) -> bool:
    """True if every listed toolchain either passed or was never locally built.

    A fast check reports 100% survival of the *newest* toolchain alone; that
    is not official survival. An *untested* toolchain (no local project) is
    not the same as a *failed* one — don't demote a real win just because we
    haven't built every environment yet (this previously reported several
    genuine wins as Σ=0; see verify.VersionResult.tested).
    """
    versions = verify.versions_for(name)
    compat = trial.get("compat") or {}
    untested = set(trial.get("untested") or [])
    return bool(versions) and all(
        (v in compat and compat[v]) or v in untested for v in versions
    )


def write_candidate(name: str, candidate: str) -> None:
    path = work_file(name)
    assert path is not None
    text = path.read_text()
    start = verify.decl_start(text, verify.BENCHMARK[name])
    if start is None:
        return
    path.write_text(text[:start] + candidate.rstrip() + "\n")


def best_checkpoint(
    name: str,
    *,
    episode: Optional[str] = None,
    since: float = 0.0,
    current: dict[str, Any],
    current_candidate: Optional[str],
    timeout: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Restore the highest-scoring fully-surviving candidate seen this episode.

    Heartbeats are measured on the newest toolchain either way, so a fast
    check's `objective_sum_pct` is comparable; only survival needs confirming.
    The upstream reference is always a valid 100%-surviving fallback (Σ = 0).
    """
    by_hash: dict[str, dict[str, Any]] = {}
    for trial in read_trials(name, episode=episode, since=since):
        if not submittable(trial):
            continue
        prev = by_hash.get(trial["hash"])
        if prev is None:
            by_hash[trial["hash"]] = trial
            continue
        prev_full = fully_surviving(name, prev)
        new_full = fully_surviving(name, trial)
        if new_full and not prev_full:
            by_hash[trial["hash"]] = trial
        elif new_full == prev_full and trial["objective_sum_pct"] > prev["objective_sum_pct"]:
            by_hash[trial["hash"]] = trial

    ref_text = verify.BENCHMARK[name]["src"].strip()
    best: dict[str, Any] = {
        "name": name,
        "compiled": True,
        "statement_ok": True,
        "objective_sum_pct": 0.0,
        "survival_pct": 100.0,
        "length_reduction_pct": 0.0,
        "heartbeat_reduction_pct": 0.0,
        "seed": "reference",
    }
    best_candidate = ref_text
    best_sum = 0.0

    if (
        current_candidate
        and submittable(current)
        and fully_surviving(name, current)
        and (current.get("objective_sum_pct") or 0) > best_sum
    ):
        best, best_candidate, best_sum = (
            current, current_candidate.strip(), current["objective_sum_pct"]
        )

    promotions: list[dict[str, Any]] = []
    ranked = sorted(by_hash.values(), key=lambda t: t["objective_sum_pct"], reverse=True)
    for trial in ranked:
        if trial["objective_sum_pct"] <= best_sum:
            break
        text = (trial.get("candidate") or "").strip()
        if text and text == best_candidate:
            continue
        if fully_surviving(name, trial):
            best, best_candidate, best_sum = trial, text, trial["objective_sum_pct"]
            promotions.append({
                "hash": trial["hash"],
                "claimed_sum": trial["objective_sum_pct"],
                "confirmed_sum": trial["objective_sum_pct"],
                "survival_pct": trial.get("survival_pct"),
                "accepted": True,
                "reused": True,
            })
            continue
        write_candidate(name, text)
        res = check(name, all_versions=True, timeout=timeout)
        accepted = (
            fully_surviving(name, res)
            and submittable(res)
            and (res.get("objective_sum_pct") or 0) > best_sum
        )
        promotions.append({
            "hash": trial["hash"],
            "claimed_sum": trial["objective_sum_pct"],
            "confirmed_sum": res.get("objective_sum_pct"),
            "survival_pct": res.get("survival_pct"),
            "accepted": accepted,
            "reused": False,
        })
        if accepted:
            best, best_candidate, best_sum = res, text, res["objective_sum_pct"]

    if best_candidate:
        write_candidate(name, best_candidate)
    return best, promotions


# ── Teacher episode ───────────────────────────────────────────────────────────

def corpus_package_dir(project_dir: Path, source: str) -> Optional[str]:
    """The actual on-disk directory name under .lake/packages for a corpus.
    Capitalization is inconsistent and varies per toolchain — confirmed
    'Arklib' alongside lowercase 'cslib' in the very same v4.31 project — so
    an agent guessing from the corpus name wastes turns on wrong-case paths.
    Hit concretely in 3 separate episode traces (Astra trace review,
    2026-09-07). Returns None for problems with no upstream package
    (e.g. putnambench, which is a standalone `import Mathlib` statement)."""
    packages = project_dir / ".lake" / "packages"
    if not packages.is_dir():
        return None
    for entry in packages.iterdir():
        if entry.is_dir() and entry.name.lower() == source.lower():
            return entry.name
    return None


def build_prompt(name: str) -> str:
    row = verify.BENCHMARK[name]
    versions = verify.versions_for(name)
    top = primary_version(name)
    others = [v for v in versions if v != top]
    local_ref = local_reference().get(name, {})
    ref_hb = local_ref.get("heartbeats") or local_score.original_heartbeats(name)
    proj_dir = verify.project_dir(top)
    pkg_dir = corpus_package_dir(proj_dir, row.get("source", "")) if proj_dir else None
    corpus_package_note = (
        f"`.lake/packages/{pkg_dir}` — exact on-disk name, don't guess capitalization"
        if pkg_dir else
        "(none — this problem has no upstream corpus package)"
    )
    return PROMPT.read_text().format(
        name=name,
        source=row.get("source", "?"),
        work_file=str(work_file(name)),
        work_file_name=work_file(name).name,
        project_dir=str(proj_dir),
        primary_version=top,
        other_versions=", ".join(others) if others else "(none — single toolchain)",
        ref_heartbeats=ref_hb,
        ref_length=local_score.original_length(name),
        competition_dir=str(ROOT),
        corpus_package_note=corpus_package_note,
    )


MCP_SERVER_PYTHON = ROOT / "mcp_server" / "venv" / "bin" / "python"
MCP_SERVER_SCRIPT = ROOT / "mcp_server" / "server.py"
OCTO_BIN = ROOT / "mcp_server" / "octo_venv" / "bin" / "octo-mcp"


# Codex features turned off for --toolset student, so that inside Codex's
# mandatory code-mode `exec` cell the only thing that can touch the machine
# is our own MCP server (which logs every resolved call). `code_mode_host`
# itself can't be disabled — the run fails closed without it.
STUDENT_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "multi_agent", "tool_suggest", "sleep_tool",
    "browser_use", "computer_use", "apps", "goals", "image_generation", "view_image",
)


def codex_command(
    name: str, model: str, effort: str, *, use_octo: bool = False,
    toolset: str = "legacy", episode: Optional[str] = None, tool_log: Optional[Path] = None,
) -> list[str]:
    cmd = [
        "codex", "exec",
        "--ignore-user-config",           # thin, reproducible tool profile —
                                           # but this also skips ~/.codex/config.toml,
                                           # which is where `codex mcp add` persists
                                           # server registrations, so our own tools
                                           # (get_target, evaluate_candidate) have to
                                           # be injected explicitly below instead of
                                           # relying on that global registration.
        "--skip-git-repo-check",
        # Codex auto-loads every AGENTS.md from the git root down to -C into
        # the model's context. The repo's AGENTS.md is for coding agents
        # working ON the repo, not the teacher: loading it would change the
        # prompt (wrapper) and leak project context. Verified with a canary
        # file, 2026-09-23: read without this flag, not read with it.
        "-c", "project_doc_max_bytes=0",
        "-C", str(ROOT),
        "-m", model,
        "-c", f'model_reasoning_effort="{effort}"',
        "--json",
    ]
    if MCP_SERVER_PYTHON.is_file() and MCP_SERVER_SCRIPT.is_file():
        # --approve-for-me can't be combined with an explicit -s/--sandbox
        # flag (it sets its own, built on workspace-write) — and it's
        # required here: without it, non-interactive `codex exec` has no way
        # to satisfy the approval prompt an MCP tool call triggers by
        # default, and the call just fails ("requires approval, but approval
        # policy is never"). Confirmed live, 2026-09-07.
        cmd += [
            "--approve-for-me",
            "-c", f'mcp_servers.lean-arena.command="{MCP_SERVER_PYTHON}"',
            "-c", f'mcp_servers.lean-arena.args=["{MCP_SERVER_SCRIPT}"]',
            # submit_proof(all_versions=true) compiles on every toolchain;
            # Codex's default MCP tool timeout is far shorter than that.
            "-c", "mcp_servers.lean-arena.tool_timeout_sec=1800",
        ]
        if toolset == "student":
            assert tool_log is not None
            for feature in STUDENT_DISABLED_FEATURES:
                cmd += ["--disable", feature]
            cmd += [
                "-c", 'web_search="disabled"',
                "-c", 'mcp_servers.lean-arena.env.ARENA_TOOLSET="student"',
                "-c", f'mcp_servers.lean-arena.env.ARENA_PROBLEM="{name}"',
                "-c", f'mcp_servers.lean-arena.env.ARENA_EPISODE="{episode or ""}"',
                "-c", f'mcp_servers.lean-arena.env.ARENA_TOOL_LOG="{tool_log}"',
            ]
        # Experimental, one-off-tested-only (2026-09-07): Axiomatic Octo,
        # semantic search over Lean declarations. Pre-built coverage
        # confirmed for cslib/physlib/mathlib/batteries/core at our pinned
        # versions, free anonymous tier (no account, no key, 60 queries/hr).
        # NOT confirmed for arklib/strata. OCTO_FOLDER has to be the specific
        # per-problem project dir, not the shared competition root, since
        # that's what scopes which dependency versions it searches.
        if use_octo and toolset != "student" and OCTO_BIN.is_file():
            proj_dir = verify.project_dir(primary_version(name))
            if proj_dir is not None:
                cmd += [
                    "-c", f'mcp_servers.octo.command="{OCTO_BIN}"',
                    "-c", f'mcp_servers.octo.env.OCTO_FOLDER="{proj_dir}"',
                ]
    else:
        cmd += ["-s", "workspace-write"]
    return cmd


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "stealth/ox-alpha"
OPENROUTER_EFFORTS = ("low", "high", "max")  # this model has no "medium"
OPENROUTER_SYSTEM = (
    "You are an autonomous coding agent working on a single task. You have five "
    "tools, invoked via plain text — this environment has no native function "
    "calling, and tool arguments are NOT JSON (so shell commands and file "
    "contents never need escaping).\n\n"
    "To call a tool, your ENTIRE reply must be a single fenced block tagged "
    "`tool_call`. Its first line is the tool name; what follows depends on the "
    "tool. Nothing else may appear in the block. Only the FIRST tool_call block "
    "in a reply is ever executed — if you include more than one, the rest are "
    "silently dropped (the result will say so), so issue one call, read its "
    "result, then decide the next.\n\n"
    "get_target — no arguments; returns your current candidate declaration "
    "(statement + proof) exactly as it stands right now, with its file and "
    "starting line. Use this instead of read_file/bash to see what you're "
    "working with — it's already isolated from the rest of the file for you:\n"
    "```tool_call\n"
    "get_target\n"
    "```\n\n"
    "bash — remaining lines are the shell command verbatim (run via `bash -lc`, "
    "cwd defaults to the competition directory). Use for `lake env lean`, "
    "`arena.py check`, and rg/sed exploration of the corpus under .lake/packages:\n"
    "```tool_call\n"
    "bash\n"
    'cd /some/dir && rg -n "foo|bar" .\n'
    "```\n\n"
    "read_file — second line is the path, verbatim:\n"
    "```tool_call\n"
    "read_file\n"
    "/abs/path/to/file.lean\n"
    "```\n\n"
    "submit_proof — the PREFERRED way to update your answer. Remaining lines are "
    "the full replacement declaration (statement + `:=` + proof, byte-identical "
    "statement, verbatim, unescaped) — NOT the whole file, just this one "
    "declaration. This is the normal way to submit or revise your candidate. "
    "Its result automatically includes a quick primary-toolchain compile+score "
    "check (and how it compares to your best validated candidate so far this "
    "episode) — you don't need a separate `arena.py check` call just to see "
    "whether what you just submitted compiles; save that for the heavier "
    "`--all-versions` pass before finishing:\n"
    "```tool_call\n"
    "submit_proof\n"
    "theorem foo : P := by\n"
    "  proof_here\n"
    "```\n\n"
    "write_file — for files OTHER than the work file only; calling it on the "
    "work file is rejected (that file is too large to reproduce reliably — use "
    "submit_proof for it, always). Second line is the path, third line is "
    "exactly `---`, and everything after "
    "(verbatim, unescaped, to the closing fence) becomes the new file content — "
    "the FULL file content, not a diff:\n"
    "```tool_call\n"
    "write_file\n"
    "/abs/path/to/file.lean\n"
    "---\n"
    "<full file content>\n"
    "```\n\n"
    "Do not describe a tool call in prose without actually emitting the fenced "
    "block in the same reply — a reply with no `tool_call` block ends the "
    "session immediately, even if you said you were about to do something. "
    "When you are completely done, reply with plain text and no tool_call block, "
    "summarizing what you did as instructed below."
)
TOOL_CALL_RE = re.compile(r"```tool_call\s*\n(.*?)\n?```", re.DOTALL)

# Real OpenAI-style function calling, for models that support it (gpt-6-astra,
# gpt-5.6-sol almost certainly do — OPENROUTER_SYSTEM's text-fenced protocol
# above was only ever built because the original OpenRouter model on this
# backend, stealth/ox-alpha, had no native tool calling). Measured directly,
# 2026-09: the same model scored lower through the text-fence emulation than
# through real native tool-calling on the same problems — this exists to test
# whether that gap is about the protocol rather than the provider.
OPENROUTER_SYSTEM_NATIVE = (
    "You are an autonomous coding agent working on a single task. Use the "
    "provided tools — no special formatting needed, just call them.\n\n"
    "bash — run a shell command via `bash -lc`, cwd defaults to the "
    "competition directory. Use for `lake env lean`, `arena.py check`, and "
    "rg/sed exploration of the corpus under .lake/packages.\n\n"
    "read_file — read any file by absolute path.\n\n"
    "submit_proof — the PREFERRED way to update your answer. Its `proof` "
    "argument is the full replacement declaration (statement + `:=` + proof, "
    "byte-identical statement) — NOT the whole file, just this one "
    "declaration. This is the normal way to submit or revise your candidate.\n\n"
    "write_file — for files OTHER than the work file only; calling it on the "
    "work file is rejected (too large to reproduce reliably — use "
    "submit_proof for it, always). Takes the full file content, not a diff.\n\n"
    "You may call more than one tool in a turn if needed. When you are "
    "completely done, reply with plain text and no tool call, summarizing "
    "what you did as instructed below."
)

OPENROUTER_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command via `bash -lc` (cwd defaults to the "
                "competition directory)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command, verbatim."},
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
            "description": "Read a file by absolute path.",
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
            "name": "submit_proof",
            "description": (
                "Replace the candidate declaration (statement + `:=` + proof) "
                "for this problem. The statement must stay byte-identical to "
                "the original. This is the normal way to submit or revise "
                "your candidate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proof": {
                        "type": "string",
                        "description": "The full replacement declaration, verbatim, unescaped.",
                    },
                },
                "required": ["proof"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file OTHER than the work file (writing to "
                "the work file is rejected — use submit_proof for that)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "The full file content, not a diff."},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def parse_text_tool_call(content: Optional[str]) -> Optional[dict[str, Any]]:
    if not content:
        return None
    m = TOOL_CALL_RE.search(content)
    if not m:
        return None
    body = m.group(1)
    if body.endswith("\n"):
        body = body[:-1]
    lines = body.split("\n")
    if not lines:
        return None
    name = lines[0].strip()
    rest = lines[1:]

    if name == "get_target":
        return {"name": "get_target", "arguments": {}}

    if name == "bash":
        command = "\n".join(rest).strip()
        return {"name": "bash", "arguments": {"command": command}} if command else None

    if name == "read_file":
        path = rest[0].strip() if rest else ""
        return {"name": "read_file", "arguments": {"path": path}} if path else None

    if name == "submit_proof":
        proof = "\n".join(rest).strip()
        return {"name": "submit_proof", "arguments": {"proof": proof}} if proof else None

    if name == "write_file":
        if not rest:
            return None
        path = rest[0].strip()
        if not path:
            return None
        sep_idx = next((i for i, ln in enumerate(rest[1:], start=1) if ln.strip() == "---"), None)
        if sep_idx is None:
            return None
        content_lines = rest[sep_idx + 1 :]
        return {"name": "write_file", "arguments": {"path": path, "content": "\n".join(content_lines)}}

    return None


def _safe_path(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    # Scoped to ROOT (competition/), not ROOT.parent — RUNS/TRACES live one
    # level up specifically so they're outside this boundary too. See the
    # comment on RUNS above for why.
    guard = ROOT.resolve()
    if guard != p and guard not in p.parents:
        raise ValueError(f"path outside allowed tree: {p}")
    return p


def _truncate(s: str, limit: int = 8000) -> str:
    if len(s) <= limit:
        return s
    half = limit // 2
    return f"{s[:half]}\n... [truncated {len(s) - limit} chars] ...\n{s[-half:]}"


_RUNS_LEAK_MARKERS = (
    str(RUNS), "../runs", "../../runs", "runs/trials", "runs/episodes.jsonl",
    "codex.jsonl", "openrouter.jsonl", "claude.jsonl", "episode.json",
    str(RUNS.parent / "traces"), "../traces", "../../traces",
    str(RUNS.parent / "mining"), "../mining", "mining/discovered",
    str(RUNS.parent / "docs"), "../docs",
    ".codex/sessions",
)


def _bash_leak_check(command: str) -> Optional[str]:
    """Best-effort guard: openrouter `bash` has no OS sandbox, so cwd=ROOT
    alone doesn't stop `cd ../runs`. Not adversarial-proof (Codex `-C` is
    also cwd-only). Blocks the accidental-discovery pattern that actually
    happened (an agent grepping its own prior episode transcripts). Also
    flags mining/, docs/, and ~/.codex/sessions."""
    for marker in _RUNS_LEAK_MARKERS:
        if marker in command:
            return marker
    return None


def execute_openrouter_tool(call_name: str, call_args: dict[str, Any], *, name: str) -> str:
    try:
        if call_name == "get_target":
            # Every trace reviewed (2026-09-07, Astra) opened with 2-3 turns
            # of read-the-whole-file-then-hunt-for-the-declaration — this is
            # exactly that lookup done once, correctly, without a wasted turn.
            wf = work_file(name)
            if wf is None:
                return "[tool error] no work file — has this episode been prepared?"
            text = wf.read_text()
            start = verify.decl_start(text, verify.BENCHMARK[name])
            if start is None:
                return f"[tool error] could not locate the {name} declaration in {wf}"
            line_no = text.count("\n", 0, start) + 1
            decl = text[start:].strip()
            return f"Target declaration (from {wf}, starting at line {line_no}):\n{decl}"
        if call_name == "bash":
            command = call_args.get("command", "")
            hit = _bash_leak_check(command)
            if hit:
                return (
                    f"[tool error] refused: command references prior-episode data "
                    f"({hit!r}). Episode transcripts/scores are off-limits — solve "
                    f"this from the corpus/spec, not from past attempts."
                )
            timeout = min(int(call_args.get("timeout") or 300), 1200)
            # See the comment on _run_teacher's child_env: propagate the
            # episode id via env var so a `check` the model runs itself here
            # also gets tagged correctly, not just our own in-process checks.
            child_env = {**os.environ, "ARENA_EPISODE": CURRENT_EPISODE.get() or ""}
            proc = subprocess.run(
                ["bash", "-lc", command], cwd=ROOT,
                capture_output=True, text=True, timeout=timeout, env=child_env,
            )
            return _truncate(f"$ {command}\n[exit {proc.returncode}]\n{proc.stdout}{proc.stderr}")
        if call_name == "read_file":
            path = _safe_path(call_args.get("path", ""))
            return _truncate(path.read_text())
        if call_name == "write_file":
            path = _safe_path(call_args.get("path", ""))
            wf = work_file(name)
            if wf is not None and path == wf.resolve():
                return (
                    "[tool error] write_file is disabled for the work file — it's "
                    "too large to reproduce reliably. Use submit_proof instead: it "
                    "takes only the replacement declaration (statement + `:=` + "
                    "proof), not the whole file."
                )
            content = call_args.get("content", "")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"wrote {len(content)} bytes to {path}"
        if call_name == "submit_proof":
            proof = call_args.get("proof", "")
            if not proof.strip():
                return "[tool error] empty proof"
            write_candidate(name, proof)
            return f"wrote {len(proof)} chars as the candidate declaration for {name}"
        return f"unknown tool: {call_name}"
    except subprocess.TimeoutExpired:
        return f"[timed out]"
    except Exception as e:
        return f"[tool error] {type(e).__name__}: {e}"


def _openrouter_request(
    messages: list[dict[str, Any]],
    model: str,
    effort: str,
    api_key: str,
    *,
    max_tokens: int = 32000,
    tools: Optional[list[dict[str, Any]]] = None,
    retries: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning": {"effort": effort if effort in OPENROUTER_EFFORTS else "high"},
        # Ask OpenRouter to report actual $ cost alongside token counts, not
        # just prompt/completion_tokens — free on models where it's zero.
        "usage": {"include": True},
    }
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                OPENROUTER_URL, data=data,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=280) as resp:
                out = json.loads(resp.read())
            choice = out["choices"][0]
            message = choice["message"]
            # The Stealth provider occasionally returns HTTP 200 with an empty
            # message and native_finish_reason "network_error" — a transient
            # upstream failure, not a real "no tool calls, I'm done" turn.
            if not message.get("content") and not message.get("tool_calls"):
                last_err = RuntimeError(
                    f"empty message, native_finish_reason={choice.get('native_finish_reason')!r}"
                )
                time.sleep(8 * (attempt + 1))
                continue
            return message, (out.get("usage") or {})
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"openrouter request failed after {retries} tries: {last_err}")


def _looks_truncated(content: Optional[str]) -> bool:
    """True if a tool_call fence was opened but never closed — the reply hit
    max_tokens mid-block (often because hidden reasoning ate most of the
    budget), not a genuine final answer."""
    if not content:
        return False
    idx = content.find("```tool_call")
    if idx == -1:
        return False
    return content.count("```", idx) < 2


_UNFINISHED_RE = re.compile(r"(let me|i'll|i will|let's|going to|now let)\s*$", re.IGNORECASE)


def _looks_unfinished(content: Optional[str]) -> bool:
    """Heuristic: a real final answer is substantive; narrated-but-not-acted-on
    intent ("Let me rewrite the proof.") is short and trails off in future tense."""
    if not content:
        return True
    stripped = content.strip()
    if len(stripped) < 220:
        return True
    return bool(_UNFINISHED_RE.search(stripped[-120:]))


def run_openrouter(
    name: str,
    model: str,
    effort: str,
    log_path: Path,
    *,
    wall_seconds: int = 3600,
    max_turns: int = 100,
    checkpoint_timeout: int = 300,
    native_tools: bool = False,
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "backend": "openrouter", "model": model, "effort": effort, "wrapper": WRAPPER_ID,
        "native_tools": native_tools,
    }
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        info["exit_code"] = 1
        info["error"] = "OPENROUTER_API_KEY not set"
        log_path.write_text(json.dumps(info) + "\n")
        return info

    started = time.time()
    # The shared prompt template says "no cap on tool calls" — true for
    # codex/claude, false here: this backend enforces max_turns as a hard
    # cutoff. Astra flagged this directly (2026-09-06 harness-critique
    # consult) as a planning-assumption bug, not just a wording nit — the
    # model plans its search around a stated budget, and this backend's
    # budget claim was materially wrong.
    budget_correction = (
        f"\n\n---\nCorrection to the budget note above: under this backend, "
        f"tool calls are hard-capped at {max_turns} turns total, not "
        f"unlimited — submit_proof and a check are separate turns, so "
        f"submitting and immediately checking costs 2. If nothing you "
        f"submit ever passes --all-versions, the harness keeps the original "
        f"reference proof as your final score (0% improvement, not a "
        f"broken submission) — a safe, unimproved finish beats a risky one "
        f"that never compiles. Your own closing prose is not scored; "
        f"whatever you last successfully submitted and validated is what "
        f"counts, even if you run out of turns before writing a summary. "
        f"Each tool result below states your remaining turns."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": OPENROUTER_SYSTEM_NATIVE if native_tools else OPENROUTER_SYSTEM},
        {"role": "user", "content": build_prompt(name) + budget_correction},
    ]
    turn = 0
    stop_reason = "no_tool_calls"
    just_nudged = False  # allow re-nudging after real progress; only block back-to-back nudges
    wrap_up_nudged = False
    wrap_up_at = max(1, max_turns - 5)  # give it a graceful finish instead of a mid-proof
                                         # hard truncation at the cutoff below
    try:
        last_candidate = extract_candidate(name)
    except Exception:
        last_candidate = None
    outer_retry_budget = 3  # separate from _openrouter_request's own retries — a sustained
                             # rate limit can outlast that budget; don't lose a whole episode to it
    truncation_retry_budget = 5  # separate pool from just_nudged: a cut-off tool_call block
                                  # is a distinct, unambiguous signal, not the narration tic
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    with log_path.open("w") as log:
        while True:
            turn += 1
            elapsed = time.time() - started
            if elapsed > wall_seconds:
                stop_reason = "wall_clock"
                log.write(json.dumps({"turn": turn, "harness": f"stopping: wall clock {elapsed:.0f}s"}) + "\n")
                break
            if turn > max_turns:
                stop_reason = "max_turns"
                log.write(json.dumps({"turn": turn, "harness": f"stopping: max_turns {max_turns}"}) + "\n")
                break
            if not wrap_up_nudged and turn == wrap_up_at:
                wrap_up_nudged = True
                messages.append({
                    "role": "user",
                    "content": (
                        f"You're nearing the turn budget for this session (about "
                        f"{max_turns - turn} tool calls left). Start wrapping up now: "
                        f"if you have a working improvement, submit_proof it if you "
                        f"haven't already, then finish with a plain-text summary "
                        f"rather than continuing to explore."
                    ),
                })
                log.write(json.dumps({"turn": turn, "harness": f"nudge: approaching max_turns {max_turns}"}) + "\n")
                log.flush()
            try:
                msg, req_usage = _openrouter_request(
                    messages, model, effort, api_key, retries=6,
                    tools=OPENROUTER_TOOLS_SCHEMA if native_tools else None,
                )
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    usage_totals[k] += int(req_usage.get(k) or 0)
                usage_totals["cost_usd"] += float(req_usage.get("cost") or 0)
            except Exception as e:
                if outer_retry_budget > 0:
                    outer_retry_budget -= 1
                    log.write(json.dumps({"turn": turn, "harness": f"outer retry ({outer_retry_budget} left) after: {e}"}) + "\n")
                    log.flush()
                    turn -= 1
                    time.sleep(60)
                    continue
                stop_reason = "request_error"
                log.write(json.dumps({"turn": turn, "harness_error": str(e)}) + "\n")
                break
            log.write(json.dumps({"turn": turn, "role": "assistant", "message": msg}) + "\n")
            log.flush()

            content = msg.get("content")

            if native_tools:
                tool_calls = msg.get("tool_calls") or []
                messages.append(
                    {"role": "assistant", "content": content, "tool_calls": tool_calls}
                    if tool_calls else {"role": "assistant", "content": content}
                )
                if not tool_calls:
                    if not just_nudged and _looks_unfinished(content):
                        just_nudged = True
                        log.write(json.dumps({"turn": turn, "harness": "nudge: no tool call, reply looked unfinished"}) + "\n")
                        log.flush()
                        messages.append({
                            "role": "user",
                            "content": (
                                "You did not call a tool. If you intended to act (e.g. "
                                "submit a proof), call the appropriate tool now. If you "
                                "are actually finished, reply again with your final "
                                "summary as instructed."
                            ),
                        })
                        continue
                    stop_reason = "no_tool_calls"
                    break

                just_nudged = False
                any_edit = False
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    fn_name = fn.get("name", "")
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        fn_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError:
                        fn_args = {}
                    if not isinstance(fn_args, dict):
                        fn_args = {}
                    result = execute_openrouter_tool(fn_name, fn_args, name=name)
                    if fn_name in ("bash", "submit_proof", "write_file"):
                        any_edit = True
                    log.write(json.dumps({"turn": turn, "role": "tool", "name": fn_name, "args": fn_args, "result": result}) + "\n")
                    log.flush()
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})

                # Same auto-check-on-edit behavior as the text-fenced path
                # below, just appended as one trailing message after all of
                # this turn's tool calls are resolved (native calling can
                # return several tool_calls in one turn) instead of folded
                # into a single tool result.
                trailer = []
                if any_edit:
                    try:
                        current = extract_candidate(name)
                    except Exception:
                        current = None
                    if current and current != last_candidate:
                        last_candidate = current
                        try:
                            cp = check(name, all_versions=False, timeout=checkpoint_timeout)
                            best = best_so_far(name, CURRENT_EPISODE.get())
                            best_str = f"objective_sum_pct={best['objective_sum_pct']}" if best else "none yet"
                            trailer.append(
                                f"auto-check on this edit, primary toolchain only: "
                                f"compiled={cp.get('compiled')} eligible={cp.get('eligible')} "
                                f"heartbeats={cp.get('heartbeats')} "
                                f"objective_sum_pct={cp.get('objective_sum_pct')} || "
                                f"best validated candidate so far this episode: {best_str}. "
                                f"Run `arena.py check --all-versions` yourself to confirm "
                                f"cross-version survival before finishing."
                            )
                        except Exception as e:
                            log.write(json.dumps({"turn": turn, "harness": f"checkpoint check failed: {e}"}) + "\n")
                            log.flush()
                remaining = max_turns - turn
                trailer.append(f"{remaining} of {max_turns} tool calls remaining.")
                messages.append({"role": "user", "content": "[" + " ".join(trailer) + "]"})
                continue

            messages.append({"role": "assistant", "content": content})

            call = parse_text_tool_call(content)
            if call is None:
                if truncation_retry_budget > 0 and _looks_truncated(content):
                    truncation_retry_budget -= 1
                    log.write(json.dumps({"turn": turn, "harness": f"nudge: tool_call block truncated ({truncation_retry_budget} retries left)"}) + "\n")
                    log.flush()
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your reply was cut off before the tool_call block closed — you "
                            "ran out of response budget (this often happens when a lot of "
                            "reasoning precedes a large proof). Retry now: either be more "
                            "concise, or build the proof up incrementally across several "
                            "smaller submit_proof calls instead of one large one."
                        ),
                    })
                    continue
                if not just_nudged and _looks_unfinished(content):
                    just_nudged = True
                    log.write(json.dumps({"turn": turn, "harness": "nudge: no tool_call block, reply looked unfinished"}) + "\n")
                    log.flush()
                    messages.append({
                        "role": "user",
                        "content": (
                            "You did not include a tool_call block. If you intended to act "
                            "(e.g. submit a proof), do so now with the fenced format — "
                            "remember, submit_proof takes only the declaration, not the "
                            "whole file. If you are actually finished, reply again with your "
                            "final summary as instructed."
                        ),
                    })
                    continue
                stop_reason = "no_tool_calls"
                break

            just_nudged = False
            # Only the first ```tool_call``` block in a reply is ever parsed
            # (TOOL_CALL_RE.search, not findall) — a reply with several was
            # previously silently truncated to just the first with no signal
            # that the rest never ran. Confirmed live in two real episodes
            # (Astra trace review, 2026-09-07): a failed relative-path read
            # followed by a `pwd` + corrected absolute-path read in the same
            # reply, where only the first (failing) read executed; and a
            # submit_proof followed by a compile command, where only the
            # submission executed and the compile had to be re-requested a
            # full turn later.
            extra_blocks = len(TOOL_CALL_RE.findall(content)) - 1
            fn_name = call.get("name", "")
            fn_args = call.get("arguments") or {}
            if not isinstance(fn_args, dict):
                fn_args = {}
            result = execute_openrouter_tool(fn_name, fn_args, name=name)

            # Surface the checkpoint check directly in the tool result —
            # previously this ran silently, for bookkeeping only, forcing a
            # SEPARATE bash `arena.py check` turn after every submit_proof
            # just to learn whether it compiled. Astra's trace review
            # (2026-09-07) found half of one 20-turn episode's budget spent
            # on exactly these split submit-then-check round trips. This only
            # fires when the candidate actually changed, so a plain
            # exploratory bash call (e.g. an rg search) doesn't trigger an
            # extra compile. A `check` the model runs itself (via bash, as a
            # subprocess) can't inherit CURRENT_EPISODE either, so it
            # wouldn't land in the trial log under this episode without this —
            # doing it in-process here is what makes every real edit
            # recoverable, not just whatever's left at the end.
            if fn_name in ("bash", "submit_proof", "write_file"):
                try:
                    current = extract_candidate(name)
                except Exception:
                    current = None
                if current and current != last_candidate:
                    last_candidate = current
                    try:
                        cp = check(name, all_versions=False, timeout=checkpoint_timeout)
                        best = best_so_far(name, CURRENT_EPISODE.get())
                        best_str = f"objective_sum_pct={best['objective_sum_pct']}" if best else "none yet"
                        result += (
                            f"\n\n[auto-check on this edit, primary toolchain only: "
                            f"compiled={cp.get('compiled')} eligible={cp.get('eligible')} "
                            f"heartbeats={cp.get('heartbeats')} "
                            f"objective_sum_pct={cp.get('objective_sum_pct')} || "
                            f"best validated candidate so far this episode: {best_str}. "
                            f"Run `arena.py check --all-versions` yourself to confirm "
                            f"cross-version survival before finishing.]"
                        )
                    except Exception as e:
                        log.write(json.dumps({"turn": turn, "harness": f"checkpoint check failed: {e}"}) + "\n")
                        log.flush()

            if extra_blocks > 0:
                result += (
                    f"\n\n[harness note: your reply contained {extra_blocks + 1} "
                    f"tool_call blocks — only this first one ({fn_name}) ran. "
                    f"The rest were NOT executed. Only one tool call per reply "
                    f"is ever run; if you intended the others, issue them one "
                    f"at a time in following turns.]"
                )
            log.write(json.dumps({"turn": turn, "role": "tool", "name": fn_name, "args": fn_args, "result": result}) + "\n")
            log.flush()
            remaining = max_turns - turn
            messages.append({
                "role": "user",
                "content": f"Tool result:\n{result}\n\n[{remaining} of {max_turns} tool calls remaining]",
            })

    info["turns"] = turn
    info["stop_reason"] = stop_reason
    info["exit_code"] = 0
    info["wall_seconds"] = round(time.time() - started, 1)
    info["usage"] = {**usage_totals, "num_turns": turn}
    return info


SESSION_KEYS = ("session_id", "conversation_id", "thread_id", "rollout_path")


# Isolation for every Claude teacher run. Claude Code otherwise injects the
# owner's auto-memory for this repo (verified 2026-09-23: a teacher quoted
# project strategy from it) plus user/project settings, hooks and skills.
# --bare would strip all of it but refuses subscription auth (API key only).
CLAUDE_ISOLATION = [
    "--setting-sources", "",
    "--settings", '{"autoMemoryEnabled": false}',
    "--disable-slash-commands",
    "--no-session-persistence",
]


def claude_command(model: str, effort: str, *, mcp_config: Optional[Path] = None,
                   max_budget_usd: Optional[float] = None) -> list[str]:
    """Headless Claude Code. With mcp_config (--toolset student): no built-in
    tools, only the student MCP tools; otherwise the legacy full tool set."""
    # Resolve explicitly: some launchers (background jobs, other agents) hand
    # children a PATH without ~/.local/bin, where the installer puts claude.
    exe = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    cmd = [exe, "-p", "--model", model, "--effort", effort,
           "--output-format", "stream-json", "--verbose", *CLAUDE_ISOLATION]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    if mcp_config is not None:
        return cmd + ["--tools", "", "--mcp-config", str(mcp_config), "--strict-mcp-config",
                      "--allowedTools", "mcp__lean-arena__*"]
    return cmd + ["--permission-mode", "bypassPermissions", "--add-dir", str(ROOT)]


def _run_teacher(
    cmd: list[str],
    prompt: str,
    log_path: Path,
    info: dict[str, Any],
    *,
    wall_seconds: Optional[int] = None,
) -> dict[str, Any]:
    started = time.time()
    # CURRENT_EPISODE is a contextvar — it doesn't cross the process boundary,
    # so a `python3 arena.py check` the agent runs itself (as a subprocess of
    # this subprocess) can't see it and record_trial() tags it episode=None.
    # An env var does cross forks/execs, so pass it down explicitly; record_trial
    # falls back to reading it. This is what makes checkpoint recovery see the
    # agent's own intermediate checks for the codex/claude backends, not just
    # the harness's final in-process one.
    child_env = {**os.environ, "ARENA_EPISODE": CURRENT_EPISODE.get() or "",
                 "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}  # see CLAUDE_ISOLATION
    timed_out = False
    with log_path.open("w") as log:
        proc = subprocess.Popen(
            cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, env=child_env,
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write(prompt)
        proc.stdin.close()

        # Hard backstop only — neither backend exposes a native turn/token
        # cap, and the read loop below blocks on `for line in proc.stdout`,
        # so a stalled/runaway session needs an external timer to preempt it
        # rather than a check inline in the loop. This is what makes the
        # earlier orphaned-lean-process pattern (an outer shell `timeout`
        # that doesn't reach grandchildren) not apply here: this terminates
        # OUR direct child, which owns the process group for its own
        # descendants (lake env lean etc.), same as subprocess timeout=
        # elsewhere in this file.
        timer: Optional[threading.Timer] = None
        if wall_seconds:
            def _on_timeout() -> None:
                nonlocal timed_out
                timed_out = True
                proc.terminate()
            timer = threading.Timer(wall_seconds, _on_timeout)
            timer.daemon = True
            timer.start()
        try:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for key in SESSION_KEYS:
                    found = _deep_get(event, key)
                    if found and key not in info:
                        info[key] = found
        finally:
            if timer:
                timer.cancel()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    info["exit_code"] = proc.returncode
    info["wall_seconds"] = round(time.time() - started, 1)
    if timed_out:
        info["capped"] = True
        info["stop_reason"] = "teacher_wall_clock"
    return info


def _with_turn_budget(prompt: str, max_turns: Optional[int]) -> str:
    """Codex/Claude expose no native turn/token cap — `codex exec` runs a
    single opaque agentic session with no mid-stream budget knob, and
    force-killing it loses the only usage report it ever emits (see
    _parse_codex_usage). So instead of an external cap, tell the model its
    budget and let it wrap up on its own — this is what a "capped" episode
    means for these two backends, unlike openrouter's hard turn cutoff."""
    if not max_turns:
        return prompt
    return prompt + (
        f"\n\n---\nResource budget: aim to land your best candidate within "
        f"roughly {max_turns} tool calls. This is a soft guide, not a hard "
        f"cutoff — take a few more if you're clearly about to land a real "
        f"improvement. But once you're circling without concrete progress, "
        f"stop: submit_proof your current best (if you haven't already) and "
        f"end the session instead of continuing to explore."
    )


def _parse_codex_usage(log_path: Path) -> dict[str, Any]:
    """Codex exec's whole run is a single "turn" from the CLI's point of
    view — it emits exactly one turn.completed event, at the very end, with
    cumulative token usage for the whole session. There is no incremental
    per-tool-call usage in the stream, so a session killed before that event
    (e.g. by _run_teacher's wall-clock backstop) yields no usage at all —
    that's a real blind spot, not a bug here; document it, don't fake it.
    "num_turns" is a proxy (agent_message + command_execution item counts),
    since codex has no native turn counter of its own to report."""
    usage: dict[str, Any] = {}
    turns = 0
    if not log_path.is_file():
        return usage
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = dict(event["usage"])
        elif event.get("type") == "item.completed":
            item_type = (event.get("item") or {}).get("type")
            if item_type in ("agent_message", "command_execution"):
                turns += 1
    if usage:
        usage["num_turns"] = turns
    return usage


def _parse_claude_usage(log_path: Path) -> dict[str, Any]:
    """Claude Code's stream-json emits a final `type: "result"` event with
    the session's cumulative usage and an actual total_cost_usd computed at
    provider rates — no manual accumulation needed, unlike the per-message
    usage blocks earlier in the same stream. Same blind spot as codex if the
    session is killed before this event fires."""
    if not log_path.is_file():
        return {}
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            usage = dict(event.get("usage") or {})
            if "total_cost_usd" in event:
                usage["cost_usd"] = event["total_cost_usd"]
            if "num_turns" in event:
                usage["num_turns"] = event["num_turns"]
            return usage
    return {}


def run_codex(
    name: str, model: str, effort: str, log_path: Path, *,
    max_turns: Optional[int] = None, teacher_timeout: Optional[int] = None,
    use_octo: bool = False, toolset: str = "legacy",
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "backend": "codex", "model": model, "effort": effort, "wrapper": WRAPPER_ID,
    }
    if max_turns:
        info["turn_budget"] = max_turns
    if toolset == "student":
        # Same user turn the student is served with; the tool log next to the
        # rollout is the trace (see student_tools.py).
        import student_tools
        if not (MCP_SERVER_PYTHON.is_file() and MCP_SERVER_SCRIPT.is_file()):
            raise RuntimeError("--toolset student needs the mcp_server venv")
        tool_log = log_path.parent / "tools.jsonl"
        info["toolset"] = student_tools.TOOLSET_ID
        info["tool_log"] = str(tool_log)
        prompt = _with_turn_budget(student_tools.prompt_for(name), max_turns)
        (log_path.parent / "prompt.txt").write_text(prompt)
        cmd = codex_command(name, model, effort, toolset="student",
                            episode=CURRENT_EPISODE.get(), tool_log=tool_log)
        info = _run_teacher(cmd, prompt, log_path, info, wall_seconds=teacher_timeout)
        info["usage"] = _parse_codex_usage(log_path)
        return info
    prompt = _with_turn_budget(build_prompt(name), max_turns)
    if MCP_SERVER_PYTHON.is_file() and MCP_SERVER_SCRIPT.is_file():
        prompt += (
            "\n\n---\nTwo extra tools are available beyond your usual "
            "shell/file tools, both scoped to this problem "
            f'(pass name="{name}"): `get_target` returns your current '
            "candidate declaration directly, already isolated from the rest "
            "of the file — prefer it over reading the whole file yourself. "
            "`evaluate_candidate` replaces the candidate and compiles+scores "
            "it in one call (pass all_versions=true for the full "
            "cross-toolchain confirmation before finishing), and reports the "
            "best validated candidate so far this episode — prefer it over "
            "editing the file directly and running a separate check command."
        )
    if use_octo and OCTO_BIN.is_file():
        info["used_octo"] = True
        prompt += (
            "\n\n---\nAn `octo` MCP server is also available: `query` does "
            "semantic search over this problem's Lean dependencies (pass a "
            "natural-language description of what you need, not just "
            "keywords — it searches meaning, not text). Use it to find "
            "relevant lemmas/instances you don't already know the exact "
            "name for; prefer it over guessing names or grepping when "
            "you're not sure what exists."
        )
    info = _run_teacher(codex_command(name, model, effort, use_octo=use_octo), prompt, log_path, info, wall_seconds=teacher_timeout)
    info["usage"] = _parse_codex_usage(log_path)
    return info


def run_claude(
    name: str, model: str, effort: str, log_path: Path, *,
    max_turns: Optional[int] = None, teacher_timeout: Optional[int] = None,
    toolset: str = "legacy", max_budget_usd: Optional[float] = None,
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "backend": "claude", "model": model, "effort": effort, "wrapper": WRAPPER_ID,
    }
    if max_turns:
        info["turn_budget"] = max_turns
    mcp_config = None
    if toolset == "student":
        import student_tools
        tool_log = log_path.parent / "tools.jsonl"
        mcp_config = log_path.parent / "mcp.json"
        mcp_config.write_text(json.dumps({"mcpServers": {"lean-arena": {
            "command": str(MCP_SERVER_PYTHON), "args": [str(MCP_SERVER_SCRIPT)],
            "env": {"ARENA_TOOLSET": "student", "ARENA_PROBLEM": name,
                    "ARENA_EPISODE": CURRENT_EPISODE.get() or "", "ARENA_TOOL_LOG": str(tool_log)},
        }}}))
        info["toolset"] = student_tools.TOOLSET_ID
        info["tool_log"] = str(tool_log)
        prompt = _with_turn_budget(student_tools.prompt_for(name), max_turns)
    else:
        prompt = _with_turn_budget(build_prompt(name), max_turns)
    (log_path.parent / "prompt.txt").write_text(prompt)
    info = _run_teacher(claude_command(model, effort, mcp_config=mcp_config, max_budget_usd=max_budget_usd),
                        prompt, log_path, info,
                        wall_seconds=teacher_timeout)
    info["usage"] = _parse_claude_usage(log_path)
    return info


def _deep_get(obj: Any, key: str) -> Optional[Any]:
    if isinstance(obj, dict):
        if isinstance(obj.get(key), str):
            return obj[key]
        for value in obj.values():
            found = _deep_get(value, key)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _deep_get(value, key)
            if found:
                return found
    return None


def run_episode(
    name: str,
    *,
    backend: str = "codex",
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    timeout: int = 1800,
    fresh: bool = True,
    max_turns: Optional[int] = None,
    teacher_timeout: Optional[int] = None,
    use_octo: bool = False,
    native_tools: bool = False,
    toolset: str = "legacy",
    max_budget_usd: Optional[float] = None,
) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / f"{stamp}-{slug(name)}"
    run_dir.mkdir(parents=True, exist_ok=True)

    wf = prepare(name, force=fresh)
    (run_dir / "before.lean").write_text(wf.read_text())
    ref = local_reference().get(name, {})
    before = {
        "length": local_score.original_length(name),
        "heartbeats": ref.get("heartbeats") or local_score.original_heartbeats(name),
        "compiled": ref.get("compiled"),
    }

    token = CURRENT_EPISODE.set(stamp)
    try:
        if backend == "claude":
            if model == DEFAULT_MODEL:
                model = "opus"
            teacher_info = run_claude(name, model, effort, run_dir / "claude.jsonl",
                                       max_turns=max_turns, teacher_timeout=teacher_timeout,
                                       toolset=toolset, max_budget_usd=max_budget_usd)
        elif backend == "openrouter":
            if model == DEFAULT_MODEL:
                model = OPENROUTER_DEFAULT_MODEL
            teacher_info = run_openrouter(name, model, effort, run_dir / "openrouter.jsonl",
                                           native_tools=native_tools,
                                           **({"max_turns": max_turns} if max_turns else {}))
        else:
            teacher_info = run_codex(name, model, effort, run_dir / "codex.jsonl",
                                      max_turns=max_turns, teacher_timeout=teacher_timeout,
                                      use_octo=use_octo, toolset=toolset)
        agent_final = check(name, all_versions=True, timeout=timeout)
        agent_text = extract_candidate(name) or ""
        (run_dir / "agent_final.lean").write_text(wf.read_text())
        after, promotions = best_checkpoint(
            name,
            episode=stamp,
            current=agent_final,
            current_candidate=agent_text,
            timeout=timeout,
        )
        (run_dir / "after.lean").write_text(wf.read_text())
    finally:
        CURRENT_EPISODE.reset(token)

    record = {
        "timestamp": stamp,
        "name": name,
        "wrapper": WRAPPER_ID,
        "run_dir": str(run_dir),
        "backend": backend,
        "codex": teacher_info,
        "before": before,
        "after": after,
        "agent_final": agent_final,
        "checkpoint_promotions": promotions,
        "candidate": extract_candidate(name),
    }
    EPISODES.parent.mkdir(parents=True, exist_ok=True)
    with EPISODES.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    (run_dir / "episode.json").write_text(json.dumps(record, indent=2))
    return record


# ── Readiness ─────────────────────────────────────────────────────────────────

def rescore(name: str, run_dir: Path, *, all_versions: bool = True, timeout: int = 1800) -> dict[str, Any]:
    """Re-check a candidate already sitting on disk from a past episode — no
    teacher call, no new API spend. Exists because several genuine wins were
    reported as Σ=0 purely because a toolchain wasn't built locally yet at
    episode time; once it is, this recovers the true score for free."""
    agent_final_path = run_dir / "agent_final.lean"
    if not agent_final_path.is_file():
        sys.exit(f"no agent_final.lean in {run_dir}")
    text = agent_final_path.read_text()
    start = verify.decl_start(text, verify.BENCHMARK[name])
    if start is None:
        sys.exit(f"could not locate the {name} declaration in {agent_final_path}")
    candidate = text[start:].strip()
    return check(name, all_versions=all_versions, timeout=timeout, candidate=candidate)


def usage_report() -> None:
    """Per-episode token/cost visibility, computed by re-parsing each run's
    raw teacher log on demand rather than trusting episodes.jsonl — most
    existing records predate this and were written before usage was ever
    captured, so this has to work retroactively over logs already on disk,
    not just for episodes run after this was added.

    Old openrouter episodes are the one real gap: _openrouter_request used
    to discard the response's usage object entirely (never logged it), so
    there's nothing to recover for those short of re-running them."""
    if not RUNS.is_dir():
        print("no runs/ directory yet")
        return
    total_cost = 0.0
    known_cost_n = 0
    for run_dir in sorted(RUNS.iterdir()):
        if not run_dir.is_dir():
            continue
        ep_path = run_dir / "episode.json"
        if not ep_path.is_file():
            continue
        try:
            ep = json.loads(ep_path.read_text())
        except json.JSONDecodeError:
            continue
        backend = ep.get("backend", "?")
        if backend == "codex":
            u = _parse_codex_usage(run_dir / "codex.jsonl")
        elif backend == "claude":
            u = _parse_claude_usage(run_dir / "claude.jsonl")
        elif backend == "openrouter":
            u = (ep.get("codex") or {}).get("usage") or {}
        else:
            u = {}

        cost = u.get("cost_usd")
        if isinstance(cost, (int, float)):
            total_cost += cost
            known_cost_n += 1
        in_tok = u.get("input_tokens", u.get("prompt_tokens"))
        cached = u.get("cached_input_tokens", u.get("cache_read_input_tokens"))
        out_tok = u.get("output_tokens", u.get("completion_tokens"))
        turns = u.get("num_turns")
        capped = " [capped]" if (ep.get("codex") or {}).get("capped") else ""
        cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) else "?"
        print(
            f"{run_dir.name:42s} {ep.get('name', '?'):45s} {backend:11s} "
            f"in={in_tok!s:>9} cached={cached!s:>9} out={out_tok!s:>7} "
            f"turns={turns!s:>4} cost={cost_str}{capped}"
        )
    print(
        f"\ntotal known cost: ${total_cost:.4f} across {known_cost_n} episode(s) "
        f"with a reported $ figure (claude reports it directly; codex/openrouter "
        f"here mostly report token counts only — stealth/ox-alpha is free, and "
        f"gpt-5.6-sol's per-token rate isn't wired in, so its $ cost isn't shown)"
    )


def list_problems() -> None:
    swept = verify.sweep_stray_temp_files()
    if swept:
        print(f"[swept {len(swept)} stray temp file(s) from a previous killed check]", file=sys.stderr)
    refs = local_reference()
    for name in verify.BENCHMARK:
        versions = verify.versions_for(name)
        top = primary_version(name)
        ref = refs.get(name, {})
        # Live filesystem check, not the (possibly stale) measurement file —
        # that file predates this machine's last rebuild and was reporting
        # projects as ready when they had zero packages built.
        ready = "".join("." if verify.env_ready(v) else "x" for v in versions) or "?"
        print(
            f"{name}\n"
            f"    corpus={verify.BENCHMARK[name].get('source')} primary={top} "
            f"versions={','.join(versions)} env={ready} "
            f"len={local_score.original_length(name)} "
            f"hb_local={ref.get('heartbeats')} hb_published={ref.get('published_heartbeats')}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--name", required=True)
    p.add_argument("--version")
    p.add_argument("--force", action="store_true", help="reset to the reference proof")

    c = sub.add_parser("check")
    c.add_argument("--name", required=True)
    c.add_argument("--all-versions", action="store_true")
    c.add_argument("--timeout", type=int, default=1800)

    r = sub.add_parser("run")
    r.add_argument("--name", required=True)
    r.add_argument("--backend", choices=["codex", "claude", "openrouter"], default="codex")
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--effort", default=DEFAULT_EFFORT)
    r.add_argument("--timeout", type=int, default=1800)
    r.add_argument("--keep-work-file", action="store_true",
                   help="continue from the current work file instead of resetting")
    r.add_argument("--max-turns", type=int, default=None,
                   help="turn/tool-call budget: hard cutoff for openrouter, a soft "
                        "in-prompt hint for codex/claude (neither exposes a real cap)")
    r.add_argument("--teacher-timeout", type=int, default=None,
                   help="hard wall-clock cap in seconds for the teacher subprocess "
                        "(codex/claude only; openrouter already has its own wall_seconds)")
    r.add_argument("--use-octo", action="store_true",
                   help="codex backend only, experimental (2026-09-07, one test run so "
                        "far): register Axiomatic Octo as a second MCP server for "
                        "semantic search over this problem's dependencies")
    r.add_argument("--native-tools", action="store_true",
                   help="openrouter backend only, experimental: use real OpenAI-style "
                        "function calling instead of the text-fenced tool_call protocol "
                        "(only makes sense for a model that actually supports native "
                        "tool calling — gpt-6-astra/gpt-5.6-sol should, stealth/ox-alpha "
                        "does not, which is why the text-fenced path exists at all)")
    r.add_argument("--max-budget-usd", type=float, default=None,
                   help="claude backend: stop the teacher at this (API-equivalent) spend")
    r.add_argument("--toolset", choices=["legacy", "student"], default="legacy",
                   help="codex/claude backends: `student` exposes only the student tool set "
                        "(student_tools.py) over MCP, disables Codex's own shell, and logs "
                        "every resolved call to <run_dir>/tools.jsonl — the SFT trace. "
                        "Use this for all training-data collection.")

    sub.add_parser("list")
    sub.add_parser("usage")

    rs = sub.add_parser("rescore")
    rs.add_argument("--name", required=True)
    rs.add_argument("--run-dir", required=True,
                     help="run directory basename (e.g. 20260828T040501Z-putnam_1964_a4) or full path")
    rs.add_argument("--timeout", type=int, default=1800)

    pr = sub.add_parser("prompt")
    pr.add_argument("--name", required=True)

    args = ap.parse_args()
    if getattr(args, "name", None) and args.name not in verify.BENCHMARK:
        sys.exit(f"unknown problem: {args.name}")

    if args.cmd == "prepare":
        print(prepare(args.name, args.version, force=args.force))
    elif args.cmd == "check":
        print(json.dumps(check(args.name, all_versions=args.all_versions,
                               timeout=args.timeout), indent=2))
    elif args.cmd == "prompt":
        print(build_prompt(args.name))
    elif args.cmd == "run":
        rec = run_episode(args.name, backend=args.backend, model=args.model,
                          effort=args.effort, timeout=args.timeout,
                          fresh=not args.keep_work_file,
                          max_turns=args.max_turns, teacher_timeout=args.teacher_timeout,
                          use_octo=args.use_octo, native_tools=args.native_tools,
                          toolset=args.toolset, max_budget_usd=args.max_budget_usd)
        print(json.dumps(rec["after"], indent=2))
    elif args.cmd == "list":
        list_problems()
    elif args.cmd == "usage":
        usage_report()
    elif args.cmd == "rescore":
        rd = Path(args.run_dir)
        if not rd.is_absolute() and not rd.is_dir():
            rd = RUNS / args.run_dir
        print(json.dumps(rescore(args.name, rd, timeout=args.timeout), indent=2))


if __name__ == "__main__":
    main()
