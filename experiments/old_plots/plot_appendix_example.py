#!/usr/bin/env python3
"""
Plots the literal Section 3.1 worked example from
draft-ietf-ccwg-ratelimited-increase (initcwnd=10 segments, send 10, pause,
send 4 more) as actually run on msquic, using the -prime:12000 -burst:4800
-pause:300 -cycles:1 quicsample invocation.

Marks the resumption point (from the [demo] cycle=1 BURST START abs_us) and
draws the draft's two reference outcomes as horizontal lines:
  - "unconstrained" (buggy) prediction: cwnd would reach 24 segments
  - "constrained" (correct) prediction: cwnd capped at 20 segments
so the actual measured curve can be read directly against both.

Usage:
    python3 plot_appendix_example.py /tmp/cwnd_client.csv appendix_example.png \
        --resume-abs-us 1622083087 --seg-bytes 1200
"""
import argparse
import pandas as pd
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv")
    ap.add_argument("output_png")
    ap.add_argument("--resume-abs-us", type=int, required=True,
                     help="abs_us from the [demo] cycle=1 BURST START line (start of the 2nd burst)")
    ap.add_argument("--seg-bytes", type=float, default=1200,
                     help="Assumed segment/MSS size in bytes, for the segment-count axis (default 1200)")
    ap.add_argument("--title", default="Section 3.1 Worked Example on msquic (10 then 4 segments)")
    args = ap.parse_args()

    df = pd.read_csv(args.input_csv, header=None, names=["time_us", "cwnd_bytes", "maxfs_bytes", "phase"])
    df = df.sort_values("time_us").reset_index(drop=True)

    t0 = df["time_us"].iloc[0]
    df["time_ms"] = (df["time_us"] - t0) / 1000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0
    df["maxfs_kb"] = df["maxfs_bytes"] / 1024.0
    resume_ms = (args.resume_abs_us - t0) / 1000.0

    print(f"Loaded {len(df)} rows spanning {df['time_ms'].iloc[-1]:.1f}ms")
    print(f"Resumption (burst 2 start) at {resume_ms:.1f}ms")

    before = df[df["time_us"] < args.resume_abs_us]
    after = df[df["time_us"] >= args.resume_abs_us]
    cwnd_before = before["cwnd_bytes"].iloc[-1] if not before.empty else None
    cwnd_after_final = after["cwnd_bytes"].iloc[-1] if not after.empty else None
    print(f"cwnd just before resumption: {cwnd_before} bytes")
    print(f"cwnd at end of run (after resumption): {cwnd_after_final} bytes")
    if cwnd_before is not None and cwnd_after_final is not None:
        if cwnd_after_final <= cwnd_before + 1:
            print("=> cwnd did NOT grow further after resumption: matches the draft's CONSTRAINED (correct) prediction.")
        else:
            print("=> cwnd grew further after resumption: matches the draft's UNCONSTRAINED (buggy) prediction.")

    seg = args.seg_bytes
    unconstrained_kb = (24 * seg) / 1024.0
    constrained_kb = (20 * seg) / 1024.0

    fig, ax1 = plt.subplots(figsize=(9, 5.5))

    ax1.step(df["time_ms"], df["cwnd_kb"], where="post", linewidth=2, color="#1f77b4",
              marker="o", markersize=4, label="cwnd (measured)", zorder=4)
    ax1.step(df["time_ms"], df["maxfs_kb"], where="post", linewidth=1.3, color="#d62728",
              linestyle="--", marker=".", markersize=4, label="BytesInFlightMax (maxFS)", zorder=3)

    ax1.axhline(unconstrained_kb, color="grey", linestyle=":", linewidth=1.2,
                label=f"Draft \"unconstrained\" prediction (24 seg = {unconstrained_kb:.1f} KB)")
    ax1.axhline(constrained_kb, color="green", linestyle=":", linewidth=1.2,
                label=f"Draft \"constrained\" prediction (20 seg = {constrained_kb:.1f} KB)")

    ax1.axvline(resume_ms, color="black", linestyle="-", linewidth=1, alpha=0.6, zorder=1)
    ax1.text(resume_ms, ax1.get_ylim()[1] if False else max(df["cwnd_kb"].max(), unconstrained_kb) * 1.02,
              "  resume (send 4 more segments)", rotation=0, fontsize=8, va="bottom")

    ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("bytes (KB)")
    ax1.set_title(args.title)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.output_png, dpi=150)
    print(f"\nSaved plot to {args.output_png}")


if __name__ == "__main__":
    main()
