#!/usr/bin/env python3
"""
Analyses the 4-build campaign (run_campaign.sh fix -> results_v3/).

Builds: stock (upstream), stockfix (upstream + AIMD-accumulator fix),
        ours (rate-limited increase patch), oursfix (ours + AIMD fix).

Comparisons (difference of medians, 95 % bootstrap CI, permutation p):
  ours     vs stock     - our patch on upstream as it is
  stockfix vs stock     - the accumulator fix alone
  oursfix  vs stockfix  - our patch when both builds have the fix (cleanest test)
  oursfix  vs ours      - the fix on top of our patch

Extra per-run metric: share of cwnd increases in congestion avoidance that are
exactly +1 SMSS on one ACK, the signature of the wrapped accumulator.

Output: results_v3/analysis/{runs.csv, stats.csv, medians.csv},
        report/figures/fourway.{pdf,png}, report/figures/fourway_compete.{pdf,png},
        report/tables/fourway_rows.tex
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = sys.argv[:1]
import analyze_campaign as AC  # noqa: E402

ROOT = os.path.dirname(HERE)
RES = os.path.join(HERE, "results_v3")
OUT = os.path.join(RES, "analysis")
FIG = os.path.join(ROOT, "report", "figures")
TAB = os.path.join(ROOT, "report", "tables")
for d in (OUT, FIG, TAB):
    os.makedirs(d, exist_ok=True)

V = ["stock", "stockfix", "ours", "oursfix"]
LBL = {"stock": "Stock", "stockfix": "Stock + AIMD fix", "ours": "Ours", "oursfix": "Ours + AIMD fix"}
COL = {"stock": "#c0392b", "stockfix": "#e8a09a", "ours": "#1f5fa8", "oursfix": "#8fb4e0"}
SMSS = 1472
PTS = ["dur_10s", "dur_30s", "rtt_80", "bw_50", "compete"]
PT_LBL = {"dur_10s": "6 s rate-limited", "dur_30s": "28 s rate-limited", "rtt_80": "RTT 80 ms",
          "bw_50": "50 Mbit/s", "compete": "+ TCP flow"}
PT_TICK = {"dur_10s": "6 s\nrate-ltd.", "dur_30s": "28 s\nrate-ltd.", "rtt_80": "RTT\n80 ms",
           "bw_50": "50\nMbit/s", "compete": "+ TCP\nflow"}
COMPARE = [("ours", "stock"), ("stockfix", "stock"), ("oursfix", "stockfix"), ("oursfix", "ours")]
RNG = np.random.default_rng(7)


def smss_per_ack_share(tr):
    a = tr[tr.ev == "A"]
    d = a.cwnd.diff()
    ca_up = (a.cwnd.shift() >= a.ssthresh) & (d > 0)
    return float(((d == SMSS) & ca_up).sum() / max(1, ca_up.sum()))


rows, tcps = [], []
for pdir in sorted(glob.glob(os.path.join(RES, "*"))):
    if not os.path.exists(os.path.join(pdir, "point.txt")):
        continue
    point = os.path.basename(pdir)
    for f in sorted(glob.glob(os.path.join(pdir, "*_client.csv"))):
        tag = os.path.basename(f)[:-len("_client.csv")]
        row, tr, ping, ph, tcp = AC.run_metrics(pdir, tag)
        row["point"] = point
        row["smss_per_ack_share"] = smss_per_ack_share(tr)
        rows.append(row)
        if tcp is not None and len(tcp):
            t = tcp.copy()
            t["variant"], t["rep"] = row["variant"], row["rep"]
            tcps.append(t)
runs = pd.DataFrame(rows)
runs.to_csv(os.path.join(OUT, "runs.csv"), index=False)

METRICS = dict(AC.METRICS)
METRICS["smss_per_ack_share"] = "share of CA increases that are +1 SMSS/ACK"
st = []
for pt in PTS:
    g = runs[runs.point == pt]
    for m in METRICS:
        if m not in g or g[m].isna().all():
            continue
        for x, y in COMPARE:
            b = g[g.variant == x][m].dropna().values
            a = g[g.variant == y][m].dropna().values
            if len(a) < 3 or len(b) < 3:
                continue
            lo, hi = AC.boot_ci_median_diff(a, b)
            st.append(dict(point=pt, metric=m, compare=f"{x} vs {y}", n=min(len(a), len(b)),
                           base_median=np.median(a), new_median=np.median(b),
                           diff_median=np.median(b) - np.median(a), ci_lo=lo, ci_hi=hi,
                           p_perm=AC.perm_p(a, b)))
stats = pd.DataFrame(st)
stats.to_csv(os.path.join(OUT, "stats.csv"), index=False)
med = runs.groupby(["point", "variant"])[list(METRICS) + ["maxfs_at_resume_kb", "bottleneck_drops", "ping_lost_after_resume"]] \
          .median(numeric_only=True)
med.to_csv(os.path.join(OUT, "medians.csv"))

pd.set_option("display.width", 250)
show = ["cwnd_at_resume_kb", "burst_peak_inflight_kb", "lost_kb_after_resume", "bottleneck_drops",
        "ping_max_ms_after_resume", "fct_1mb_s", "resume_8mb_s", "smss_per_ack_share",
        "tcp_mbps_after2s", "tcp_min_mbps_after2s", "tcp_cwnd_min_after3s_kb", "tcp_retr_after3s"]
print(med[[c for c in show if c in med]].round(2).to_string())
print()
key = ["cwnd_at_resume_kb", "lost_kb_after_resume", "resume_8mb_s", "fct_1mb_s", "smss_per_ack_share",
       "tcp_mbps_after2s", "tcp_min_mbps_after2s", "tcp_cwnd_min_after3s_kb"]
print(stats[stats.metric.isin(key)][["point", "metric", "compare", "base_median", "new_median", "ci_lo", "ci_hi", "p_perm"]]
      .to_string(index=False, float_format=lambda v: f"{v:.3g}"))

# ------------------------------------------------------------------ figures
plt.rcParams.update({"font.family": "serif", "font.size": 8.5, "axes.titlesize": 9,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 8})
W = 6.3
panels = [("cwnd_at_resume_kb", "cwnd at resumption (KB)"),
          ("lost_kb_after_resume", "data lost after resuming (KB, log)"),
          ("smss_per_ack_share", "CA increases of +1 SMSS per ACK"),
          ("resume_8mb_s", "8 MB transfer time (s)")]
fig, axes = plt.subplots(2, 2, figsize=(W, 4.9))
for ax, (m, title) in zip(axes.flat, panels):
    for i, pt in enumerate(PTS):
        g = runs[runs.point == pt]
        for k, v in enumerate(V):
            x = i + (k - 1.5) * 0.19
            vals = g[g.variant == v][m].dropna().values
            if m == "lost_kb_after_resume":
                vals = np.maximum(vals, 1)
            ax.scatter(x + RNG.uniform(-0.04, 0.04, len(vals)), vals, s=5, color=COL[v], alpha=0.6, lw=0)
            ax.plot([x - 0.08, x + 0.08], [np.median(vals)] * 2, color=COL[v], lw=2.2,
                    label=LBL[v] if i == 0 else None)
    if m == "lost_kb_after_resume":
        ax.set_yscale("log")
    elif m == "resume_8mb_s":
        pass
    else:
        ax.set_ylim(bottom=0)
    ax.set_xticks(range(len(PTS)), [PT_TICK[p] for p in PTS], fontsize=7)
    ax.set_title(title, loc="left", fontsize=8.5)
    ax.grid(axis="x", visible=False)
h, l = axes[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.0))
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig(os.path.join(FIG, "fourway.pdf"))
fig.savefig(os.path.join(FIG, "fourway.png"), dpi=130)
plt.close(fig)

if tcps:
    T = pd.concat(tcps)
    fig, axes = plt.subplots(1, 3, figsize=(W, 2.5), gridspec_kw={"width_ratios": [2.2, 1, 1]})
    ax = axes[0]
    for v in V:
        series = []
        for rep, s in T[T.variant == v].groupby("rep"):
            s = s[(s.s >= -3) & (s.s < 6)].copy()
            s["bin"] = np.floor(s.s / 0.5) * 0.5
            series.append(s.groupby("bin").bytes.sum() * 8 / 0.5 / 1e6)
        M = pd.concat(series, axis=1)
        ax.step(M.index, M.median(axis=1), where="post", color=COL[v], lw=1.4, label=LBL[v])
    ax.axvline(0, color="k", ls=":", lw=0.8)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("time relative to resumption (s)")
    ax.set_ylabel("TCP rate, 0.5 s bins (Mbit/s)")
    ax.set_title("(a) median over 10 runs", loc="left")
    ax.legend(loc="lower left", frameon=False, fontsize=7)
    cg = runs[runs.point == "compete"]
    for ax, m, t in ((axes[1], "tcp_min_mbps_after2s", "(b) worst 0.5 s of\nTCP rate (Mbit/s)"),
                     (axes[2], "lost_kb_after_resume", "(c) QUIC data lost\nafter resuming (KB)")):
        for k, v in enumerate(V):
            vals = cg[cg.variant == v][m].dropna().values
            if m == "lost_kb_after_resume":
                vals = np.maximum(vals, 1)
            ax.scatter(k + RNG.uniform(-0.15, 0.15, len(vals)), vals, s=8, color=COL[v], zorder=3)
            ax.plot([k - 0.25, k + 0.25], [np.median(vals)] * 2, color="k", lw=1.2)
        ax.set_xticks(range(4), ["S", "S+f", "O", "O+f"])
        ax.set_title(t, loc="left", fontsize=8)
        ax.grid(axis="x", visible=False)
        if m == "lost_kb_after_resume":
            ax.set_yscale("log")
        else:
            ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fourway_compete.pdf"))
    fig.savefig(os.path.join(FIG, "fourway_compete.png"), dpi=130)
    plt.close(fig)

# ---------------------------------------------- clean timeline (30 s, both fixed)
def timeline(point, variants, rep, name):
    pdir = os.path.join(RES, point)
    fig, axes = plt.subplots(len(variants), 1, figsize=(W, 2.2 * len(variants) + 0.5), sharex=True, sharey=True)
    for ax, v in zip(axes, variants):
        tag = f"{v}_rep{rep}"
        tr = AC.analyse_run(pdir, tag)[1].copy()
        ph = AC.parse_out(os.path.join(pdir, f"{tag}_client.out"))[0] if hasattr(AC, "parse_out") else None
        t0 = AC.analyse_run(pdir, tag)[3]["final_us"]
        tr["s"] = (tr.t_us - t0) / 1e6
        sends = tr[(tr.ev == "S") & (tr.s < 0)]
        steady = sends[sends.s > -8].inflight.mean()
        tpk = sends.loc[sends.inflight.idxmax(), "s"]
        rl0 = sends[(sends.s > tpk) & (sends.inflight < 1.5 * steady)].s.iloc[0]
        lo, hi = tpk - 1.5, 4
        d = tr[(tr.s >= lo) & (tr.s <= hi)]
        f = d[d.ev == "S"].groupby((np.floor(d[d.ev == "S"].s * 10) / 10)).inflight.max()
        a = d[d.ev == "A"]
        ax.axvspan(rl0, 0, color="#f4ecd8", lw=0, zorder=0, label="app is rate-limited")
        ax.fill_between(f.index, 0, f / 1e3, step="post", color="0.75", lw=0, label="bytes in flight (max per 100 ms)")
        ax.plot(a.s, a.cwnd / 1e3, color={"stockfix": "#c0392b", "oursfix": "#1f5fa8"}.get(v, COL[v]), lw=1.5, label="cwnd")
        ax.plot(a.s, a.maxfs / 1e3, color="k", ls="--", lw=0.9, label="maxFS")
        L = d[d.ev == "L"]
        ax.plot(L.s, np.full(len(L), 25), "x", color="k", ms=3.5, mew=0.9, label="loss")
        ax.axvline(0, color="k", ls=":", lw=0.8)
        ax.set_title(f"{LBL[v]} (run {rep})", loc="left")
        ax.set_ylabel("KB")
    axes[0].set_ylim(0, 900)
    axes[-1].set_xlabel("time relative to resumption (s); the app has 8 MB to send at 0")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=5, frameon=False, fontsize=7.5)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(FIG, name + ".pdf"))
    fig.savefig(os.path.join(FIG, name + ".png"), dpi=130)
    plt.close(fig)


timeline("dur_30s", ["stockfix", "oursfix"], 1, "clean_timeline")


# ------------------------------------------------------------------ LaTeX rows
def fmt(x):
    if pd.isna(x):
        return "---"
    return f"{x:.0f}" if abs(x) >= 10 else (f"{x:.2f}" if abs(x) < 1 else f"{x:.1f}")


lines = []
for pt in PTS:
    for m, unit in (("cwnd_at_resume_kb", "KB"), ("lost_kb_after_resume", "KB"), ("resume_8mb_s", "s")):
        cells = [PT_LBL[pt] if m == "cwnd_at_resume_kb" else "", METRICS[m].split(" (")[0]]
        for v in V:
            cells.append(fmt(med.loc[(pt, v), m]))
        s = stats[(stats.point == pt) & (stats.metric == m) & (stats["compare"] == "oursfix vs stockfix")]
        p = s.p_perm.iloc[0] if len(s) else np.nan
        cells.append(r"$<$0.001" if p < 0.001 else f"{p:.3f}")
        lines.append(" & ".join(cells) + r" \\")
    lines.append(r"\addlinespace")
open(os.path.join(TAB, "fourway_rows.tex"), "w").write("\n".join(lines[:-1]) + "\n")
print("wrote", OUT, FIG + "/fourway*.pdf", TAB + "/fourway_rows.tex")
