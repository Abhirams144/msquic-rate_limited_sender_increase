#!/usr/bin/env python3
"""
Analyses the before/after runs produced by run_rls_experiments.sh.

Inputs per run TAG (= <variant>_rep<n>) in experiments/results/:
  TAG_client.csv   cwnd trace: event,time_us,cwnd,maxFS,inflight,ssthresh,bytes
                   (event S = sent, A = ack, L = loss; time = CLOCK_MONOTONIC us)
  TAG_client.out   sender stdout: phase timestamps ([demo] ... abs_us=) + [stats]
  TAG_ping.txt     ping -D output of the competing flow (wall-clock timestamps)
  TAG_clock_offset.txt   wall clock minus monotonic clock, seconds
  TAG_drops.txt    packets dropped at the forward bottleneck queue during the run

Outputs (experiments/results/analysis/):
  runs.csv         one row of metrics per run
  summary.csv      mean / min / max per variant and metric
  timeline_<variant>.csv   100 ms bins of one representative run, time 0 = resume
  ping_<variant>.csv       competing-flow RTT samples of that run, time 0 = resume
  fig_*.png        matplotlib figures for the report / repo

Usage: python3 analyze_rls.py [results_dir] [--rep N]
"""
import argparse
import glob
import os
import re
import statistics as st

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SMSS = 1232
STEADY_WINDOW_S = 8.0     # last N seconds of the rate-limited phase used for steady-state stats
BURST_WINDOW_S = 0.5      # window after resumption in which the initial burst is measured
PING_WINDOW_S = 3.0       # window after resumption for competing-flow delay


def parse_out(path):
    txt = open(path).read()
    def grab(pattern):
        m = re.search(pattern, txt)
        return int(m.group(1)) if m else None
    phases = {
        "prime_us": grab(r"PRIME abs_us=(\d+)"),
        "cycle1_us": grab(r"cycle=1 abs_us=(\d+)\s+BURST START"),
        "final_us": grab(r"FINAL abs_us=(\d+)"),
        "done_us": grab(r"abs_us=(\d+)\s+TRANSFER COMPLETE"),
    }
    m = re.search(r"\[stats\] sent_pkts=(\d+) lost_pkts=(\d+) spurious_lost=(\d+) "
                  r"congestion_events=(\d+) sent_bytes=(\d+) min_rtt_us=(\d+) max_rtt_us=(\d+)", txt)
    stats = {}
    if m:
        keys = ["sent_pkts", "lost_pkts", "spurious_lost", "congestion_events",
                "sent_bytes", "min_rtt_us", "max_rtt_us"]
        stats = {k: int(v) for k, v in zip(keys, m.groups())}
    return phases, stats


def load_trace(path):
    df = pd.read_csv(path, header=None,
                     names=["ev", "t_us", "cwnd", "maxfs", "inflight", "ssthresh", "bytes"])
    return df.sort_values("t_us", kind="stable").reset_index(drop=True)


def load_ping(path, offset_s):
    rows = []
    for line in open(path):
        m = re.match(r"\[(\d+\.\d+)\].*icmp_seq=(\d+).*time=([\d.]+) ms", line)
        if m:
            wall, seq, rtt = float(m.group(1)), int(m.group(2)), float(m.group(3))
            rows.append({"t_us": int((wall - offset_s) * 1e6), "seq": seq, "rtt_ms": rtt})
    return pd.DataFrame(rows)


def analyse_run(res, tag):
    phases, stats = parse_out(os.path.join(res, f"{tag}_client.out"))
    tr = load_trace(os.path.join(res, f"{tag}_client.csv"))
    offset = float(open(os.path.join(res, f"{tag}_clock_offset.txt")).read().strip())
    ping = load_ping(os.path.join(res, f"{tag}_ping.txt"), offset)
    drops = int(open(os.path.join(res, f"{tag}_drops.txt")).read().split("=")[1])

    t_res = phases["final_us"]
    pre = tr[tr.t_us < t_res]
    steady = pre[pre.t_us >= t_res - STEADY_WINDOW_S * 1e6]
    acks_pre = pre[pre.ev == "A"]
    last = acks_pre.iloc[-1] if len(acks_pre) else pre.iloc[-1]

    sends_steady = steady[steady.ev == "S"]
    burst = tr[(tr.t_us >= t_res) & (tr.t_us < t_res + BURST_WINDOW_S * 1e6) & (tr.ev == "S")]
    post_loss = tr[(tr.t_us >= t_res) & (tr.ev == "L")]
    pre_loss = tr[(tr.t_us < t_res) & (tr.ev == "L")]

    base = ping[(ping.t_us >= t_res - STEADY_WINDOW_S * 1e6) & (ping.t_us < t_res)]
    pwin = ping[(ping.t_us >= t_res) & (ping.t_us < t_res + PING_WINDOW_S * 1e6)]
    # ping probes sent during the window that never got a reply (dropped at the bottleneck)
    if len(ping) >= 2:
        seq_rate = (ping.seq.iloc[-1] - ping.seq.iloc[0]) / max(1, (ping.t_us.iloc[-1] - ping.t_us.iloc[0]))
    else:
        seq_rate = 0
    expected = int(round(PING_WINDOW_S * 1e6 * seq_rate))
    ping_lost = max(0, expected - len(pwin))

    resume_s = (phases["done_us"] - t_res) / 1e6 if phases["done_us"] else float("nan")
    row = {
        "tag": tag,
        "variant": tag.split("_")[0],
        "rep": int(tag.split("rep")[1]),
        "cwnd_at_resume_kb": last.cwnd / 1000,
        "maxfs_at_resume_kb": last.maxfs / 1000,
        "steady_mean_inflight_kb": sends_steady.inflight.mean() / 1000 if len(sends_steady) else float("nan"),
        "cwnd_over_flight": last.cwnd / sends_steady.inflight.mean() if len(sends_steady) else float("nan"),
        "burst_peak_inflight_kb": burst.inflight.max() / 1000 if len(burst) else float("nan"),
        "lost_kb_after_resume": post_loss.bytes.sum() / 1000,
        "loss_events_after_resume": len(post_loss),
        "lost_kb_before_resume": pre_loss.bytes.sum() / 1000,
        "ping_base_ms": base.rtt_ms.median() if len(base) else float("nan"),
        "ping_max_ms_after_resume": pwin.rtt_ms.max() if len(pwin) else float("nan"),
        "ping_p95_ms_after_resume": pwin.rtt_ms.quantile(0.95) if len(pwin) else float("nan"),
        "ping_lost_after_resume": ping_lost,
        "bottleneck_drops": drops,
        "resume_8mb_s": resume_s,
        "resume_goodput_mbps": 8e6 * 8 / resume_s / 1e6 if resume_s == resume_s else float("nan"),
    }
    row.update({f"stat_{k}": v for k, v in stats.items()})
    return row, tr, ping, phases


def binned_timeline(tr, ping, phases, bin_ms=100):
    t0 = phases["final_us"]
    df = tr.copy()
    df["t_s"] = (df.t_us - t0) / 1e6
    df["bin"] = (df.t_s * 1000 // bin_ms) * bin_ms / 1000
    acks = df[df.ev == "A"].groupby("bin").last()[["cwnd", "maxfs", "ssthresh"]]
    sends = df[df.ev == "S"].groupby("bin").inflight.max().rename("inflight_max")
    loss = df[df.ev == "L"].groupby("bin").bytes.sum().rename("lost_bytes")
    out = pd.concat([acks, sends, loss], axis=1).sort_index()
    out[["cwnd", "maxfs", "ssthresh"]] = out[["cwnd", "maxfs", "ssthresh"]].ffill()
    out["inflight_max"] = out["inflight_max"].fillna(0)
    out["lost_bytes"] = out["lost_bytes"].fillna(0)
    out.index.name = "t_s"
    p = ping.copy()
    p["t_s"] = (p.t_us - t0) / 1e6
    phase_s = {k: (v - t0) / 1e6 for k, v in phases.items() if v}
    return out.reset_index(), p[["t_s", "seq", "rtt_ms"]], phase_s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
    ap.add_argument("--rep", type=int, default=1, help="representative repetition for timelines")
    args = ap.parse_args()
    res = args.results
    out_dir = os.path.join(res, "analysis")
    os.makedirs(out_dir, exist_ok=True)

    tags = sorted({os.path.basename(p)[:-len("_client.csv")] for p in glob.glob(os.path.join(res, "*_client.csv"))})
    rows, keep = [], {}
    for tag in tags:
        try:
            row, tr, ping, phases = analyse_run(res, tag)
        except Exception as e:  # incomplete run
            print(f"skip {tag}: {e}")
            continue
        rows.append(row)
        if row["rep"] == args.rep:
            keep[row["variant"]] = (tr, ping, phases)
    runs = pd.DataFrame(rows).sort_values(["variant", "rep"])
    runs.to_csv(os.path.join(out_dir, "runs.csv"), index=False)

    metrics = [c for c in runs.columns if c not in ("tag", "variant", "rep")]
    summ = runs.groupby("variant")[metrics].agg(["mean", "min", "max"])
    summ.to_csv(os.path.join(out_dir, "summary.csv"))
    pd.set_option("display.width", 200)
    print(runs[["tag"] + metrics[:12]].to_string(index=False))
    print()
    print(runs.groupby("variant")[metrics].mean().T.to_string())

    tl = {}
    for v, (tr, ping, phases) in keep.items():
        t, p, ph = binned_timeline(tr, ping, phases)
        t.to_csv(os.path.join(out_dir, f"timeline_{v}.csv"), index=False)
        p.to_csv(os.path.join(out_dir, f"ping_{v}.csv"), index=False)
        tl[v] = (t, p, ph)
        print(f"{v}: phases (s rel. resume) {ph}")

    # ---- figures ----
    colors = {"before": "#c0392b", "after": "#1f5fa8"}
    if len(tl) == 2:
        fig, axes = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True)
        for ax, v in zip(axes, ["before", "after"]):
            t, p, ph = tl[v]
            ax.plot(t.t_s, t.cwnd / 1000, color=colors[v], lw=1.6, label="cwnd")
            ax.plot(t.t_s, t.maxfs / 1000, color="0.35", lw=1.0, ls="--", label="maxFS")
            ax.fill_between(t.t_s, 0, t.inflight_max / 1000, color="0.75", step="post", label="bytes in flight (max per 100 ms)")
            ax.axvline(0, color="k", ls=":", lw=1)
            if "cycle1_us" in ph:
                ax.axvspan(ph["cycle1_us"], 0, color="#f5e6c8", alpha=0.5, zorder=0, label="app-limited phase")
            ax.set_ylabel("KB")
            ax.set_title(f"{v.capitalize()} patch", loc="left")
            ax.grid(alpha=0.3)
            ax.legend(loc="upper left", fontsize=8)
        axes[-1].set_xlabel("time relative to resumption (s)")
        fig.suptitle("cwnd vs. what the sender actually put in flight")
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, "fig_timeline.png"), dpi=150)

        fig, ax = plt.subplots(figsize=(11, 4.5))
        for v in ["before", "after"]:
            t, p, ph = tl[v]
            w = p[(p.t_s >= -2) & (p.t_s <= 6)]
            ax.plot(w.t_s, w.rtt_ms, color=colors[v], lw=1.0, label=f"{v} patch")
        ax.axvline(0, color="k", ls=":", lw=1)
        ax.set_xlabel("time relative to resumption (s)")
        ax.set_ylabel("ping RTT of competing flow (ms)")
        ax.set_title("Queueing delay inflicted on other traffic when the sender resumes")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, "fig_ping.png"), dpi=150)

    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6))
    for ax, (col, lab) in zip(axes, [("cwnd_at_resume_kb", "cwnd at resumption (KB)"),
                                     ("burst_peak_inflight_kb", "peak flight in first 0.5 s (KB)"),
                                     ("lost_kb_after_resume", "bytes lost after resumption (KB)"),
                                     ("ping_max_ms_after_resume", "max competing RTT (ms)")]):
        for i, v in enumerate(["before", "after"]):
            vals = runs[runs.variant == v][col]
            ax.bar(i, vals.mean(), color=colors[v], alpha=0.8)
            ax.scatter([i] * len(vals), vals, color="k", s=10, zorder=3)
        ax.set_xticks([0, 1], ["before", "after"])
        ax.set_title(lab, fontsize=9)
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig_metrics.png"), dpi=150)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
