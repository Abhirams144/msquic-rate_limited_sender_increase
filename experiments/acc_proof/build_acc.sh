#!/bin/bash
# Builds two Release quicsample binaries that differ only in the two AIMD lines:
#   msquic/build-acc-stock    <- cubic_S0_stock_logged.c
#   msquic/build-acc-stockfix <- cubic_S1_stockfix_logged.c
# Restores msquic/src/core/cubic.c afterwards.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
MSQ=$HERE/../../msquic
cd "$MSQ"
trap 'git checkout -- src/core/cubic.c' EXIT
for v in stock stockfix; do
  if [ $v = stock ]; then SRC=$HERE/cubic_S0_stock_logged.c; else SRC=$HERE/cubic_S1_stockfix_logged.c; fi
  cp "$SRC" src/core/cubic.c
  cmake -S . -B build-acc-$v -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release -DQUIC_TLS_LIB=quictls \
        -DQUIC_BUILD_TOOLS=ON -DCMAKE_C_FLAGS=-DQUIC_CUBIC_CWND_LOG > "$HERE/build_$v.log" 2>&1 || exit 1
  cmake --build build-acc-$v --target quicsample -j"$(nproc)" >> "$HERE/build_$v.log" 2>&1 || { echo "build $v failed"; exit 1; }
  sha256sum "$SRC" > "$HERE/source_$v.sha256"
  echo "built $v"
done
