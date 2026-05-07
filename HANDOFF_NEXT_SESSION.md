# Next Session Handoff

## Current Verified State

The project is now stable after Phase 1/2/3 changes:

- Board-side periodic `STAT` output is working.
- I-cache is enabled and D-cache remains disabled.
- PS-side DMA aggregation is implemented and functional.
- GUI has throughput controls, including `Throughput Mode`, default `window=64`, and `64 MiB` / `256 MiB` test presets.
- Host throughput mode now has a dedicated non-blocking sender path:
  - packets are cached while outstanding
  - the sender fills `outstanding` up to `window_size`
  - all currently available ACKs are drained before sleeping
  - progress/log callbacks remain aggregate and interval-throttled
- Host-side diagnostics now include `tx_pkt`, `ack_rx`, `occ_avg`, `occ_max`, `idle_sleep`, and `empty`.
- New board-side optimization after the latest user run:
  - CRC32 is table-driven via `NET_CRC32_USE_TABLE=1`
  - normal ACK v1 `OK` responses are coalesced via `NET_ACK_COALESCE_ENABLE=1`
  - `NET_ACK_COALESCE_PACKET_COUNT=8`
  - `NET_ACK_COALESCE_TIMEOUT_US=1000`
  - error, duplicate, and `BUSY` ACKs remain immediate
  - `Net_Poll()` now drains up to `NET_INPUT_POLL_BUDGET=32` packets per main-loop pass
- Reliability fix after high-BUSY run:
  - `NET_STRICT_IN_ORDER_RX=1`
  - board accepts only `seq == expected_seq` into aggregation memory
  - higher sequence numbers return `PENDING` and are not written to DMA stream
  - host treats `PENDING` as a short-backoff retry
  - host throughput mode now uses AIMD-style adaptive effective window on `BUSY`, `PENDING`, and timeout
  - board `STAT` now includes `acc` / `acc_pkt` for accepted payload rate, distinct from offered `rx` / `rx_pkt`
- UART/STAT formatting fix:
  - `UART_Printf()` buffer increased from 256 to 512 bytes
  - periodic stats are split into `STAT rate ...` and `STAT state ...`
  - this avoids truncating the trailing `\r\n` when stats fields grow

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

The constant `~231 KiB/s` with `rx_pkt=163/s` suggested a pacing or ACK-loop limit on the host side:

```text
163 packets/s * 1456 bytes ~= 237 KiB/s
```

The host-side throughput path has now been changed to test that hypothesis without changing the wire protocol. The next board run should compare the new host metrics against board `STAT`.

Check the new host metrics first:

```text
tx_pkt ~= host offered packet rate
ack_rx ~= board ACK return rate
occ_avg/occ_max ~= how full the host window stays
idle_sleep / empty ~= whether the sender is often waiting with no ACK/retry/send work
```

## Completed In This Session

Implemented the suggested host-side throughput sender path without changing the wire protocol:

- `AD9361_test2/tools/pc_sender/sender_core.py`
  - added throughput-mode `_send_throughput()`
  - added cached outstanding packets
  - added non-blocking ACK drain loop
  - added sender-side counters
- `AD9361_test2/tools/pc_sender/sender_gui.py`
  - added metrics display/logging for packet rates, window occupancy, idle sleep, and empty polls
- `AD9361_test2/README.md`
  - documented the throughput sender path and new metrics

Local verification completed:

```text
python -m py_compile sender_core.py sender_gui.py send_data.py
python send_data.py --help
local UDP ACK simulator:
  throughput path acked 65536 bytes
  legacy path acked 65536 bytes
```

## Next Board Test Interpretation

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

If `tx_pkt` and `ack_rx` remain stuck near `163/s` while `occ_avg` stays close to `window_size`, the board or network path is probably returning ACKs at that rate and host windowing alone is no longer the primary bottleneck.

If `occ_avg` is low and `empty` / `idle_sleep` grow quickly, the host is still waiting too often and the next step is a true two-thread sender/ACK receiver or deeper OS/socket inspection.

Latest user run with the host sender change showed:

```text
PC delivered ~= 230 KiB/s
tx_pkt ~= 164/s
ack_rx ~= 159/s
occ ~= 63.9/64
PS rx_pkt ~= 162/s
PS rx ~= 230 KiB/s
busy = 0
qmax = 2
agg_avg = 8736
agg_full = 0
```

Interpretation: this did not meet the host-pacing improvement target. The host
window stayed full, so the next optimization moved to board-side fixed per-packet
cost: bitwise CRC and per-packet ACK transmit.

Latest user run after CRC/ACK/input-drain changes showed:

```text
PC delivered ~= 2921 KiB/s
tx_pkt ~= 2079/s
ack_rx ~= 1484/s
busy ~= 29410 by end
PS rx ~= 2978 KiB/s
PS dma ~= 1024 KiB/s
rx_pkt ~= 2111/s
q = 8/8
qmax = 8
agg_full ~= all blocks
crc = 0
dma_err = 0
```

Interpretation: throughput improved, but the previous ACK v1 cumulative behavior
was unsafe under high `BUSY`. Because `rx` counted offered packets before acceptance,
PC delivered could overstate real accepted/DMA data. The reliability fix above was
implemented to prevent mis-ACK/data loss.

## Next Board Test Interpretation After CRC/ACK Changes

Expected signs of improvement:

```text
PS acc_pkt > 162/s
PS acc > 230 KiB/s
PC delivered should track PS acc, not offered rx
ack count grows much slower than rx_pkt, about rx_pkt / 8 on clean transfers
agg_avg increases beyond 8736
agg_full may become nonzero if enough packets arrive before timeout
crc = 0
busy should be much lower after adaptive window settles
pending may appear briefly when strict ordering rejects ahead-of-gap packets
dma_err = 0
```

If throughput improves significantly, continue tuning `NET_ACK_COALESCE_PACKET_COUNT`
between `4`, `8`, and `16` and compare host `occ_avg`, board `acc_pkt`, and loss/error
counters.

If throughput still remains near `230 KiB/s`, the next likely bottleneck is deeper
lwIP/GEM RX path overhead, interrupt behavior, or memory/cache attributes. Consider
adding board-side timing counters around `xemacif_input()`, `net_udp_receive_callback()`,
CRC, ACK send, and `pbuf_copy_partial()`.

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
