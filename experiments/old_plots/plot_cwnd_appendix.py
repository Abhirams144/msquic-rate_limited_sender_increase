import pandas as pd
import matplotlib.pyplot as plt
import sys

if len(sys.argv) < 3:
    print("Usage: python3 plot_cwnd_appendix.py <csv_path> <output_png> [title] [--min-gap-ms N]")
    sys.exit(1)

csv_path = sys.argv[1]
output_png = sys.argv[2]
title = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "CUBIC Telemetry"

# Load CSV without headers and assign explicit column names
names = ["time_us", "cwnd", "flight_size", "phase"]
df = pd.read_csv(csv_path, header=None, names=names)

# Convert timestamp to relative seconds starting at 0
df["time_sec"] = (df["time_us"] - df["time_us"].iloc[0]) / 1e6

plt.figure(figsize=(10, 5), dpi=150)
plt.plot(df["time_sec"], df["cwnd"] / 1000, label="CongestionWindow (KB)", color="#1f77b4", linewidth=2)
plt.plot(df["time_sec"], df["flight_size"] / 1000, label="BytesInFlight (KB)", color="#2ca02c", linestyle="--", linewidth=1.5)

plt.title(title, fontsize=12, fontweight="bold")
plt.xlabel("Time (seconds)", fontsize=10)
plt.ylabel("Size (KB)", fontsize=10)
plt.grid(True, linestyle="--", alpha=0.5)
plt.legend(loc="upper left")
plt.tight_layout()

plt.savefig(output_png)
print(f"[*] Plot saved to {output_png}")
