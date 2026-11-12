# Evidence for the AIMD-accumulator underflow in MsQuic CUBIC

Report: `report/aimd_bug_report.pdf`. Everything here is raw tool output or the exact input used to produce it.

| File | What it is |
|---|---|
| `reproducer_tests.cpp` | The two tests added to upstream `CubicTest.cpp` (nothing else of ours) |
| `fix_on_upstream_main.diff` | The fix on upstream `main` 3c9ec01c1: two lines swapped |
| `full_change_on_upstream_main.diff` | Fix + 2 new tests + 2 updated expectations (what a PR would contain) |
| `repro_upstream_main_RED.txt` | Reproducers on unmodified upstream `cubic.c`: both fail |
| `repro_upstream_main_GREEN.txt` | Same after the two-line swap: all pass |
| `catch_wrap.gdb` | gdb script: breaks on `cubic.c:661` only when the subtraction is about to go below zero |
| `gdb_upstream_suite_hits.txt` | gdb over upstream's unmodified `CubicTest.*`: 2 underflows, all 52 tests pass |
| `gdb_catch_wrap.txt` | gdb on the behavioural reproducer: the wrap that makes cwnd jump 12384 -> 23531 |
| `upstream_main_coretest_baseline.txt` | Full `msquiccoretest` on unmodified upstream: 559 passed, 4 skipped, 0 failed |
| `upstream_main_coretest_with_fix.txt` | Same with the full change: 561 passed, 4 skipped, 0 failed |
| `cubic_S0_stock_logged.c`, `cubic_S1_stockfix_logged.c`, `S0_vs_S1.diff` | Network builds: upstream CUBIC + trace logger (also logs AimdWindow/AimdAccumulator); differ only in the two lines |
| `build_acc.sh`, `source_*.sha256` | Builds `msquic/build-acc-{stock,stockfix}` from those sources |
| `analyze_acc.py` | Analyses `sudo experiments/run_campaign.sh acc` (results in `experiments/results_v4_acc/`) |
| `github_issue.md` | Draft issue and PR text for microsoft/msquic |
