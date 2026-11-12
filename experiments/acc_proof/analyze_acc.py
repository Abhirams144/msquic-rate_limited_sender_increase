#!/usr/bin/env python3
"""
Direct network evidence for the AIMD-accumulator underflow.

Input: experiments/results_v4_acc/<point>/{accstock,accstockfix}_rep<n>_client.{csv,out}
       produced by `sudo experiments/run_campaign.sh acc`. The two builds differ
       only in the two AIMD lines (acc_proof/S0_vs_S1.diff); their trace has two
       extra columns, AimdWindow and AimdAccumulator.

A wrapped accumulator is recognised without any model: AimdAccumulator only
ever holds acknowledged bytes (at most a few MB here), so a value >= 2^31 can
only come from the uint32 subtraction wrapping below zero.

Outputs: acc_proof/acc_runs.csv (one row per run), acc_proof/acc_summary.csv,
         report/figures/acc_network.{pdf,png}
"""
import glob
import os
import re

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "experiments", "results_v4_acc")
FIG = os.path.join(ROOT, "report", "figures")
COLS = ["ev", "t_us", "cwnd", "maxfs", "inflight", "ssthresh", "bytes", "aimd", "acc"]
WRAP = 2 ** 31
SMSS = 1472
INF = 4294967295
LBL = {"accstock": "stock (upstream code)", "accstockfix": "stock + 2-line fix"}
C = {"accstock": "#c0392b", "accstockfix": "#1f5fa8"}


def load(point, tag):
    tr = pd.read_csv(os.path.join(RES, point, f"{tag}_client.csv"), names=COLS)
    out = open(os.path.join(RES, point, f"{tag}_client.out")).read()
    fin = int(re.search(r"FINAL abs_us=(\d+)", out).group(1))
    tr["s"] = (tr.t_us - fin) / 1e6
    return tr, fin


def run_row(point, tag):
    tr, fin = load(point, tag)
    a = tr[tr.ev == "A"].copy()
    ca = a[(a.ssthresh != INF) & (a.cwnd >= a.ssthresh)]
    a = a.reset_index(drop=True)
    wrapped = a.acc >= WRAP
    # a "wrap event" = an ACK after which the accumulator is wrapped but was not before
    wrap_events = int((wrapped & ~wrapped.shift(fill_value=False)).sum())
    # same definition as analyze_v3.smss_per_ack_share; the testbed's QUIC
    # datagram payload (MSS) is 1472 bytes
    d = a.cwnd.diff()
    ca_up = (a.cwnd.shift() >= a.ssthresh) & (d > 0)
    full_pkt = ((d == SMSS) & ca_up).sum()
    grow = ca_up.sum()
    after = tr[tr.t_us >= fin]
    return {
        "point": point, "variant": tag.split("_rep")[0], "rep": int(tag.split("_rep")[1]),
        "acks": len(a), "ca_acks": len(ca),
        "wrap_events": wrap_events,
        "acks_with_wrapped_acc": int(wrapped.sum()),
        "max_acc": int(a.acc.max()),
        "ca_full_pkt_increase_share": full_pkt / grow if grow else np.nan,
        "cwnd_at_resume_kb": tr[tr.t_us < fin].cwnd.iloc[-1] / 1000,
        "lost_kb_after_resume": after[after.ev == "L"].bytes.sum() / 1000,
    }


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(RES, "*", "*_client.csv"))):
        point = os.path.basename(os.path.dirname(f))
        tag = os.path.basename(f)[: -len("_client.csv")]
        try:
            rows.append(run_row(point, tag))
        except Exception as e:  # incomplete run
            print("skip", f, e)
    runs = pd.DataFrame(rows)
    runs.to_csv(os.path.join(HERE, "acc_runs.csv"), index=False)
    summ = runs.groupby(["point", "variant"]).agg(
        runs=("rep", "count"),
        runs_with_wrap=("wrap_events", lambda x: int((x > 0).sum())),
        wrap_events_median=("wrap_events", "median"),
        wrapped_acks_median=("acks_with_wrapped_acc", "median"),
        full_pkt_share_median=("ca_full_pkt_increase_share", "median"),
        cwnd_at_resume_kb=("cwnd_at_resume_kb", "median"),
        lost_kb_after_resume=("lost_kb_after_resume", "median"),
    ).round(3)
    summ.to_csv(os.path.join(HERE, "acc_summary.csv"))
    print(summ.to_string())

    # figure: one representative run per build and setting (the run whose
    # number of wrap events is closest to the build's median)
    points = [p for p in ("dur_10s", "compete") if p in set(runs.point)]
    titles = {"dur_10s": "6 s rate-limited, 10 Mbit/s", "compete": "25 Mbit/s + competing TCP flow"}
    fig, ax = plt.subplots(2, len(points), figsize=(7.2, 4.6), sharex="col", squeeze=False)
    for j, point in enumerate(points):
        for v in ("accstock", "accstockfix"):
            r = runs[(runs.point == point) & (runs.variant == v)]
            rep = int(r.iloc[(r.wrap_events - r.wrap_events.median()).abs().argsort().iloc[0]].rep)
            tr, _ = load(point, f"{v}_rep{rep}")
            a = tr[(tr.ev == "A") & (tr.s > -2) & (tr.s < 6)]
            ax[0, j].plot(a.s, a.acc.clip(lower=1), color=C[v], lw=1.0, ls="-" if v == "accstockfix" else "-",
                          label=f"{LBL[v]}", zorder=3 if v == "accstockfix" else 2)
            ax[1, j].plot(a.s, a.cwnd / 1000, color=C[v], lw=1.4, ls="-" if v == "accstockfix" else "--",
                          label=f"{LBL[v]}")
        ax[0, j].axhline(2 ** 32, color="#666666", lw=0.8, ls=":")
        ax[0, j].text(-1.9, 2 ** 32 * 2.5, r"$2^{32}$: values above $2^{31}$ can only be wrapped", fontsize=6.5, color="#444444")
        ax[0, j].set_yscale("log")
        ax[0, j].set_ylim(1, 2 ** 32 * 40)
        ax[0, j].set_title(titles.get(point, point), loc="left", fontsize=8.5)
        ax[1, j].set_xlabel("time relative to resumption (s)")
        ax[1, j].set_ylim(bottom=0)
    ax[0, 0].set_ylabel("AimdAccumulator (bytes)")
    ax[1, 0].set_ylabel("cwnd (KB)")
    for a_ in ax.flat:
        a_.grid(True, color="#e6e6e6", lw=0.6)
        a_.spines[["top", "right"]].set_visible(False)
        a_.tick_params(labelsize=7)
    h, l = ax[1, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(FIG, "acc_network.pdf"))
    fig.savefig(os.path.join(FIG, "acc_network.png"), dpi=140)
    print("wrote", os.path.join(FIG, "acc_network.pdf"))


if __name__ == "__main__":
    main()
