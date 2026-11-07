
//
// Scenario F (Reno-friendly state while capped): loss at 40 packets, a long
// rate-limited phase, the app resumes cwnd-limited, then a second loss. Prints
// AimdWindow / AimdAccumulator, which the rate-limited cap does not clamp.
//
TEST_F(CubicScenario, F_AimdAfterCap)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ false);
    Scn = "F";
    StartupWithLoss(40, 12);
    auto LogA = [&](const char* Ph, uint32_t R) {
        printf("AIMD,%s,%u,%u,%u,%u,%u,%u\n", Ph, R, Cubic->CongestionWindow, Cubic->BytesInFlightMax,
               Cubic->SlowStartThreshold, Cubic->AimdWindow, Cubic->AimdAccumulator);
    };
    for (uint32_t r = 0; r < 200; r++) { Send(4); AckAll(4 * kSmss); }
    LogA("end_ratelimited", 0);
    for (uint32_t r = 0; r < 3; r++) {           // app resumes, cwnd-limited
        uint32_t N = Cubic->CongestionWindow / kSmss;
        Send(N); AckAll(N * kSmss); LogA("resume", r);
    }
    uint32_t N = Cubic->CongestionWindow / kSmss;
    Send(N);
    Lose(N / 4 * kSmss);                            // second loss
    AckAll((N - N / 4) * kSmss);                    // ends recovery
    LogA("after_loss", 0);
    for (uint32_t r = 0; r < 6; r++) {            // cwnd-limited, one ACK per packet
        uint32_t M = Cubic->CongestionWindow / kSmss;
        Send(M);
        for (uint32_t k = 0; k < M; k++) {
            Now += 50000 / M;
            QUIC_ACK_EVENT Ack = MakeAckEvent(Now, Pn - M + k + 1, Pn - M + k + 1, kSmss);
            CC->QuicCongestionControlOnDataAcknowledged(CC, &Ack);
        }
        LogA("post_loss_round", r);
    }
}
