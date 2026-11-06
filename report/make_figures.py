#!/usr/bin/env python3
"""Generates every figure of the LaTeX report as vector PDF (report/figures/).

Inputs
  report/ablation/traces_all.csv        controlled scenarios (unit-test harness)
  experiments/results/                  network experiment (5 runs per build)
"""
import glob
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = "/home/eventhorizon144/WN_ASSIGNMENT"
OUT = f"{ROOT}/report/figures"
RES = f"{ROOT}/experiments/results"
os.makedirs(OUT, exist_ok=True)

SMSS = 1232  # scenario harness: 1280-byte MTU, IPv6
RTT = 0.05   # scenario harness: 50 ms per round

C = {
    "stock": "#c0392b", "full": "#1f5fa8", "no_reset": "#e08e0b",
    "no_cacap": "#7d3c98", "ssthresh_lower": "#17a589", "no_restore": "#7f8c8d",
    "no_floor": "#a04000", "flight": "#bdbdbd",
}
LBL = {
    "stock": "Stock MsQuic", "full": "Patched (final)",
    "no_reset": "Patch without maxFS reset", "no_cacap": "Patch without CA cap",
    "ssthresh_lower": "Patch + ssthresh lowering (rejected)",
    "no_restore": "Patch without spurious restore", "no_floor": "Patch without 2-packet floor",
}

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "mathtext.fontset": "dejavuserif",
    "font.size": 9, "axes.titlesize": 9.5, "axes.labelsize": 9, "legend.fontsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.6,
    "lines.linewidth": 1.5, "savefig.bbox": "tight", "savefig.pad_inches": 0.03,
    "figure.dpi": 150,
})
W = 6.3  # text width in inches


def save(fig, name):
    fig.savefig(f"{OUT}/{name}.pdf")
    fig.savefig(f"{OUT}/{name}.png", dpi=130)
    plt.close(fig)


S = pd.read_csv(f"{ROOT}/report/ablation/traces_all.csv")
S["pk_cwnd"] = S.cwnd / SMSS
S["pk_maxfs"] = S.maxfs / SMSS
S["pk_ss"] = S.ss / SMSS
S["pk_flight"] = S.inflight / SMSS


def scen(scn, v):
    return S[(S.scn == scn) & (S.variant == v)].reset_index(drop=True)


# ---------------------------------------------------------------- Scenario A
def fig_scenario_a():
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.8), gridspec_kw={"width_ratios": [2.3, 1]})
    ax = axes[0]
    variants = ["stock", "no_cacap", "no_reset", "full"]
    bursts = []
    for v in variants:
        g = scen("A", v)
        rl = g[g.phase == "ratelimited"]
        x = np.concatenate([[0], (rl["round"] + 1) * RTT])
        y = np.concatenate([[g[g.phase == "loss"].pk_cwnd.iloc[-1]], rl.pk_cwnd])
        ax.plot(x, y, color=C[v], label=LBL[v], lw=1.7 if v in ("stock", "full") else 1.2,
                ls="-" if v in ("stock", "full") else "--")
        bursts.append(g[g.phase == "resume"].pk_flight.iloc[0])
    ax.fill_between([0, 10], 0, 4, color=C["flight"], alpha=0.7, lw=0, label="app's actual flight (4 packets)")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 85)
    ax.set_xlabel("time since the loss (s); one RTT = 50 ms")
    ax.set_ylabel("cwnd (packets)")
    ax.set_title("(a) cwnd while the app is rate-limited", loc="left")
    ax.legend(loc="upper left", frameon=False, fontsize=7.3)
    ax = axes[1]
    ax.barh(range(4), bursts, color=[C[v] for v in variants])
    for i, b in enumerate(bursts):
        ax.text(b + 1, i, f"{b:.0f}", va="center", fontsize=8, fontweight="bold")
    ax.set_yticks(range(4), ["Stock", "w/o CA cap", "w/o reset", "Patched"], fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 92)
    ax.set_xlabel("packets released in the first RTT")
    ax.set_title("(b) burst when the app resumes", loc="left")
    ax.grid(axis="y", visible=False)
    save(fig, "scenario_a")


# ---------------------------------------------------------------- Scenario B
def fig_scenario_b():
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.5), sharey=True)
    for ax, v in zip(axes, ["full", "ssthresh_lower"]):
        g = scen("B", v)
        rl = g[g.phase == "ratelimited"]
        rs = g[g.phase == "resume"]
        x = np.concatenate([rl["round"] + 1, 40 + rs["round"] + 1])
        cw = np.concatenate([rl.pk_cwnd, rs.pk_flight])
        ss = np.concatenate([rl.pk_ss, g[g.phase == "resume_ack"].pk_ss])
        mf = rl.pk_maxfs.iloc[-1]
        ax.step(x, cw, where="post", color=C[v], label="cwnd")
        ax.step(x, ss, where="post", color="k", ls=":", lw=1.1, label="ssthresh")
        ax.axhline(mf + 1, color="0.4", ls="--", lw=0.9, label="maxFS + 1 SMSS")
        ax.axhline(2 * mf, color="0.6", ls="-.", lw=0.9, label="2 maxFS (slow-start cap)")
        ax.axvspan(40, 55, color="#f4ecd8", lw=0, zorder=0)
        ax.text(40.5, 40, "app resumes", fontsize=7.5)
        ax.set_title(LBL[v])
        ax.set_xlabel("RTT round")
        ax.set_xlim(0, 55)
        ax.set_ylim(15, 42)
    axes[0].set_ylabel("packets")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, -0.06))
    fig.subplots_adjust(bottom=0.25)
    save(fig, "scenario_b")


# ---------------------------------------------------------------- Scenario C
def fig_scenario_c():
    steps = ["before_loss", "loss", "undo", "first_ack_after_undo"]
    names = ["full window\nin flight", "loss\ndeclared", "loss undone\n(spurious)", "1st ACK\nafter undo"]
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.7), sharey=True)
    for ax, (col, title) in zip(axes, [("pk_cwnd", "cwnd"), ("pk_maxfs", "maxFS")]):
        xs = np.arange(len(steps))
        for k, v in enumerate(["full", "no_restore"]):
            g = scen("C", v)
            vals = [g[g.phase == s][col].iloc[-1] for s in steps]
            b = ax.bar(xs + (k - 0.5) * 0.36, vals, width=0.34, color=C[v], label=LBL[v])
            for xi, val in zip(xs + (k - 0.5) * 0.36, vals):
                ax.text(xi, val + 0.7, f"{val:.0f}" if abs(val - round(val)) < 0.05 else f"{val:.1f}",
                        ha="center", va="bottom", fontsize=6.5, rotation=90)
        ax.set_xticks(xs, names, fontsize=7)
        ax.set_title(title + " (packets)")
        ax.set_ylim(0, 46)
        ax.grid(axis="x", visible=False)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, -0.04))
    fig.subplots_adjust(bottom=0.28)
    save(fig, "scenario_c")


# ---------------------------------------------------------------- Scenario D
def fig_scenario_d():
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.5), gridspec_kw={"width_ratios": [1, 1.6]})
    ax = axes[0]
    vs = ["stock", "full", "no_floor"]
    vals = []
    for v in vs:
        g = scen("D", v)
        vals.append(g[g.phase == "heartbeat"].cwnd.iloc[-1])
    ax.bar(range(3), vals, color=[C[v] for v in vs])
    for i, val in enumerate(vals):
        ax.text(i, val * 1.15, f"{val:,} B", ha="center", fontsize=7.5)
    ax.set_yscale("log")
    ax.set_ylim(300, 80000)
    ax.axhline(SMSS, color="0.3", ls=":", lw=0.9)
    ax.text(2.45, SMSS * 1.08, "1 packet", fontsize=7, ha="right", color="0.3")
    ax.set_xticks(range(3), ["Stock", "Patched", "Patch w/o\nfloor"], fontsize=7.5)
    ax.set_ylabel("cwnd during heartbeats (bytes)")
    ax.set_title("(a) heartbeat phase", loc="left")
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    for v in ["stock", "full", "ssthresh_lower", "no_floor"]:
        g = scen("D", v)
        rs = g[g.phase == "resume"]
        ax.plot(rs["round"] + 1, rs.pk_flight, marker="o", ms=3, color=C[v], label=LBL[v],
                lw=1.6 if v in ("stock", "full") else 1.1)
    ax.set_xlabel("RTT after the app starts a bulk transfer")
    ax.set_ylabel("packets sent in that RTT")
    ax.set_xlim(0.5, 15.5)
    ax.set_xticks(range(1, 16, 2))
    ax.set_title("(b) the app starts a bulk transfer", loc="left")
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, -0.08))
    fig.subplots_adjust(bottom=0.3, wspace=0.35)
    save(fig, "scenario_d")


# ---------------------------------------------------------------- network data
def parse_out(path):
    txt = open(path).read()
    g = lambda p: int(re.search(p, txt).group(1))
    return {"final": g(r"FINAL abs_us=(\d+)"), "cycle1": g(r"cycle=1 abs_us=(\d+)\s+BURST START"),
            "done": g(r"abs_us=(\d+)\s+TRANSFER COMPLETE")}


def load_trace(tag):
    d = pd.read_csv(f"{RES}/{tag}_client.csv", header=None,
                    names=["ev", "t", "cwnd", "maxfs", "inflight", "ss", "bytes"])
    return d


def load_ping(tag):
    off = float(open(f"{RES}/{tag}_clock_offset.txt").read())
    rows = []
    for line in open(f"{RES}/{tag}_ping.txt"):
        m = re.match(r"\[(\d+\.\d+)\].*icmp_seq=(\d+).*time=([\d.]+) ms", line)
        if m:
            rows.append(((float(m.group(1)) - off) * 1e6, float(m.group(3))))
    return pd.DataFrame(rows, columns=["t", "rtt"])


def fig_net_timeline():
    fig, axes = plt.subplots(2, 1, figsize=(W, 5.0), sharex=True)
    for ax, (v, tag) in zip(axes, [("stock", "before_rep1"), ("full", "after_rep1")]):
        ph = parse_out(f"{RES}/{tag}_client.out")
        d = load_trace(tag)
        d["s"] = (d.t - ph["final"]) / 1e6
        d = d[(d.s >= -16.5) & (d.s <= 6.9)]
        d["bin"] = np.floor(d.s * 10) / 10
        a = d[d.ev == "A"].groupby("bin")[["cwnd", "maxfs"]].last()
        f = d[d.ev == "S"].groupby("bin").inflight.max()
        ax.fill_between(f.index, 0, f / 1e3, step="post", color=C["flight"], alpha=0.8, lw=0,
                        label="bytes in flight (max per 100 ms)")
        ax.plot(a.index, a.cwnd / 1e3, color=C[v], label="cwnd")
        ax.plot(a.index, a.maxfs / 1e3, color="k", ls="--", lw=1.0, label="maxFS")
        ax.axvline(0, color="k", lw=0.8, ls=":")
        ax.axvspan((ph["cycle1"] - ph["final"]) / 1e6 + 5, 0, color="#f4ecd8", lw=0, zorder=0)
        ax.set_title(f"{LBL[v]} (run 1 of 5)", loc="left")
        ax.set_ylabel("KB")
        ax.set_ylim(0, 900)
    for ax in axes:
        ax.text(-5.6, 560, "app-limited: 6000 B every 10 ms", fontsize=7.5, ha="center", color="0.25")
    h, l = axes[0].get_legend_handles_labels()
    h2, _ = axes[1].get_legend_handles_labels()
    h = [h[0], h[1], h2[1], h[2]]
    l = [l[0], "cwnd (stock)", "cwnd (patched)", "maxFS"]
    fig.legend(h, l, loc="lower center", ncol=4, frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, 0.0))
    fig.subplots_adjust(bottom=0.15, hspace=0.3)
    axes[1].set_xlabel("time relative to resumption (s); the app has 8 MB to send at 0")
    axes[1].set_xlim(-16.3, 6.9)
    save(fig, "net_timeline")


def fig_net_ping():
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.6), gridspec_kw={"width_ratios": [1.5, 1]})
    ax = axes[0]
    for v, tag in [("stock", "before_rep1"), ("full", "after_rep1")]:
        ph = parse_out(f"{RES}/{tag}_client.out")
        p = load_ping(tag)
        p["s"] = (p.t - ph["final"]) / 1e6
        w = p[(p.s >= -0.5) & (p.s <= 3)]
        ax.plot(w.s, w.rtt, color=C[v], lw=1.0, label=LBL[v])
    ax.axhline(43, color="0.3", ls=":", lw=0.9)
    ax.text(2.95, 47, "base RTT 43 ms", fontsize=7, ha="right", color="0.3")
    ax.axvline(0, color="k", lw=0.8, ls=":")
    ax.set_xlabel("time relative to resumption (s)")
    ax.set_ylabel("competing ping RTT (ms)")
    ax.set_title("(a) run 1 of each build", loc="left")
    ax.set_ylim(0, 400)
    ax.legend(loc="upper right", frameon=False)
    ax = axes[1]
    for v, pre in [("stock", "before"), ("full", "after")]:
        vals = []
        for tag in sorted(os.path.basename(x)[:-11] for x in glob.glob(f"{RES}/{pre}_rep*_client.out")):
            ph = parse_out(f"{RES}/{tag}_client.out")
            p = load_ping(tag)
            p["s"] = (p.t - ph["final"]) / 1e6
            vals.append(p[(p.s >= 0) & (p.s <= 3)].rtt.values)
        x = np.sort(np.concatenate(vals))
        ax.plot(x, np.arange(1, len(x) + 1) / len(x), color=C[v], label=LBL[v])
    ax.set_xlabel("ping RTT in first 3 s after resuming (ms)")
    ax.set_ylabel("CDF (5 runs pooled)")
    ax.set_title("(b) all runs", loc="left")
    ax.set_xlim(0, 400)
    save(fig, "net_ping")


def fig_net_metrics():
    r = pd.read_csv(f"{RES}/analysis/runs.csv")
    panels = [("cwnd_at_resume_kb", "cwnd at resumption (KB)"),
              ("burst_peak_inflight_kb", "peak flight, first 0.5 s (KB)"),
              ("lost_kb_after_resume", "data lost after resuming (KB)"),
              ("ping_max_ms_after_resume", "max competing RTT (ms)")]
    fig, axes = plt.subplots(2, 2, figsize=(W * 0.85, 4.0))
    for ax, (col, title) in zip(axes.flat, panels):
        for i, (v, pre) in enumerate([("stock", "before"), ("full", "after")]):
            vals = r[r.variant == pre][col].values
            ax.bar(i, vals.mean(), color=C[v], alpha=0.35, width=0.6)
            ax.scatter(np.full(len(vals), i) + np.linspace(-0.12, 0.12, len(vals)), vals,
                       color=C[v], s=12, zorder=3)
            ax.text(i + 0.33, vals.mean(), f"mean {vals.mean():.0f}", ha="left", va="center",
                    fontsize=7.5, fontweight="bold")
        ax.set_xticks([0, 1], ["Stock", "Patched"], fontsize=8)
        ax.set_xlim(-0.5, 2.25)
        ax.set_title(title, fontsize=8.5, loc="left")
        ax.grid(axis="x", visible=False)
        ax.set_ylim(0, max(r[col]) * 1.18)
    fig.subplots_adjust(hspace=0.45, wspace=0.35)
    save(fig, "net_metrics")


if __name__ == "__main__":
    fig_scenario_a()
    fig_scenario_b()
    fig_scenario_c()
    fig_scenario_d()
    fig_net_timeline()
    fig_net_ping()
    fig_net_metrics()
    print(sorted(os.listdir(OUT)))
