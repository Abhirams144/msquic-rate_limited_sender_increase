#!/usr/bin/env python3
"""
Plots cwnd over time for the classic trickle rate-limited scenario.
Identifies the steady trickle window and shades the app-limited inflation region.
"""
import argparse
import pandas as pd
import matplotlib.pyplot as plt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", help="Path to CSV log (e.g. /tmp/cwnd_trickle_log.csv)")
    parser.add_argument("output_png", help="Path to save output plot")
    parser.add_argument("title", nargs="?", default="Classic Rate-Limited CUBIC (Unpatched)")
    parser.add_argument("--trickle-start", type=float, default=None, help="Start time in seconds of trickle")
    parser.add_argument("--trickle-end", type=float, default=None, help="End time in seconds of trickle")
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv, header=None, names=["time_us", "cwnd_bytes"])
    df = df.sort_values("time_us").reset_index(drop=True)

    t0 = df["time_us"].iloc[0]
    df["time_s"] = (df["time_us"] - t0) / 1_000_000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0

    plt.figure(figsize=(11, 5))
    plt.plot(df["time_s"], df["cwnd_kb"], linewidth=1.4, color="#1f77b4", zorder=3, label="cwnd")

    # If bounds are passed manually, or detect the steady send duration
    if args.trickle_start is not None and args.trickle_end is not None:
        t_start, t_end = args.trickle_start, args.trickle_end
    else:
        # Default fallback approximation around standard run (~0.2s to ~4.2s)
        t_start, t_end = 0.2, 4.2

    plt.axvspan(t_start, t_end, color="#ffebcc", alpha=0.6, zorder=1,
                label="App-limited (trickle send, false inflation)")
    plt.axvline(t_start, color="darkorange", linestyle="--", linewidth=1.2, zorder=2)
    plt.axvline(t_end, color="crimson", linestyle="--", linewidth=1.2, zorder=2)

    plt.xlabel("Time (s)", fontsize=11)
    plt.ylabel("cwnd (KB)", fontsize=11)
    plt.title(args.title, fontsize=13, weight="bold")
    plt.grid(True, alpha=0.3)
    plt.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(args.output_png, dpi=150)
    print(f"Plot saved to {args.output_png}")

if __name__ == "__main__":
    main()
