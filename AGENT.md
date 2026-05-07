# AGENT.md

## Project Background

This is a Xilinx SDK 2018.3 bare-metal Zynq-7000 + AD9361 OFDM project.

Current data path:

PC sender
-> UDP packets
-> Zynq PS lwIP RAW API
-> packet validation / CRC
-> PS DDR TX buffer
-> AXI DMA MM2S
-> PL OFDM / AD9361 TX path

The current implementation already has:

- UDP receive path on Zynq PS
- custom packet header with sequence number and CRC
- ACK mechanism
- PC-side sliding-window sender
- DMA TX ring slots
- lwIP RAW API
- CLI and GUI sender tools

The next goal is to optimize the project from "functional" to "high-throughput, robust, observable, and recoverable".

The most important current issue is:

The PS->PL DMA side is not saturated. DMA/PL often waits for data. The effective DMA slot utilization is very low, around 1/32 in current observations. This strongly suggests that the bottleneck is not raw DMA bandwidth, but the front-end path:

PC sender
-> UDP stack
-> lwIP callback
-> CRC / memcpy
-> small DMA slots
-> frequent DMA starts
-> ACK / window strategy
-> excessive per-packet overhead

Do not blindly preserve existing temporary strategies such as "ACK every 10 packets". Replace them with better mechanisms if needed.

---

## Hard Constraints

1. Keep compatibility with Xilinx SDK 2018.3.
2. Keep the project bare-metal / standalone.
3. Do not introduce RTOS.
4. Do not modify Vivado hardware, HDF, or PL logic unless absolutely necessary.
5. Prefer incremental, testable changes.
6. Do not break the existing UDP -> DMA -> PL basic path.
7. Keep the command-line PC sender usable.
8. GUI sender can be updated, but throughput testing must not depend on GUI.
9. Avoid per-packet UART printing.
10. UART output should be periodic statistics only.
11. Put new configurable parameters in config headers, not scattered magic numbers.
12. Update README.md after protocol, ACK, DMA buffer, or sender behavior changes.

---

## Main Optimization Direction

The current structure is too fine-grained:

one UDP chunk
-> one small DMA slot
-> one short DMA transfer

This causes high fixed overhead per payload byte.

The desired structure is:

many UDP chunks
-> one larger PS-side aggregation block
-> one longer DMA transfer
-> more continuous PL input stream

Main goal:

Reduce per-packet and per-DMA-transfer overhead, improve PS->PL feeding continuity, and increase effective throughput.

---

## Development Priorities

Work in this order:

1. Add statistics and observability.
2. Reduce PS front-end overhead.
3. Enable I-cache first.
4. Add PS-side DMA aggregation blocks.
5. Redesign ACK/retransmission using cumulative ACK + bitmap + flow control.
6. Improve PC sender throughput mode.
7. Consider D-cache only after the above is stable.
8. Consider AXI DMA SG mode only if simple DMA remains a measured bottleneck.

Do not start with SG DMA. First fix the small-transfer and front-end overhead problem.

---

## Phase 1: Add Statistics and Diagnostics

Add lightweight runtime statistics on the Zynq side.

Required counters:

- rx_packets
- rx_bytes
- rx_payload_bytes
- bad_magic_count
- bad_length_count
- crc_error_count
- duplicate_count
- pending_count
- busy_count
- dropped_count
- dma_start_count
- dma_done_count
- dma_error_count
- dma_bytes_total
- queue_occupancy_current
- queue_occupancy_max
- ack_tx_count
- nack_tx_count
- retransmit_rx_count

If aggregation is implemented, also add:

- agg_block_submit_count
- agg_flush_full_count
- agg_flush_timeout_count
- agg_bytes_total
- agg_avg_block_bytes
- agg_min_block_bytes
- agg_max_block_bytes

Add helper functions, for example:

    NetStats_Init();
    NetStats_OnRxPacket(...);
    NetStats_OnBadPacket(...);
    NetStats_OnDmaStart(...);
    NetStats_OnDmaDone(...);
    NetStats_PrintPeriodic();

UART output rules:

- No per-packet UART print in throughput mode.
- Print one STAT line about once per second.
- Keep the STAT line compact and readable.

Example STAT format:

    STAT rx_kBps=... dma_kBps=... rx_pkt=... crc=... busy=... pend=... q_cur=... q_max=... dma_done=... dma_err=...

Acceptance criteria:

- Project builds.
- Existing UDP transmission still works.
- Serial output is periodic and readable.
- Throughput can be measured without GUI verbose logs.
- It is possible to compare PC send rate, board RX rate, and DMA rate.

---

## Phase 2: Enable I-Cache First

Enable instruction cache to reduce CPU overhead in lwIP, CRC, memcpy, and protocol parsing.

Initial cache policy:

    Xil_ICacheEnable();
    Xil_DCacheDisable();

Do not enable D-cache in the first optimization pass.

Reason:

- I-cache improves instruction execution speed and is low risk.
- D-cache may introduce DMA coherency bugs if not handled carefully.
- The current bottleneck is likely PS front-end CPU overhead and small-transfer overhead.

Add config macros:

    #define APP_ENABLE_ICACHE 1
    #define APP_ENABLE_DCACHE 0

Acceptance criteria:

- Project still boots.
- Ethernet still works.
- DMA TX still works.
- Throughput before and after I-cache can be compared.

---

## Phase 3: Add PS-Side DMA Aggregation Blocks

Do not let every UDP chunk directly trigger one small DMA transfer.

Implement an aggregation layer:

UDP chunk
-> validate header and CRC
-> append payload into current aggregation block
-> submit aggregation block to DMA when full or timeout expires

Recommended initial config:

    #define NET_AGG_ENABLE              1
    #define NET_AGG_BLOCK_BYTES         (16 * 1024)
    #define NET_AGG_BLOCK_COUNT         8
    #define NET_AGG_FLUSH_TIMEOUT_US    1000

Keep UDP chunk payload MTU-safe, for example 1456 bytes, to avoid IP fragmentation.

Aggregation rules:

1. Append only valid UDP payloads.
2. Keep packet sequence tracking independent from DMA block boundaries.
3. Submit block to DMA when the block is full.
4. Submit partially filled block when flush timeout expires.
5. DMA transfer length must be aligned to 8 bytes.
6. Padding bytes must be deterministic, preferably zero.
7. Never overwrite a block owned by DMA.
8. Track block ownership explicitly.

Required block states:

- FREE
- FILLING
- READY
- DMA_BUSY

Suggested flow:

    UDP receive callback:
        validate packet
        update receive/retransmission state
        append payload to current aggregation block
        mark ACK state as received
        if aggregation block is full:
            mark block READY

    Net_RxPoll or Net_TxPoll:
        check aggregation timeout
        flush partial block if needed
        start DMA if DMA idle and READY block exists
        handle DMA completion
        recycle completed block

Important:

ACK should mean "packet safely accepted into PS-side buffer/state", not "DMA already finished".

Acceptance criteria:

- Average DMA transfer size is much larger than one UDP chunk.
- DMA start count per MB decreases significantly.
- DMA/PL receives longer continuous bursts.
- Existing sender still works.
- STAT output reports aggregation behavior.

---

## Phase 4: Redesign ACK, Retransmission, and Flow Control

Replace the old fixed "ACK every N packets" strategy.

Implement ACK v2 using cumulative ACK + bitmap + board-side flow-control information.

Suggested ACK v2 packet:

    typedef struct {
        uint32_t magic;
        uint32_t version;
        uint32_t ack_base_seq;
        uint32_t ack_bitmap;
        uint32_t rx_free_bytes;
        uint32_t rx_ready_bytes;
        uint32_t error_flags;
        uint32_t crc_error_count;
        uint32_t dropped_count;
    } net_ack_v2_t;

Meaning:

- ack_base_seq:
  largest continuously received sequence number.

- ack_bitmap:
  receive status of the next 32 packets after ack_base_seq.
  Bit 0 corresponds to ack_base_seq + 1.
  Bit 1 corresponds to ack_base_seq + 2.
  And so on.

- rx_free_bytes:
  remaining board-side receive / aggregation capacity.

- rx_ready_bytes:
  bytes already accepted and waiting for DMA.

- error_flags:
  summary flags such as busy, overflow, DMA error, or protocol error.

ACK policy:

1. Send ACK periodically, for example every 1 ms to 5 ms.
2. Send ACK immediately when a sequence gap is detected.
3. Send ACK immediately when board-side buffer pressure is high.
4. Send ACK immediately on serious errors.
5. Do not wait for DMA completion before ACKing received packets.
6. DMA progress should be tracked in statistics, not used as the only ACK trigger.

Retransmission policy on PC side:

1. Maintain a sliding window.
2. Keep sent packets in memory until acknowledged.
3. Use ack_base_seq and ack_bitmap to mark received packets.
4. Retransmit only missing packets.
5. Do not use stop-and-wait.
6. Timeout should be fallback, not primary loss detection.
7. Do not retransmit packets that are already ACKed by bitmap.
8. Support duplicate packet handling on the board side.

Flow control policy:

1. PC sender must read rx_free_bytes from ACK v2.
2. If rx_free_bytes is low, reduce sending rate or window size.
3. If rx_free_bytes is healthy and no loss occurs, cautiously increase window size.
4. Use simple AIMD behavior:
   - stable: slowly increase window
   - busy / loss / timeout: decrease window

Suggested AIMD behavior:

    if stable:
        window_size = min(window_size + 1, max_window)

    if busy_or_timeout_or_loss:
        window_size = max(window_size / 2, min_window)

Acceptance criteria:

- One lost packet should not stall the whole stream.
- Missing packets are selectively retransmitted.
- Board-side buffer overflow should be rare.
- ACK behavior is independent from DMA completion.
- ACK v2 format is documented in README.md.

---

## Phase 5: Improve PC Sender Throughput Mode

Add or improve a dedicated throughput mode in the Python sender.

Requirements:

1. No per-packet print.
2. No per-packet GUI update.
3. CLI throughput test must work without GUI.
4. Use separate send loop and ACK receive loop if practical.
5. Use large socket buffers.
6. Pre-generate packet headers and CRC when possible.
7. Print aggregate statistics periodically only.
8. Support large test sizes such as 64 MB, 256 MB, or continuous mode.

Suggested CLI example:

    python send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 64 --throughput-mode

Throughput mode should report:

- PC send rate
- ACKed rate
- estimated board receive rate
- retransmission count
- timeout count
- busy count
- RTT estimate
- current window size
- board rx_free_bytes if ACK v2 is enabled

Do not allow console or GUI refresh to dominate runtime.

Acceptance criteria:

- Sender can push data fast enough to test board-side bottlenecks.
- Throughput test does not depend on Tkinter GUI.
- Progress output is periodic and lightweight.
- Sender supports ACK v2 and selective retransmission.

---

## Phase 6: Optional D-Cache Optimization

Only consider D-cache after Phase 1 to Phase 5 are stable.

If enabling D-cache:

1. Flush DMA TX buffers before MM2S starts.
2. Make sure flush range is aligned correctly.
3. Do not read stale DMA-related memory.
4. Consider making DMA buffer region non-cacheable if needed.
5. Keep compile-time switch:

    #define APP_ENABLE_ICACHE 1
    #define APP_ENABLE_DCACHE 0

Change APP_ENABLE_DCACHE to 1 only after careful testing.

Acceptance criteria:

- No corrupted DMA payload.
- D-cache version is compared against I-cache-only version.
- Any throughput improvement is measurable.
- README.md documents the cache policy.

---

## Phase 7: Optional AXI DMA SG Mode

Do not implement SG DMA first.

Only consider SG DMA after aggregation is working and measurements show that simple DMA start/interrupt overhead is still a bottleneck.

If SG DMA is implemented:

1. Use descriptor ring.
2. Submit multiple aggregation blocks at once.
3. Keep interrupt handler minimal.
4. Reclaim completed descriptors outside ISR.
5. Preserve simple DMA mode as fallback.
6. Add compile-time config:

    #define DMA_USE_SG_MODE 0

Acceptance criteria:

- SG mode is optional.
- Simple DMA mode still works.
- SG mode improves measured throughput or lowers CPU overhead.

---

## Robustness Improvements

Add protection against invalid input and runtime failures.

Required checks:

1. Validate magic.
2. Validate header length.
3. Validate payload length.
4. Validate CRC if enabled.
5. Validate sequence number range.
6. Reject packets larger than configured chunk size.
7. Reject packets that cannot fit into aggregation buffer.
8. Handle duplicate packets safely.
9. Handle out-of-order packets safely.
10. Never write outside buffer boundaries.
11. Never overwrite DMA-owned block.
12. Recover from DMA error if possible.

DMA watchdog:

Add a simple DMA watchdog.

If DMA remains busy for too long or error flag is set:

1. Stop or reset DMA.
2. Mark DMA error in statistics.
3. Reclaim or reset DMA-owned blocks safely.
4. Send error flag in ACK v2.
5. Continue operation if possible.

Do not let one DMA error permanently hang the whole application.

---

## Testing Plan

Run these tests after every major change.

Basic correctness:

    python send_data.py --ip 192.168.1.50 --test-size 64 --chunk-size 32 --window-size 1
    python send_data.py --ip 192.168.1.50 --test-size 4096
    python send_data.py --ip 192.168.1.50 --test-size 65536

Throughput tests:

    python send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 16 --throughput-mode
    python send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 32 --throughput-mode
    python send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 64 --throughput-mode

Compare these metrics:

- PC send rate
- board RX rate
- DMA rate
- queue occupancy
- aggregation average block size
- busy count
- timeout count
- retransmission count
- DMA error count
- CRC error count
- DMA starts per MB

Expected improvement:

- larger average DMA transfer size
- fewer DMA starts per MB
- higher PS->PL DMA utilization
- lower per-packet CPU overhead
- fewer BUSY responses
- more stable long-duration streaming

---

## Documentation Requirements

Update README.md after implementation.

Must document:

1. New cache policy.
2. New STAT output fields.
3. New aggregation block design.
4. New ACK v2 packet format.
5. New retransmission behavior.
6. New flow-control behavior.
7. New sender options.
8. Recommended throughput test commands.
9. Known limitations.

Also update comments in related config headers.

---

## Final Expected Architecture

Before optimization:

    one UDP chunk
    -> one DMA slot
    -> one short DMA transfer
    -> high per-packet and per-transfer overhead

After optimization:

    many UDP chunks
    -> one PS-side aggregation block
    -> one longer DMA transfer
    -> more continuous PL input stream
    -> ACK bitmap + selective retransmission
    -> board-side flow control

The key principle is:

Do not tune small parameters blindly. First reduce fixed overhead per payload byte.

Prioritize architectural throughput improvement over temporary parameter hacks.