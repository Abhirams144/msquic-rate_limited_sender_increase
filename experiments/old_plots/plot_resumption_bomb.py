#!/usr/bin/env python3
import sys
import pandas as pd
import matplotlib.pyplot as plt

def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cwnd_log.csv"
    output_png = sys.argv[2] if len(sys.argv) > 2 else "resumption_bomb.png"
    is_after = "after" in output_png.lower() or (len(sys.argv) > 3 and "after" in sys.argv[3].lower())

    df = pd.read_csv(csv_path, header=None, names=["time_us", "cwnd_bytes", "maxfs_bytes", "state"])
    df["time_us"] = pd.to_numeric(df["time_us"], errors='coerce')
    df["cwnd_bytes"] = pd.to_numeric(df["cwnd_bytes"], errors='coerce')
    df["maxfs_bytes"] = pd.to_numeric(df["maxfs_bytes"], errors='coerce')
    df = df.dropna(subset=["time_us", "cwnd_bytes", "maxfs_bytes"])
    df = df.sort_values("time_us").reset_index(drop=True)

    t0 = df["time_us"].iloc[0]
    df["time_s"] = (df["time_us"] - t0) / 1_000_000.0
    df["cwnd_kb"] = df["cwnd_bytes"] / 1024.0
    df["maxfs_kb"] = df["maxfs_bytes"] / 1024.0

    # Compute ceiling lines
    df["draft_cap_kb"] = df["maxfs_kb"] + (1200.0 / 1024.0)
    if is_after:
        df["msquic_cap_kb"] = df["draft_cap_kb"]  # Patched MsQuic matches the draft
    else:
        df["msquic_cap_kb"] = df["maxfs_kb"] * 2.0  # Unpatched loose 2x cap

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.step(df["time_s"], df["cwnd_kb"], where="post",
            linewidth=2, color="#1f77b4", label="Measured cwnd")

    if is_after:
        ax.plot(df["time_s"], df["msquic_cap_kb"],
                linewidth=3.5, color="#d62728", alpha=0.4, label="msquic's patched cap")
        ax.plot(df["time_s"], df["draft_cap_kb"],
                linestyle="--", color="#2ca02c", linewidth=1.5, label="Draft's required cap (maxFS + 1 MSS)")
    else:
        ax.plot(df["time_s"], df["msquic_cap_kb"],
                linestyle="--", color="#d62728", label="msquic's actual cap (2 x maxFS)")
        ax.plot(df["time_s"], df["draft_cap_kb"],
                linestyle="--", color="#2ca02c", linewidth=2.0, label="Draft's required cap (maxFS + 1 MSS)")

    # Locate the resumption point by finding the long pause in time
    time_gaps = df["time_s"].diff()
    max_gap = time_gaps.max()

    if max_gap > 3.0:
        resumption_idx = time_gaps.idxmax()
        resumption_time = df["time_s"].iloc[resumption_idx]

        ax.axvline(resumption_time, color="gray", linestyle=":", alpha=0.8)
        label_text = "App Resumes\n(Time-bomb triggers)" if not is_after else "App Resumes\n(Window Safely Capped)"
        label_color = "#d62728" if not is_after else "#2ca02c"
        ax.text(resumption_time + 0.15, df["cwnd_kb"].max() * 0.75,
                label_text, fontsize=11, weight="bold", color=label_color)

        ax.set_xlim(resumption_time - 3.0, df["time_s"].iloc[-1] + 0.5)
    else:
        print("[!] Warning: No multi-second pause detected. Did the connection terminate early?")
        ax.set_xlim(0, df["time_s"].iloc[-1] + 0.2)

    ax.set_ylim(0, max(df["msquic_cap_kb"].max(), df["cwnd_kb"].max()) * 1.1)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Size (KB)", fontsize=11)
    title = "The Resumption Bomb: Neutralized" if is_after else "The Resumption Bomb: Stale maxFS allows CUBIC Time-Bomb to Explode"
    ax.set_title(title, fontsize=12, weight="bold")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="lower left", frameon=True)

    plt.tight_layout()
    plt.savefig(output_png, dpi=150)
    print(f"[*] Plot saved to {output_png}")

if __name__ == "__main__":
    main()
