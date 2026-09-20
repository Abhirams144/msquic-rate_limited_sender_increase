#!/bin/bash
# Tears down the dumbbell topology. Deleting a namespace automatically
# removes any veth ends that live inside it (and their peers).
for ns in c1 c2 r1 r2 s1 s2; do
    ip netns del $ns 2>/dev/null
done
echo "[*] Dumbbell topology removed."
