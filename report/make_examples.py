#!/usr/bin/env python3
"""
Four extra examples for the brief report, each from real data:

(a) the upstream AIMD bug in isolation  - harness scenario F (report/ablation/f_*.txt)
(b) when the problem matters            - sweep campaign, data lost vs measured
                                          rate-limited time (experiments/results_v2)
(c) sharing the path with TCP           - four-build campaign, worst 0.5 s of the
                                          competing TCP flow in every run (results_v3)
(d) ECN instead of loss                 - harness scenario E (report/ablation/traces_all.csv)

Writes report/figures/examples.{pdf,png}, and panels (a) and (d) on their own
as bug_harness.{pdf,png} and scenario_e.{pdf,png} for the full report.
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ABL = os.path.join(ROOT, "report", "ablation")
FIG = os.path.join(ROOT, "report", "figures")
RED, BLUE, PINK, LBLUE = "#c0392b", "#1f5fa8", "#e8a09a", "#8fb3e0"
INK, MUTED = "#222222", "#666666"
SMSS = 1232

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.titlesize": 8.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.grid": True, "grid.color": "#e6e6e6",
    "grid.linewidth": 0.6, "legend.frameon": False, "legend.fontsize": 7,
})

fig, ax = plt.subplots(2, 2, figsize=(7.0, 4.8))

# (a) AIMD bug, scenario F --------------------------------------------------
def read_f(path):
    rows = [l.strip().split(",") for l in open(path) if l.startswith("AIMD,")]
    d = pd.DataFrame(rows, columns=["tag", "ph", "r", "cwnd", "maxfs", "ss", "aimd", "acc"])
    d[["r", "cwnd"]] = d[["r", "cwnd"]].astype(int)
    first = d[d.ph == "after_loss"].cwnd.iloc[0]
    post = d[d.ph == "post_loss_round"]
    return [0] + list(post.r + 1), [first / 1000] + list(post.cwnd / 1000)

def panel_bug(a, title):
    x, y = read_f(os.path.join(ABL, "f_stock.txt"))
    a.plot(x, y, color=RED, lw=2, ls="--", marker="o", ms=4, label="stock (bug)")
    x2, y2 = read_f(os.path.join(ABL, "f_stockfix.txt"))
    a.plot(x2, y2, color=BLUE, lw=2, marker="s", ms=4, label="stock + fix")
    a.set_yscale("log")
    a.set_xlabel("round trips after a loss (window fully used)")
    a.set_ylabel("cwnd (KB)")
    a.set_title(title, loc="left")
    a.annotate(f"{y[-1]:.0f} KB", (x[-1], y[-1]), xytext=(-4, -2), textcoords="offset points",
               ha="right", va="top", color=INK, fontsize=7)
    a.annotate(f"{y2[-1]:.0f} KB", (x2[-1], y2[-1]), xytext=(-4, 5), textcoords="offset points",
               ha="right", va="bottom", color=INK, fontsize=7)
    a.legend(loc="upper left")


panel_bug(ax[0, 0], "(a) Upstream bug: cwnd doubles every RTT in CA")

# (b) when it matters, sweep ------------------------------------------------
runs = pd.read_csv(os.path.join(ROOT, "experiments", "results_v2", "analysis", "runs.csv"))
d = runs[runs.point.str.startswith("dur_")]
a = ax[0, 1]
for v, c, ls, lab in (("before", RED, "--", "stock"), ("after", BLUE, "-", "patched")):
    g = d[d.variant == v].groupby("point")
    x = g.ratelimited_s.median()
    q = g.lost_kb_after_resume.quantile([0.25, 0.5, 0.75]).unstack()
    o = np.argsort(x.values)
    xs = x.values[o]
    a.fill_between(xs, q[0.25].values[o].clip(min=1), q[0.75].values[o].clip(min=1),
                   color=c, alpha=0.15, lw=0)
    a.plot(xs, q[0.5].values[o].clip(min=1), color=c, lw=2, ls=ls, marker="o", ms=4, label=lab)
a.set_yscale("log")
a.set_xlabel("time the sender was really rate-limited (s)")
a.set_ylabel("data lost after resuming (KB)")
a.set_title("(b) The harm needs time to build up", loc="left")
a.legend(loc="lower right")

# (c) sharing with TCP: worst 0.5 s of the TCP flow, every run ------------
v3runs = pd.read_csv(os.path.join(ROOT, "experiments", "results_v3", "analysis", "runs.csv"))
a = ax[1, 0]
builds = (("stock", RED, "stock"), ("stockfix", PINK, "stock\n+ fix"),
          ("ours", BLUE, "patch"), ("oursfix", LBLUE, "patch\n+ fix"))
rng = np.random.default_rng(3)
for i, (v, c, lab) in enumerate(builds):
    y = v3runs[(v3runs.point == "compete") & (v3runs.variant == v)].tcp_min_mbps_after2s.values
    a.scatter(i + rng.uniform(-0.12, 0.12, len(y)), y, s=22, color=c, edgecolor="white", lw=0.8, zorder=3)
    m = np.median(y)
    a.plot([i - 0.25, i + 0.25], [m, m], color=INK, lw=1.5, zorder=4)
    a.text(i + 0.28, m, f"{m:.1f}", color=INK, fontsize=7, va="center")
a.set_xticks(range(4), [b[2] for b in builds])
a.set_xlim(-0.5, 3.7)
a.set_ylim(-0.5, 17)
a.grid(axis="x", visible=False)
a.set_ylabel("TCP rate, worst 0.5 s after\nQUIC resumes (Mbit/s)")
a.set_title("(c) A TCP flow sharing the bottleneck (10 runs)", loc="left")

# (d) ECN, scenario E -------------------------------------------------------
T = pd.read_csv(os.path.join(ABL, "traces_all.csv"))
T = T[pd.to_numeric(T["round"], errors="coerce").notna()]
def panel_ecn(a, title):
    for v, c, ls, lab in (("stock", RED, "--", "stock"), ("full", BLUE, "-", "patched")):
        e = T[(T.scn == "E") & (T.variant == v)].reset_index(drop=True)
        e = e[e.phase.isin(["after_ecn", "ratelimited"])].reset_index(drop=True)
        a.plot(np.arange(len(e)), e.cwnd.astype(float) / SMSS, color=c, lw=2, ls=ls, label=lab)
        if v == "full":
            a.fill_between(np.arange(len(e)), 0, e.inflight.astype(float) / SMSS, color="#cccccc",
                           lw=0, step="post", label="in flight after ACKs")
    e = T[(T.scn == "E") & (T.variant == "full") & (T.phase == "ratelimited")]
    cap = (e.maxfs.astype(float).iloc[0] + SMSS) / SMSS
    ss = e.ss.astype(float).iloc[0] / SMSS
    a.axhline(ss, color=MUTED, lw=0.8, ls=":")
    a.axhline(cap, color=MUTED, lw=0.8, ls=":")
    a.text(100, ss + 0.8, "ssthresh", color=MUTED, fontsize=7, ha="right", va="bottom")
    a.text(100, cap - 0.8, "CA cap = maxFS + 1", color=MUTED, fontsize=7, ha="right", va="top")
    a.set_ylim(0, 72)
    a.set_xlabel("round trips after an ECN-CE mark")
    a.set_ylabel("cwnd (packets)")
    a.set_title(title, loc="left")
    a.legend(loc="upper left", ncol=3)


panel_ecn(ax[1, 1], "(d) Same problem after ECN, not loss")

fig.tight_layout()
fig.savefig(os.path.join(FIG, "examples.pdf"))
fig.savefig(os.path.join(FIG, "examples.png"), dpi=140)
print("wrote", os.path.join(FIG, "examples.pdf"))

# Single panels for the full report -----------------------------------------
for name, fn, title in (("bug_harness", panel_bug, "Scenario F: cwnd after a loss, window fully used"),
                        ("scenario_e", panel_ecn, "Scenario E: cwnd after an ECN-CE mark")):
    f, a = plt.subplots(figsize=(4.6, 2.9))
    fn(a, title)
    f.tight_layout()
    f.savefig(os.path.join(FIG, name + ".pdf"))
    f.savefig(os.path.join(FIG, name + ".png"), dpi=140)
    plt.close(f)
    print("wrote", os.path.join(FIG, name + ".pdf"))
