#!/usr/bin/env python3
"""
Does the AIMD-accumulator bug matter for plain bulk transfers?

Input: experiments/results_v5_bulk/<point>/{accstock,accstockfix}_rep<n>_*
       produced by `sudo experiments/run_campaign.sh bulk`: one bulk transfer
       per run, no rate-limited phase, same two builds as the `acc` run
       (differ only in the two AIMD lines; trace logs AimdWindow and
       AimdAccumulator).

Outputs: acc_proof/bulk_runs.csv, acc_proof/bulk_summary.csv,
         report/figures/bulk_network.{pdf,png}
"""
import glob
import os
import re
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "experiments"))
import analyze_campaign as AC  # noqa: E402  (parse_iperf, perm_p)

RES = os.path.join(ROOT, "experiments", "results_v5_bulk")
FIG = os.path.join(ROOT, "report", "figures")
COLS = ["ev", "t_us", "cwnd", "maxfs", "inflight", "ssthresh", "bytes", "aimd", "acc"]
WRAP = 2 ** 31
SMSS = 1472
LBL = {"accstock": "stock (upstream code)", "accstockfix": "stock + 2-line fix"}
C = {"accstock": "#c0392b", "accstockfix": "#1f5fa8"}
POINTS = ["bulk_10", "bulk_rtt80", "bulk_50", "bulk_compete"]
TITLE = {"bulk_10": "10 Mbit/s, 40 ms, 30 MB", "bulk_rtt80": "10 Mbit/s, 80 ms, 30 MB",
         "bulk_50": "50 Mbit/s, 40 ms, 100 MB", "bulk_compete": "25 Mbit/s + TCP, 60 MB"}


def load(pdir, tag):
    tr = pd.read_csv(os.path.join(pdir, f"{tag}_client.csv"), names=COLS)
    out = open(os.path.join(pdir, f"{tag}_client.out")).read()
    m = re.search(r"FINAL abs_us=(\d+)\s+RESUME BURST START \((\d+) bytes\)", out)
    t0, nbytes = int(m.group(1)), int(m.group(2))
    t1 = int(re.search(r"abs_us=(\d+)\s+TRANSFER COMPLETE", out).group(1))
    st = dict((k, int(v)) for k, v in re.findall(r"(\w+)=(\d+)", re.search(r"\[stats\].*", out).group(0)))
    tr["s"] = (tr.t_us - t0) / 1e6
    return tr, t0, t1, st, nbytes


PERSIST = 100    # ACKs; "persistent" wrap
HUGE = 10 ** 8   # bytes; more than any transfer here, so only reachable by wrapping


def longest_run(mask):
    best = cur = 0
    for x in mask:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def ping_rtts(path):
    return np.array([float(x) for x in re.findall(r"time=([\d.]+) ms", open(path).read())])


def run_row(pdir, point, tag):
    tr, t0, t1, st, nbytes = load(pdir, tag)
    a = tr[tr.ev == "A"].reset_index(drop=True)
    wrapped = a.acc >= WRAP
    d = a.cwnd.diff()
    ca_up = (a.cwnd.shift() >= a.ssthresh) & (d > 0)
    grow = ca_up.sum()
    in_ca = a[a.cwnd >= a.ssthresh]
    dur = (t1 - t0) / 1e6
    row = {
        "point": point, "variant": tag.split("_rep")[0], "rep": int(tag.split("_rep")[1]),
        "acks": len(a),
        "wrap_events": int((wrapped & ~wrapped.shift(fill_value=False)).sum()),
        "wrapped_ack_share": wrapped.mean(),
        "max_acc": int(a.acc.max()),
        # a wrap that the next ACK does not undo keeps AimdAccumulator above the
        # size of the whole transfer; count the longest such stretch of ACKs
        "longest_wrap_acks": longest_run(a.acc.values > HUGE),
        "wrapped_ack_share_long": float((a.acc > HUGE).mean()),
        "full_pkt_share": ((d == SMSS) & ca_up).sum() / grow if grow else np.nan,
        "completion_s": dur,
        # application bytes delivered (retransmissions excluded) per second
        "goodput_mbps": nbytes * 8 / dur / 1e6,
        "lost_pkts": st["lost_pkts"],
        "loss_pct": 100 * st["lost_pkts"] / st["sent_pkts"],
        "congestion_events": st["congestion_events"],
        "cwnd_ca_median_kb": in_ca.cwnd.median() / 1000,
        "bottleneck_drops": int(open(os.path.join(pdir, f"{tag}_drops.txt")).read().split("=")[1]),
    }
    p = ping_rtts(os.path.join(pdir, f"{tag}_ping.txt"))
    row["ping_median_ms"] = np.median(p) if len(p) else np.nan
    row["ping_p95_ms"] = np.percentile(p, 95) if len(p) else np.nan
    ip = os.path.join(pdir, f"{tag}_iperf.txt")
    if os.path.exists(ip):
        start = float(open(os.path.join(pdir, f"{tag}_iperf_start.txt")).read())
        off = float(open(os.path.join(pdir, f"{tag}_clock_offset.txt")).read())
        tcp = AC.parse_iperf(ip, start, off)
        w = tcp[(tcp.t_us >= t0) & (tcp.t_us < t1)]
        row["tcp_mbps"] = w.bytes.sum() * 8 / (len(w) * 0.1) / 1e6 if len(w) else np.nan
        row["tcp_retr"] = w.retr.sum()
    return row, tr


METRICS = ["longest_wrap_acks", "wrapped_ack_share_long", "wrap_events", "wrapped_ack_share", "full_pkt_share", "completion_s", "goodput_mbps",
           "lost_pkts", "loss_pct", "congestion_events", "cwnd_ca_median_kb", "bottleneck_drops",
           "ping_median_ms", "ping_p95_ms", "tcp_mbps", "tcp_retr"]


def main():
    rows, traces = [], {}
    for f in sorted(glob.glob(os.path.join(RES, "*", "*_client.csv"))):
        pdir = os.path.dirname(f)
        point = os.path.basename(pdir)
        tag = os.path.basename(f)[: -len("_client.csv")]
        r, tr = run_row(pdir, point, tag)
        rows.append(r)
        traces[(point, tag)] = tr
    runs = pd.DataFrame(rows)
    runs.to_csv(os.path.join(HERE, "bulk_runs.csv"), index=False)

    out = []
    for point in POINTS:
        s = runs[(runs.point == point) & (runs.variant == "accstock")]
        x = runs[(runs.point == point) & (runs.variant == "accstockfix")]
        for m in METRICS:
            if m not in runs or s[m].isna().all():
                continue
            out.append({"point": point, "metric": m, "stock": s[m].median(), "fix": x[m].median(),
                        "runs_wrap_stock": int((s.wrap_events > 0).sum()),
                        "runs_wrap_fix": int((x.wrap_events > 0).sum()),
                        "runs_persist_stock": int((s.longest_wrap_acks > PERSIST).sum()),
                        "runs_persist_fix": int((x.longest_wrap_acks > PERSIST).sum()),
                        "p": AC.perm_p(s[m].dropna().values, x[m].dropna().values)})
    summ = pd.DataFrame(out)
    summ.to_csv(os.path.join(HERE, "bulk_summary.csv"), index=False)
    pd.set_option("display.width", 200)
    print(summ.round(4).to_string(index=False))
    print("max acc fix:", runs[runs.variant == "accstockfix"].groupby("point").max_acc.max().to_dict())

    # per-run table for the report: persistent-wrap runs vs the rest
    runs["group"] = np.where(runs.variant == "accstockfix", "fix",
                             np.where(runs.longest_wrap_acks > PERSIST, "stock_persistent", "stock_undone"))
    grp = runs.groupby(["point", "group"]).agg(
        n=("rep", "count"), lost_min=("lost_pkts", "min"), lost_med=("lost_pkts", "median"),
        lost_max=("lost_pkts", "max"), drops_med=("bottleneck_drops", "median"),
        completion_med=("completion_s", "median"), goodput_med=("goodput_mbps", "median"),
        tcp_med=("tcp_mbps", "median"), cwnd_med=("cwnd_ca_median_kb", "median"),
        longest_min=("longest_wrap_acks", "min"), longest_max=("longest_wrap_acks", "max"))
    grp.to_csv(os.path.join(HERE, "bulk_groups.csv"))
    print(grp.round(2).to_string())
    print("fix: max longest_wrap_acks", runs[runs.variant == "accstockfix"].longest_wrap_acks.max())

    fig, ax = plt.subplots(1, 3, figsize=(7.4, 2.9), gridspec_kw={"width_ratios": [1.25, 1.2, 0.85]})
    # (a) lost packets per run
    a_ = ax[0]
    for k, point in enumerate(POINTS):
        for j, v in enumerate(("accstock", "accstockfix")):
            r = runs[(runs.point == point) & (runs.variant == v)]
            x = k + (-0.17 if j == 0 else 0.17) + np.linspace(-0.07, 0.07, len(r))
            pers = (r.longest_wrap_acks > PERSIST).values
            a_.scatter(x[~pers], r.lost_pkts.values[~pers], s=12, facecolors="none", edgecolors=C[v], lw=0.9)
            a_.scatter(x[pers], r.lost_pkts.values[pers], s=14, color=C[v], marker="D")
    a_.set_yscale("log")
    a_.set_xticks(range(len(POINTS)))
    a_.set_xticklabels(["10 Mb/s\n40 ms", "10 Mb/s\n80 ms", "50 Mb/s\n40 ms", "25 Mb/s\n+ TCP"], fontsize=6.5)
    a_.set_ylabel("lost packets per run", fontsize=8)
    a_.set_title("(a) every run", loc="left", fontsize=8.5)
    # (b) cwnd: a persistent-wrap run vs the fixed build, 50 Mbit/s
    a_ = ax[1]
    point = "bulk_50"
    r = runs[(runs.point == point) & (runs.variant == "accstock")]
    rep_s = int(r.loc[r.longest_wrap_acks.idxmax()].rep)
    r = runs[(runs.point == point) & (runs.variant == "accstockfix")]
    rep_f = int(r.iloc[(r.lost_pkts - r.lost_pkts.median()).abs().argsort().iloc[0]].rep)
    for v, rep in (("accstock", rep_s), ("accstockfix", rep_f)):
        t = traces[(point, f"{v}_rep{rep}")]
        t = t[t.ev == "A"]
        a_.plot(t.s, t.cwnd / 1000, color=C[v], lw=0.8, ls="--" if v == "accstock" else "-")
    a_.set_xlabel("time (s)", fontsize=8)
    a_.set_ylabel("cwnd (KB)", fontsize=8)
    a_.set_ylim(bottom=0)
    a_.set_title("(b) 50 Mb/s, stock run with wrap", loc="left", fontsize=8.5)
    # (c) competing flows: QUIC and TCP goodput per run
    a_ = ax[2]
    rc = runs[runs.point == "bulk_compete"]
    for j, v in enumerate(("accstock", "accstockfix")):
        r = rc[rc.variant == v]
        pers = (r.longest_wrap_acks > PERSIST).values
        for col, xo in (("goodput_mbps", 0), ("tcp_mbps", 1)):
            x = xo + (-0.15 if j == 0 else 0.15) + np.linspace(-0.06, 0.06, len(r))
            a_.scatter(x[~pers], r[col].values[~pers], s=12, facecolors="none", edgecolors=C[v], lw=0.9)
            a_.scatter(x[pers], r[col].values[pers], s=14, color=C[v], marker="D")
    a_.axhline(12.5, color="#888888", lw=0.7, ls=":")
    a_.set_xticks([0, 1])
    a_.set_xticklabels(["QUIC", "TCP"], fontsize=7)
    a_.set_ylabel("goodput (Mbit/s)", fontsize=8)
    a_.set_title("(c) 25 Mb/s shared", loc="left", fontsize=8.5)
    for a_ in ax:
        a_.grid(True, color="#e6e6e6", lw=0.6)
        a_.spines[["top", "right"]].set_visible(False)
        a_.tick_params(labelsize=7)
    from matplotlib.lines import Line2D
    h = [Line2D([], [], color=C["accstock"], ls="--", lw=1.2), Line2D([], [], color=C["accstockfix"], lw=1.2),
         Line2D([], [], color="#555555", marker="D", ls="none", ms=4),
         Line2D([], [], color="#555555", marker="o", mfc="none", ls="none", ms=4)]
    l = [LBL["accstock"], LBL["accstockfix"], "wrap persisted (> 100 ACKs)", "no persistent wrap"]
    fig.legend(h, l, loc="lower center", ncol=4, frameon=False, fontsize=7)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(os.path.join(FIG, "bulk_network.pdf"))
    fig.savefig(os.path.join(FIG, "bulk_network.png"), dpi=140)
    print("wrote", os.path.join(FIG, "bulk_network.pdf"), "stock rep", rep_s, "fix rep", rep_f)


if __name__ == "__main__":
    main()
