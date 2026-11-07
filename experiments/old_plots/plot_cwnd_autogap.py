#!/usr/bin/env python3
"""
Plots cwnd (and BytesInFlightMax, if present) from a cwnd log, shading the
genuine idle windows.

Idle windows are found from gaps in the LOGGED TIMESTAMPS THEMSELVES: cwnd is
only logged when a real ACK arrives, so a true app-limited pause shows up as
an absence of rows -- not merely as a flat or small value, which can also
happen while data is still slowly draining under congestion.

Log format (from the cubic.c patch): time_us,cwnd_bytes[,bytes_in_flight_max]

Usage:
    python3 plot_cwnd_autogap.py /tmp/cwnd_client.csv out.png "Title" --min-gap-ms 200
"""
import argparse
import pandas as pd
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv")
    ap.add_argument("output_png")
    ap.add_argument("title", nargs="?", default="CUBIC Congestion Window over Time")
    ap.add_argument("--min-gap-ms", type=float, default=200,
                    help="Minimum silence (ms) between rows to count as a real idle window")
    args = ap.parse_args()

    # Accept both 2-column and 3-column logs.
    raw = pd.read_csv(args.input_csv, header=None)
    if raw.shape[1] >= 3:
        raw = raw.iloc[:, :3]
        raw.columns = ["time_us", "cwnd_bytes", "maxfs_bytes"]
        has_maxfs = True
    else:
        raw = raw.iloc[:, :2]
        raw.columns = ["time_us", "cwnd_bytes"]
        has_maxfs = False

    df = raw.sort_values("time_us").reset_index(drop=True)
    t0 = df["time_us"].iloc[0]
    df["time_s"] = (df["time_us"] - t0) / 1_000_000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0
    if has_maxfs:
        df["maxfs_kb"] = df["maxfs_bytes"] / 1024.0

    print(f"Loaded {len(df)} rows spanning {df['time_s'].iloc[-1]:.2f}s")
    print(f"cwnd range: {df['cwnd_bytes'].min()} - {df['cwnd_bytes'].max()} bytes")

    if has_maxfs:
        # The draft's rule: in congestion avoidance cwnd should not exceed
        # maxFS + 1. msquic instead caps at 2 * maxFS. Report the ratio so
        # it is obvious which limit is actually binding.
        nz = df[df["maxfs_bytes"] > 0].copy()
        if not nz.empty:
            nz["ratio"] = nz["cwnd_bytes"] / nz["maxfs_bytes"]
            print(f"cwnd/maxFS ratio: min={nz['ratio'].min():.2f} "
                  f"max={nz['ratio'].max():.2f} mean={nz['ratio'].mean():.2f}")
            pinned = (nz["ratio"] > 1.98).mean() * 100
            print(f"rows sitting at ~2x maxFS (the msquic cap): {pinned:.1f}%")

    # Find idle windows: consecutive rows separated by >= min_gap_ms.
    df["gap_ms"] = df["time_us"].diff() / 1000.0
    gaps = df[df["gap_ms"] >= args.min_gap_ms]
    windows = []
    print(f"\nFound {len(gaps)} idle window(s) >= {args.min_gap_ms}ms:")
    for idx, row in gaps.iterrows():
        start_s = df["time_s"].iloc[idx - 1]
        end_s = row["time_s"]
        before = df["cwnd_bytes"].iloc[idx - 1]
        after = row["cwnd_bytes"]
        windows.append((start_s, end_s))
        verdict = "cwnd unchanged" if before == after else f"cwnd {before} -> {after}"
        print(f"  {start_s:7.3f}s -> {end_s:7.3f}s  ({row['gap_ms']:6.0f}ms silent)  {verdict}")

    plt.figure(figsize=(11, 5))
    for i, (s, e) in enumerate(windows):
        plt.axvspan(s, e, color="orange", alpha=0.18, zorder=1,
                    label="App-limited pause (no ACKs)" if i == 0 else None)

    plt.plot(df["time_s"], df["cwnd_kb"], linewidth=1.3, color="#1f77b4",
             zorder=3, label="cwnd")
    if has_maxfs:
        plt.plot(df["time_s"], df["maxfs_kb"], linewidth=1.3, color="#d62728",
                 linestyle="--", zorder=3, label="BytesInFlightMax (maxFS)")

    plt.xlabel("Time (s)")
    plt.ylabel("bytes (KB)")
    plt.title(args.title)
    plt.grid(True, alpha=0.3)
    plt.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(args.output_png, dpi=150)
    print(f"\nSaved plot to {args.output_png}")


if __name__ == "__main__":
    main()
