#!/usr/bin/env python3
"""Compile a candidate proof and measure its heartbeats in a real Lean project.

PutnamBench problems are self-contained (`header` has the imports). Project
problems are compiled *inside* their repository: we rebuild the prefix of the
upstream source file up to the target declaration, so `variable`s, `open`s and
imports are exactly what the original proof saw, then splice in the candidate.

Heartbeats use the same formula as Mathlib's `#count_heartbeats in`
(`IO.getNumHeartbeats` delta / 1000) via a local marker command, so we
don't need Mathlib in projects that lack it (e.g. Strata on v4.29.1).

  python3 verify.py --name putnam_1964_a4 --reference
  python3 verify.py --name putnam_1964_a4 --proof-file cand.lean --all-versions
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"

# Lean toolchain string in `version_info` → project directory.
VERSION_DIR: dict[str, str] = {
    "v4.33.0-rc2": "v4.33",
    "v4.32.0": "v4.32",
    "v4.31.0": "v4.31",
    "v4.30.0": "v4.30",
    "v4.29.1": "v4.29.1",
    "v4.29.0": "v4.29",
    "v4.28.0": "v4.28",
    "v4.27.0": "v4.27",
    "v4.26.0": "v4.26",
    "v4.25.0": "v4.25",
}

# Counting command: mirrors Mathlib.Util.CountHeartbeats (delta / 1000).
# No `#` prefix: in scopes where Mathlib's `#s` (Finset.card) notation is open,
# `#foo` parses as a term and the command is never seen.
HB_MARKER = "arena_measure_heartbeats"


# hb_preamble's custom elaborator needs Lean's own Command-elaboration APIs
# (elabCommand, logInfo, etc.) — normally available transitively through
# whatever a substantial file already imports, but not guaranteed for a
# narrow-import target. Confirmed live: a Strata utility file importing only
# a single low-level module failed with "unknown identifier `elabCommand`"
# purely from this gap — same measurement code, different target file.
HB_IMPORT = "import Lean.Elab.Command\n"
_MODULE_LINE_RE = re.compile(r"^module\s*$", re.MULTILINE)


def _insert_hb_import(text: str) -> str:
    """Place HB_IMPORT as early as legal. Usually that's the very top, but
    Lean's module system requires a literal `module` line (only preceded by
    comments) to be the file's first real token — blindly prepending broke
    every physlib problem this way (confirmed live: "invalid 'import'
    command, it must be used in the beginning of the file"). If `module` is
    present, the import has to go right after it instead."""
    m = _MODULE_LINE_RE.search(text)
    if m:
        return text[: m.end()] + "\n" + HB_IMPORT + text[m.end():]
    return HB_IMPORT + text


def hb_preamble(unlimit: bool = True) -> str:
    inner = "set_option Elab.async false in "
    if unlimit:
        inner += "set_option maxHeartbeats 0 in "
    return f"""
open Lean Elab Command in
elab "{HB_MARKER} " cmd:command : command => do
  let t0 ← IO.getNumHeartbeats
  try
    elabCommand (← `(command| {inner}$cmd))
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_HEARTBEATS {{(t1 - t0) / 1000}}"
"""

HB_RE = re.compile(r"ARENA_HEARTBEATS\s+(\d+)")
DIAG_RE = re.compile(
    r"(?m)^.*?:(?P<line>\d+):\d+: (?P<kind>error|warning)(?:\([^)]*\))?: (?P<msg>.*)$"
)


EXTRA_BENCHMARK = ROOT / "benchmark_data_extra.jsonl"  # our promoted problems (see benchmark.py)


def load_benchmark() -> dict[str, dict[str, Any]]:
    rows = []
    for path in (ROOT / "benchmark_data_warmup.jsonl", EXTRA_BENCHMARK):
        if path.exists():
            rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["name"]: r for r in rows}


BENCHMARK = load_benchmark()


def versions_for(name: str) -> list[str]:
    out: list[str] = []
    for entry in BENCHMARK[name].get("version_info") or []:
        out.extend(entry.keys())
    return out


def version_key(version: str) -> tuple[int, int, int, int]:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?", version)
    if not m:
        return (0, 0, 0, 0)
    major, minor, patch, rc = m.groups()
    # A release outranks its own release candidates.
    return (int(major), int(minor), int(patch), int(rc) if rc else 999)


def newest_version(versions: list[str]) -> Optional[str]:
    return max(versions, key=version_key) if versions else None


def project_dir(version: str) -> Optional[Path]:
    sub = VERSION_DIR.get(version)
    if sub is None:
        return None
    d = PROJECTS / sub
    return d if d.is_dir() else None


def env_ready(version: str) -> bool:
    """Coarse, live filesystem check: has *anything* been compiled here?

    Not a per-corpus check (that would need to know which package a given
    problem's source lives under) — just enough to catch "never built at
    all", which is the failure mode that mattered: `arena.py list`'s old
    readiness column read a measurement file from before this machine was
    rebuilt from the handoff zip, and kept reporting projects as ready that
    had zero packages built.
    """
    proj = project_dir(version)
    if proj is None:
        return False
    packages = proj / ".lake" / "packages"
    if not packages.is_dir():
        return False
    return next(packages.glob("*/.lake/build/lib/lean/**/*.olean"), None) is not None


def sweep_stray_temp_files(max_age_seconds: int = 3600) -> list[Path]:
    """`run_one`'s `arena_*.lean` scratch file is unlinked in a `finally`, which
    doesn't run if the parent process is killed by an external signal (e.g. an
    outer `timeout` wrapper reaping the parent without reaching its orphaned
    `lake env lean` child) — this cleans up anything left behind. Age-gated so
    it never touches a file a genuinely still-running check is using; only
    call this opportunistically (e.g. from `prepare`/`list`), not mid-check."""
    removed = []
    now = time.time()
    if not PROJECTS.is_dir():
        return removed
    for f in PROJECTS.glob("*/arena_*.lean"):
        try:
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink()
                removed.append(f)
        except OSError:
            pass
    return removed


def find_source_file(proj: Path, rel_path: str) -> Optional[Path]:
    """Locate `rel_path` inside one of the project's Lake packages."""
    pkgs = proj / ".lake" / "packages"
    if not pkgs.is_dir():
        return None
    for pkg in sorted(pkgs.iterdir()):
        cand = pkg / rel_path
        if cand.is_file():
            return cand
    return None


def decl_start(text: str, row: dict[str, Any]) -> Optional[int]:
    """Offset in `text` where the target declaration begins.

    The full statement is matched, not its first line: statements can open with
    a shared modifier (`open Foo in`) that recurs dozens of times in a file, and
    `start_line` from the benchmark does not line up with the checked-out file.
    It is still used to disambiguate if a statement somehow appears twice.
    """
    stmt = row["statement"].strip()
    start_line = row.get("start_line")

    def pick(offsets: list[int]) -> Optional[int]:
        if not offsets:
            return None
        if isinstance(start_line, int) and start_line > 0 and len(offsets) > 1:
            return min(offsets, key=lambda i: abs(text.count("\n", 0, i) + 1 - start_line))
        return offsets[0]

    idx = pick([m.start() for m in re.finditer(re.escape(stmt), text)])
    if idx is None:
        first = stmt.splitlines()[0].strip()
        idx = pick([m.start() for m in re.finditer(re.escape(first), text)])
    if idx is None:
        return None
    return text.rfind("\n", 0, idx) + 1


def build_standalone_file(name: str, proof: str, *, unlimit: bool = True) -> str:
    """Self-contained problems (PutnamBench) carry their imports in `header`."""
    row = BENCHMARK[name]
    return _insert_hb_import(f"{row.get('header', '')}\n{hb_preamble(unlimit)}\n{HB_MARKER}\n{proof}\n")


MODIFIER_LINE_RE = re.compile(
    r"^\s*(?:@\[.*\]|(?:private|protected|nonrec|noncomputable|scoped)"
    r"|(?:open|set_option|attribute|variable)\b.*\bin)\s*$"
)


def trim_decl_modifiers(prefix: str) -> str:
    """Drop doc comments / attributes that attach to the target declaration.

    Left in place they dangle (`/-- … -/` followed by our injected commands is a
    parse error), and they are not part of the submitted statement anyway.
    """
    while True:
        stripped = prefix.rstrip()
        if stripped.endswith("-/"):
            open_at = stripped.rfind("/--")
            if open_at >= 0 and stripped.find("-/", open_at) == len(stripped) - 2:
                prefix = prefix[:open_at]
                continue
        lines = stripped.splitlines()
        if lines and MODIFIER_LINE_RE.match(lines[-1]):
            prefix = "\n".join(lines[:-1]) + "\n"
            continue
        return prefix


def build_project_file(
    src_file: Path, row: dict[str, Any], proof: str, *, unlimit: bool = True
) -> Optional[str]:
    text = src_file.read_text()
    start = decl_start(text, row)
    if start is None:
        return None
    prefix = trim_decl_modifiers(text[:start])
    # Prefix keeps imports / open / variable / section context; tail is dropped
    # so we only elaborate what the target declaration needs.
    return _insert_hb_import(f"{prefix}\n{hb_preamble(unlimit)}\n{HB_MARKER}\n{proof}\n")


@dataclass
class VersionResult:
    version: str
    ok: bool = False
    heartbeats: Optional[int] = None
    errors: list[str] = field(default_factory=list)
    note: str = ""
    # False only for "no local project" / "source file not found" — an
    # environment we never built, not a real compile failure. Distinguishing
    # this matters: treating "untested" the same as "failed" is exactly what
    # made several genuine wins report as Σ=0 (see arena.py's fully_surviving).
    tested: bool = True


def run_one(
    name: str, proof: str, version: str, *, timeout: int = 1800, unlimit: bool = True
) -> VersionResult:
    row = BENCHMARK[name]
    proj = project_dir(version)
    if proj is None:
        return VersionResult(version=version, note="no local project for this toolchain", tested=False)

    rel = row.get("file_path")
    if rel:
        src_file = find_source_file(proj, rel)
        if src_file is None:
            return VersionResult(version=version, note=f"source file not found: {rel}", tested=False)
        text = build_project_file(src_file, row, proof, unlimit=unlimit)
        if text is None:
            return VersionResult(version=version, note="could not locate declaration in source")
        work_dir = src_file.parent
    else:
        text = build_standalone_file(name, proof, unlimit=unlimit)
        work_dir = proj

    with tempfile.NamedTemporaryFile(
        "w", suffix=".lean", prefix="arena_", dir=work_dir, delete=False
    ) as fh:
        fh.write(text or "")
        tmp = Path(fh.name)
    try:
        # start_new_session=True makes this process its own group leader —
        # required for the timeout path below. `lake env lean` forks `lean`
        # as a child rather than exec'ing into it, so subprocess.run's normal
        # timeout handling (which only kills the direct child) leaves `lean`
        # orphaned and still running. Confirmed live on 2026-09-06: three
        # `lake env lean` processes stuck 8-19 minutes past their own
        # 60s --timeout, load average climbing to 9+ before being caught —
        # this was arena.py's own internal timeout, not an outer shell
        # wrapper (that was a separate, earlier incident).
        proc = subprocess.Popen(
            ["lake", "env", "lean", str(tmp)],
            cwd=proj,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass  # exited on its own between the timeout firing and here
            proc.communicate()  # reap, avoid a zombie
            return VersionResult(version=version, note=f"timeout after {timeout}s")
    finally:
        tmp.unlink(missing_ok=True)

    # Upstream files carry their own `sorry`s and lints; only diagnostics at or
    # after the spliced declaration are ours.
    decl_line = (text or "").count("\n", 0, (text or "").find(HB_MARKER)) + 1
    out = stdout + stderr
    errors = [
        m.group("msg")
        for m in DIAG_RE.finditer(out)
        if int(m.group("line")) >= decl_line
        and (m.group("kind") == "error" or "sorry" in m.group("msg"))
    ]
    hb = HB_RE.search(out)
    # Success is judged on our declaration, not on the process exit code: some
    # upstream files fail to compile cleanly on their own (pre-existing lints).
    return VersionResult(
        version=version,
        ok=(hb is not None and not errors),
        heartbeats=int(hb.group(1)) if hb else None,
        errors=errors[:5],
    )


def verify(
    name: str,
    proof: str,
    *,
    versions: Optional[list[str]] = None,
    timeout: int = 1800,
    unlimit: bool = True,
) -> dict[str, Any]:
    vs = versions if versions is not None else versions_for(name)
    results = [run_one(name, proof, v, timeout=timeout, unlimit=unlimit) for v in vs]
    tested = [r for r in results if r.tested]
    # Reference heartbeats were measured on the newest toolchain (calibrated:
    # putnam_1964_a4 gives 111474 on v4.27.0 vs 111476 published).
    top = newest_version([r.version for r in results])
    primary = next((r for r in results if r.version == top), None)
    return {
        "name": name,
        "heartbeats": primary.heartbeats if primary else None,
        "compiled": bool(primary and primary.ok),
        "compat": {r.version: r.ok for r in results},
        "untested": [r.version for r in results if not r.tested],
        "num_tested": len(tested),
        "per_version": [asdict(r) for r in results],
    }


REFERENCE_FILE = ROOT / "reference_measurements.jsonl"


def read_references(path: Path = REFERENCE_FILE) -> dict[str, dict[str, Any]]:
    """Tolerant read: skip damaged lines instead of failing the whole file."""
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("name"):
            out[row["name"]] = row
    return out


def measure_references(
    out: Path = REFERENCE_FILE,
    *,
    timeout: int = 1800,
    only: Optional[list[str]] = None,
    missing_only: bool = False,
) -> None:
    """Measure every reference proof on every toolchain we have locally.

    Gives (a) heartbeat denominators produced by *our* method, which cancels the
    small systematic offset against the published numbers, and (b) the survival
    baseline, i.e. which environments actually work here.
    """
    published = {
        json.loads(line)["name"]: json.loads(line)["heartbeat"]
        for line in (ROOT / "benchmark_heartbeats.jsonl").read_text().splitlines()
        if line.strip()
    }
    have = read_references(out)
    todo = list(only) if only else list(BENCHMARK)
    if missing_only:
        todo = [n for n in todo if not (have.get(n) or {}).get("heartbeats")]

    for name in todo:
        res = verify(name, BENCHMARK[name]["src"], timeout=timeout)
        res["published_heartbeats"] = published.get(name)
        have[name] = res
        # Rewrite whole file atomically each time: a killed run then leaves a
        # readable file instead of a half-written line.
        tmp = out.with_suffix(".tmp")
        with tmp.open("w") as fh:
            for key in BENCHMARK:
                if key in have:
                    fh.write(json.dumps(have[key]) + "\n")
        tmp.replace(out)
        hb, pub = res["heartbeats"], res["published_heartbeats"]
        delta = f"{(hb - pub) / pub * 100:+.1f}%" if (hb and pub) else "n/a"
        print(f"{name}: hb={hb} published={pub} ({delta}) compat={res['compat']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure-references", action="store_true",
                    help=f"measure reference proofs → {REFERENCE_FILE.name}")
    ap.add_argument("--only", action="append", help="restrict --measure-references to these names")
    ap.add_argument("--missing-only", action="store_true",
                    help="skip references already measured")
    ap.add_argument("--name")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--proof-file", type=Path, help="file containing `statement := proof`")
    g.add_argument("--reference", action="store_true", help="verify the benchmark proof itself")
    ap.add_argument("--version", action="append", help="limit to these toolchains (repeatable)")
    ap.add_argument("--all-versions", action="store_true", help="every toolchain in version_info")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument(
        "--keep-max-heartbeats",
        action="store_true",
        help="measure under the file's own maxHeartbeats instead of unlimited",
    )
    args = ap.parse_args()

    if args.measure_references:
        measure_references(timeout=args.timeout, only=args.only, missing_only=args.missing_only)
        return

    if not args.name or not (args.proof_file or args.reference):
        ap.error("--name plus one of --proof-file/--reference (or --measure-references)")
    if args.name not in BENCHMARK:
        sys.exit(f"unknown problem: {args.name}")
    proof = BENCHMARK[args.name]["src"] if args.reference else args.proof_file.read_text()

    if args.version:
        versions = args.version
    elif args.all_versions:
        versions = versions_for(args.name)
    else:
        top = newest_version(versions_for(args.name))
        versions = [top] if top else []

    result = verify(
        args.name,
        proof,
        versions=versions,
        timeout=args.timeout,
        unlimit=not args.keep_max_heartbeats,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
