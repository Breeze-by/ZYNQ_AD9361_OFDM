# Next Session Handoff

## Current Verified State

The project is now stable after Phase 1/2/3 changes:

- Board-side periodic `STAT` output is working.
- I-cache is enabled and D-cache remains disabled.
- PS-side DMA aggregation is implemented and functional.
- GUI has throughput controls, including `Throughput Mode`, default `window=64`, and `64 MiB` / `256 MiB` test presets.

Latest user test after GUI/window update:

```text
PC delivered ~= 231 KiB/s
inflight ~= 63
PS rx ~= 231 KiB/s
PS dma ~= 230 KiB/s
rx_pkt = 163 per STAT interval
dma_done = 27 or 28 per STAT interval
q = 1/8 or 2/8
qmax = 2
busy = 0
pending = 0
crc = 0
dma_err = 0
agg_avg = 8736
agg_min = 8736
agg_max = 8736
agg_full = 0
agg_to = all submitted blocks
```

Interpretation:

- Aggregation is working: `dma_done` is about `rx_pkt / 6`.
- Link is stable: no CRC, busy, pending, drop, or DMA errors.
- Throughput did not improve: still around `231 KiB/s`.
- Increasing host window from `16` to `64` did not improve throughput.
- Bottleneck is no longer per-DMA-start overhead alone.

## Important Current Files

- Board RX/aggregation path: `AD9361_test2/src/drivers/net/net_rx.c`
- Network parameters: `AD9361_test2/src/drivers/net/net_config.h`
- Board stats: `AD9361_test2/src/drivers/net/net_stats.c`, `net_stats.h`
- Host sender core: `AD9361_test2/tools/pc_sender/sender_core.py`
- Host GUI: `AD9361_test2/tools/pc_sender/sender_gui.py`

## Current Key Parameters

Board:

```c
APP_ENABLE_ICACHE = 1
APP_ENABLE_DCACHE = 0
NET_AGG_BLOCK_BYTES = 16384
NET_AGG_BLOCK_COUNT = 8
NET_AGG_MIN_FLUSH_BYTES = 8192
NET_AGG_FLUSH_TIMEOUT_US = 1000
NET_AGG_IDLE_FLUSH_TIMEOUT_US = 100000
NET_MAX_RECOMMENDED_WINDOW_SIZE = 64
```

Host GUI defaults:

```text
chunk_size = 1456
window_size = 64
test_size = 64 MiB
progress_ms = 1000
throughput_mode = true
verbose_events = false
```

## What Not To Do Next

- Do not keep increasing `window_size` blindly. `inflight=63`, `qmax=2`, and `busy=0` show the board is not being filled faster by window alone.
- Do not start with SG DMA. Aggregation already reduced DMA starts significantly, but throughput stayed flat.
- Do not enable D-cache yet. There is no proof that cache coherency risk is worth it before finding the current host/ACK pacing bottleneck.
- Do not rewrite the full protocol and ACK v2 immediately unless measurements first show ACK receive handling is the bottleneck.

## Most Likely Next Investigation

The constant `~231 KiB/s` with `rx_pkt=163/s` suggests a pacing or ACK-loop limit on the host side:

```text
163 packets/s * 1456 bytes ~= 237 KiB/s
```

The host still appears to send in bursts but only sustains about `163` accepted packets per second. Since board `busy=0` and `qmax<=2`, the sender is probably not continuously feeding the board.

Focus next on host sender architecture:

1. Inspect `UdpSender.send()` in `sender_core.py`.
2. Check whether the single-thread send/receive loop is effectively ACK-paced.
3. Add sender-side counters:
   - packets_sent_per_second
   - ack_received_per_second
   - send_loop_sleep_time
   - socket_timeout_wakeups
   - outstanding window occupancy over time
4. In throughput mode, consider splitting into:
   - one send loop that fills the window aggressively
   - one ACK receive loop that drains ACKs and updates outstanding state
5. Ensure progress/log callbacks cannot throttle send/ACK handling.

## Suggested Next Code Change

Implement a dedicated GUI/CLI throughput sender path without changing the wire protocol yet:

- Pre-build all UDP packets for generated test data or build packets ahead of the hot loop.
- Keep a larger in-memory packet table.
- Send packets until `outstanding >= window_size`.
- Drain all available ACKs in a tight loop before sleeping.
- Avoid `recvfrom` timeout cadence becoming the main scheduler.
- Print/log only once per `progress_interval_s`.

If the sender can push faster and board stats then show:

```text
rx increases
qmax increases
agg_full increases
agg_avg approaches 16 KiB
busy may become nonzero at very high offered load
```

then the bottleneck was host sender pacing.

If sender-side packet rate increases but board `rx` remains fixed near `231 KiB/s`, investigate lwIP receive/input polling and board-side CPU time next.

## Validation Commands

Use GUI first, not CLI:

```text
Mode: Test Data
Throughput Mode: enabled
Test size: 64 MiB or 256 MiB
Chunk Bytes: 1456
Window Size: 64
Progress ms: 1000
Verbose Packet Events: disabled
```

Expected good aggregation baseline:

```text
agg_avg >= 8192
dma_done << rx_pkt
busy = 0 initially
crc = 0
dma_err = 0
```

Target improvement:

```text
PC delivered > 231 KiB/s
PS rx > 231 KiB/s
agg_avg closer to 16384
agg_full > 0 during sustained transfer
```
