"""Statement-level train/val/test split, shared by collection and SFT build.

`test` is never collected on (competition/collect.py) and never trained on
(training/build_sft.py). A problem is `test` if:

  1. it is an official competition problem: listed in
     competition/benchmark_data_warmup.jsonl (the organizers call it the
     "development subset" of the full benchmark, so assume every warm-up
     problem is in the final set), or in training/official_benchmark.txt
     (the full benchmark's names, to be filled in when it is released on
     Oct 1, 2026; one name per line). Training on these would train on the
     competition's own test set; or
  2. it falls in the hashed TEST_FRACTION of everything else, our own
     held-out mined problems for measuring generalization.

The rest splits deterministically by name hash into val / train, so every
episode of one theorem lands on the same side regardless of when it was
collected. Changing any of this reshuffles splits: bump SPLIT_ID.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

SPLIT_ID = "sha256-name-v2-official-test"
TEST_FRACTION = 0.15
VAL_FRACTION = 0.10

REPO = Path(__file__).resolve().parent.parent
WARMUP = REPO / "competition" / "benchmark_data_warmup.jsonl"
OFFICIAL = REPO / "training" / "official_benchmark.txt"


@lru_cache(maxsize=1)
def official_names() -> frozenset[str]:
    names: set[str] = set()
    if WARMUP.exists():
        names |= {json.loads(l)["name"] for l in WARMUP.read_text().splitlines() if l.strip()}
    if OFFICIAL.exists():
        names |= {l.strip() for l in OFFICIAL.read_text().splitlines() if l.strip() and not l.startswith("#")}
    return frozenset(names)


def split_of(name: str) -> str:
    if name in official_names():
        return "test"
    u = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if u < TEST_FRACTION:
        return "test"
    if u < TEST_FRACTION + VAL_FRACTION:
        return "val"
    return "train"
