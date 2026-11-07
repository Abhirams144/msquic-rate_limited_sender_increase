#!/usr/bin/env python3
"""
Overlays a pre-patch ("before") and post-patch ("after") cwnd trace,
time-aligned at the resumption point (end of the app-limited pause), so the
difference in post-resumption behavior is directly comparable on one axis.

Usage:
    python3 plot_resumption_bomb.py before.csv after.csv out.png \
        --resume-before-us <abs_us> --resume-after-us <abs_us> \
        --window-s 8
"""
import argparse
import pandas as pd
import matplotlib.pyplot as plt


def load(path):
    raw = pd.read_csv(path, header=None)
    raw = raw.iloc[:, :2]
    raw.columns = ["time_us", "cwnd_bytes"]
    return raw.sort_values("time_us").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before_csv")
    ap.add_argument("after_csv")
    ap.add_argument("output_png")
    ap.add_argument("--resume-before-us", type=int, required=True,
                     help="abs_us of resumption (burst start) in the BEFORE run")
    ap.add_argument("--resume-after-us", type=int, required=True,
                     help="abs_us of resumption (burst start) in the AFTER run")
    ap.add_argument("--window-s", type=float, default=10,
                     help="Seconds of data to show before/after the resumption point")
    ap.add_argument("--title", default="Resumption After an App-Limited Pause: Before vs. After the Fix")
    args = ap.parse_args()

    before = load(args.before_csv)
    after = load(args.after_csv)

    before["t_rel_s"] = (before["time_us"] - args.resume_before_us) / 1_000_000.0
    after["t_rel_s"] = (after["time_us"] - args.resume_after_us) / 1_000_000.0

    before = before[(before["t_rel_s"] >= -1) & (before["t_rel_s"] <= args.window_s)]
    after = after[(after["t_rel_s"] >= -1) & (after["t_rel_s"] <= args.window_s)]

    before["cwnd_kb"] = before["cwnd_bytes"] / 1024.0
    after["cwnd_kb"] = after["cwnd_bytes"] / 1024.0

    def stats(label, df):
        if df.empty:
            print(f"{label}: no rows in window")
            return
        post = df[df["t_rel_s"] >= 0]
        if post.empty:
            print(f"{label}: no post-resumption rows")
            return
        print(f"{label}: cwnd after resumption ranges {post['cwnd_kb'].min():.1f} - {post['cwnd_kb'].max():.1f} KB "
              f"(swing {post['cwnd_kb'].max() - post['cwnd_kb'].min():.1f} KB), "
              f"{len(post)} rows")

    stats("BEFORE (pre-patch)", before)
    stats("AFTER (patched)", after)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(before["t_rel_s"], before["cwnd_kb"], color="#d62728", linewidth=1.3,
            label="Before patch (unpatched cubic.c)", zorder=3)
    ax.plot(after["t_rel_s"], after["cwnd_kb"], color="#1f77b4", linewidth=1.3,
            label="After patch (Gap 1 + Gap 2 fixed)", zorder=4)
    ax.axvline(0, color="black", linestyle=":", linewidth=1, alpha=0.6)
    ax.text(0, ax.get_ylim()[1], "  resume", fontsize=8, va="top")

    ax.set_xlabel("Time since resumption (s)")
    ax.set_ylabel("cwnd (KB)")
    ax.set_title(args.title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(args.output_png, dpi=150)
    print(f"\nSaved plot to {args.output_png}")


if __name__ == "__main__":
    main()
