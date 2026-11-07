#!/usr/bin/env python3
"""
Analyses the sweep campaign produced by run_campaign.sh.

Input:  experiments/results_v2/<point>/{point.txt, <variant>_rep<n>_*}
Output: experiments/results_v2/analysis/{runs.csv, stats.csv}
        report/figures/sweep.{pdf,png}, report/figures/compete.{pdf,png}
        report/tables/campaign_*.tex   (numbers for the report, generated)

Per-run metrics come from analyze_rls.analyse_run (same definitions as the
first experiment), plus completion times of the resumed transfer and, for the
"compete" point, the throughput and retransmissions of the competing TCP flow.

Statistics per point and metric: median and IQR per build; the difference of
medians (patched - stock) with a 95 % bootstrap CI; a two-sided permutation
test on the difference of means. No SciPy needed.

Usage: python3 analyze_campaign.py [results_v2_dir]
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_rls import analyse_run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "experiments", "results_v2")
FIG = os.path.join(ROOT, "report", "figures")
TAB = os.path.join(ROOT, "report", "tables")
OUT = os.path.join(RES, "analysis")
for d in (FIG, TAB, OUT):
    os.makedirs(d, exist_ok=True)

RNG = np.random.default_rng(1)
C = {"before": "#c0392b", "after": "#1f5fa8"}
LBL = {"before": "Stock MsQuic", "after": "Patched (final)"}


# ------------------------------------------------------------------ per run
def completion_times(tr, t_res):
    """Seconds after resumption until 1 MB and 8 MB of new data are acked."""
    a = tr[(tr.t_us >= t_res) & (tr.ev == "A")]
    cum = a.bytes.cumsum()
    out = {}
    for lab, nbytes in (("fct_1mb_s", 1e6), ("fct_2mb_s", 2e6)):
        hit = a[cum >= nbytes]
        out[lab] = (hit.t_us.iloc[0] - t_res) / 1e6 if len(hit) else np.nan
    return out


def parse_iperf(path, start_wall, offset_s):
    """iperf3 interval lines -> DataFrame(t_us monotonic at interval start, bytes, retr, cwnd_kb).
    Idle intervals ("0.00 Bytes  0.00 bits/sec") are kept: dropping them would
    inflate any average. Bytes are counted when written to the socket, in
    chunks of 128 KB, so goodput is only meaningful over windows of >= 0.5 s."""
    unit = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    pat = re.compile(r"\]\s+([\d.]+)-([\d.]+)\s+sec\s+([\d.]+)\s+([KMG]?)Bytes\s+[\d.]+\s+[KMG]?bits/sec"
                     r"\s+(\d+)\s+([\d.]+)\s+([KMG]?)Bytes")
    rows = []
    for line in open(path):
        m = pat.search(line)
        if not m:
            continue
        a, b, nb, nu, retr, cw, cu = m.groups()
        if float(b) - float(a) > 0.5:      # summary lines
            continue
        rows.append({"t_us": int((start_wall + float(a) - offset_s) * 1e6),
                     "bytes": float(nb) * unit[nu], "retr": int(retr),
                     "cwnd_kb": float(cw) * unit[cu] / 1000})
    return pd.DataFrame(rows)


def tcp_mbps(tcp, lo, hi):
    w = tcp[(tcp.s >= lo) & (tcp.s < hi)]
    return w.bytes.sum() * 8 / (hi - lo) / 1e6 if len(w) else np.nan


def run_metrics(point_dir, tag):
    row, tr, ping, phases = analyse_run(point_dir, tag)
    t_res = phases["final_us"]
    row.update(completion_times(tr, t_res))
    # Time the sender was really rate-limited: from its last cwnd-limited
    # send (flight >= 90 % of cwnd) to resumption. The app starts pacing
    # earlier, but the 3 MB prime takes ~5 s to drain at 10 Mbit/s.
    sends = tr[(tr.ev == "S") & (tr.t_us < t_res)]
    busy = sends[sends.inflight >= 0.9 * sends.cwnd]
    row["ratelimited_s"] = (t_res - busy.t_us.iloc[-1]) / 1e6 if len(busy) else np.nan
    row["app_paced_s"] = (t_res - phases["cycle1_us"]) / 1e6 if phases["cycle1_us"] else np.nan
    row["min_rtt_ms"] = row.get("stat_min_rtt_us", np.nan) / 1000
    ip = os.path.join(point_dir, f"{tag}_iperf.txt")
    tcp = None
    if os.path.exists(ip):
        start = float(open(os.path.join(point_dir, f"{tag}_iperf_start.txt")).read())
        off = float(open(os.path.join(point_dir, f"{tag}_clock_offset.txt")).read())
        tcp = parse_iperf(ip, start, off)
        if len(tcp):
            tcp["s"] = (tcp.t_us - t_res) / 1e6
            row["tcp_mbps_before"] = tcp_mbps(tcp, -3, 0)
            row["tcp_mbps_after2s"] = tcp_mbps(tcp, 0, 2)
            row["tcp_min_mbps_after2s"] = min(tcp_mbps(tcp, x, x + 0.5) for x in (0, 0.5, 1.0, 1.5))
            row["tcp_retr_after3s"] = tcp[(tcp.s >= 0) & (tcp.s < 3)].retr.sum()
            row["tcp_cwnd_before_kb"] = tcp[(tcp.s >= -3) & (tcp.s < 0)].cwnd_kb.median()
            row["tcp_cwnd_min_after3s_kb"] = tcp[(tcp.s >= 0) & (tcp.s < 3)].cwnd_kb.min()
    return row, tr, ping, phases, tcp


# ------------------------------------------------------------------ stats
def boot_ci_median_diff(a, b, n=10000):
    ia = RNG.integers(0, len(a), (n, len(a)))
    ib = RNG.integers(0, len(b), (n, len(b)))
    d = np.median(b[ib], axis=1) - np.median(a[ia], axis=1)
    return np.percentile(d, [2.5, 97.5])


def perm_p(a, b, n=20000):
    obs = abs(b.mean() - a.mean())
    pool = np.concatenate([a, b])
    cnt = 0
    for _ in range(n):
        RNG.shuffle(pool)
        if abs(pool[len(a):].mean() - pool[:len(a)].mean()) >= obs - 1e-12:
            cnt += 1
    return (cnt + 1) / (n + 1)


METRICS = {
    "cwnd_at_resume_kb": "cwnd at resumption (KB)",
    "burst_peak_inflight_kb": "peak flight, first 0.5 s (KB)",
    "lost_kb_after_resume": "data lost after resuming (KB)",
    "loss_events_after_resume": "loss events after resuming",
    "ping_max_ms_after_resume": "max competing RTT (ms)",
    "ping_p95_ms_after_resume": "p95 competing RTT (ms)",
    "fct_1mb_s": "first 1 MB delivered (s)",
    "resume_8mb_s": "8 MB transfer time (s)",
    "tcp_mbps_after2s": "TCP goodput, first 2 s (Mbit/s)",
    "tcp_min_mbps_after2s": "TCP worst 0.5 s goodput (Mbit/s)",
    "tcp_cwnd_min_after3s_kb": "TCP cwnd minimum, first 3 s (KB)",
    "tcp_retr_after3s": "TCP retransmissions, first 3 s",
}


def main():
    rows, examples = [], {}
    for pdir in sorted(glob.glob(os.path.join(RES, "*"))):
        if not os.path.exists(os.path.join(pdir, "point.txt")):
            continue
        point = os.path.basename(pdir)
        cfg = dict(kv.split("=") for kv in open(os.path.join(pdir, "point.txt")).read().split())
        tags = sorted({os.path.basename(p)[:-len("_client.csv")] for p in glob.glob(os.path.join(pdir, "*_client.csv"))})
        for tag in tags:
            if "TRANSFER COMPLETE" not in open(os.path.join(pdir, f"{tag}_client.out")).read():
                print(f"skip {point}/{tag}: incomplete")
                continue
            try:
                row, tr, ping, phases, tcp = run_metrics(pdir, tag)
            except Exception as e:
                print(f"skip {point}/{tag}: {e}")
                continue
            row.update(point=point, **cfg)
            rows.append(row)
            if tcp is not None:
                examples.setdefault(point, []).append((row["variant"], tcp))
    if not rows:
        sys.exit(f"no runs in {RES}")
    runs = pd.DataFrame(rows)
    runs["bw_mbit"] = runs.bw.str.replace("mbit", "").astype(float)
    runs["delay_ms"] = runs.delay.str.replace("ms", "").astype(float)
    runs.to_csv(os.path.join(OUT, "runs.csv"), index=False)

    # ---------- statistics ----------
    st = []
    for point, g in runs.groupby("point"):
        for m in METRICS:
            if m not in g or g[m].isna().all():
                continue
            a = g[g.variant == "before"][m].dropna().values
            b = g[g.variant == "after"][m].dropna().values
            if len(a) < 2 or len(b) < 2:
                continue
            lo, hi = boot_ci_median_diff(a, b)
            st.append(dict(point=point, metric=m, n_stock=len(a), n_patched=len(b),
                           stock_median=np.median(a), stock_q1=np.percentile(a, 25), stock_q3=np.percentile(a, 75),
                           patched_median=np.median(b), patched_q1=np.percentile(b, 25), patched_q3=np.percentile(b, 75),
                           diff_median=np.median(b) - np.median(a), ci_lo=lo, ci_hi=hi, p_perm=perm_p(a, b)))
    stats = pd.DataFrame(st)
    stats.to_csv(os.path.join(OUT, "stats.csv"), index=False)
    pd.set_option("display.width", 220)
    print(stats[["point", "metric", "n_stock", "stock_median", "patched_median", "diff_median", "ci_lo", "ci_hi", "p_perm"]]
          .to_string(index=False, float_format=lambda x: f"{x:.3g}"))

    # ---------- figures ----------
    plt.rcParams.update({"font.family": "serif", "font.size": 8.5, "axes.titlesize": 9,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 8})
    W = 6.3
    base = runs[runs.point == "dur_10s"]
    sweeps = []
    d = runs[runs.point.str.startswith("dur_")]
    if d.point.nunique() > 1:
        sweeps.append(("time really rate-limited (s)", d, "ratelimited_s", None))
    r = pd.concat([runs[runs.point.str.startswith("rtt_")], base])
    if r.point.nunique() > 1:
        sweeps.append(("base RTT (ms)", r, "min_rtt_ms", None))
    bw = pd.concat([runs[runs.point.str.startswith("bw_")], base])
    if bw.point.nunique() > 1:
        sweeps.append(("bottleneck (Mbit/s)", bw, "bw_mbit", None))
    cols = ["cwnd_at_resume_kb", "lost_kb_after_resume", "ping_max_ms_after_resume", "resume_8mb_s"]
    if sweeps:
        fig, axes = plt.subplots(len(sweeps), len(cols), figsize=(W, 1.75 * len(sweeps) + 0.6), squeeze=False)
        for i, (xlab, df, xcol, _) in enumerate(sweeps):
            for j, m in enumerate(cols):
                ax = axes[i, j]
                xpt = df.groupby("point")[xcol].median()   # one x per point, shared by both builds
                for v in ("before", "after"):
                    g = df[df.variant == v].groupby("point")
                    x = xpt.loc[g[m].median().index]
                    med, q1, q3 = g[m].median(), g[m].quantile(0.25), g[m].quantile(0.75)
                    o = np.argsort(x.values)
                    xs, ms, l, h = x.values[o], med.values[o], q1.values[o], q3.values[o]
                    ax.plot(xs, ms, "o-", color=C[v], ms=3.5, lw=1.4, label=LBL[v])
                    ax.fill_between(xs, l, h, color=C[v], alpha=0.18, lw=0)
                ax.set_ylim(bottom=0)
                if i == 0:
                    ax.set_title(METRICS[m], fontsize=8)
                ax.set_xlabel(xlab, fontsize=7)
                ax.ticklabel_format(axis="x", useOffset=False, style="plain")
                ax.tick_params(labelsize=7)
        h, l = axes[0, 0].get_legend_handles_labels()
        fig.legend(h, l, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.0))
        fig.tight_layout(rect=(0, 0.07, 1, 1))
        fig.savefig(os.path.join(FIG, "sweep.pdf"))
        fig.savefig(os.path.join(FIG, "sweep.png"), dpi=130)
        plt.close(fig)

    if "compete" in examples:
        fig, axes = plt.subplots(1, 3, figsize=(W, 2.4), gridspec_kw={"width_ratios": [2.2, 1, 1]})
        ax = axes[0]
        for v in ("before", "after"):
            series = []
            for vv, tcp in examples["compete"]:
                if vv != v:
                    continue
                s = tcp[(tcp.s >= -3) & (tcp.s < 6)].copy()
                s["bin"] = np.floor(s.s / 0.5) * 0.5
                series.append(s.groupby("bin").bytes.sum() * 8 / 0.5 / 1e6)
            if series:
                M = pd.concat(series, axis=1)
                ax.step(M.index, M.median(axis=1), where="post", color=C[v], lw=1.3, label=LBL[v])
                ax.fill_between(M.index, M.quantile(0.25, axis=1), M.quantile(0.75, axis=1), step="post", color=C[v], alpha=0.18, lw=0)
        ax.axvline(0, color="k", ls=":", lw=0.8)
        ax.set_xlabel("time relative to resumption (s)")
        ax.set_ylabel("competing TCP rate, 0.5 s bins (Mbit/s)")
        ax.set_title("(a) median and IQR over runs", loc="left")
        ax.set_ylim(bottom=0)
        ax.legend(loc="lower right", frameon=False)
        cg = runs[runs.point == "compete"]
        for ax, m, t in ((axes[1], "tcp_min_mbps_after2s", "(b) worst 0.5 s of\nTCP rate (Mbit/s)"),
                         (axes[2], "tcp_cwnd_min_after3s_kb", "(c) TCP cwnd minimum\nin first 3 s (KB)")):
            for k, v in enumerate(("before", "after")):
                vals = cg[cg.variant == v][m].dropna().values
                ax.boxplot(vals, positions=[k], widths=0.5, showfliers=False,
                           medianprops=dict(color=C[v], lw=1.5))
                ax.scatter(k + RNG.uniform(-0.12, 0.12, len(vals)), vals, color=C[v], s=9, zorder=3)
            ax.set_xticks([0, 1], ["Stock", "Patched"])
            ax.set_title(t, loc="left", fontsize=8)
            ax.set_ylim(bottom=0)
            ax.grid(axis="x", visible=False)
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "compete.pdf"))
        fig.savefig(os.path.join(FIG, "compete.png"), dpi=130)
        plt.close(fig)

    # ---------- LaTeX table: every point, key metrics ----------
    def fmt(x):
        return "---" if pd.isna(x) else (f"{x:.0f}" if abs(x) >= 10 else f"{x:.2g}" if abs(x) < 1 else f"{x:.1f}")

    def pfmt(p):
        return r"$<$0.001" if p < 0.001 else f"{p:.3f}"
    order = ["dur_2s", "dur_5s", "dur_10s", "dur_20s", "dur_30s", "rtt_10", "rtt_20", "rtt_80", "bw_25", "bw_50", "compete"]
    key = ["cwnd_at_resume_kb", "lost_kb_after_resume", "ping_max_ms_after_resume", "resume_8mb_s"]
    lines = []
    for pt in [p for p in order if p in set(stats.point)] + sorted(set(stats.point) - set(order)):
        g = runs[runs.point == pt]
        rl = g.ratelimited_s.median()
        rl_txt = f"{rl:.1f}" if rl < 10 else f"{rl:.0f}"
        desc = (f"{g.bw.iloc[0].replace('mbit', ' Mbit/s')}, RTT {g.min_rtt_ms.median():.0f} ms, {rl_txt} s"
                + (", +TCP" if pt == "compete" else ""))
        cells = [pt.replace("_", r"\_"), desc]
        for m in key:
            s = stats[(stats.point == pt) & (stats.metric == m)]
            if len(s):
                s = s.iloc[0]
                star = r"$^{*}$" if s.p_perm < 0.01 else ""
                cells.append(f"{fmt(s.stock_median)} / \\textbf{{{fmt(s.patched_median)}}}{star}")
            else:
                cells.append("---")
        n = int(stats[stats.point == pt].n_stock.min())
        cells.append(str(n))
        lines.append(" & ".join(cells) + r" \\")
    open(os.path.join(TAB, "campaign_rows.tex"), "w").write("\n".join(lines) + "\n")
    print(f"wrote {OUT}, {FIG}/sweep.*, {TAB}/campaign_rows.tex")


if __name__ == "__main__":
    main()
