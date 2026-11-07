#!/bin/bash
# Runs scenario F against stock and the patched cubic.c (variants given as args).
set -u
MSQ=/home/eventhorizon144/WN_ASSIGNMENT/msquic
HERE=/home/eventhorizon144/WN_ASSIGNMENT/report/ablation
SRC=${SRC:-$HERE/cubic_ablation.c}
cd "$MSQ"
restore() { git checkout -- src/core/cubic.c src/core/unittest/CubicTest.cpp; rm -f src/core/rls_ablation.h; }
trap restore EXIT
git checkout -- src/core/unittest/CubicTest.cpp
cat "$HERE/scenarios.cpp.inc" "$HERE/scenario_f.cpp.inc" >> src/core/unittest/CubicTest.cpp
for v in "$@"; do
    if [ "$v" = stock ]; then cp "$HERE/cubic_stock.c" src/core/cubic.c; echo > src/core/rls_ablation.h
    else cp "$SRC" src/core/cubic.c; echo > src/core/rls_ablation.h; fi
    touch src/core/cubic.c
    cmake --build build-test --target msquiccoretest -j"$(nproc)" > "$HERE/build_f_$v.log" 2>&1 || { tail -20 "$HERE/build_f_$v.log"; exit 1; }
    echo "== $v"
    build-test/bin/Debug/msquiccoretest --gtest_filter='CubicScenario.F*' 2>&1 | grep '^AIMD,'
done
