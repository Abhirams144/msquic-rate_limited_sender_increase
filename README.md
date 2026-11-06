# msquic-rate_limited_sender_increase
This Repo features implementation of the Rate-Limited Sender Increase solution to the msquic library, primarily the cubic as presently. In the near future, it will be extended to other algorithms too.

## Rate-Limited Sender Increase in CUBIC

Implements draft-ietf-ccwg-ratelimited-increase-11 in MsQuic's CUBIC
(`src/core/cubic.c`): maxFS is reset on every cwnd reduction, and cwnd is capped
at 2 * maxFS in slow start and maxFS + 1 SMSS in congestion avoidance.

- `patches/` - the change as `git format-patch` files against upstream msquic
  `464c873c0` (the commit the `msquic` gitlink points to). Also on the
  `rate-limited-increase` branch inside the local msquic checkout.
- `experiments/run_rls_experiments.sh` - before/after experiment on the dumbbell
  topology (needs root).
- `experiments/analyze_rls.py` - metrics and figures from `experiments/results/`.

### Reproduce

```bash
git clone https://github.com/microsoft/msquic && cd msquic
git checkout 464c873c0 && git submodule update --init --recursive
git am ../patches/*.patch
# stock build for comparison: build-before from 464c873c0 with -DQUIC_CUBIC_CWND_LOG
# (the trace hook must be added to stock cubic.c by hand, see patches/0001)
cmake -S . -B build-after -DQUIC_TLS_LIB=quictls -DCMAKE_BUILD_TYPE=Release \
      -DQUIC_BUILD_TOOLS=ON -DCMAKE_C_FLAGS=-DQUIC_CUBIC_CWND_LOG
cmake --build build-after --target quicsample -j
cd .. && sudo experiments/run_rls_experiments.sh && python3 experiments/analyze_rls.py
```

Unit tests: build with `-DQUIC_BUILD_TEST=ON` and run
`msquiccoretest --gtest_filter=CubicTest.*` (56 tests).
