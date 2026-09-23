#!/usr/bin/env python3
"""Run one teacher on every official problem and build a Space submission.

  nohup python3 competition/leaderboard_run.py --model gpt-5.6-terra --batch terra-1 \
      > runs/leaderboard-terra-1.out 2>&1 &
  python3 competition/leaderboard_run.py --batch terra-1 --build-only    # rebuild the JSONL

Episodes run strictly one at a time (`arena.py run --toolset student`) and
are tagged with --batch, so a restarted run skips problems already done in
that batch. The submission is written to submissions/<batch>.jsonl, one
{"name", "proof"} row per official problem. "proof" is the full declaration
(statement + proof), which is what the Space's own self-check submits. Each
row is the episode's final candidate after checkpoint recovery, so a worse
last edit has already been rolled back. A problem whose episode failed or
never ran gets its original reference proof: it scores 0 reduction but keeps
100% survival, instead of a missing row.

These are official (test-split) problems: the episodes are never used as
SFT data (training/splits.py).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import arena  # noqa: E402
import verify  # noqa: E402

SUBMISSIONS = ROOT.parent / "submissions"
BATCHES = arena.RUNS / "leaderboard_batches.jsonl"


def official() -> list[str]:
    rows = (ROOT / "benchmark_data_warmup.jsonl").read_text().splitlines()
    return [json.loads(l)["name"] for l in rows if l.strip()]


def batch_episodes(batch: str) -> dict[str, dict]:
    """problem -> episode record, for episodes tagged with this batch."""
    stamps = {}
    if BATCHES.exists():
        for line in BATCHES.read_text().splitlines():
            ev = json.loads(line)
            if ev["batch"] == batch:
                stamps[ev["timestamp"]] = ev["name"]
    out = {}
    for line in arena.EPISODES.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("timestamp") in stamps:
            out[rec["name"]] = rec
    return out


def run(name: str, args: argparse.Namespace) -> None:
    before = {json.loads(l)["timestamp"] for l in arena.EPISODES.read_text().splitlines() if l.strip()}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "arena.py"), "run", "--name", name, "--backend", "codex",
         "--toolset", "student", "--model", args.model, "--effort", args.effort,
         "--teacher-timeout", str(args.teacher_timeout)],
        cwd=ROOT, capture_output=True, text=True,
    )
    new = [json.loads(l) for l in arena.EPISODES.read_text().splitlines() if l.strip()]
    new = [r for r in new if r["timestamp"] not in before and r["name"] == name]
    if new:
        with BATCHES.open("a") as fh:
            fh.write(json.dumps({"batch": args.batch, "name": name, "timestamp": new[-1]["timestamp"]}) + "\n")
    after = (new[-1].get("after") if new else None) or {}
    print(f"    exit={proc.returncode} Σ={after.get('objective_sum_pct')} survival={after.get('survival_pct')}",
          flush=True)
    if not new:
        print((proc.stdout + proc.stderr)[-1500:], flush=True)


def build(batch: str) -> Path:
    eps = batch_episodes(batch)
    SUBMISSIONS.mkdir(exist_ok=True)
    out = SUBMISSIONS / f"{batch}.jsonl"
    total = 0.0
    print(f"\n{'problem':58s} {'Σ':>7s} {'surv':>5s} {'combined':>8s}  source")
    with out.open("w") as fh:
        for name in official():
            rec = eps.get(name)
            after = (rec or {}).get("after") or {}
            ok = bool(rec and rec.get("candidate") and after.get("survival_pct") == 100)
            proof = rec["candidate"] if ok else verify.BENCHMARK[name]["src"]
            fh.write(json.dumps({"name": name, "proof": proof}, ensure_ascii=False) + "\n")
            obj = (after.get("objective_sum_pct") or 0.0) if ok else 0.0
            combined = (obj + 100.0) / 3  # (length% + heartbeat% + survival%) / 3, survival 100
            total += combined
            print(f"{name[:58]:58s} {obj:7.2f} {100:5d} {combined:8.2f}  "
                  f"{'episode ' + rec['timestamp'] if ok else 'REFERENCE (no usable episode)'}")
    print(f"\nmean combined (local estimate of the leaderboard score): {total / len(official()):.2f}")
    print(f"wrote {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", required=True, help="name for this run, e.g. terra-1")
    ap.add_argument("--model", default="gpt-5.6-terra")
    ap.add_argument("--effort", default=arena.DEFAULT_EFFORT)
    ap.add_argument("--teacher-timeout", type=int, default=2400)
    ap.add_argument("--build-only", action="store_true")
    args = ap.parse_args()

    if not args.build_only:
        done = batch_episodes(args.batch)
        todo = [n for n in official() if n not in done]
        print(f"batch {args.batch}: {len(todo)} of {len(official())} problems to run with {args.model}", flush=True)
        for i, name in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {name}", flush=True)
            run(name, args)
    build(args.batch)


if __name__ == "__main__":
    main()
