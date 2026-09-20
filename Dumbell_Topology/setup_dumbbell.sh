#!/bin/bash
# Basic dumbbell topology using Linux network namespaces.
#
#   c1 --\                              /-- s1
#         r1 ===== bottleneck ===== r2
#   c2 --/        (tc netem)             \-- s2
#
# c1,c2 = sender namespaces   r1,r2 = router namespaces   s1,s2 = receiver namespaces
# The bottleneck (rate/delay/queue-limited link) sits ONLY on the r1<->r2 veth pair.

set -e

# ---- Tunable bottleneck parameters ----
BW="${BW:-10mbit}"      # bottleneck bandwidth
DELAY="${DELAY:-20ms}"  # one-way delay applied at EACH end (so RTT ~= 4*DELAY)
QUEUE="${QUEUE:-1000}"  # bottleneck queue limit, in packets

echo "[*] Bottleneck: BW=$BW DELAY=$DELAY(each side) QUEUE=${QUEUE}pkts"

# ---- 1. Create namespaces ----
for ns in c1 c2 r1 r2 s1 s2; do
    ip netns add $ns
done

# ---- 2. Create veth pairs ----
# client side
ip link add veth-c1 netns c1 type veth peer name veth-r1-c1 netns r1
ip link add veth-c2 netns c2 type veth peer name veth-r1-c2 netns r1
# bottleneck link (the ONLY link we shape)
ip link add veth-r1b netns r1 type veth peer name veth-r2b netns r2
# server side
ip link add veth-s1 netns s1 type veth peer name veth-r2-s1 netns r2
ip link add veth-s2 netns s2 type veth peer name veth-r2-s2 netns r2

# ---- 3. Assign IPs ----
ip -n c1 addr add 10.0.1.1/24 dev veth-c1
ip -n r1 addr add 10.0.1.254/24 dev veth-r1-c1

ip -n c2 addr add 10.0.2.1/24 dev veth-c2
ip -n r1 addr add 10.0.2.254/24 dev veth-r1-c2

ip -n r1 addr add 10.0.100.1/30 dev veth-r1b
ip -n r2 addr add 10.0.100.2/30 dev veth-r2b

ip -n s1 addr add 10.0.3.1/24 dev veth-s1
ip -n r2 addr add 10.0.3.254/24 dev veth-r2-s1

ip -n s2 addr add 10.0.4.1/24 dev veth-s2
ip -n r2 addr add 10.0.4.254/24 dev veth-r2-s2

# ---- 4. Bring all interfaces up (+ loopback in every ns) ----
for ns in c1 c2 r1 r2 s1 s2; do
    ip -n $ns link set lo up
done
ip -n c1 link set veth-c1 up
ip -n c2 link set veth-c2 up
ip -n r1 link set veth-r1-c1 up
ip -n r1 link set veth-r1-c2 up
ip -n r1 link set veth-r1b up
ip -n r2 link set veth-r2b up
ip -n r2 link set veth-r2-s1 up
ip -n r2 link set veth-r2-s2 up
ip -n s1 link set veth-s1 up
ip -n s2 link set veth-s2 up

# ---- 5. Enable forwarding on both routers ----
ip netns exec r1 sysctl -qw net.ipv4.ip_forward=1
ip netns exec r2 sysctl -qw net.ipv4.ip_forward=1

# ---- 6. Routes ----
# clients -> default via r1
ip -n c1 route add default via 10.0.1.254
ip -n c2 route add default via 10.0.2.254
# servers -> default via r2
ip -n s1 route add default via 10.0.3.254
ip -n s2 route add default via 10.0.4.254
# r1 -> reach server subnets via r2 across the bottleneck
ip -n r1 route add 10.0.3.0/24 via 10.0.100.2
ip -n r1 route add 10.0.4.0/24 via 10.0.100.2
# r2 -> reach client subnets via r1 across the bottleneck
ip -n r2 route add 10.0.1.0/24 via 10.0.100.1
ip -n r2 route add 10.0.2.0/24 via 10.0.100.1

# ---- 7. Apply the bottleneck (tc netem) on BOTH ends of the r1<->r2 link ----
# tc is egress-only, so we shape both directions by applying to each end.
ip netns exec r1 tc qdisc add dev veth-r1b root netem delay ${DELAY} rate ${BW} limit ${QUEUE}
ip netns exec r2 tc qdisc add dev veth-r2b root netem delay ${DELAY} rate ${BW} limit ${QUEUE}

echo "[*] Dumbbell topology created."
echo "    c1=10.0.1.1  c2=10.0.2.1  s1=10.0.3.1  s2=10.0.4.1"
