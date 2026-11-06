
//====================================================================
//  Report scenarios (not part of the patch). Each TEST prints CSV rows
//  "SCN,<scenario>,<phase>,<round>,<time_us>,<cwnd>,<maxFS>,<ssthresh>,<inflight>"
//  so the same deterministic workload can be compared across builds of
//  cubic.c (stock, full patch, and the patch with one change disabled).
//====================================================================

static const uint32_t kSmss = 1232; // 1280-byte MTU minus IPv6/UDP overhead

class CubicScenario : public CubicTest {
protected:
    uint64_t Pn = 0;
    uint64_t Now = 1000000;
    const char* Scn = "";

    void Log(const char* Phase, uint32_t Round) {
        printf("SCN,%s,%s,%u,%llu,%u,%u,%u,%u\n", Scn, Phase, Round,
               (unsigned long long)Now, Cubic->CongestionWindow, Cubic->BytesInFlightMax,
               Cubic->SlowStartThreshold, Cubic->BytesInFlight);
    }
    void Send(uint32_t Packets, uint32_t Bytes = kSmss) {
        for (uint32_t i = 0; i < Packets; i++) {
            Connection.Send.NextPacketNumber = ++Pn + 1;
            CC->QuicCongestionControlOnDataSent(CC, Bytes);
        }
    }
    void AckAll(uint32_t Bytes) {
        Now += 50000; // one 50 ms RTT per round
        QUIC_ACK_EVENT Ack = MakeAckEvent(Now, Pn, Pn, Bytes);
        CC->QuicCongestionControlOnDataAcknowledged(CC, &Ack);
    }
    void Lose(uint32_t Bytes) {
        QUIC_LOSS_EVENT Loss = MakeLossEvent(Bytes, Pn, Pn);
        CC->QuicCongestionControlOnDataLost(CC, &Loss);
    }
    // Slow start, cwnd-limited, until cwnd reaches Target bytes; then a round of
    // Target bytes in which LostPackets are declared lost.
    void StartupWithLoss(uint32_t TargetPackets, uint32_t LostPackets) {
        uint32_t Round = 0;
        while (Cubic->CongestionWindow < TargetPackets * kSmss) {
            uint32_t N = Cubic->CongestionWindow / kSmss;
            Send(N);
            Log("startup", Round);
            AckAll(N * kSmss);
            Log("startup", Round++);
        }
        Send(TargetPackets);
        Log("startup", Round);
        Lose(LostPackets * kSmss);
        Log("loss", Round);
        AckAll((TargetPackets - LostPackets) * kSmss); // still in recovery
        Log("loss", Round);
    }
};

//
// Scenario A (Gap 1 + Gap 2): loss at a 40-packet flight, then 10 s of
// app-limited sending (4 packets per RTT), then the app resumes cwnd-limited.
//
TEST_F(CubicScenario, A_RateLimitedAfterLoss)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ false);
    Scn = "A";
    StartupWithLoss(40, 12);
    for (uint32_t r = 0; r < 200; r++) {
        Send(4);
        AckAll(4 * kSmss);
        Log("ratelimited", r);
    }
    for (uint32_t r = 0; r < 8; r++) {
        uint32_t N = Cubic->CongestionWindow / kSmss;
        Send(N);
        Log("resume", r); // inflight here = the burst the sender releases
        AckAll(N * kSmss);
        Log("resume_ack", r);
    }
}

//
// Scenario B (ssthresh adjustment): a loss that removes half the flight, so
// maxFS + 1 SMSS ends up below ssthresh; then app-limited sending.
//
TEST_F(CubicScenario, B_CapBelowSsthresh)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ false);
    Scn = "B";
    StartupWithLoss(40, 20);
    for (uint32_t r = 0; r < 40; r++) {
        Send(4);
        AckAll(4 * kSmss);
        Log("ratelimited", r);
    }    for (uint32_t r = 0; r < 15; r++) {
        uint32_t N = Cubic->CongestionWindow / kSmss;
        if (N == 0) { N = 1; }
        Send(N);
        Log("resume", r);
        AckAll(N * kSmss);
        Log("resume_ack", r);
    }
}

//
// Scenario C (spurious-loss undo): in congestion avoidance with a full
// window in flight, 30% of it is declared lost, then the loss is found to be
// spurious and undone, and the remaining flight is acknowledged.
//
TEST_F(CubicScenario, C_SpuriousUndo)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ false);
    Scn = "C";
    StartupWithLoss(40, 4);
    for (uint32_t r = 0; r < 10; r++) { // cwnd-limited in CA
        uint32_t N = Cubic->CongestionWindow / kSmss;
        Send(N);
        AckAll(N * kSmss);
        Log("ca", r);
    }
    uint32_t N = Cubic->CongestionWindow / kSmss;
    Send(N);
    Log("before_loss", 0);
    uint32_t Lost = (N * 3 / 10);
    Lose(Lost * kSmss);
    Log("loss", 0);
    CC->QuicCongestionControlOnSpuriousCongestionEvent(CC);
    Log("undo", 0);
    AckAll((N - Lost) * kSmss);
    Log("first_ack_after_undo", 0);
}

//
// Scenario D (minimum-window floor): a heartbeat app sends one 300-byte
// packet per RTT in congestion avoidance; one heartbeat is lost.
//
TEST_F(CubicScenario, D_TinyFlight)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ false);
    Scn = "D";
    StartupWithLoss(40, 12);
    for (uint32_t r = 0; r < 5; r++) {
        Send(1, 300);
        AckAll(300);
        Log("heartbeat", r);
    }
    Send(1, 300);
    Lose(300);
    Log("heartbeat_lost", 0);
    for (uint32_t r = 0; r < 20; r++) {
        Send(1, 300);
        AckAll(300);
        Log("heartbeat", 100 + r);
    }    for (uint32_t r = 0; r < 15; r++) {
        uint32_t N = Cubic->CongestionWindow / kSmss;
        if (N == 0) { N = 1; }
        Send(N);
        Log("resume", r);
        AckAll(N * kSmss);
        Log("resume_ack", r);
    }
}

//
// Scenario E (ECN reset): a full 40-packet window was sent, half of it has
// been acknowledged, then an ECN-CE mark arrives.
//
TEST_F(CubicScenario, E_Ecn)
{
    InitializeDefaultWithRtt(/*WindowPackets = */ 10, /*HyStart = */ false);
    Scn = "E";
    while (Cubic->CongestionWindow < 40 * kSmss) {
        uint32_t N = Cubic->CongestionWindow / kSmss;
        Send(N);
        AckAll(N * kSmss);
    }
    Send(40);
    AckAll(20 * kSmss);
    Log("before_ecn", 0);
    QUIC_ECN_EVENT Ecn{};
    Ecn.LargestPacketNumberAcked = Pn;
    Ecn.LargestSentPacketNumber = Pn;
    CC->QuicCongestionControlOnEcn(CC, &Ecn);
    Log("after_ecn", 0);
    for (uint32_t r = 0; r < 100; r++) { // app-limited afterwards
        Send(4);
        AckAll(4 * kSmss);
        Log("ratelimited", r);
    }
}
