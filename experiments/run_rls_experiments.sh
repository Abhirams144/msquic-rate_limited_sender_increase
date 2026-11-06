#!/bin/bash
# Before/after experiment for Rate-Limited Sender Increase in MsQuic CUBIC.
#
# Must run as root (network namespaces + tc):
#     sudo ./run_rls_experiments.sh            # 5 repetitions per variant
#     sudo REPS=3 ./run_rls_experiments.sh
#
# Scenario (one QUIC connection c1 -> s1 across the dumbbell bottleneck):
#   1. PRIME   : 3 MB bulk send. Slow start overshoots, losses, CUBIC enters CA.
#   2. RATE-LIMITED : the app writes 6000 B every 10 ms (~4.8 Mbit/s, about half
#                the link) for ~16 s. The sender is application-limited.
#   3. RESUME  : the app suddenly has 8 MB to send (a cwnd-limited burst).
# Meanwhile a competing ping flow c2 -> s2 (every 10 ms) measures the queueing
# delay the QUIC sender inflicts on other traffic sharing the bottleneck.
#
# Variants: "before" = stock msquic cubic.c, "after" = rate-limited increase
# patch. Both built with -DQUIC_CUBIC_CWND_LOG so they emit the same trace.

set -u
if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi

ROOT=/home/eventhorizon144/WN_ASSIGNMENT
EXP=$ROOT/experiments
OUT=$EXP/results
CERT=$ROOT/msquic/build/bin/Release/cert.pem
KEY=$ROOT/msquic/build/bin/Release/key.pem
REPS="${REPS:-5}"
export BW="${BW:-10mbit}" DELAY="${DELAY:-20ms}" QUEUE="${QUEUE:-100}"
CLIENT_ARGS="-client -unsecure -target:10.0.3.1 -prime:3000000 -burst:6000 -pause:10 -cycles:1500 -final:8000000"

for v in before after; do
    [ -x "$ROOT/msquic/build-$v/bin/Release/quicsample" ] || { echo "missing build-$v"; exit 1; }
done

cleanup() {
    pkill -x quicsample 2>/dev/null; pkill -f "^sleep 1001$" 2>/dev/null
    pkill -x ping 2>/dev/null
    bash "$EXP/teardown_dumbbell.sh" >/dev/null 2>&1
}
trap cleanup EXIT

rm -rf "$OUT"; mkdir -p "$OUT"
bash "$EXP/teardown_dumbbell.sh" >/dev/null 2>&1
bash "$EXP/setup_dumbbell.sh" || exit 1

cat > "$OUT/config.txt" <<EOF
date=$(date -Iseconds)
kernel=$(uname -r)
BW=$BW DELAY=$DELAY(each way, RTT ~4x) QUEUE=$QUEUE packets
client_args=$CLIENT_ARGS
reps=$REPS
EOF

drops() {  # packets dropped so far at the forward bottleneck queue
    ip netns exec r1 tc -s qdisc show dev veth-r1b | awk '/dropped/ {gsub(",","",$7); print $7; exit}'
}

for rep in $(seq 1 "$REPS"); do
    # alternate the order so drift (CPU, timers) does not favour one variant
    if [ $((rep % 2)) -eq 1 ]; then ORDER="before after"; else ORDER="after before"; fi
    for v in $ORDER; do
        BIN=$ROOT/msquic/build-$v/bin/Release/quicsample
        TAG=${v}_rep${rep}
        echo "[*] run $TAG"

        sleep 1001 | ip netns exec s1 env CWND_LOG="$OUT/${TAG}_server.csv" \
            "$BIN" -server -cert_file:"$CERT" -key_file:"$KEY" > "$OUT/${TAG}_server.out" 2>&1 &
        sleep 1

        # wall-clock minus monotonic, so ping (-D, wall clock) aligns with the cwnd trace (monotonic)
        python3 -c 'import time; print(time.time() - time.monotonic())' > "$OUT/${TAG}_clock_offset.txt"
        D0=$(drops)
        ip netns exec c2 ping -D -i 0.01 10.0.4.1 > "$OUT/${TAG}_ping.txt" 2>&1 &
        PING_PID=$!
        sleep 0.5

        timeout 120 ip netns exec c1 env CWND_LOG="$OUT/${TAG}_client.csv" \
            "$BIN" $CLIENT_ARGS > "$OUT/${TAG}_client.out" 2>&1
        echo "client_exit=$?" >> "$OUT/${TAG}_client.out"

        sleep 0.5
        kill "$PING_PID" 2>/dev/null; wait "$PING_PID" 2>/dev/null
        D1=$(drops)
        echo "bottleneck_drops=$((D1 - D0))" > "$OUT/${TAG}_drops.txt"
        pkill -x quicsample 2>/dev/null; pkill -f "^sleep 1001$" 2>/dev/null
        sleep 1
        grep -E "stats|TRANSFER COMPLETE" "$OUT/${TAG}_client.out" | sed 's/^/    /'
        cat "$OUT/${TAG}_drops.txt" | sed 's/^/    /'
    done
done

chown -R "$(stat -c %U:%G "$EXP")" "$OUT"
echo "[*] done. Results in $OUT"
