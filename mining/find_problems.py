#!/usr/bin/env python3
"""Search Strata/PhysLib/CSLib/ArkLib for new Lean Refactor Arena candidates.

Pipeline:
  1. fetch  - shallow-clone/refresh each corpus (Strata reuses ../arena/Strata).
  2. extract - line-boundary scan for top-level theorem/lemma declarations,
     using local_score.py's Lean-aware body/tokenizer helpers for exact
     proof-body extraction and proof_length token counts.
  3. filter - drop anything already in benchmark_data_warmup.jsonl or
     discovered_problems.jsonl, anything forbidden_hit() flags, and anything
     outside a plausible size window.
  4. judge  - batch survivors to stealth/ox-alpha (free on OpenRouter) to rank
     genuine golfing candidates against the arena's scoring criteria.
  5. write  - keepers appended to discovered_problems.jsonl (NOT the canonical
     benchmark_data_warmup.jsonl) with an Ox-alpha rationale and enough
     metadata (repo, commit, file, line range) to verify/promote later.

Usage:
  python3 mining/find_problems.py                       # all 4 corpora
  python3 mining/find_problems.py --corpora strata,cslib
  python3 mining/find_problems.py --max-judge 200        # cap candidates sent to Ox-alpha
  python3 mining/find_problems.py --dry-run              # extract+filter only, skip Ox-alpha
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "competition"))
from local_score import (  # noqa: E402
    DECL_RE,
    _body_after_defining_assign,
    _find_named_decl_start,
    forbidden_hit,
    tokenize_proof_body,
)

REPO = Path(__file__).resolve().parent.parent
COMPETITION = REPO / "competition"
CACHE = COMPETITION / ".corpus_cache"
OUT_PATH = Path(__file__).resolve().parent / "discovered_problems.jsonl"
BENCHMARK_PATH = COMPETITION / "benchmark_data_warmup.jsonl"
STRATA_LOCAL = REPO / "arena" / "Strata"

CORPORA: dict[str, str] = {
    "strata": "https://github.com/strata-org/Strata",
    "physlib": "https://github.com/leanprover-community/physlib",
    "cslib": "https://github.com/leanprover/cslib",
    "arklib": "https://github.com/Verified-zkEVM/ArkLib",
}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "stealth/ox-alpha"
BATCH_SIZE = 5
MIN_LINES = 10
MAX_LINES = 220
MIN_TOKENS = 60
MAX_TOKENS = 3000

BOUNDARY_RE = re.compile(
    r"^(?:noncomputable\s+|private\s+|protected\s+|partial\s+|unsafe\s+)*"
    r"(theorem|lemma|def|abbrev|instance|structure|inductive|class|example|"
    r"namespace|section|end|open|variable|variables|universe|axiom|macro|"
    r"macro_rules|notation|syntax|attribute|@\[)"
)


@dataclass
class Candidate:
    name: str
    kind: str
    corpus: str
    corpus_url: str
    corpus_commit: str
    file_path: str
    start_line: int
    end_line: int
    statement: str
    src: str
    proof_body: str
    proof_length: int
    num_lines: int


def sh(cmd: list[str], cwd: Optional[Path] = None) -> str:
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def ensure_corpus(name: str, url: str) -> Path:
    if name == "strata" and STRATA_LOCAL.exists():
        print(f"[fetch] strata: reusing local clone at {STRATA_LOCAL}", file=sys.stderr)
        return STRATA_LOCAL
    CACHE.mkdir(exist_ok=True)
    dest = CACHE / name
    if dest.exists():
        print(f"[fetch] {name}: already cloned at {dest}", file=sys.stderr)
        return dest
    print(f"[fetch] {name}: cloning {url} (depth=1)...", file=sys.stderr)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", url, str(dest)],
        check=True, capture_output=True, text=True,
    )
    return dest


NS_RE = re.compile(r"^namespace\s+(\S+)")


def find_declarations(text: str) -> list[dict]:
    """Line-boundary scan: theorem/lemma spans up to the next top-level marker.

    Tracks a namespace/section stack (sections don't contribute to naming,
    only `namespace ... end` does) so declaration names come out fully
    qualified, matching how benchmark_data_warmup.jsonl names things.
    """
    lines = text.split("\n")
    n = len(lines)
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = BOUNDARY_RE.match(line)
        if m:
            boundaries.append((i, m.group(1)))

    ns_stack: list[tuple[str, Optional[str]]] = []
    prefix_at: dict[int, str] = {}
    for i, kw in boundaries:
        prefix_at[i] = ".".join(name for k, name in ns_stack if k == "namespace" and name)
        if kw == "namespace":
            m = NS_RE.match(lines[i])
            ns_stack.append(("namespace", m.group(1) if m else None))
        elif kw == "section":
            ns_stack.append(("section", None))
        elif kw == "end":
            if ns_stack:
                ns_stack.pop()

    decls = []
    for idx, (i, kw) in enumerate(boundaries):
        if kw not in ("theorem", "lemma"):
            continue
        start = i
        j = idx - 1
        while j >= 0 and boundaries[j][0] == start - 1 and boundaries[j][1] == "@[":
            start = boundaries[j][0]
            j -= 1
        end = n
        for bi, _ in boundaries[idx + 1 :]:
            if bi > i:
                end = bi
                break
        while end > start + 1 and lines[end - 1].strip() == "":
            end -= 1
        decl_text = "\n".join(lines[start:end])
        decls.append(
            {
                "start_line": start + 1,
                "end_line": end,
                "text": decl_text,
                "kind": kw,
                "ns_prefix": prefix_at[i],
            }
        )
    return decls


def split_statement_body(decl_text: str, name: str) -> tuple[Optional[str], Optional[str]]:
    start = _find_named_decl_start(decl_text, name)
    if start is None:
        return None, None
    body = _body_after_defining_assign(decl_text, start)
    if body is None:
        return None, None
    assign_idx = len(decl_text) - len(body) - 2
    statement = decl_text[start:assign_idx].rstrip()
    return statement, body


def extract_candidates(
    corpus: str, url: str, repo_path: Path, known_names: set[str]
) -> list[Candidate]:
    commit = sh(["git", "rev-parse", "HEAD"], cwd=repo_path)
    out: list[Candidate] = []
    lean_files = [
        p for p in repo_path.rglob("*.lean")
        if ".lake" not in p.parts and ".git" not in p.parts
    ]
    print(f"[extract] {corpus}: scanning {len(lean_files)} .lean files @ {commit[:10]}", file=sys.stderr)
    for path in lean_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for decl in find_declarations(text):
            m = DECL_RE.search(decl["text"])
            if not m or m.group(1) not in ("theorem", "lemma"):
                continue
            short_name = m.group(2)
            prefix = decl["ns_prefix"]
            name = f"{prefix}.{short_name}" if prefix else short_name
            if name in known_names or short_name in known_names:
                continue
            statement, body = split_statement_body(decl["text"], name)
            if statement is None or body is None:
                continue
            if forbidden_hit(body) is not None:
                continue
            num_lines = len([ln for ln in body.splitlines() if ln.strip()])
            if not (MIN_LINES <= num_lines <= MAX_LINES):
                continue
            try:
                length = len(tokenize_proof_body(body))
            except Exception:
                continue
            if not (MIN_TOKENS <= length <= MAX_TOKENS):
                continue
            known_names.add(name)
            out.append(
                Candidate(
                    name=name,
                    kind=m.group(1),
                    corpus=corpus,
                    corpus_url=url,
                    corpus_commit=commit,
                    file_path=str(path.relative_to(repo_path)),
                    start_line=decl["start_line"],
                    end_line=decl["end_line"],
                    statement=statement,
                    src=decl["text"],
                    proof_body=body,
                    proof_length=length,
                    num_lines=num_lines,
                )
            )
    print(f"[extract] {corpus}: {len(out)} candidates pass local filters", file=sys.stderr)
    return out


JUDGE_PREAMBLE = """You are screening candidate Lean 4 theorems for "Lean Refactor Arena", a \
proof-golfing benchmark. Each accepted problem becomes a target where models must \
rewrite the EXISTING proof of the theorem to be shorter (fewer tokens) and cheaper \
to compile (fewer elaboration heartbeats), while proving the exact same statement \
and, ideally, surviving unchanged across nearby Lean/Mathlib toolchain versions.

Good candidates:
- Look verbose or redundant for the goal: long simp/aesop/grind chains, several \
haves that could collapse, long calc blocks, repeated near-identical tactic \
blocks, non-terminal simp/rw before another tactic finishes the goal.
- Are self-contained: the statement and proof don't obviously depend on private \
helpers not shown here.
- Are meaty enough to have real golf headroom, but not a multi-hundred-line saga \
that is really several sub-lemmas glued together.

Bad candidates:
- Trivial or already near-minimal (e.g. already a 1-3 line term-mode proof).
- Actually definition/instance/decidability boilerplate mislabeled as a theorem.
- Dominated by heavy computation/decide rather than tactic verbosity.

For each candidate below, decide keep=true only if it is a genuinely good \
golfing candidate. Reply with ONLY a JSON array (no prose, no markdown fences), \
one object per candidate in the same order:
[{"name": "...", "keep": true, "confidence": 1-5, "rationale": "one sentence"}, ...]

Candidates:
"""


def build_prompt(batch: list[Candidate]) -> str:
    parts = [JUDGE_PREAMBLE]
    for i, c in enumerate(batch):
        parts.append(
            f"\n--- Candidate {i + 1}: {c.name} "
            f"({c.corpus}, {c.file_path}:{c.start_line}-{c.end_line}, "
            f"{c.num_lines} lines, {c.proof_length} proof tokens) ---\n"
            f"{c.src}\n"
        )
    return "".join(parts)


def call_ox_alpha(prompt: str, api_key: str, max_tokens: int = 4000, retries: int = 3) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "reasoning": {"effort": "low"},
        }
    ).encode()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                OPENROUTER_URL,
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=280) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"].get("content")
            if content:
                return content
            last_err = RuntimeError(f"empty content: {data}")
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            last_err = e
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"ox-alpha call failed after {retries} tries: {last_err}")


def parse_verdicts(text: str) -> list[dict]:
    text = text.strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON array in response: {text[:300]!r}")
    return json.loads(m.group(0))


def judge_batch(batch: list[Candidate], api_key: str) -> list[dict]:
    prompt = build_prompt(batch)
    raw = call_ox_alpha(prompt, api_key)
    try:
        verdicts = parse_verdicts(raw)
    except Exception as e:
        print(f"[judge] batch parse failed ({e}); skipping batch of {len(batch)}", file=sys.stderr)
        return []
    by_name = {v.get("name"): v for v in verdicts if isinstance(v, dict)}
    results = []
    for i, c in enumerate(batch):
        v = by_name.get(c.name) or (verdicts[i] if i < len(verdicts) else None)
        if not isinstance(v, dict):
            continue
        results.append({"candidate": c, "verdict": v})
    return results


def load_known_names() -> set[str]:
    names: set[str] = set()
    for path in (BENCHMARK_PATH, OUT_PATH):
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    names.add(json.loads(line)["name"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return names


def write_candidate(c: Candidate, verdict: dict) -> None:
    row = {
        "name": c.name,
        "source": c.corpus,
        "statement": c.statement,
        "src": c.src,
        "proof_length": c.proof_length,
        "num_lines": c.num_lines,
        "header": "",
        "file_path": c.file_path,
        "url": c.corpus_url,
        "start_line": c.start_line,
        "end_line": c.end_line,
        "version_info": [],
        "_discovery": {
            "status": "candidate",
            "corpus_commit": c.corpus_commit,
            "ox_alpha_confidence": verdict.get("confidence"),
            "ox_alpha_rationale": verdict.get("rationale"),
        },
    }
    with OUT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpora", default=",".join(CORPORA.keys()))
    ap.add_argument("--max-judge", type=int, default=400, help="safety cap on candidates sent to Ox-alpha")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true", help="extract + filter only, skip Ox-alpha")
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not args.dry_run and not api_key:
        sys.exit("OPENROUTER_API_KEY not set")

    corpora = [c.strip() for c in args.corpora.split(",") if c.strip()]
    known_names = load_known_names()
    print(f"[init] {len(known_names)} names already known (benchmark + discovered)", file=sys.stderr)

    all_candidates: list[Candidate] = []
    for name in corpora:
        url = CORPORA[name]
        repo_path = ensure_corpus(name, url)
        all_candidates.extend(extract_candidates(name, url, repo_path, known_names))

    print(f"[filter] {len(all_candidates)} total candidates after local filters", file=sys.stderr)
    if len(all_candidates) > args.max_judge:
        print(
            f"[filter] truncating to --max-judge={args.max_judge} "
            f"({len(all_candidates) - args.max_judge} dropped, not scored)",
            file=sys.stderr,
        )
        all_candidates = all_candidates[: args.max_judge]

    if args.dry_run:
        print(f"[dry-run] would judge {len(all_candidates)} candidates; skipping Ox-alpha", file=sys.stderr)
        for c in all_candidates:
            print(f"  {c.corpus:8s} {c.name} ({c.num_lines}L, {c.proof_length}tok) {c.file_path}:{c.start_line}")
        return

    batches = [all_candidates[i : i + BATCH_SIZE] for i in range(0, len(all_candidates), BATCH_SIZE)]
    print(f"[judge] {len(batches)} batches of up to {BATCH_SIZE}, {args.workers} workers", file=sys.stderr)

    kept = 0
    seen = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(judge_batch, b, api_key): b for b in batches}
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                results = fut.result()
            except Exception as e:
                print(f"[judge] batch failed entirely: {e}", file=sys.stderr)
                continue
            seen += len(batch)
            for r in results:
                c, v = r["candidate"], r["verdict"]
                if v.get("keep"):
                    write_candidate(c, v)
                    kept += 1
                    print(f"[keep] {c.corpus}/{c.name} conf={v.get('confidence')} — {v.get('rationale')}")
            print(f"[progress] judged {seen}/{len(all_candidates)}, kept {kept}", file=sys.stderr)

    print(f"[done] kept {kept}/{len(all_candidates)} candidates -> {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
