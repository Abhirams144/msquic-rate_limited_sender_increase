#!/bin/bash
# Builds msquiccoretest once per cubic.c variant and records the scenario traces.
# Variants: stock (upstream cubic.c), full (patch), and the patch with one change
# disabled. Restores the committed sources at the end, whatever happens.
set -u
MSQ=/home/eventhorizon144/WN_ASSIGNMENT/msquic
HERE=/home/eventhorizon144/WN_ASSIGNMENT/report/ablation
cd "$MSQ"

restore() {
    git checkout -- src/core/cubic.c src/core/unittest/CubicTest.cpp
    rm -f src/core/rls_ablation.h
}
trap restore EXIT

declare -A DEFS=(
    [full]=""
    [no_reset]="#define RLS_NO_RESET"
    [no_cacap]="#define RLS_NO_CACAP"
    [ssthresh_lower]="#define RLS_SSTHRESH_LOWER"
    [no_restore]="#define RLS_NO_RESTORE"
    [no_floor]="#define RLS_NO_FLOOR"
)

git checkout -- src/core/unittest/CubicTest.cpp
cat "$HERE/scenarios.cpp.inc" >> src/core/unittest/CubicTest.cpp

for v in stock full no_reset no_cacap ssthresh_lower no_restore no_floor; do
    if [ "$v" = stock ]; then
        cp "$HERE/cubic_stock.c" src/core/cubic.c
        echo "" > src/core/rls_ablation.h
    else
        cp "$HERE/cubic_ablation.c" src/core/cubic.c
        printf '%s\n' "${DEFS[$v]}" > src/core/rls_ablation.h
    fi
    touch src/core/cubic.c
    if ! cmake --build build-test --target msquiccoretest -j"$(nproc)" > "$HERE/build_$v.log" 2>&1; then
        echo "build failed for $v"; tail -20 "$HERE/build_$v.log"; exit 1
    fi
    build-test/bin/Debug/msquiccoretest --gtest_filter='CubicScenario.*' 2>&1 \
        | grep '^SCN,' | sed "s/^SCN,/$v,/" > "$HERE/trace_$v.csv"
    echo "$v: $(wc -l < "$HERE/trace_$v.csv") rows"
done
