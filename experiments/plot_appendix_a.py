#!/usr/bin/env python3
import sys
import pandas as pd
import matplotlib.pyplot as plt

def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cwnd_log.csv"
    output_png = sys.argv[2] if len(sys.argv) > 2 else "appendix_a_cwnd.png"

    # Read CSV (time_us, cwnd_bytes)
    df = pd.read_csv(csv_path, header=None, names=["time_us", "cwnd_bytes"])
    df = df.sort_values("time_us").reset_index(drop=True)

    # Normalize to relative milliseconds and packets (~1200 bytes per MSS)
    t0 = df["time_us"].iloc[0]
    df["time_ms"] = (df["time_us"] - t0) / 1000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0
    df["cwnd_pkts"] = df["cwnd_bytes"] / 1200.0

    # -------------------------------------------------------------
    # FILTER: Remove transient idle drops back to the 10 MSS floor
    # Keeps the active window envelope evaluated across each round
    # -------------------------------------------------------------
    floor_bytes = 10 * 1200 * 1.05  # slightly above 10 MSS (~12.6 KB)
    df_filtered = df[df["cwnd_bytes"] > floor_bytes].copy().reset_index(drop=True)

    # Fallback in case every point was at or below the floor
    plot_df = df_filtered if not df_filtered.empty else df

    fig, ax1 = plt.subplots(figsize=(10, 5))

    # Plot cwnd line using the active window points
    ax1.plot(plot_df["time_ms"], plot_df["cwnd_kb"], marker="o", markersize=4, 
             linewidth=1.8, color="#1f77b4", label="cwnd (KB)")
    ax1.set_xlabel("Elapsed Time (ms)", fontsize=11)
    ax1.set_ylabel("cwnd (KB)", fontsize=11, color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.grid(True, linestyle="--", alpha=0.4)

    # Add secondary y-axis to see the equivalent packet count (MSS)
    ax2 = ax1.twinx()
    ax2.set_ylabel("Approx. cwnd (Packets @ 1200B MSS)", fontsize=11, color="#555555")
    ax2.set_ylim(plot_df["cwnd_pkts"].min() * 0.8, plot_df["cwnd_pkts"].max() * 1.1)

    # Highlight the RTT boundaries (~41ms intervals)
    for round_idx in range(1, 7):
        round_t = (round_idx - 1) * 41
        ax1.axvline(round_t, color="gray", linestyle=":", alpha=0.6)
        ax1.text(round_t + 2, plot_df["cwnd_kb"].max() * 0.9, f"R{round_idx}", 
                 fontsize=9, color="gray", weight="bold")

    plt.title("Appendix A: Rate-Limited Sender Step Evaluation", fontsize=13, weight="bold")
    plt.tight_layout()
    plt.savefig(output_png, dpi=150)
    print(f"Plot successfully saved to {output_png}")

if __name__ == "__main__":
    main()
