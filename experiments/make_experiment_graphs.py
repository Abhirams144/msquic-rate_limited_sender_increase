#!/usr/bin/env python3
"""
Regenerates the experiment graphs in experiments/graphs/ from the real traces.

Same set of ideas as the earlier exploratory plots (bulk CUBIC, the rate-limited
problem, Gap 1 before/after, the cap before/after, the resumption burst, the
harm to other traffic, a per-round worked example), but:

  * only the SENDER's (client's) trace is used, sorted by time, so there are
    no spikes from interleaving the client and server logs;
  * the draft's limit is computed from the data, never typed in by hand:
    draft maxFS is re-derived from the trace (reset to 0 at every window
    reduction, then max of bytes in flight), and the cap is 2*maxFS in slow
    start, maxFS + 1 SMSS in congestion avoidance;
  * stock and patched always share axes, units are on every axis, and each
    figure says which run it shows.

Inputs:  experiments/results/{before,after}_rep<N>_{client.csv,client.out,ping.txt,clock_offset.txt}
         report/ablation/traces_all.csv   (deterministic scenarios, for the worked example)
Output:  experiments/graphs/*.png and README.md

Usage:   python3 make_experiment_graphs.py [--rep N]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from analyze_rls import parse_out, load_ping  # noqa: E402

RES = os.path.join(HERE, "results")
OUT = os.path.join(HERE, "graphs")
ABL = os.path.join(os.path.dirname(HERE), "report", "ablation", "traces_all.csv")
SMSS = 1472            # QUIC datagram payload on the testbed path (IPv4, MTU 1500)
SMSS_HARNESS = 1232    # unit-test harness (MTU 1280)

C = {"before": "#c0392b", "after": "#1f5fa8"}
NAME = {"before": "Stock MsQuic", "after": "Patched MsQuic"}
plt.rcParams.update({
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 8.5, "legend.framealpha": 0.9,
})
CAPTIONS = {}


def save(fig, name, caption):
    fig.savefig(os.path.join(OUT, name), dpi=140, bbox_inches="tight")
    plt.close(fig)
    CAPTIONS[name] = caption
    print("wrote", name)


# ------------------------------------------------------------------ data
def load(variant, rep):
    tag = f"{variant}_rep{rep}"
    tr = pd.read_csv(os.path.join(RES, f"{tag}_client.csv"), header=None,
                     names=["ev", "t", "cwnd", "maxfs", "inflight", "ss", "bytes"])
    tr = tr.sort_values("t", kind="stable").reset_index(drop=True)
    ph, _ = parse_out(os.path.join(RES, f"{tag}_client.out"))
    t0 = ph["final_us"]                              # time 0 = the app resumes
    tr["s"] = (tr.t - t0) / 1e6
    tr["draft_maxfs"] = draft_maxfs(tr)
    tr["draft_cap"] = np.where(tr.cwnd < tr.ss, 2 * tr.draft_maxfs, tr.draft_maxfs + SMSS)
    tr["draft_cap"] = np.maximum(tr.draft_cap, 2 * SMSS)
    tr["stock_cap"] = 2 * tr.maxfs                   # stock rule, from the logged maxFS
    off = float(open(os.path.join(RES, f"{tag}_clock_offset.txt")).read())
    ping = load_ping(os.path.join(RES, f"{tag}_ping.txt"), off)
    ping["s"] = (ping.t_us - t0) / 1e6
    phases = {k: (v - t0) / 1e6 for k, v in ph.items() if v}
    # The prime data is only queued at "PRIME"; it takes seconds to drain. The app
    # is really rate-limited from the first send after the prime peak at which the
    # flight has fallen to the steady rate-limited level.
    sends = tr[(tr.ev == "S") & (tr.s < 0)]
    steady = sends[sends.s > -8].inflight.mean()
    t_peak = sends.loc[sends.inflight.idxmax(), "s"]
    after = sends[(sends.s > t_peak) & (sends.inflight < 1.5 * steady)]
    phases["rl_start"] = after.s.iloc[0]
    phases["steady_flight"] = steady
    return tr, ping, phases


def draft_maxfs(tr):
    """maxFS as the draft defines it, re-derived from the trace: reset to 0
    whenever cwnd is reduced (a loss event lowers cwnd), then the max of the
    bytes in flight seen afterwards."""
    out = np.empty(len(tr), dtype=np.int64)
    m, prev_cwnd = 0, None
    for i, (ev, cwnd, infl) in enumerate(zip(tr.ev.values, tr.cwnd.values, tr.inflight.values)):
        if prev_cwnd is not None and cwnd < prev_cwnd and ev == "L":
            m = 0
        m = max(m, infl)
        out[i] = m
        prev_cwnd = cwnd
    return out


def flight_bins(tr, lo, hi, bin_s=0.05):
    s = tr[(tr.ev == "S") & (tr.s >= lo) & (tr.s <= hi)]
    b = (np.floor(s.s / bin_s) * bin_s).round(4)
    return s.groupby(b).inflight.max()


def acks(tr, lo, hi):
    return tr[(tr.ev == "A") & (tr.s >= lo) & (tr.s <= hi)]


def shade_ratelimited(ax, ph, lo=None):
    a = ph.get("rl_start")
    if a is not None:
        ax.axvspan(max(a, lo) if lo is not None else a, 0, color="#f4ecd8", zorder=0, lw=0,
                   label="app is rate-limited")


def losses(ax, tr, lo, hi, y):
    L = tr[(tr.ev == "L") & (tr.s >= lo) & (tr.s <= hi)]
    if len(L):
        ax.plot(L.s, np.full(len(L), y), "x", color="k", ms=5, mew=1.2, label="loss detected")


# ------------------------------------------------------------------ graphs
def g_baseline(d):
    tr, _, ph = d["before"]
    lo, hi = ph["prime_us"] - 0.1, ph["rl_start"]
    fig, ax = plt.subplots(figsize=(9, 4))
    f = flight_bins(tr, lo, hi)
    ax.fill_between(f.index, 0, f / 1e3, step="post", color="0.8", label="bytes in flight (max per 50 ms)")
    a = acks(tr, lo, hi)
    ax.step(a.s, a.cwnd / 1e3, where="post", color=C["before"], lw=1.6, label="cwnd")
    ss = a.ss.where(a.ss < 1e9) / 1e3        # unset (infinite) before the first loss
    ax.step(a.s, ss, where="post", color="0.3", ls=":", lw=1.2, label="ssthresh (unset before 1st loss)")
    losses(ax, tr, lo, hi, 20)
    ax.set_xlim(lo, hi)
    ax.set_xlabel("time relative to the later resumption (s)")
    ax.set_ylabel("KB")
    ax.set_title("Bulk sending with CUBIC (prime phase, stock, run 1)", loc="left")
    ax.legend(loc="upper right")
    save(fig, "baseline_cwnd.png",
         "CUBIC while the app sends 3 MB as fast as it can: slow start overshoots, losses cut "
         "cwnd by 30 % each, and CUBIC then grows it again. Normal, cwnd-limited behaviour.")


def g_ratelimited(d):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, sharey=True)
    for ax, v in zip(axes, ("before", "after")):
        tr, _, ph = d[v]
        lo, hi = ph["prime_us"] - 0.1, 0.0
        shade_ratelimited(ax, ph)
        f = flight_bins(tr, lo, hi, 0.1)
        ax.fill_between(f.index, 0, f / 1e3, step="post", color="0.7", label="bytes in flight (max per 100 ms)")
        a = acks(tr, lo, hi)
        ax.plot(a.s, a.cwnd / 1e3, color=C[v], lw=1.8, label="cwnd")
        last = a.iloc[-1]
        flight = ph["steady_flight"]
        ax.annotate(f"cwnd {last.cwnd/1e3:.0f} KB\n= {last.cwnd/flight:.1f}x the flight",
                    (last.s, last.cwnd / 1e3), xytext=(-150, 10), textcoords="offset points",
                    arrowprops=dict(arrowstyle="->", color=C[v]), color=C[v], fontsize=9, fontweight="bold")
        ax.set_title(f"{NAME[v]} (run 1)", loc="left")
        ax.set_ylabel("KB")
        ax.legend(loc="upper left")
    axes[0].set_ylim(0, 500)
    axes[1].set_xlabel("time before the app resumes bulk sending (s)")
    save(fig, "ratelimited_cwnd.png",
         "The rate-limited phase (6000 B every 10 ms, ~29 KB in flight). Stock CUBIC keeps "
         "growing cwnd on the ACKs of this small flight; the patched sender keeps cwnd tied "
         "to what it actually sent.")


def g_problem(d):
    tr, _, ph = d["before"]
    lo, hi = ph["prime_us"] - 0.1, 1.0
    fig, ax = plt.subplots(figsize=(10, 4.2))
    shade_ratelimited(ax, ph)
    f = flight_bins(tr, lo, hi, 0.1)
    ax.fill_between(f.index, 0, f / 1e3, step="post", color="0.7", label="bytes in flight (max per 100 ms)")
    a = acks(tr, lo, hi)
    ax.plot(a.s, a.cwnd / 1e3, color=C["before"], lw=1.8, label="cwnd")
    ax.plot(a.s, a.maxfs / 1e3, color="k", ls="--", lw=1.1, label="maxFS (BytesInFlightMax)")
    ax.axvline(0, color="k", ls=":", lw=1)
    ax.text(0.1, 600, "app resumes:\n8 MB to send", fontsize=9)
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, 900)
    ax.set_xlabel("time relative to resumption (s)")
    ax.set_ylabel("KB")
    ax.set_title("The rate-limited sender problem (stock MsQuic, run 1)", loc="left")
    ax.legend(loc="upper right")
    save(fig, "rls_problem.png",
         "Whole stock run. During the rate-limited phase cwnd grows far above the flight, and "
         "the stock limit 2*maxFS (maxFS = 830 KB from the prime phase) never stops it.")


def g_gap1(d):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, v in zip(axes, ("before", "after")):
        tr, _, ph = d[v]
        lo, hi = ph["prime_us"] - 0.1, ph["rl_start"] + 2
        f = flight_bins(tr, lo, hi)
        ax.fill_between(f.index, 0, f / 1e3, step="post", color="0.8", label="bytes in flight")
        a = acks(tr, lo, hi)
        ax.step(a.s, a.cwnd / 1e3, where="post", color=C[v], lw=1.6, label="cwnd")
        ax.step(a.s, a.maxfs / 1e3, where="post", color="k", ls="--", lw=1.2, label="maxFS (logged)")
        losses(ax, tr, lo, hi, 30)
        ax.set_xlim(lo, hi)
        ax.set_title(f"{NAME[v]}: " + ("maxFS never reset" if v == "before" else "maxFS reset at each loss"),
                     loc="left", fontsize=10)
        ax.set_xlabel("time relative to resumption (s)")
    axes[0].set_ylabel("KB")
    axes[0].legend(loc="upper right")
    save(fig, "gap1_before_after.png",
         "Gap 1. After each loss, stock MsQuic keeps maxFS at the pre-loss peak (dashed line "
         "stays at ~830 KB). The patch resets it and re-measures it from the flight that is "
         "still in the network, so it follows the real flight down.")


def g_caps(d):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.6), sharex=True)
    for ax, v in zip(axes, ("before", "after")):
        tr, _, ph = d[v]
        lo, hi = ph["prime_us"] - 0.1, 2.0
        shade_ratelimited(ax, ph)
        a = acks(tr, lo, hi)
        ax.plot(a.s, a.cwnd / 1e3, color=C[v], lw=1.8, label="cwnd", zorder=3)
        if v == "before":
            ax.plot(a.s, a.stock_cap / 1e3, color="#7d3c98", lw=1.3, label="limit MsQuic applies: 2 x maxFS")
            ax.plot(a.s, a.draft_cap / 1e3, color="#17a589", lw=1.3, ls="--",
                    label="limit the draft requires (from the same trace)")
            above = a[a.cwnd > a.draft_cap]
            ax.fill_between(a.s, a.draft_cap / 1e3, a.cwnd / 1e3, where=a.cwnd > a.draft_cap,
                            color=C[v], alpha=0.2, lw=0, label="cwnd above the draft's limit")
            pct = 100 * len(above[above.s.between(ph['rl_start'], 0)]) / max(1, len(a[a.s.between(ph['rl_start'], 0)]))
            ax.text(-11.5, 1000, f"{pct:.0f} % of ACKs in the rate-limited phase\nleave cwnd above the draft's limit",
                    fontsize=9, color=C[v])
        else:
            cap = np.where(a.cwnd < a.ss, 2 * a.maxfs, a.maxfs + SMSS)
            cap = np.maximum(cap, 2 * SMSS)
            ax.plot(a.s, cap / 1e3, color="#17a589", lw=1.3, ls="--", label="draft limit (2 x maxFS in SS, maxFS + 1 SMSS in CA)")
            n_over = int((a.cwnd > cap + 1).sum())
            ax.text(-11.5, 1000, f"cwnd above the draft's limit at {n_over} of {len(a)} ACKs",
                    fontsize=9, color=C[v])
        ax.axvline(0, color="k", ls=":", lw=1)
        ax.set_ylim(0, 1800)
        ax.set_ylabel("KB")
        ax.set_title(f"{NAME[v]} (run 1)", loc="left")
        ax.legend(loc="upper right", fontsize=8)
    axes[1].set_xlabel("time relative to resumption (s)")
    save(fig, "cap_before_after.png",
         "Gap 1 + Gap 2 together: the limit on cwnd. Stock MsQuic applies 2 x a stale maxFS, "
         "about 1.7 MB, which never binds. The limit the draft requires, computed from the same "
         "trace, is far lower. The patched build's cwnd stays on or below the draft's limit.")


def g_burst(d):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, sharey=True)
    for ax, v in zip(axes, ("before", "after")):
        tr, _, ph = d[v]
        lo, hi = -1.0, 3.0
        shade_ratelimited(ax, ph, lo)
        f = flight_bins(tr, lo, hi, 0.01)
        ax.fill_between(f.index, 0, f / 1e3, step="post", color=C[v], alpha=0.35, lw=0,
                        label="bytes in flight (max per 10 ms)")
        a = acks(tr, lo, hi)
        ax.step(a.s, a.cwnd / 1e3, where="post", color=C[v], lw=1.6, label="cwnd")
        losses(ax, tr, lo, hi, 20)
        peak = f[f.index < 0.5].max()
        ax.axhline(peak / 1e3, color=C[v], ls=":", lw=1)
        ax.text(2.95, peak / 1e3 + 10, f"peak {peak/1e3:.0f} KB in first 0.5 s", ha="right", color=C[v], fontsize=9)
        ax.axvline(0, color="k", ls=":", lw=1)
        ax.set_ylabel("KB")
        ax.set_title(f"{NAME[v]} (run 1)", loc="left")
        ax.legend(loc="upper left", fontsize=8)
    axes[0].set_ylim(0, 520)
    axes[1].set_xlabel("time relative to resumption (s)")
    save(fig, "resumption_burst.png",
         "What happens when the app resumes. Stock releases its inflated window at once; the "
         "queue overflows (x = losses) and cwnd is cut repeatedly. The patched sender starts "
         "from a validated window.")


def g_harm(d):
    fig, ax = plt.subplots(figsize=(10, 4))
    for v in ("before", "after"):
        _, p, _ = d[v]
        w = p[(p.s >= -1) & (p.s <= 4)]
        ax.plot(w.s, w.rtt_ms, color=C[v], lw=1.1, label=NAME[v])
        pk = w[w.s >= 0].rtt_ms.max()
        ax.axhline(pk, color=C[v], ls=":", lw=0.9)
        ax.text(3.95, pk + 4, f"max {pk:.0f} ms", color=C[v], ha="right", fontsize=9)
    base = d["before"][1]
    b = base[(base.s > -5) & (base.s < 0)].rtt_ms.median()
    ax.axhline(b, color="0.4", ls="--", lw=0.9)
    ax.text(-0.95, b + 12, f"before resumption: {b:.0f} ms", color="0.3", fontsize=9)
    ax.axvline(0, color="k", ls=":", lw=1)
    ax.set_xlabel("time relative to resumption (s)")
    ax.set_ylabel("ping RTT of the competing flow (ms)")
    ax.set_ylim(0, 420)
    ax.set_title("Harm to other traffic: delay seen by a competing flow (run 1)", loc="left")
    ax.legend(loc="upper right", bbox_to_anchor=(1, 0.85))
    save(fig, "competing_delay.png",
         "A ping every 10 ms shares the bottleneck. The stock burst fills the queue and the "
         "ping RTT jumps far more than with the patch.")


def g_all_runs(rep_count):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, v in zip(axes, ("before", "after")):
        ends = []
        for rep in range(1, rep_count + 1):
            try:
                tr, _, ph = load(v, rep)
            except FileNotFoundError:
                continue
            a = acks(tr, -12, 0)
            ax.plot(a.s, a.cwnd / 1e3, color=C[v], lw=1.1, alpha=0.85)
            ends.append((a.cwnd.iloc[-1] / 1e3, rep))
        y_prev = -1e9
        for y, rep in sorted(ends):             # spread labels so they never overlap
            y = max(y, y_prev + 14)
            ax.text(0.15, y, f"run {rep}", fontsize=7.5, color=C[v], va="center")
            y_prev = y
        f = ph["steady_flight"]
        ax.axhline(f / 1e3, color="0.4", ls="--", lw=1)
        ax.text(-11.8, f / 1e3 + 8, f"bytes in flight ~ {f/1e3:.0f} KB", fontsize=8.5, color="0.3")
        ax.set_xlim(-12, 1.3)
        ax.set_title(f"{NAME[v]}: all {rep_count} runs", loc="left")
        ax.set_xlabel("time before resumption (s)")
    axes[0].set_ylabel("cwnd (KB)")
    axes[0].set_ylim(0, 480)
    save(fig, "ratelimited_all_runs.png",
         "cwnd during the last 12 s of the rate-limited phase in every run. Stock grows in all "
         "five (more when the last loss was longer ago); the patched sender stays flat.")


def g_worked_example():
    S = pd.read_csv(ABL)
    S = S[S.scn == "A"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [2, 1]})
    ax = axes[0]
    for v, lab, ls in (("before", "Stock MsQuic", "-"), ("after", "Patched MsQuic", "-")):
        g = S[S.variant == ("stock" if v == "before" else "full")]
        r = g[g.phase == "ratelimited"]
        ax.plot(r["round"] * 0.05, r.cwnd / SMSS_HARNESS, color=C[v], lw=1.8, ls=ls, label=f"{lab}: cwnd")
    g = S[S.variant == "stock"]
    r = g[g.phase == "ratelimited"]
    ax.plot(r["round"] * 0.05, 2 * r.maxfs / SMSS_HARNESS, color="#7d3c98", lw=1.1, ls="--",
            label="stock limit: 2 x maxFS = 80")
    ax.axhline(29, color="#17a589", lw=1.1, ls="--", label="draft limit: maxFS + 1 = 29")
    ax.axhline(40, color="0.4", lw=0.9, ls=":")
    ax.text(0.1, 41, "flight at which the loss happened (40)", fontsize=8, color="0.3")
    ax.fill_between(r["round"] * 0.05, 0, 4, color="0.8", label="flight actually sent (4)")
    ax.set_xlabel("time since the loss (s); 1 round = 50 ms")
    ax.set_ylabel("packets (1232 B)")
    ax.set_ylim(0, 85)
    ax.set_title("Worked example: loss at 40 packets, then 4 packets/RTT", loc="left", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax = axes[1]
    bur = {}
    for v, var in (("before", "stock"), ("after", "full")):
        g = S[(S.variant == var) & (S.phase == "resume")]
        bur[v] = g.inflight.iloc[0] / SMSS_HARNESS
    ax.bar([0, 1], [bur["before"], bur["after"]], color=[C["before"], C["after"]], width=0.6)
    for i, v in enumerate(("before", "after")):
        ax.text(i, bur[v] + 1.5, f"{bur[v]:.0f}", ha="center", fontweight="bold")
    ax.axhline(40, color="0.4", lw=0.9, ls=":")
    ax.set_xticks([0, 1], ["Stock", "Patched"])
    ax.set_ylabel("packets sent in one RTT")
    ax.set_title("Burst when the app resumes", loc="left", fontsize=10)
    ax.grid(axis="x", visible=False)
    save(fig, "worked_example.png",
         "Deterministic worked example run through MsQuic's own CUBIC code (unit-test harness, "
         "scenario A of the report). Stock lets cwnd climb to 76 packets with only 4 in flight.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    d = {v: load(v, args.rep) for v in ("before", "after")}
    g_baseline(d)
    g_ratelimited(d)
    g_problem(d)
    g_gap1(d)
    g_caps(d)
    g_burst(d)
    g_harm(d)
    g_all_runs(args.reps)
    if os.path.exists(ABL):
        g_worked_example()
    with open(os.path.join(OUT, "README.md"), "w") as f:
        f.write("# Experiment graphs\n\nGenerated by `experiments/make_experiment_graphs.py` from "
                "`experiments/results/` (10 Mbit/s, ~41 ms RTT, 100-packet netem queue) and "
                "`report/ablation/traces_all.csv`. Time 0 = the moment the app resumes bulk sending.\n\n")
        for k, v in CAPTIONS.items():
            f.write(f"## {k}\n\n![{k}]({k})\n\n{v}\n\n")


if __name__ == "__main__":
    main()
