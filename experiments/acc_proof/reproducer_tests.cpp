
//
// Test: AIMD Accumulator - no unsigned underflow (state-level reproducer)
// Scenario: the accumulator crosses AimdWindow by less than one MSS, which is
// the common case (ACKs of one or two packets). The accumulator must keep the
// small remainder. With the current order (grow AimdWindow, then subtract the
// grown window) the uint32 subtraction wraps to ~4.29e9, after which every
// ACK grows AimdWindow by one MSS.
//
TEST_F(CubicTest, AIMD_AccumulatorNoUnderflow)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ true);
    const uint16_t DatagramPayloadLength = QuicPathGetDatagramPayloadSize(&Connection.Paths.Paths[0]);

    EnterCongestionAvoidance();

    const uint32_t Window = 20 * DatagramPayloadLength;
    Cubic->AimdWindow = Window;
    Cubic->WindowPrior = Window;          // full-rate accumulation
    Cubic->AimdAccumulator = Window - 50; // 50 bytes below the threshold

    CC->QuicCongestionControlOnDataSent(CC, 4 * DatagramPayloadLength);
    QUIC_ACK_EVENT Ack1 = MakeAckEvent(1100000, 16, 16, 100); // crosses by 50 bytes
    CC->QuicCongestionControlOnDataAcknowledged(CC, &Ack1);

    ASSERT_EQ(Cubic->AimdWindow, Window + DatagramPayloadLength);
    ASSERT_EQ(Cubic->AimdAccumulator, 50u);
    ASSERT_LT(Cubic->AimdAccumulator, Cubic->AimdWindow);

    // A further small ACK must not grow AimdWindow again.
    QUIC_ACK_EVENT Ack2 = MakeAckEvent(1110000, 17, 17, 100);
    CC->QuicCongestionControlOnDataAcknowledged(CC, &Ack2);
    ASSERT_EQ(Cubic->AimdWindow, Window + DatagramPayloadLength);
}

//
// Test: AIMD window growth with one ACK per packet (behavioural reproducer)
// Scenario: only the public callbacks are used; no internal field is set.
// After a loss, the sender sends a full window every RTT and every packet is
// acknowledged individually, as on a real network. The Reno-friendly window
// may grow by at most one MSS per AimdWindow bytes acknowledged (RFC 9438
// Section 4.3; MsQuic's own comment: "0.5MSS/RTT ... then 1MSS/RTT").
//
TEST_F(CubicTest, AIMD_PerPacketAcksGrowAtMostOneMssPerWindow)
{
    // 13 packets: after the loss cwnd = 0.7 * 13 * MSS = 11211 bytes, which is
    // not a multiple of the MSS - the normal case on a real path. (With a
    // window that is an exact multiple of the MSS and ACKs of exactly one
    // MSS, the wrap is undone by the next ACK and the bug stays hidden.)
    InitializeDefaultWithRtt(/*WindowPackets = */ 13, /*HyStart = */ false);
    const uint16_t DatagramPayloadLength = QuicPathGetDatagramPayloadSize(&Connection.Paths.Paths[0]);

    EnterCongestionAvoidance();

    uint64_t Now = 1100000;
    uint64_t PacketNumber = 20;
    for (uint32_t Round = 0; Round < 8; Round++) {
        const uint32_t Packets = Cubic->CongestionWindow / DatagramPayloadLength;
        const uint32_t AimdBefore = Cubic->AimdWindow;
        const uint32_t CwndBefore = Cubic->CongestionWindow;
        CC->QuicCongestionControlOnDataSent(CC, Packets * DatagramPayloadLength);
        for (uint32_t k = 0; k < Packets; k++) {
            Now += 50000 / Packets;
            PacketNumber++;
            QUIC_ACK_EVENT Ack = MakeAckEvent(Now, PacketNumber, PacketNumber, DatagramPayloadLength);
            CC->QuicCongestionControlOnDataAcknowledged(CC, &Ack);
        }
        const uint32_t BytesAcked = Packets * DatagramPayloadLength;
        const uint32_t MaxGrowth = DatagramPayloadLength * (BytesAcked / AimdBefore + 1);
        printf("round %u: cwnd %u -> %u, AimdWindow %u -> %u, AimdAccumulator %u\n",
               Round, CwndBefore, Cubic->CongestionWindow, AimdBefore, Cubic->AimdWindow,
               Cubic->AimdAccumulator);
        ASSERT_LE(Cubic->AimdWindow - AimdBefore, MaxGrowth) << "round " << Round;
        ASSERT_LE(Cubic->AimdAccumulator, Cubic->AimdWindow) << "round " << Round;
    }
}
