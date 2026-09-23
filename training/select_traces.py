#!/usr/bin/env python3
"""Pick a small, diverse set of genuine wins out of runs/episodes.jsonl and turn
each into a (prompt, completion) SFT pair — the "prompt -> final proof" format
for the training-structure overfit smoke test.

Usage: python3 select_traces.py [--n 10] [--out data/sft_promptfinal.jsonl]

Deliberately not reusing arena.py's harder-to-import bits (contextvars-heavy
module, competition/ cwd assumptions) — this only needs three things from it:
BENCHMARK (for the corpus tag) and decl_start (to slice out the declaration).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPETITION = ROOT / "competition"
RUNS = ROOT / "runs"
EPISODES = RUNS / "episodes.jsonl"

sys.path.insert(0, str(COMPETITION))
import verify  # noqa: E402
import arena  # noqa: E402 — for build_prompt(); safe to import, only touches ROOT-relative paths
import local_score  # noqa: E402 — for remove_comments_po


def best_per_problem() -> dict[str, dict]:
    best: dict[str, dict] = {}
    with EPISODES.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            after = rec.get("after") or {}
            if not after.get("compiled") or (after.get("survival_pct") or 0) < 100:
                continue
            name = rec.get("name")
            score = after.get("objective_sum_pct")
            if score is None:
                continue
            if name not in best or score > best[name]["score"]:
                best[name] = {"score": score, "record": rec}
    return best


def pick_diverse(best: dict[str, dict], n: int) -> list[dict]:
    by_corpus: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for name, entry in best.items():
        corpus = verify.BENCHMARK.get(name, {}).get("source", "?")
        by_corpus[corpus].append((name, entry))
    for lst in by_corpus.values():
        lst.sort(key=lambda kv: kv[1]["score"], reverse=True)

    chosen: list[tuple[str, dict]] = []
    corpora = list(by_corpus)
    round_idx = 0
    while len(chosen) < n and any(by_corpus.values()):
        for corpus in corpora:
            if len(chosen) >= n:
                break
            if round_idx < len(by_corpus[corpus]):
                chosen.append(by_corpus[corpus][round_idx])
        round_idx += 1
        if round_idx > max(len(v) for v in by_corpus.values()):
            break
    return [{"name": name, **entry} for name, entry in chosen[:n]]


def build_example(name: str, record: dict) -> dict | None:
    # Some pre-migration records carry an absolute run_dir from the original
    # dev machine (/Users/evanwang/...) — always rebuild from the basename
    # against our own RUNS rather than trusting the stored path, same fix as
    # harvest_traces.py's find_openrouter_trace().
    run_dir = RUNS / Path(record["run_dir"]).name
    agent_final = run_dir / "agent_final.lean"
    if not agent_final.is_file():
        print(f"  skip {name}: no agent_final.lean in {run_dir}", file=sys.stderr)
        return None
    text = agent_final.read_text()
    start = verify.decl_start(text, verify.BENCHMARK[name])
    if start is None:
        print(f"  skip {name}: could not locate declaration in {agent_final}", file=sys.stderr)
        return None
    # Strip comments the same way the scorer does before measuring length —
    # otherwise leftover scratch/draft text an agent never cleaned up (seen
    # verbatim in interleaved_affine_gaps_imply_tensor_gaps: a ~12KB trailing
    # `/- ... -/` block) would bleed into the training target uncorrected,
    # even though it never counted toward that episode's actual score.
    completion = local_score.remove_comments_po(text[start:]).strip()
    prompt = arena.build_prompt(name)
    return {
        "name": name,
        "corpus": verify.BENCHMARK[name].get("source", "?"),
        "backend": record.get("backend"),
        "objective_sum_pct": record["after"].get("objective_sum_pct"),
        "run_dir": str(run_dir),
        "prompt": prompt,
        "completion": completion,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", default=str(Path(__file__).parent / "data" / "sft_promptfinal.jsonl"))
    args = ap.parse_args()

    best = best_per_problem()
    print(f"{len(best)} problems have a fully-surviving, compiled episode", file=sys.stderr)
    chosen = pick_diverse(best, args.n)

    examples = []
    for entry in chosen:
        ex = build_example(entry["name"], entry["record"])
        if ex is not None:
            examples.append(ex)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for ex in examples:
            fh.write(json.dumps(ex) + "\n")

    print(f"wrote {len(examples)} examples to {out_path}", file=sys.stderr)
    for ex in examples:
        print(f"  {ex['objective_sum_pct']:7.2f}  {ex['corpus']:12s} {ex['name']}", file=sys.stderr)


if __name__ == "__main__":
    main()
