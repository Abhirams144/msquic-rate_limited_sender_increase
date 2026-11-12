#!/bin/bash
# Parameter-sweep campaign for the rate-limited sender increase patch.
#
#   sudo ./run_campaign.sh                    # all points, 10 reps (~1.5-2 h)
#   sudo REPS=5 ./run_campaign.sh             # quicker
#   sudo ONLY="dur_10s rtt_80" ./run_campaign.sh   # a subset of points
#   sudo ./run_campaign.sh fix                 # 4-build campaign with the AIMD fix
#   sudo ./run_campaign.sh acc                 # stock vs stock + AIMD fix, logging
#                                              # AimdWindow/AimdAccumulator (acc_proof/)
#   sudo ./run_campaign.sh bulk                # same two builds, plain bulk transfers
#                                              # (no rate-limited phase)
#
# Re-running continues where it stopped: completed runs are skipped.
#
# Each point is one bottleneck setting + one length of the rate-limited phase.
# Runs are interleaved (rep -> point -> build, build order alternating per rep)
# so slow drift of the machine cannot favour one build, and an interrupted
# campaign still has a balanced number of reps for every point.
#
# Differences from run_rls_experiments.sh:
#   * GSO/TSO/GRO are turned off on every veth, so the netem queue limit counts
#     real packets (with UDP GSO one queued buffer could hold many packets).
#   * the "compete" point adds a long-running TCP CUBIC flow (iperf3) c2 -> s2.

set -u
if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi

ROOT=/home/eventhorizon144/WN_ASSIGNMENT
EXP=$ROOT/experiments
MODE="${1:-main}"
if [ "$MODE" = fix ]; then
    # 4 builds: upstream, upstream + AIMD-accumulator fix, ours, ours + fix
    OUT=$EXP/results_v3
    VARIANTS=(stock stockfix ours oursfix)
    ONLY="${ONLY:-dur_10s dur_30s rtt_80 bw_50 compete}"
elif [ "$MODE" = acc ]; then
    # Direct evidence for the accumulator bug: two builds whose cubic.c differ
    # only in the two AIMD lines (experiments/acc_proof/S0_vs_S1.diff); the
    # trace also records AimdWindow and AimdAccumulator.
    OUT=$EXP/results_v4_acc
    VARIANTS=(accstock accstockfix)
    ONLY="${ONLY:-dur_10s compete}"
elif [ "$MODE" = bulk ]; then
    # Does the accumulator bug matter without any rate-limited phase? Same two
    # builds as "acc"; one plain bulk transfer of CYCLES megabytes per run.
    OUT=$EXP/results_v5_bulk
    VARIANTS=(accstock accstockfix)
else
    OUT=$EXP/results_v2
    VARIANTS=(before after)
fi
declare -A BUILD=([before]=build-before [after]=build-after [stock]=build-before
                  [stockfix]=build-stockfix [ours]=build-after [oursfix]=build-oursfix
                  [accstock]=build-acc-stock [accstockfix]=build-acc-stockfix)
CERT=$ROOT/msquic/build/bin/Release/cert.pem
KEY=$ROOT/msquic/build/bin/Release/key.pem
REPS="${REPS:-10}"
ONLY="${ONLY:-}"

# name        BW       DELAY(each way)  QUEUE  CYCLES  COMPETE
POINTS=(
  "dur_2s     10mbit   20ms   100   250   none"
  "dur_5s     10mbit   20ms   100   500   none"
  "dur_10s    10mbit   20ms   100   1000  none"
  "dur_20s    10mbit   20ms   100   2000  none"
  "dur_30s    10mbit   20ms   100   3000  none"
  "rtt_10     10mbit   5ms    100   1000  none"
  "rtt_20     10mbit   10ms   100   1000  none"
  "rtt_80     10mbit   40ms   100   1000  none"
  "bw_25      25mbit   20ms   100   1000  none"
  "bw_50      50mbit   20ms   100   1000  none"
  "compete    25mbit   20ms   100   1000  tcp"
)
# rtt_40 and bw_10 are the same setting as dur_10s and are taken from it.
if [ "$MODE" = bulk ]; then
  # name           BW      DELAY  QUEUE  MBYTES  COMPETE
  POINTS=(
    "bulk_10       10mbit  20ms   100    30      none"
    "bulk_rtt80    10mbit  40ms   100    30      none"
    "bulk_50       50mbit  20ms   100    100     none"
    "bulk_compete  25mbit  20ms   100    60      tcp"
  )
fi

for v in "${VARIANTS[@]}"; do
    [ -x "$ROOT/msquic/${BUILD[$v]}/bin/Release/quicsample" ] || { echo "missing ${BUILD[$v]}"; exit 1; }
done

cleanup() {
    pkill -x quicsample 2>/dev/null; pkill -f "^sleep 1001$" 2>/dev/null
    pkill -x ping 2>/dev/null; pkill -x iperf3 2>/dev/null
    bash "$EXP/teardown_dumbbell.sh" >/dev/null 2>&1
    chown -R "$(stat -c %U:%G "$EXP")" "$OUT" 2>/dev/null
}
trap cleanup EXIT

mkdir -p "$OUT"
bash "$EXP/teardown_dumbbell.sh" >/dev/null 2>&1
QUEUE=100 bash "$EXP/setup_dumbbell.sh" || exit 1

# --- no segmentation offloads anywhere: one queued skb == one packet ---
for pair in c1:veth-c1 c2:veth-c2 r1:veth-r1-c1 r1:veth-r1-c2 r1:veth-r1b \
            r2:veth-r2b r2:veth-r2-s1 r2:veth-r2-s2 s1:veth-s1 s2:veth-s2; do
    ns=${pair%%:*}; dev=${pair#*:}
    for feat in gso tso gro tx-udp-segmentation; do
        ip netns exec "$ns" ethtool -K "$dev" "$feat" off >/dev/null 2>&1
    done
done

{
  echo "date=$(date -Iseconds) kernel=$(uname -r) reps=$REPS mode=$MODE builds=${VARIANTS[*]}"
  echo "offloads on veth-c1:"; ip netns exec c1 ethtool -k veth-c1 | grep -E "segmentation|generic-receive"
  printf '%s\n' "${POINTS[@]}"
} >> "$OUT/config.txt"

ip netns exec s2 iperf3 -s -D --logfile "$OUT/iperf3_server.log"

set_bottleneck() {  # BW DELAY QUEUE
    ip netns exec r1 tc qdisc replace dev veth-r1b root netem delay "$2" rate "$1" limit "$3"
    ip netns exec r2 tc qdisc replace dev veth-r2b root netem delay "$2" rate "$1" limit "$3"
}
drops() {
    ip netns exec r1 tc -s qdisc show dev veth-r1b | awk '/dropped/ {gsub(",","",$7); print $7; exit}'
}

NPTS=0
for p in "${POINTS[@]}"; do
    n=${p%% *}; if [ -z "$ONLY" ] || [[ " $ONLY " == *" $n "* ]]; then NPTS=$((NPTS + 1)); fi
done
NV=${#VARIANTS[@]}
TOTAL=$(( REPS * NPTS * NV )); N=0; T0=$(date +%s)
for rep in $(seq 1 "$REPS"); do
  for p in "${POINTS[@]}"; do
    read -r NAME BW DELAY QUEUE CYCLES COMPETE <<< "$p"
    if [ -n "$ONLY" ] && ! [[ " $ONLY " == *" $NAME "* ]]; then continue; fi
    DIR=$OUT/$NAME; mkdir -p "$DIR"
    echo "bw=$BW delay=$DELAY queue=$QUEUE cycles=$CYCLES compete=$COMPETE mode=$MODE" > "$DIR/point.txt"
    # rotate the build order every repetition so no build always runs first
    ORDER=""
    for k in $(seq 0 $((NV - 1))); do ORDER="$ORDER ${VARIANTS[$(( (k + rep - 1) % NV ))]}"; done
    for v in $ORDER; do
      N=$((N + 1))
      TAG=${v}_rep${rep}
      if grep -q "TRANSFER COMPLETE" "$DIR/${TAG}_client.out" 2>/dev/null; then continue; fi
      ELAPSED=$(( $(date +%s) - T0 ))
      echo "[$N/$TOTAL, ${ELAPSED}s] $NAME $TAG"
      set_bottleneck "$BW" "$DELAY" "$QUEUE"
      BIN=$ROOT/msquic/${BUILD[$v]}/bin/Release/quicsample
      if [ "$MODE" = bulk ]; then
          CLIENT_ARGS="-prime:0 -cycles:0 -final:$((CYCLES * 1000000))"
      else
          CLIENT_ARGS="-prime:3000000 -burst:6000 -pause:10 -cycles:$CYCLES -final:8000000"
      fi

      sleep 1001 | ip netns exec s1 env CWND_LOG="$DIR/${TAG}_server.csv" \
          "$BIN" -server -cert_file:"$CERT" -key_file:"$KEY" > "$DIR/${TAG}_server.out" 2>&1 &
      sleep 1

      IPERF_PID=""
      if [ "$COMPETE" = tcp ]; then
          python3 -c 'import time; print(time.time())' > "$DIR/${TAG}_iperf_start.txt"
          ip netns exec c2 iperf3 -c 10.0.4.1 -t 300 -i 0.1 -C cubic --forceflush \
              > "$DIR/${TAG}_iperf.txt" 2>&1 &
          IPERF_PID=$!
          sleep 3   # let the TCP flow reach steady state first
      fi

      python3 -c 'import time; print(time.time() - time.monotonic())' > "$DIR/${TAG}_clock_offset.txt"
      D0=$(drops)
      ip netns exec c2 ping -D -i 0.01 10.0.4.1 > "$DIR/${TAG}_ping.txt" 2>&1 &
      PING_PID=$!
      sleep 0.5

      timeout 300 ip netns exec c1 env CWND_LOG="$DIR/${TAG}_client.csv" \
          "$BIN" -client -unsecure -target:10.0.3.1 $CLIENT_ARGS > "$DIR/${TAG}_client.out" 2>&1
      echo "client_exit=$?" >> "$DIR/${TAG}_client.out"

      sleep 0.5
      kill "$PING_PID" 2>/dev/null; wait "$PING_PID" 2>/dev/null
      [ -n "$IPERF_PID" ] && { kill "$IPERF_PID" 2>/dev/null; wait "$IPERF_PID" 2>/dev/null; }
      D1=$(drops)
      echo "bottleneck_drops=$((D1 - D0))" > "$DIR/${TAG}_drops.txt"
      pkill -x quicsample 2>/dev/null; pkill -f "^sleep 1001$" 2>/dev/null
      sleep 1
      grep -E "^\[stats\]" "$DIR/${TAG}_client.out" | sed 's/^/    /'
    done
  done
done

echo "[*] done in $(( $(date +%s) - T0 ))s. Results in $OUT"
echo "    next: python3 $EXP/analyze_campaign.py"
