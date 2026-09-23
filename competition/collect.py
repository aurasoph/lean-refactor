#!/usr/bin/env python3
"""Unattended SFT-data collection. One command, runs for days, resumable:

  nohup python3 competition/collect.py > runs/collect.out 2>&1 &
  python3 competition/collect.py --status          # progress, any time
  python3 competition/collect.py --dry-run         # what it would do next

Each iteration re-derives state from runs/episodes.jsonl (kill it and restart
it whenever) and does the highest-priority job, one Lean job at a time:

  1. first pass:  a --weak (Sol) episode on every problem that has none
  2. salvage:     a --strong (Astra) episode where the weak teacher's
                  episodes produced nothing usable (weaker-first: the student
                  imitates the weak teacher where it can)
  3. grow pool:   promote the next --promote-batch mined candidates
                  (mining/promote_discovered.py) when 1-2 are exhausted
  4. also:        one episode per problem from each --also teacher (e.g.
                  claude:opus), for teacher diversity
  5. more seeds:  another weak episode on the problem with the fewest usable
                  episodes, up to --max-seeds

A teacher is a Codex model name (gpt-5.6-sol) or `claude:<model>` for Claude
Code (claude:opus, claude:sonnet), which runs with no built-in tools, only
the student MCP tools, and no user memory/settings (arena.CLAUDE_ISOLATION).
Claude episodes use the owner's Claude subscription, the same usage pool
as interactive Claude Code.

It stops when --target usable episodes exist or nothing is left. "Usable"
approximates training/build_sft.py's filter (the build applies the rest).

All episodes use `arena.py run --toolset student`: the only
tools the teacher has are student_tools.py's, and runs/<ep>/tools.jsonl is
the trace. Held-out test problems (training/splits.py) are never collected.

Usage guard (never spend paid credits / extra usage): both CLIs report the
subscription's rate-limit windows in their logs (Codex rollouts:
rate_limits.primary/secondary; Claude stream: rate_limit_event). Before each
episode, if that backend's 5-hour window is above --max-5h or its weekly
window above --max-week, the loop sleeps until the window resets. If any run
reports credits/overage in use, collection stops outright. Claude runs also
get --max-budget-usd per episode. Turning off extra usage / credit top-ups
in your account settings is still the only hard guarantee.

Failures don't burn the queue. If an episode makes no tool calls (Codex
error, usage limit, auth), the loop backs off (15 min, doubling to 3 h) and
retries. A problem whose episodes fail --max-failures times is skipped.

Never wrap this in an outer shell `timeout` (docs/HANDOFF.md).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO / "training"))

import arena  # noqa: E402
import student_tools  # noqa: E402
import verify  # noqa: E402
from splits import split_of  # noqa: E402

LOG = arena.RUNS / "collect.log"


def log(event: dict[str, Any]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **event})
    with LOG.open("a") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def episodes() -> list[dict[str, Any]]:
    """student-toolset episodes on the current wrapper, newest last."""
    out = []
    if arena.EPISODES.exists():
        for line in arena.EPISODES.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            info = rec.get("codex") or {}
            if (rec.get("backend") in ("codex", "claude") and rec.get("wrapper") == arena.WRAPPER_ID
                    and info.get("toolset") == student_tools.TOOLSET_ID):
                out.append(rec)
    return out


def tool_calls(rec: dict[str, Any]) -> int:
    p = arena.RUNS / Path(rec.get("run_dir", "")).name / "tools.jsonl"
    return sum(1 for l in p.read_text().splitlines() if l.strip()) if p.is_file() else 0


def usable(rec: dict[str, Any]) -> bool:
    final = rec.get("agent_final") or {}
    return (bool(final.get("eligible")) and (final.get("survival_pct") or 0) >= 100
            and (final.get("objective_sum_pct") or 0) > 0 and not rec.get("checkpoint_promotions")
            and tool_calls(rec) > 0)


def failures() -> Counter:
    """Per problem: episodes with no tool calls + arena.py crashes (from collect.log)."""
    c: Counter = Counter()
    for rec in episodes():
        if tool_calls(rec) == 0:
            c[rec["name"]] += 1
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "end" and ev.get("exit") not in (0, None):
                c[ev["name"]] += 1
    return c


def problems() -> list[str]:
    """Collectable problems: not held out, every listed toolchain built."""
    out = []
    for name in verify.BENCHMARK:
        versions = verify.versions_for(name)
        if split_of(name) != "test" and versions and all(verify.env_ready(v) for v in versions):
            out.append(name)
    return out


def teacher(spec: str) -> tuple[str, str]:
    """'claude:opus' -> ('claude', 'opus'); 'gpt-5.6-sol' -> ('codex', 'gpt-5.6-sol')."""
    backend, _, model = spec.partition(":")
    return (backend, model) if model else ("codex", spec)


def spec_of(rec: dict[str, Any]) -> str:
    model = (rec.get("codex") or {}).get("model")
    return f"claude:{model}" if rec.get("backend") == "claude" else model


CODEX_SESSIONS = Path.home() / ".codex" / "sessions"


def _latest(paths: list[Path]) -> Optional[Path]:
    paths = [p for p in paths if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def usage(backend: str) -> Optional[dict[str, Any]]:
    """Latest reported subscription usage for a CLI: {'5h': (frac, reset_ts),
    'week': (frac, reset_ts), 'paid': bool}. None if nothing reported yet."""
    if backend == "claude":
        log_file = _latest(list(arena.RUNS.glob("*/claude.jsonl")))
        last = None
        for line in (log_file.read_text().splitlines() if log_file else []):
            if '"rate_limit_event"' in line:
                try:
                    last = json.loads(line)["rate_limit_info"]
                except (json.JSONDecodeError, KeyError):
                    pass
        if not last:
            return None
        w = last.get("unifiedWindows") or {}
        get = lambda k: ((w.get(k) or {}).get("utilization") or 0.0, (w.get(k) or {}).get("resetsAt") or 0)
        return {"5h": get("five_hour"), "week": get("seven_day"), "paid": bool(last.get("isUsingOverage"))}
    rollout = _latest(list(CODEX_SESSIONS.glob("*/*/*/rollout-*.jsonl")))  # includes interactive Codex use
    last = None
    for line in (rollout.read_text().splitlines() if rollout else []):
        if '"rate_limits"' in line:
            try:
                last = json.loads(line)["payload"]["rate_limits"]
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
    if not last:
        return None
    get = lambda k: (((last.get(k) or {}).get("used_percent") or 0.0) / 100, (last.get(k) or {}).get("resets_at") or 0)
    credits = last.get("credits") or {}
    paid = bool(last.get("rate_limit_reached_type")) and bool(credits.get("has_credits"))
    return {"5h": get("primary"), "week": get("secondary"), "paid": paid}


def usage_wait(backend: str, args: argparse.Namespace) -> Optional[tuple[str, float]]:
    """('stop', 0) if paid usage is in play; ('wait', seconds) if a window is too full; else None."""
    u = usage(backend)
    if u is None:
        return None
    if u["paid"]:
        return ("stop", 0.0)
    now = time.time()
    for key, cap in (("week", args.max_week), ("5h", args.max_5h)):
        frac, reset = u[key]
        if frac >= cap and reset > now:
            return ("wait", reset - now + 60)
    return None


def state(args: argparse.Namespace) -> dict[str, Any]:
    fails = failures()
    probs = [p for p in problems() if fails[p] < args.max_failures]
    real: dict[str, list[dict]] = defaultdict(list)  # episodes that actually ran
    for rec in episodes():
        if tool_calls(rec) > 0:
            real[rec["name"]].append(rec)

    def n(p: str, model: Optional[str] = None, ok: Optional[bool] = None) -> int:
        return sum(1 for r in real[p]
                   if (model is None or spec_of(r) == model)
                   and (ok is None or usable(r) == ok))

    return {
        "problems": probs,
        "skipped": sorted(p for p in problems() if fails[p] >= args.max_failures),
        "usable_total": sum(n(p, ok=True) for p in probs),
        "first_pass": [p for p in probs if n(p, args.weak) == 0],
        "salvage": [p for p in probs if n(p, args.weak) > 0 and n(p, ok=True) == 0 and n(p, args.strong) == 0],
        "also": [(p, t) for t in args.also for p in probs if n(p, t) == 0],
        "seeds": sorted((p for p in probs if 0 < n(p, ok=True) < args.max_seeds and n(p) < args.max_seeds + 1),
                        key=lambda p: (n(p, ok=True), n(p))),
        "per_model": Counter(spec_of(r) for p in probs for r in real[p]),
    }


def promotion_pool() -> int:
    out = subprocess.run([sys.executable, str(REPO / "mining" / "promote_discovered.py"), "--dry-run"],
                         capture_output=True, text=True)
    try:
        return int(out.stderr.split(" candidate")[0].split()[-1])
    except (ValueError, IndexError):
        return 0


def next_job(st: dict[str, Any], args: argparse.Namespace, pool: int,
             blocked: frozenset = frozenset()) -> Optional[tuple[str, str, str]]:
    """Highest-priority job whose teacher's backend isn't usage-blocked."""
    ok = lambda spec: bool(spec) and teacher(spec)[0] not in blocked
    if st["first_pass"] and ok(args.weak):
        return ("episode", st["first_pass"][0], args.weak)
    if st["salvage"] and ok(args.strong):
        return ("episode", st["salvage"][0], args.strong)
    if pool > 0:
        return ("promote", "", "")
    for p, t in st["also"]:
        if ok(t):
            return ("episode", p, t)
    if st["seeds"] and ok(args.weak):
        return ("episode", st["seeds"][0], args.weak)
    return None


def run_episode(name: str, spec: str, args: argparse.Namespace) -> bool:
    backend, model = teacher(spec)
    log({"event": "start", "name": name, "model": spec})
    t0 = time.time()
    before = {r["timestamp"] for r in episodes()}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "arena.py"), "run", "--name", name,
         "--backend", backend, "--toolset", "student", "--model", model,
         "--effort", args.effort, "--teacher-timeout", str(args.teacher_timeout),
         *(["--max-budget-usd", str(args.max_budget_usd)] if backend == "claude" else [])],
        cwd=ROOT, capture_output=True, text=True,
    )
    # Only an episode recorded by THIS run counts — a crash before recording
    # must not be mistaken for success via an older episode of the problem.
    newest = next((r for r in reversed(episodes())
                   if r["name"] == name and r["timestamp"] not in before), None)
    ran = newest is not None and tool_calls(newest) > 0 and proc.returncode == 0
    log({"event": "end", "name": name, "model": spec, "exit": proc.returncode,
         "wall": round(time.time() - t0), "tool_calls": tool_calls(newest) if newest else 0,
         "usable": bool(newest and usable(newest)),
         "objective_sum_pct": ((newest or {}).get("agent_final") or {}).get("objective_sum_pct"),
         **({} if ran else {"codex_error": codex_error(newest), "tail": (proc.stdout + proc.stderr)[-800:]})})
    return ran


def codex_error(rec: Optional[dict[str, Any]]) -> Optional[str]:
    """Last `error`/`turn.failed` message in the episode's Codex log (usage limits, auth, bad model)."""
    if rec is None:
        return None
    p = arena.RUNS / Path(rec.get("run_dir", "")).name / "codex.jsonl"
    msg = None
    if p.is_file():
        for line in p.read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "error":
                msg = ev.get("message")
            elif ev.get("type") == "turn.failed":
                msg = (ev.get("error") or {}).get("message") or msg
    return msg[:500] if msg else None


def show(st: dict[str, Any], args: argparse.Namespace, pool: int) -> None:
    print(f"usable episodes: {st['usable_total']} / target {args.target}")
    print(f"problems: {len(st['problems'])} collectable, {pool} mined candidates left to promote, "
          f"{len(st['skipped'])} skipped after {args.max_failures} failures")
    print(f"queue: first-pass {len(st['first_pass'])}, salvage {len(st['salvage'])}, "
          f"also {len(st['also'])}, extra seeds {len(st['seeds'])}")
    print(f"episodes by teacher: {dict(st['per_model'])}")
    for b in ("codex", "claude"):
        u = usage(b)
        if u:
            print(f"{b} usage: 5h {u['5h'][0]:.0%} (cap {args.max_5h:.0%}), week {u['week'][0]:.0%} "
                  f"(cap {args.max_week:.0%}), paid={'YES' if u['paid'] else 'no'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=400, help="stop at this many usable episodes")
    ap.add_argument("--weak", default="gpt-5.6-sol")
    ap.add_argument("--strong", default="gpt-6-astra", help="salvage teacher ('' to disable)")
    ap.add_argument("--also", nargs="*", default=[], metavar="TEACHER",
                    help="extra teachers run once per problem, e.g. --also claude:opus")
    ap.add_argument("--effort", default=arena.DEFAULT_EFFORT)
    ap.add_argument("--max-seeds", type=int, default=3, help="usable episodes per problem before moving on")
    ap.add_argument("--max-failures", type=int, default=3)
    ap.add_argument("--promote-batch", type=int, default=20)
    ap.add_argument("--teacher-timeout", type=int, default=2400)
    ap.add_argument("--max-5h", type=float, default=0.8, help="pause when a CLI's 5-hour window is this full")
    ap.add_argument("--max-week", type=float, default=0.7,
                    help="pause when a CLI's weekly window is this full (Claude's is shared with interactive use)")
    ap.add_argument("--max-budget-usd", type=float, default=5.0, help="per-episode cap for Claude runs")
    ap.add_argument("--max-episodes", type=int, default=None, help="stop after this many episodes this run")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    backoff = 0
    promote_stalled = False
    ran_this_run = 0
    while True:
        verify.BENCHMARK.clear()
        verify.BENCHMARK.update(verify.load_benchmark())  # promotions land between iterations
        st = state(args)
        pool = 0 if promote_stalled else promotion_pool()
        if args.status or args.dry_run:
            show(st, args, pool)
            if args.dry_run:
                gates = {b: usage_wait(b, args) for b in ("codex", "claude")}
                print(f"usage-blocked: {sorted(b for b, g in gates.items() if g) or 'none'}")
                print(f"next: {next_job(st, args, pool, frozenset(b for b, g in gates.items() if g))}")
            return
        gates = {b: usage_wait(b, args) for b in ("codex", "claude")}
        if any(g and g[0] == "stop" for g in gates.values()):
            log({"event": "done", "reason": "a CLI reports paid credits/overage in use — stopping",
                 "usage": {b: usage(b) for b in gates}, "usable": st["usable_total"]})
            return
        blocked = frozenset(b for b, g in gates.items() if g)
        if st["usable_total"] >= args.target:
            log({"event": "done", "reason": "target reached", "usable": st["usable_total"]})
            return
        job = next_job(st, args, pool, blocked)
        if job is None and blocked and next_job(st, args, pool) is not None:
            wait = min(g[1] for g in gates.values() if g)
            log({"event": "usage_wait", "blocked": sorted(blocked), "seconds": round(wait),
                 "usage": {b: usage(b) for b in blocked}})
            time.sleep(wait)
            continue
        if job is None:
            log({"event": "done", "reason": "nothing left to collect", "usable": st["usable_total"]})
            return
        kind, name, model = job
        if kind == "episode":
            if args.max_episodes is not None and ran_this_run >= args.max_episodes:
                log({"event": "done", "reason": f"--max-episodes {args.max_episodes}", "usable": st["usable_total"]})
                return
            ran_this_run += 1
        if kind == "promote":
            log({"event": "promote", "batch": args.promote_batch, "pool": pool})
            subprocess.run([sys.executable, str(REPO / "mining" / "promote_discovered.py"),
                            "--limit", str(args.promote_batch)], cwd=REPO)
            if promotion_pool() >= pool:  # checked nothing: don't loop on a broken promoter
                promote_stalled = True
                log({"event": "promote_stalled", "pool": pool})
            continue
        if run_episode(name, model, args):
            backoff = 0
            continue
        backoff += 1
        wait = min(15 * 60 * 2 ** (backoff - 1), 3 * 3600)
        log({"event": "backoff", "seconds": wait, "consecutive_failures": backoff})
        time.sleep(wait)


if __name__ == "__main__":
    main()
