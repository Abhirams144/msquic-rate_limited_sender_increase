#!/usr/bin/env python3
"""
Plots congestion window (cwnd) over time from a cwnd_log.csv produced by the
temporary logging patch in src/core/cubic.c.

Usage:
    python3 plot_cwnd.py /tmp/cwnd_log.csv baseline_cwnd.png "Baseline CUBIC (no rate limiting)"
"""
import sys
import pandas as pd
import matplotlib.pyplot as plt

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 plot_cwnd.py <input_csv> <output_png> [title]")
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else "CUBIC Congestion Window over Time"

    df = pd.read_csv(in_path, header=None, names=["time_us", "cwnd_bytes"])

    # Drop any duplicate-timestamp noise and sort chronologically, just in case.
    df = df.sort_values("time_us").reset_index(drop=True)

    # Normalize time to start at 0, convert to seconds for readability.
    t0 = df["time_us"].iloc[0]
    df["time_s"] = (df["time_us"] - t0) / 1_000_000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0

    print(f"Loaded {len(df)} data points spanning {df['time_s'].iloc[-1]:.2f} seconds")
    print(f"cwnd range: {df['cwnd_bytes'].min()} to {df['cwnd_bytes'].max()} bytes")

    plt.figure(figsize=(11, 5))
    plt.plot(df["time_s"], df["cwnd_kb"], linewidth=1.2, color="#1f77b4")
    plt.xlabel("Time (s)")
    plt.ylabel("cwnd (KB)")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")

if __name__ == "__main__":
    main()
