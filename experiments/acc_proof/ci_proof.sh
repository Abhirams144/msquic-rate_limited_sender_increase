#!/bin/bash
# Independent proof of the MsQuic CUBIC AimdAccumulator underflow, run on an
# untouched checkout of upstream MsQuic. Used by .github/workflows/aimd-proof.yml
# so the evidence is produced and hosted by GitHub, not by us; also runs locally:
#
#   experiments/acc_proof/ci_proof.sh <path to a clean msquic checkout> <log dir>
#
# Steps (each one checks its own expected outcome and stops the run otherwise):
#   A  upstream cubic.c + upstream tests + our two reproducer tests
#      A1  the two reproducers FAIL
#      A2  gdb catches the wrap inside upstream's own existing CubicTest.* tests,
#          which still all pass (they never look at the accumulator)
#      A3  (FULL=1) full msquiccoretest, our reproducers excluded: baseline
#   B  the complete proposed change: 2 swapped lines in cubic.c, the 2 new tests,
#      2 updated expectations
#      B1  the diff of cubic.c is exactly two lines
#      B2  the two reproducers PASS, all of CubicTest.* passes
#      B3  (FULL=1) full msquiccoretest: nothing else breaks
set -euo pipefail
MSQ=$(cd "$1" && pwd)
LOG=$(mkdir -p "$2" && cd "$2" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
FULL=${FULL:-1}
JOBS=${JOBS:-$(nproc)}
REPRO="CubicTest.AIMD_AccumulatorNoUnderflow:CubicTest.AIMD_PerPacketAcksGrowAtMostOneMssPerWindow"
BIN=$MSQ/build-test/bin/Debug/msquiccoretest
SUMMARY=$LOG/summary.md
say() { echo "$*" | tee -a "$SUMMARY"; }
die() { say ""; say "**UNEXPECTED: $***"; exit 1; }

cd "$MSQ"
: > "$SUMMARY"
say "## AimdAccumulator underflow: independent check"
say ""
say "- upstream commit: \`$(git log -1 --format='%H (%cd) %s' --date=short)\`"
git diff --quiet && git diff --cached --quiet || die "the msquic checkout is not clean"
say "- checkout verified clean (no local changes) before the run"
say "- runner: $(uname -srm), $(gcc --version | head -1)"

build() {
  cmake -S . -B build-test -DQUIC_BUILD_TEST=ON -DQUIC_TLS_LIB=quictls \
        -DCMAKE_BUILD_TYPE=Debug > "$LOG/$1_cmake.log" 2>&1 || { tail -50 "$LOG/$1_cmake.log"; die "cmake failed"; }
  cmake --build build-test --target msquiccoretest -j"$JOBS" > "$LOG/$1_build.log" 2>&1 \
    || { tail -80 "$LOG/$1_build.log"; die "build failed"; }
}

# ---------------------------------------------------------------- A: upstream
cat "$HERE/reproducer_tests.cpp" >> src/core/unittest/CubicTest.cpp
git diff --stat -- src/core/cubic.c | grep -q . && die "cubic.c modified in step A"
say ""
say "### A. Upstream \`cubic.c\`, upstream tests + our two reproducer tests"
say "\`git diff --stat\` (only the test file may change):"
say '```'
say "$(git diff --stat)"
say '```'
build A

set +e
"$BIN" --gtest_filter="$REPRO" > "$LOG/A1_reproducers.txt" 2>&1; rc=$?
set -e
grep -q "FAILED  ] CubicTest.AIMD_AccumulatorNoUnderflow" "$LOG/A1_reproducers.txt" || die "AIMD_AccumulatorNoUnderflow did not fail"
grep -q "FAILED  ] CubicTest.AIMD_PerPacketAcksGrowAtMostOneMssPerWindow" "$LOG/A1_reproducers.txt" || die "AIMD_PerPacketAcksGrowAtMostOneMssPerWindow did not fail"
[ "$rc" -ne 0 ] || die "reproducers exited 0"
say ""
say "**A1. Both reproducers FAIL on upstream code** (exit code $rc). Assertion output:"
say '```'
say "$(grep -E -A3 'Failure|FAILED  \]' "$LOG/A1_reproducers.txt" | grep -v '^--$' | head -40)"
say '```'

LINE=$(grep -n "Cubic->AimdAccumulator -= Cubic->AimdWindow;" src/core/cubic.c | cut -d: -f1)
[ -n "$LINE" ] || die "could not find the subtraction in cubic.c"
sed "s/cubic\.c:661/cubic.c:$LINE/g" "$HERE/catch_wrap.gdb" > "$LOG/catch_wrap.gdb"
gdb -batch -x "$LOG/catch_wrap.gdb" --args "$BIN" --gtest_filter="CubicTest.*-$REPRO" \
    > "$LOG/A2_gdb_upstream_tests.txt" 2>&1 || true
HITS=$(sed -n 's/^Total underflows: \([0-9]*\)/\1/p' "$LOG/A2_gdb_upstream_tests.txt")
[ -n "$HITS" ] && [ "$HITS" -gt 0 ] || die "gdb caught no underflow"
grep -q "PASSED  \]" "$LOG/A2_gdb_upstream_tests.txt" || die "upstream CubicTest.* did not pass under gdb"
grep -q "FAILED  \]" "$LOG/A2_gdb_upstream_tests.txt" && die "an upstream CubicTest failed under gdb"
say ""
say "**A2. gdb, conditional breakpoint on \`cubic.c:$LINE\` (\`AimdAccumulator -= AimdWindow\`) firing only when the subtraction goes below zero, over upstream's own unmodified \`CubicTest.*\`: $HITS underflow(s); every test still passes.**"
say '```'
say "$(grep -E '^(=== underflow|AimdWindow|AimdAccumulator|CongestionWindow|#1 )|PASSED  \]|tests from' "$LOG/A2_gdb_upstream_tests.txt" | head -40)"
say '```'

if [ "$FULL" = 1 ]; then
  set +e
  "$BIN" --gtest_brief=1 --gtest_filter="*-$REPRO" > "$LOG/A3_full_suite_upstream.txt" 2>&1; rc=$?
  set -e
  [ "$rc" -eq 0 ] || { tail -30 "$LOG/A3_full_suite_upstream.txt"; die "upstream full suite failed (exit $rc)"; }
  say ""
  say "**A3. Full \`msquiccoretest\` on upstream (reproducers excluded):**"
  say '```'
  say "$(grep -E '^\[ *(=====|PASSED|SKIPPED|FAILED)' "$LOG/A3_full_suite_upstream.txt")"
  say '```'
fi

# ---------------------------------------------------------- B: proposed change
git checkout -q -- .
git apply "$HERE/full_change_on_upstream_main.diff" || die "the proposed change does not apply to this upstream commit"
say ""
say "### B. The proposed change (2 lines swapped + 2 new tests + 2 updated expectations)"
CH=$(git diff --numstat -- src/core/cubic.c)
say "\`git diff -- src/core/cubic.c\`:"
say '```diff'
say "$(git diff -U2 -- src/core/cubic.c | sed -n '/^@@/,$p')"
say '```'
[ "$CH" = "$(printf '1\t1\tsrc/core/cubic.c')" ] || die "cubic.c change is not a 1-line move (numstat: $CH)"
say "**B1. \`cubic.c\` differs from upstream by one moved line (numstat \`1 1\`); \`git diff --stat\`:**"
say '```'
say "$(git diff --stat)"
say '```'
build B
set +e
"$BIN" --gtest_filter="CubicTest.*" > "$LOG/B2_cubic_tests_fixed.txt" 2>&1; rc=$?
set -e
[ "$rc" -eq 0 ] || { grep -E "FAILED|Failure" "$LOG/B2_cubic_tests_fixed.txt" | head; die "CubicTest.* failed with the fix"; }
grep -q "OK \] CubicTest.AIMD_AccumulatorNoUnderflow" "$LOG/B2_cubic_tests_fixed.txt" || die "reproducer 1 did not run"
grep -q "OK \] CubicTest.AIMD_PerPacketAcksGrowAtMostOneMssPerWindow" "$LOG/B2_cubic_tests_fixed.txt" || die "reproducer 2 did not run"
say ""
say "**B2. With the fix both reproducers PASS, and all of \`CubicTest.*\` passes:**"
say '```'
say "$(grep -E 'OK \] CubicTest.AIMD_(AccumulatorNoUnderflow|PerPacketAcks)|^\[ *(=====|PASSED|FAILED)' "$LOG/B2_cubic_tests_fixed.txt")"
say '```'

if [ "$FULL" = 1 ]; then
  set +e
  "$BIN" --gtest_brief=1 > "$LOG/B3_full_suite_fixed.txt" 2>&1; rc=$?
  set -e
  [ "$rc" -eq 0 ] || { tail -30 "$LOG/B3_full_suite_fixed.txt"; die "full suite failed with the fix (exit $rc)"; }
  say ""
  say "**B3. Full \`msquiccoretest\` with the change:**"
  say '```'
  say "$(grep -E '^\[ *(=====|PASSED|SKIPPED|FAILED)' "$LOG/B3_full_suite_fixed.txt")"
  say '```'
fi
say ""
say "All expected outcomes confirmed."
