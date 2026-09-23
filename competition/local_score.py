#!/usr/bin/env python3
"""Local scorer for Lean Refactor Arena warm-up.

Length tokenizer = ProofOptimizer's syntax-aware lexer
(arXiv:2510.15700 Appendix L), which matches all 15 warm-up `proof_length`
values exactly when applied to the proof body after the statement's `:=`
(comments + blank lines dropped; multi-line comments non-greedy).

Aggregation matches `leaderboard.py`. Heartbeat denominators come from
`benchmark_heartbeats.jsonl` (now filled for all 15 problems). Compile /
`#count_heartbeats` still need a Lean env — pass `compiled` / `heartbeats` /
`compat` when you have them.

What length covers
------------------
Tokens of everything after the statement's defining `:=`. The forbidden-pattern
list is copied verbatim from the Space's `app.py`; no extra house rules are added
here, so a local score is what the arena would report.

Usage
-----
  python3 local_score.py --self-check
  python3 local_score.py path/to/submission.jsonl
  python3 local_score.py --name putnam_1964_a4 --proof-file proof.lean
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from benchmark import (
    BENCHMARK,
    benchmark_names,
    original_heartbeats,
    original_length,
)

ROOT = Path(__file__).resolve().parent

# Upload filter synced from Space `app.py` (Aug 2026 warm-up launch).
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("#eval", re.compile(r"#\s*eval\b")),
    ("#reduce", re.compile(r"#\s*reduce\b")),
    ("IO.", re.compile(r"\bIO\.")),
    ("unsafe def/fun/theorem", re.compile(r"\bunsafe\s+(def|fun|theorem|lemma)\b")),
    ("extern", re.compile(r"\bextern\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("@[implemented_by]", re.compile(r"@\[\s*implemented[_]?[Bb]y\b")),
    ("@[extern]", re.compile(r"@\[\s*extern\b")),
    ("sorry", re.compile(r"\bsorry\b")),
    ("sorryAx", re.compile(r"\bsorryAx\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"\baxiom\b")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    ("ofReduceBool", re.compile(r"\bofReduceBool\b")),
    ("ofReduceNat", re.compile(r"\bofReduceNat\b")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_elab", re.compile(r"\brun_elab\b")),
    ("#exit", re.compile(r"#\s*exit\b")),
    ("#count_heartbeats", re.compile(r"#\s*count_heartbeats\b")),
    ("attribute command", re.compile(r"(?m)^\s*attribute\b")),
    (
        "macro/elab/notation",
        re.compile(r"\b(macro|macro_rules|elab|elab_rules|notation|syntax)\b"),
    ),
    ("deriving instance", re.compile(r"\bderiving\s+instance\b")),
    (
        "auxiliary declaration",
        re.compile(
            r"(?m)^\s*(def|abbrev|instance|structure|inductive|class|opaque)\b"
        ),
    ),
]

SORRY_RE = re.compile(r"\bsorry\b")  # kept for callers; also in FORBIDDEN_PATTERNS
DECL_RE = re.compile(
    r"(?m)^(?:(?:noncomputable|private|protected|partial|unsafe)\s+)*"
    r"(theorem|lemma|example|def|abbrev|structure|inductive|class)\s+"
    r"([^\s(:{]+)"
)

# ── Text / body extraction ───────────────────────────────────────────────────

def strip_lean_comments(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s.startswith("/-", i):
            j = s.find("-/", i + 2)
            if j < 0:
                break
            i = j + 2
            continue
        if s.startswith("--", i):
            j = s.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _body_after_defining_assign(src: str, start: int) -> Optional[str]:
    """From a decl start index, return text after the depth-0 defining `:=`."""
    i = start
    depth_paren = depth_brack = depth_brace = 0
    while i < len(src):
        c = src[i]
        if c == '"':
            i += 1
            while i < len(src) and src[i] != '"':
                if src[i] == "\\":
                    i += 2
                    continue
                i += 1
            i += 1
            continue
        if src.startswith("/-", i):
            j = src.find("-/", i + 2)
            i = (j + 2) if j >= 0 else len(src)
            continue
        if src.startswith("--", i):
            j = src.find("\n", i)
            i = j if j >= 0 else len(src)
            continue
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "[":
            depth_brack += 1
        elif c == "]":
            depth_brack -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif (
            src.startswith(":=", i)
            and depth_paren == 0
            and depth_brack == 0
            and depth_brace == 0
        ):
            return src[i + 2 :]
        i += 1
    return None


def _find_named_decl_start(src: str, name: Optional[str]) -> Optional[int]:
    """Byte offset of the theorem/lemma/… whose name matches `name` (or short id)."""
    if not name:
        return None
    short = name.split(".")[-1]
    for m in re.finditer(
        r"(?m)^(?:(?:noncomputable|private|protected|unsafe)\s+)*"
        r"(?:theorem|lemma|example|def)\s+([^\s(:{]+)",
        src,
    ):
        decl_name = m.group(1)
        if decl_name == name or decl_name == short or decl_name.endswith("." + short):
            return m.start()
    return None


def extract_proof_body(
    src: str,
    statement: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[str]:
    """Return proof body after the declaration's defining `:=`.

    Prefer locating `statement` inside `src` (benchmark field). Else find the
    named decl. Else first top-level theorem/lemma. Depth scan avoids treating
    `(P := ty)` binder defaults as the definition.
    """
    if statement is not None:
        # Exact statement may sit after helper decls / `open` noise.
        idx = src.find(statement)
        if idx >= 0:
            rest = src[idx + len(statement) :]
            m = re.match(r"\s*:=\s*", rest)
            if m:
                return rest[m.end() :]
        if src.startswith(statement):
            rest = src[len(statement) :]
            m = re.match(r"\s*:=\s*", rest)
            if m:
                return rest[m.end() :]

    start = _find_named_decl_start(src, name)
    if start is None:
        starts = [
            m.start()
            for m in re.finditer(
                r"(?m)^\s*(?:(?:noncomputable|private|protected|unsafe)\s+)*"
                r"(?:theorem|lemma|example|def)\s+",
                src,
            )
        ]
        if not starts:
            return None
        start = starts[0]
    return _body_after_defining_assign(src, start)


def _norm_stmt(s: str) -> str:
    s = strip_lean_comments(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*", "\n", s).strip()
    return s


def statements_match(expected: str, proof: str, name: Optional[str] = None) -> bool:
    """True if the named decl's statement matches the benchmark `statement`."""
    if expected in proof:
        rest = proof.split(expected, 1)[1]
        if re.match(r"\s*:=", rest):
            return True

    exp_n = _norm_stmt(expected)

    def stmt_at(start: int) -> Optional[str]:
        body = _body_after_defining_assign(proof, start)
        if body is None:
            return None
        cut = proof.find(body, start)
        if cut < 0:
            return None
        head = re.sub(r"\s*:=\s*$", "", proof[start:cut])
        prefix = proof[:start]
        open_m = re.search(r"(?s)((?:(?:open|set_option)[^\n]*\n)+)\s*$", prefix)
        if open_m:
            return (open_m.group(1) + head).strip()
        return head.strip()

    start = _find_named_decl_start(proof, name)
    if start is not None:
        candidates = [start]
    else:
        candidates = [
            m.start()
            for m in re.finditer(
                r"(?m)^(?:(?:noncomputable|private|protected|unsafe)\s+)*"
                r"(?:theorem|lemma|example|def)\s+",
                proof,
            )
        ]

    for st in candidates:
        got = stmt_at(st)
        if got is not None and _norm_stmt(got) == exp_n:
            return True
    return False


def count_toplevel_decls(src: str) -> list[tuple[str, str]]:
    """Top-level theorem/lemma/def/… names (line-start heuristic)."""
    return [(k, n) for k, n in DECL_RE.findall(strip_lean_comments(src))]


def forbidden_hit(code: str) -> Optional[str]:
    for label, pat in FORBIDDEN_PATTERNS:
        if pat.search(code):
            return label
    return None


# ── Tokenizer (ProofOptimizer Appendix L; exact on warm-up refs) ───────────────

# From arXiv:2510.15700 Appendix L (same lexer cited by Lean Refactor paper).
_LEAN_OPERATORS = [
    ":=",
    "!=",
    "&&",
    "-.",
    "->",
    "<-",
    "..",
    "...",
    "::",
    ":>",
    "<;>",
    ";;",
    "==",
    "||",
    "=>",
    "<=",
    ">=",
    "⁻¹",
    "?_",
]
_LEAN_OPERATORS_SPACED = [" ".join(conn) for conn in _LEAN_OPERATORS]
_LEAN_OPERATORS_DICT = dict(zip(_LEAN_OPERATORS_SPACED, _LEAN_OPERATORS))


def remove_comments_po(lean_snippet: str) -> str:
    """ProofOptimizer comment strip (non-greedy `/- … -/`; drop `--` tails)."""
    lean_snippet = re.sub(r" */-.*?-/", "", lean_snippet, flags=re.DOTALL)
    lean_snippet = re.sub(r" *--.*", "", lean_snippet)
    return lean_snippet


def lexer_po(lean_snippet: str) -> str:
    """ProofOptimizer syntax-aware lexer → space-separated token lines."""
    tokenized_lines: list[str] = []
    for line in lean_snippet.splitlines():
        tokens: list[str] = []
        token = ""
        for ch in line:
            if ch == " ":
                if token:
                    tokens.append(token)
                    token = ""
            elif str.isalnum(ch) or (ch in "_.'"):
                token += ch
            else:
                if token:
                    tokens.append(token)
                    token = ""
                tokens.append(ch)
        if token:
            tokens.append(token)
        tokenized_line = " ".join(tokens)
        for conn in _LEAN_OPERATORS_SPACED:
            if conn in tokenized_line:
                tokenized_line = tokenized_line.replace(conn, _LEAN_OPERATORS_DICT[conn])
        tokenized_lines.append(tokenized_line)
    return "\n".join(tokenized_lines)


def tokenize_proof_body(body: str) -> list[str]:
    """Token list for a proof body (after `:=`), matching warm-up `proof_length`."""
    proof = remove_comments_po(body)
    proof_tokenized = lexer_po(proof)
    tokens: list[str] = []
    for line in proof_tokenized.splitlines():
        if not line.strip():
            continue
        tokens.extend(p for p in line.split(" ") if p)
    return tokens


def proof_length(
    src: str,
    statement: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[int]:
    body = extract_proof_body(src, statement, name=name)
    if body is None:
        return None
    return len(tokenize_proof_body(body))


# ── Per-theorem / aggregate scoring ───────────────────────────────────────────

@dataclass
class TheoremScore:
    name: str
    compiled: Optional[bool] = None  # None = not submitted; local length-only may set True
    length: Optional[int] = None
    heartbeats: Optional[int] = None
    length_reduction_pct: float = 0.0
    heartbeat_reduction_pct: float = 0.0
    error: str = ""
    compat: Optional[dict[str, Any]] = None


def score_theorem_row(
    name: str,
    proof: str,
    *,
    compiled: Optional[bool] = True,
    heartbeats: Optional[int] = None,
    compat: Optional[dict[str, Any]] = None,
) -> TheoremScore:
    """Score one submission row. Does not run Lean unless caller set compiled."""
    entry = BENCHMARK.get(name)
    if entry is None:
        return TheoremScore(name=name, compiled=False, error="unknown theorem name")

    bad = forbidden_hit(proof)
    if bad:
        return TheoremScore(name=name, compiled=False, error=f"forbidden: {bad}")

    expected_stmt = entry["statement"]
    if not statements_match(expected_stmt, proof, name=name):
        return TheoremScore(name=name, compiled=False, error="statement mismatch")

    new_len = proof_length(proof, expected_stmt, name=name)
    if new_len is None:
        return TheoremScore(name=name, compiled=False, error="could not extract proof body")

    # Length-only local mode: treat as compiled unless caller says otherwise.
    if compiled is not None and not compiled:
        return TheoremScore(
            name=name,
            compiled=False,
            length=new_len,
            heartbeats=heartbeats,
            error="compile failed",
        )

    orig_len = original_length(name) or 0
    orig_hb = original_heartbeats(name) or 0
    len_pct = ((orig_len - new_len) / orig_len * 100.0) if orig_len > 0 else 0.0
    hb_pct = (
        ((orig_hb - heartbeats) / orig_hb * 100.0)
        if (orig_hb > 0 and heartbeats is not None)
        else 0.0
    )

    return TheoremScore(
        name=name,
        compiled=True,
        length=new_len,
        heartbeats=heartbeats,
        length_reduction_pct=round(len_pct, 2),
        heartbeat_reduction_pct=round(hb_pct, 2),
        compat=compat,
    )


def aggregate(per: dict[str, TheoremScore]) -> dict[str, Any]:
    """Same formulas as `leaderboard.Leaderboard.submit` / `_compute_user_summary`."""
    names = benchmark_names()
    n = len(names)
    total_len_pct = total_hb_pct = 0.0
    compiled = 0
    compat_checks = compat_passed = 0
    results: dict[str, Any] = {}

    for name in names:
        s = per.get(name)
        orig_len = original_length(name) or 0
        orig_hb = original_heartbeats(name) or 0
        if s is None:
            results[name] = {
                "compiled": None,
                "length": None,
                "heartbeats": None,
                "length_reduction_pct": 0.0,
                "heartbeat_reduction_pct": 0.0,
                "error": "(not in submission)",
            }
            continue
        if not s.compiled:
            results[name] = {
                "compiled": False,
                "length": s.length,
                "heartbeats": s.heartbeats,
                "length_reduction_pct": 0.0,
                "heartbeat_reduction_pct": 0.0,
                "error": s.error,
            }
            continue

        new_len = int(s.length or 0)
        new_hb = s.heartbeats
        len_pct = ((orig_len - new_len) / orig_len * 100.0) if orig_len > 0 else 0.0
        hb_pct = (
            ((orig_hb - new_hb) / orig_hb * 100.0)
            if (orig_hb > 0 and new_hb is not None)
            else 0.0
        )
        total_len_pct += len_pct
        total_hb_pct += hb_pct
        compiled += 1
        for v_res in (s.compat or {}).values():
            compat_checks += 1
            if (v_res or {}).get("passed"):
                compat_passed += 1
        results[name] = {
            "compiled": True,
            "length": new_len,
            "heartbeats": new_hb,
            "length_reduction_pct": round(len_pct, 2),
            "heartbeat_reduction_pct": round(hb_pct, 2),
            "error": "",
            **({"compat": s.compat} if s.compat else {}),
        }

    survival = (
        round(compat_passed / compat_checks * 100.0, 1) if compat_checks > 0 else 0.0
    )
    avg_len = total_len_pct / n if n else 0.0
    avg_hb = total_hb_pct / n if n else 0.0
    combined = (avg_len + avg_hb + survival) / 3.0
    return {
        "results": results,
        "avg_length_reduction_pct": round(avg_len, 2),
        "avg_heartbeat_reduction_pct": round(avg_hb, 2),
        "avg_survival_rate": survival,
        "avg_combined_pct": round(combined, 2),
        "num_compiled": compiled,
        "num_benchmark": n,
    }


def score_submission(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, TheoremScore], dict[str, Any]]:
    per: dict[str, TheoremScore] = {}
    for row in rows:
        name = row["name"]
        proof = row["proof"]
        per[name] = score_theorem_row(
            name,
            proof,
            compiled=row.get("compiled", True),
            heartbeats=row.get("heartbeats"),
            compat=row.get("compat"),
        )
    record = aggregate(per)
    return per, record


def self_check() -> dict[str, Any]:
    """Score each warm-up reference `src` as if submitted; report length MAE."""
    rows = [{"name": n, "proof": BENCHMARK[n]["src"]} for n in benchmark_names()]
    per, record = score_submission(rows)
    abs_errs = []
    for name, s in per.items():
        ref = original_length(name) or 0
        got = s.length or 0
        abs_errs.append(abs(got - ref))
        if s.error:
            print(f"  FAIL {name}: {s.error}", file=sys.stderr)
        elif abs(got - ref) > 0:
            print(f"  {name}: local={got} ref={ref} Δ={got - ref:+d} red%={s.length_reduction_pct}")
    mae = sum(abs_errs) / max(len(abs_errs), 1)
    return {
        "mae_tokens": mae,
        "avg_length_reduction_pct": record.get("avg_length_reduction_pct"),
        "avg_combined_pct": record.get("avg_combined_pct"),
        "num_ok": sum(1 for s in per.values() if s.compiled and not s.error),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("submission", nargs="?", help="JSONL with name/proof rows")
    ap.add_argument("--self-check", action="store_true", help="score warm-up references")
    ap.add_argument("--name", help="single theorem id")
    ap.add_argument("--proof-file", type=Path, help="Lean file containing the declaration")
    ap.add_argument("--json", action="store_true", help="print full JSON")
    args = ap.parse_args()

    if args.self_check:
        summary = self_check()
        print(json.dumps(summary, indent=2))
        return

    if args.name and args.proof_file:
        proof = args.proof_file.read_text()
        s = score_theorem_row(args.name, proof)
        print(json.dumps(asdict(s), indent=2))
        return

    if not args.submission:
        ap.print_help()
        sys.exit(2)

    rows = [json.loads(line) for line in Path(args.submission).read_text().splitlines() if line.strip()]
    per, record = score_submission(rows)
    if args.json:
        print(json.dumps({"per_theorem": {k: asdict(v) for k, v in per.items()}, "summary": record}, indent=2))
    else:
        for name, s in per.items():
            if s.error:
                print(f"{name}: ERROR {s.error}")
            else:
                print(
                    f"{name}: len={s.length}  len%={s.length_reduction_pct:+.2f}  "
                    f"hb%={s.heartbeat_reduction_pct:+.2f}"
                )
        print(
            f"\navg_len%={record['avg_length_reduction_pct']}  "
            f"avg_hb%={record['avg_heartbeat_reduction_pct']}  "
            f"survival%={record['avg_survival_rate']}  "
            f"combined%={record['avg_combined_pct']}  "
            f"compiled={record['num_compiled']}/{record['num_benchmark']}"
        )


if __name__ == "__main__":
    main()
