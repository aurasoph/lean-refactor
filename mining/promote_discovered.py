#!/usr/bin/env python3
"""Promote mined candidates into the live problem set.

For each unchecked candidate in mining/discovered_problems.jsonl (highest
Ox-alpha confidence first, sources interleaved), compile its ORIGINAL
upstream proof on every built toolchain that has its corpus package. If it
compiles anywhere, append it to competition/benchmark_data_extra.jsonl with
version_info = the toolchains it really compiles on, and append its local
reference measurement (heartbeats from that same compile) to
competition/reference_measurements.jsonl. No model is involved.

Every checked candidate is logged to mining/promotion_log.jsonl, so reruns
resume where they stopped. competition/collect.py calls this in batches.

  python3 mining/promote_discovered.py --dry-run
  python3 mining/promote_discovered.py --limit 20
  python3 mining/promote_discovered.py --source physlib arklib
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
COMPETITION = REPO / "competition"
MINING = Path(__file__).resolve().parent
sys.path.insert(0, str(COMPETITION))
import verify  # noqa: E402

PROJECTS_DIR = COMPETITION / "projects"


def built_toolchains_for_package(source: str) -> dict[str, str]:
    """toolchain version -> pinned commit rev, for every built project dir
    that actually has this corpus's package under .lake/packages."""
    out: dict[str, str] = {}
    for proj in sorted(PROJECTS_DIR.iterdir()):
        if not proj.is_dir():
            continue
        manifest = proj / "lake-manifest.json"
        toolchain_file = proj / "lean-toolchain"
        if not manifest.is_file() or not toolchain_file.is_file():
            continue
        packages = proj / ".lake" / "packages"
        if not packages.is_dir():
            continue
        match = next((p for p in packages.iterdir() if p.is_dir() and p.name.lower() == source.lower()), None)
        if match is None:
            continue
        toolchain = toolchain_file.read_text().strip().split(":")[-1]
        try:
            data = json.loads(manifest.read_text())
        except json.JSONDecodeError:
            continue
        rev = next(
            (p.get("rev") for p in data.get("packages", []) if p.get("name", "").lower() == source.lower()),
            None,
        )
        if rev:
            out[toolchain] = rev
    return out


def check_candidate(row: dict[str, Any], toolchains: dict[str, str], timeout: int) -> dict[str, Any]:
    """Compile the original upstream proof on every built toolchain.

    Returns version_info (only the toolchains it actually compiles on) and a
    reference-measurement row in verify.verify()'s format restricted to those
    toolchains, so one Lean pass both promotes and measures the problem.
    """
    name = row["name"]
    trial = {**row, "version_info": [{v: rev} for v, rev in sorted(toolchains.items())]}
    verify.BENCHMARK[name] = trial  # temporary in-memory registration; run_one() needs it
    try:
        res = verify.verify(name, row["src"], versions=sorted(toolchains), timeout=timeout)
    finally:
        del verify.BENCHMARK[name]
    ok = [p for p in res["per_version"] if p["ok"]]
    version_info = [{p["version"]: toolchains[p["version"]]} for p in ok]
    reference = None
    if ok:
        top = verify.newest_version([p["version"] for p in ok])
        primary = next(p for p in ok if p["version"] == top)
        reference = {
            "name": name, "heartbeats": primary["heartbeats"], "compiled": True,
            "compat": {p["version"]: True for p in ok}, "untested": [],
            "num_tested": len(ok), "per_version": ok, "published_heartbeats": None,
        }
    return {"name": name, "version_info": version_info, "reference": reference,
            "per_version": {p["version"]: p for p in res["per_version"]}}


def register(final: dict[str, Any], reference: dict[str, Any]) -> None:
    """Append a promoted problem to the live benchmark + its local reference."""
    with verify.EXTRA_BENCHMARK.open("a") as fh:
        fh.write(json.dumps(final) + "\n")
    with verify.REFERENCE_FILE.open("a") as fh:
        fh.write(json.dumps(reference) + "\n")


def checked_names() -> set[str]:
    done = set(verify.BENCHMARK)
    if LOG.exists():
        done |= {json.loads(l)["name"] for l in LOG.read_text().splitlines() if l.strip()}
    return done


_LEAD_RE = re.compile(r"^(?:\s*/--.*?-/|\s*@\[[^\]]*\])*\s*(\w+)", re.S)


def has_modifier(src: str) -> bool:
    """`private`/`protected` declarations: the heartbeat wrapper can't parse the
    modifier (every toolchain fails with "expected 'lemma'"), and no official
    warm-up problem uses one — skip them instead of spending a Lean pass each."""
    m = _LEAD_RE.match(src)
    return bool(m) and m.group(1) in ("private", "protected")


def queue(sources: list[str], min_conf: int) -> list[dict[str, Any]]:
    """Unchecked candidates, highest confidence first, sources round-robin."""
    done = checked_names()
    per: dict[str, list[dict]] = {s: [] for s in sources}
    with open(MINING / "discovered_problems.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            conf = (r.get("_discovery") or {}).get("ox_alpha_confidence", 0)
            if (r.get("source") in per and conf >= min_conf and r["name"] not in done
                    and not has_modifier(r["src"])):
                per[r["source"]].append(r)
    for rows in per.values():
        rows.sort(key=lambda r: (r.get("_discovery") or {}).get("ox_alpha_confidence", 0), reverse=True)
    out: list[dict[str, Any]] = []
    while any(per.values()):
        for s in sources:
            if per[s]:
                out.append(per[s].pop(0))
    return out


LOG = MINING / "promotion_log.jsonl"  # every candidate checked, pass or fail — makes runs resumable
SOURCES = ["strata", "cslib", "physlib", "arklib"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", nargs="+", default=SOURCES)
    ap.add_argument("--min-confidence", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None, help="check at most this many candidates this run")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--dry-run", action="store_true", help="show the queue, compile nothing")
    args = ap.parse_args()

    todo = queue(args.source, args.min_confidence)
    toolchains = {s: built_toolchains_for_package(s) for s in args.source}
    todo = [r for r in todo if toolchains.get(r["source"])]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} candidate(s) to check (confidence>={args.min_confidence}); "
          f"built toolchains: { {s: sorted(t) for s, t in toolchains.items()} }", file=sys.stderr)
    if args.dry_run:
        return

    promoted = 0
    for i, row in enumerate(todo, 1):
        name, source = row["name"], row["source"]
        print(f"[{i}/{len(todo)}] {source}/{name}", file=sys.stderr, flush=True)
        result = check_candidate(row, toolchains[source], args.timeout)
        ok = bool(result["version_info"])
        if ok:
            final = {k: v for k, v in row.items() if k != "_discovery"}
            final["version_info"] = result["version_info"]
            register(final, result["reference"])
            promoted += 1
        with LOG.open("a") as fh:
            fh.write(json.dumps({"name": name, "source": source, "promoted": ok,
                                 "versions": [next(iter(v)) for v in result["version_info"]],
                                 "failed": {v: (p["note"] or (p["errors"] or [""])[0])[:200]
                                            for v, p in result["per_version"].items() if not p["ok"]}}) + "\n")
        print(f"  -> {'PROMOTED ' + str([next(iter(v)) for v in result['version_info']]) if ok else 'rejected'}",
              file=sys.stderr, flush=True)
    print(f"\n{promoted}/{len(todo)} promoted into {verify.EXTRA_BENCHMARK.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
