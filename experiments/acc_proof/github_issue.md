# Draft: GitHub issue for microsoft/msquic

**Title:** CUBIC: AimdAccumulator underflows (uint32) when it crosses AimdWindow by less than one MSS, making cwnd grow by one MSS per ACK in congestion avoidance

## Describe the bug

In `CubicCongestionControlOnDataAcknowledged` (`src/core/cubic.c`, lines 659-662 on `main` at 3c9ec01c1), the Reno-friendly window is grown *before* the accumulator is reduced by it:

```c
if (Cubic->AimdAccumulator > Cubic->AimdWindow) {
    Cubic->AimdWindow += DatagramPayloadLength;
    Cubic->AimdAccumulator -= Cubic->AimdWindow;   // subtracts the already-grown window
}
```

Both fields are `uint32_t`. When an ACK takes the accumulator past `AimdWindow` by less than `DatagramPayloadLength`, which is the common case for ACKs of one or two packets, the subtraction wraps to ~4.29e9. From then on `AimdAccumulator > AimdWindow` is true on every ACK, so `AimdWindow` grows by one MSS per ACK. In the Reno-friendly region `CongestionWindow = AimdWindow`, so cwnd doubles every RTT while in congestion avoidance, until the wrapped value has been counted down. Congestion events reset `AimdWindow` but not `AimdAccumulator`.

The comment above the block says the intent is to "record ACKed bytes in an accumulator until at least a window ... worth of bytes are ACKed, and then increase the window by 1 MTU", i.e. subtract the window that was crossed and then grow it.

The order dates from the CUBIC rewrite in #2269 (586141e1a, January 2022), which grew the window by `Paths[0].Mtu` before subtracting; #2296 changed only the amount added. So it is in every release since v2.0.0.

The existing test `AIMD_AccumulatorTriggersWindowGrowth` sizes its ACK "to avoid unsigned underflow in the subtraction (AimdAccumulator -= AimdWindow)".

## To reproduce

Add this test to `src/core/unittest/CubicTest.cpp` on `main`. It uses only the public callbacks; no internal field is set.

```cpp
TEST_F(CubicTest, AIMD_PerPacketAcksGrowAtMostOneMssPerWindow)
{
    // After the loss cwnd = 0.7 * 13 * MSS = 11211 bytes, not a multiple of the MSS.
    InitializeDefaultWithRtt(/*WindowPackets = */ 13, /*HyStart = */ false);
    const uint16_t DatagramPayloadLength = QuicPathGetDatagramPayloadSize(&Connection.Paths.Paths[0]);
    EnterCongestionAvoidance();
    uint64_t Now = 1100000, PacketNumber = 20;
    for (uint32_t Round = 0; Round < 8; Round++) {
        const uint32_t Packets = Cubic->CongestionWindow / DatagramPayloadLength;
        const uint32_t AimdBefore = Cubic->AimdWindow;
        CC->QuicCongestionControlOnDataSent(CC, Packets * DatagramPayloadLength);
        for (uint32_t k = 0; k < Packets; k++) {
            Now += 50000 / Packets; PacketNumber++;
            QUIC_ACK_EVENT Ack = MakeAckEvent(Now, PacketNumber, PacketNumber, DatagramPayloadLength);
            CC->QuicCongestionControlOnDataAcknowledged(CC, &Ack);
        }
        const uint32_t MaxGrowth = DatagramPayloadLength * (Packets * DatagramPayloadLength / AimdBefore + 1);
        ASSERT_LE(Cubic->AimdWindow - AimdBefore, MaxGrowth) << "round " << Round;
    }
}
```

On `main` it fails in round 2:

```
round 2: cwnd 12384 -> 23531, AimdWindow 11211 -> 23531, AimdAccumulator 4294808370
Expected: (Cubic->AimdWindow - AimdBefore) <= (MaxGrowth), actual: 12320 vs 2464
```

A conditional breakpoint on line 661 (`break cubic.c:661 if Cubic->AimdAccumulator < Cubic->AimdWindow`) also fires twice while running the *existing* `CubicTest.*` suite, in `CongestionAvoidance_BoundedGrowthClamp` and `CongestionAvoidance_TimeGapOverflowProtection` (1200 - 1232 -> 4294967264). Both tests pass because they do not check the accumulator.

The wrap stays hidden when the window is an exact multiple of the MSS and every ACK adds the same amount, because the next ACK wraps the value back. After a real loss the window is 0.7x the previous one and is rarely such a multiple. On emulated 10-50 Mbit/s paths without competing traffic, 22-33% of congestion-avoidance window increases in our traces were exactly one MSS on a single ACK; with the fix, 0.2-1%.

With `AimdAccumulator` logged on every ACK (two builds of 464c873c0 that differ only in the two lines below; its `cubic.c` differs from current `main` only in the active-path lookup), the accumulator held a wrapped value (>= 2^31) in 10/10 runs per setting on stock code (median 22 and 84 separate wraps per run) and in 0/20 runs with the fix (maximum value 163285). After 6 s of application-limited sending at 10 Mbit/s, the median cwnd at resumption was 668 KB on stock code and 218 KB with the fix, and the median loss after resumption was 3351 KB and 72 KB (10 runs each, permutation p = 0.0001).

In plain bulk transfers (no application-limited phase; 10 runs per build at 10 Mbit/s with 40 and 80 ms RTT, 50 Mbit/s, and 25 Mbit/s shared with a TCP CUBIC flow) the wrap occurred 30-515 times per run on stock code, but it is usually undone by the next ACK, because the `uint32` addition wraps the value back. It persisted in 10 of 40 stock runs (0 of 40 with the fix). In all 10 the next ACK covered a single packet while `AimdWindow < WindowPrior`, so only half of it (736 B) was added, less than the shortfall. From then on the accumulator stayed wrapped for 1248-20464 ACKs, and cwnd repeatedly grew by one MSS per ACK until loss. Those runs lost 5-130x more packets than the fixed build. Against the TCP flow, QUIC's median goodput was 16.1 Mbit/s (TCP 7.1) instead of 7.7 (TCP 16.1).

The test, gdb and full-suite steps above also run in a public GitHub Actions workflow that clones this repository at 3c9ec01c1 and at current `main`, checks each expected outcome, and uploads the raw logs: https://github.com/Abhirams144/msquic-rate_limited_sender_increase/actions/runs/43286985783

## Expected behavior

`AimdWindow` grows by at most one MSS per `AimdWindow` bytes acknowledged: 0.5 MSS/RTT below `WindowPrior` and 1 MSS/RTT above it, as in the code comment and RFC 9438 Section 4.3.

## Proposed fix

```diff
 if (Cubic->AimdAccumulator > Cubic->AimdWindow) {
-    Cubic->AimdWindow += DatagramPayloadLength;
     Cubic->AimdAccumulator -= Cubic->AimdWindow;
+    Cubic->AimdWindow += DatagramPayloadLength;
 }
```

With this change the test above passes, with `AimdWindow` growing by one MSS every two RTTs (0.5 MSS/RTT). The full `msquiccoretest` suite goes from 559 passed, 4 skipped, 0 failed to 561 passed, 4 skipped, 0 failed (the 2 new tests). Two existing tests encode the old order in their expected values and need updating: `AIMD_AccumulatorTriggersWindowGrowth` (expects `BytesAcked - (SmallAimdWindow + DPL)`, should be `BytesAcked - SmallAimdWindow`) and `AIMD_SequentialLinearConvergence` (subtract, then grow).

I'm happy to open a PR with the fix, the two tests and the two updated expectations.

---

# Draft: PR description

**cubic: fix unsigned underflow of the Reno-friendly AIMD accumulator**

Fixes #<issue>.

`AimdAccumulator` was reduced by the already-grown `AimdWindow`. When the accumulator exceeded `AimdWindow` by less than one MSS, the `uint32` subtraction wrapped to ~4.29e9, after which every ACK grew `AimdWindow`, and cwnd in the Reno-friendly region, by one MSS.

- Subtract the window that was crossed, then grow it (2 lines swapped).
- Add `AIMD_AccumulatorNoUnderflow` (state level) and `AIMD_PerPacketAcksGrowAtMostOneMssPerWindow` (public callbacks only); both fail before the fix.
- Update `AIMD_AccumulatorTriggersWindowGrowth` and `AIMD_SequentialLinearConvergence`, whose expected values encoded the old order.

Testing: `msquiccoretest` 561 passed, 4 skipped, 0 failed (was 559 / 4 / 0).
