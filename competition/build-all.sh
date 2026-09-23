#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECTS="$ROOT/projects"
LOGDIR="$ROOT/build-logs"
mkdir -p "$LOGDIR"

build_one() {
  local proj="$1"
  local dir="$PROJECTS/$proj"
  local log="$LOGDIR/$proj.log"
  {
    echo "==== START $proj $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
    echo "toolchain: $(cat "$dir/lean-toolchain")"
    cd "$dir" || exit 1

    if [[ -f lake-manifest.json && -d .lake/packages ]]; then
      echo "---- manifest + packages present; skipping lake update ----"
    else
      echo "---- lake update ----"
      if ! lake update; then
        echo "FAIL: lake update"
        return 1
      fi
    fi

    if [[ -d .lake/packages/mathlib ]]; then
      echo "---- lake exe cache get ----"
      # cache get can fail on toolchain wording; continue anyway
      lake exe cache get || echo "WARN: cache get failed; building from source"
    fi

    # Build required top-level packages listed in lakefile
    pkgs=()
    while IFS= read -r name; do
      pkgs+=("$name")
    done < <(python3 - <<'PY'
import re, pathlib, sys
text = pathlib.Path("lakefile.toml").read_text()
# collect name = "X" immediately after [[require]]
names = []
blocks = re.split(r'\[\[require\]\]', text)[1:]
for b in blocks:
    m = re.search(r'^\s*name\s*=\s*"([^"]+)"', b, re.M)
    if m:
        names.append(m.group(1))
print("\n".join(names))
PY
)
    echo "---- packages to build: ${pkgs[*]} ----"
    # Prefer Lake package/lib names; Mathlib lib is Mathlib
    targets=()
    for p in "${pkgs[@]}"; do
      case "$p" in
        mathlib) targets+=("Mathlib") ;;
        *) targets+=("$p") ;;
      esac
    done
    echo "---- lake build ${targets[*]} ----"
    if lake build "${targets[@]}"; then
      echo "==== OK $proj $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
      return 0
    else
      echo "==== FAIL $proj $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
      return 1
    fi
  } >"$log" 2>&1
}

# Sequential: toolchains + mathlib caches are heavy
fail=0
ALL=(v4.33 v4.32 v4.31 v4.30 v4.29.1 v4.29 v4.28 v4.27 v4.26 v4.25)
for proj in "${@:-${ALL[@]}}"; do
  echo "Building $proj ..."
  if build_one "$proj"; then
    echo "OK $proj"
  else
    echo "FAIL $proj (see build-logs/$proj.log)"
    fail=1
  fi
done
echo "ALL_DONE fail=$fail"
exit $fail
