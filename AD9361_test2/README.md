# AD9361_test2 Data Path

This document describes the software-only part of the project. Only files under `AD9361_test2` are intended to be edited; BSP and hardware export directories remain generated artifacts.

## Scope

- Board-side application: `src/`
- Host sender tools: `tools/pc_sender/`
- Do not edit: `AD9361_test2_bsp/`, `System_wrapper_hw_platform_0/`, `System_wrapper.hdf`

## Runtime Pipeline

The current transmit path is:

1. The PC sender splits the source bytes into numbered UDP chunks.
2. Each chunk is sent as `net_data_header_t + payload`.
3. lwIP receives the UDP packet on PS.
4. `net_udp_receive_callback()` validates header, length, and CRC32.
5. The payload is appended into the current PS-side DMA aggregation block.
6. A block is submitted when it is full or when the flush timeout expires.
7. `Net_RxPoll()` starts one longer MM2S DMA transfer for each READY block.
8. `TxIntrHandler()` marks completion.
9. `Net_RxPoll()` releases the completed block and starts the next queued block.

ACK v1 is now sent after the packet is safely accepted into PS memory, not after DMA completion. lwIP owns the short-lived RX `pbuf`; after validation, the application copies payload directly into a persistent DMA aggregation block.

## Sliding Window and ACK Model

The link now uses a bounded sliding-window sender instead of the old stop-and-wait path:

- The host may have multiple in-flight chunks.
- The board keeps DMA aggregation blocks and a small accepted-history cache.
- Retransmitted chunks are deduplicated:
  - If a chunk is already completed, the board resends `OK`.
  - If a chunk is still active or queued, the board returns `PENDING`.
  - If the queue is full and the sequence is new, the board returns `BUSY`.
- Successful `OK` ACKs mean the payload was accepted into PS memory.

The current implementation is intended for direct or normal LAN links where chunks are sent and received in sequence. The host treats `OK seq=N` as confirmation for all outstanding chunks with `seq <= N`. If the design must tolerate strong UDP reordering, the board should be changed to ACK a true contiguous-completed sequence or to emit per-chunk `OK` ACKs.

## ACK Meanings

`OK`

- ACK for successful packet acceptance into PS aggregation memory.
- The host treats every outstanding chunk with `chunk_seq <= ack.seq` as completed.
- This assumes the normal direct-link case where accepted chunks progress through the board in sequence.

`PENDING`

- Reserved in the current aggregation path.
- Duplicate accepted chunks are answered with `OK`.

`BUSY`

- The board queue is full and the chunk was not accepted.
- The host retries later with a short backoff.

`BAD_MAGIC`, `BAD_LENGTH`, `BAD_CHECKSUM`, `DMA_ERROR`

- Hard failures for that transmission attempt.

## Key Tuning Parameters

Board-side values:

- `src/app/app_config.h`
  - `APP_ENABLE_ICACHE = 1`
  - `APP_ENABLE_DCACHE = 0`
  - `TX_BUFFER_WORD_COUNT = 16384`
  - Total DMA TX buffer = `16384 * 8 = 131072` bytes
- `src/drivers/net/net_config.h`
  - `NET_AGG_ENABLE = 1`
  - `NET_AGG_BLOCK_COUNT = 8`
  - `NET_AGG_BLOCK_BYTES = 16384`
  - `NET_AGG_MIN_FLUSH_BYTES = 8192`
  - `NET_AGG_FLUSH_TIMEOUT_US = 1000`
  - `NET_AGG_IDLE_FLUSH_TIMEOUT_US = 100000`
  - Total aggregation buffer = `8 * 16384 = 131072` bytes
  - `NET_DEFAULT_CHUNK_SIZE_BYTES = 1456`
  - `NET_MAX_RECOMMENDED_WINDOW_SIZE = 64`

Host defaults:

- `chunk_size = 1456`
- `window_size = 64`
- `socket_buffer_bytes = 4194304`
- `progress_interval_ms = 100`
- `verbose_events = false`
- `throughput_mode = true` in the GUI

`1456` is chosen to keep `16-byte application header + 1456-byte payload = 1472-byte UDP payload`, which stays within the common Ethernet MTU without IP fragmentation.

## Throughput Limits

The dominant software limits are usually:

- lwIP receive and `pbuf` handling
- CRC32 calculation per packet
- payload copy into DMA slots
- aggregation block fill/flush behavior
- ACK turnaround
- board-side aggregation capacity and host retry behavior
- UART logging overhead if verbose logs are enabled

The DMA engine itself is normally faster than the observed end-to-end throughput. For that reason:

- packet-level UART logging stays disabled by default
- the board aggregates multiple UDP chunks before DMA
- the host window is allowed to exceed `1`
- ACK is sent on PS buffer acceptance rather than DMA completion
- the host GUI no longer logs every packet by default
- host progress updates are throttled to reduce `PC -> PS` overhead

## Throughput Metrics

Host-side metrics now use two different meanings:

- `Delivered`
  - confirmed payload throughput based on `bytes_acked / total_elapsed_time`
  - this is the best high-level measure of real end-to-end throughput
- `Last ACK Rate`
  - single-chunk rate derived from `transfer_len / ACK_RTT`
  - useful for latency inspection, but not equal to sustained throughput

In `--throughput-mode`, the host uses a dedicated tight sender path. It keeps
packet bytes cached while they are outstanding, fills the configured window
aggressively, drains all currently available ACKs with a non-blocking socket,
and only emits aggregate progress at the configured interval. This keeps the
test from being paced by per-packet logging or by a long `recvfrom` timeout.

Additional host-side throughput diagnostics:

- `tx_pkt`
  - host UDP packets sent per second, including retransmissions
- `ack_rx`
  - ACK packets received per second
- `occ_avg` / `occ_max`
  - sampled outstanding-window occupancy average and maximum
- `idle_sleep`
  - total time spent sleeping because no ACK/retry/send work was immediately available
- `empty`
  - count of empty non-blocking receive polls / timeout wakeups

Board-side `STAT ...` is printed by `src/drivers/net/net_stats.c` about once per second. It reports interval and average RX/DMA rates, packet and DMA completion counts, aggregation block occupancy, ACK/NACK counts, protocol errors, duplicate/pending/busy counts, and aggregation counters. After aggregation is working, `dma_done` should be much lower than `rx_pkt`, while `agg_avg` should be much larger than one UDP chunk.

Example throughput command:

```bash
python tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 64 --throughput-mode
```

The same test can be run from the GUI by selecting `Test Data`, keeping `Throughput Mode` enabled, clicking `64 MiB`, and pressing `Start`.

## Recommended Operating Range

Start with:

- `chunk_size = 1456`
- `window_size = 64`
- `target_rate_kib_s = 0`

If stable, try:

1. Keep `window_size = 64` as the current recommended upper bound.
2. If you go above `64`, first confirm `busy=0` and the aggregation buffers are not persistently full.

Only increase `chunk_size` if you also re-check the MTU budget. Going above `1456` payload bytes will usually trigger IP fragmentation and often reduces real throughput.

## Important Files

- Board entry: `src/app/main.c`
- Network init: `src/drivers/net/net_init.c`
- RX queue, DMA scheduling, ACK logic: `src/drivers/net/net_rx.c`
- Board-side stats: `src/drivers/net/net_stats.c`, `src/drivers/net/net_stats.h`
- Protocol structs and CRC helpers: `src/drivers/net/net_protocol.h`, `src/drivers/net/net_protocol.c`
- DMA IRQ wrapper: `src/drivers/dma/AXI_DMA.c`
- Host sender core: `tools/pc_sender/sender_core.py`
- Host GUI: `tools/pc_sender/sender_gui.py`

## Practical Notes

- The board now acknowledges after PS-side buffer acceptance, not after DMA completion.
- `PENDING` is reserved; duplicate accepted chunks are answered with `OK`.
- If throughput is still limited, inspect board UART stats first:
  - aggregation block occupancy
  - `agg_avg`
  - `dma_done` versus `rx_pkt`
  - `busy` count
  - `err` count

High `busy` means the aggregation buffer is full for the offered load.
If `agg_avg` remains near one chunk, the sender is still not feeding PS fast enough or the flush timeout is too small.
