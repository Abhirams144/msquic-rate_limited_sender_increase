import argparse
import pandas as pd
import matplotlib.pyplot as plt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("output_png")
    parser.add_argument("title", nargs="?", default="Rate-Limited CUBIC (Unpatched)")
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv, header=None, names=["time_us", "cwnd_bytes"])
    df = df.sort_values("time_us").reset_index(drop=True)

    t0 = df["time_us"].iloc[0]
    df["time_s"] = (df["time_us"] - t0) / 1_000_000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0

    # Calculate gap between consecutive ACK log rows
    df["gap_s"] = df["time_s"].diff()

    # The rate-limited pause is the largest gap where no ACKs were logged
    max_gap_idx = df["gap_s"].idxmax()
    pause_start_s = df.loc[max_gap_idx - 1, "time_s"]
    pause_end_s = df.loc[max_gap_idx, "time_s"]

    plt.figure(figsize=(11, 5))
    plt.plot(df["time_s"], df["cwnd_kb"], linewidth=1.2, color="#1f77b4", zorder=3)

    plt.axvspan(pause_start_s, pause_end_s, color="orange", alpha=0.2, zorder=1,
                label="App-limited pause (true idle)")
    plt.axvline(pause_start_s, color="darkorange", linestyle="--", linewidth=1, zorder=2)
    plt.axvline(pause_end_s, color="darkorange", linestyle="--", linewidth=1, zorder=2)

    plt.xlabel("Time (s)")
    plt.ylabel("cwnd (KB)")
    plt.title(args.title)
    plt.legend(loc="upper left")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.output_png, dpi=150)
    print(f"Detected pause window: {pause_start_s:.3f}s to {pause_end_s:.3f}s")
    print(f"Saved plot to {args.output_png}")

if __name__ == "__main__":
    main()
