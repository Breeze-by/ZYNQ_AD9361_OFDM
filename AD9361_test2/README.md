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
5. The payload is copied directly into one DMA TX slot inside the board-side ring buffer.
6. The slot is queued for MM2S DMA.
7. `Net_RxPoll()` starts DMA when the engine is idle.
8. `TxIntrHandler()` marks completion.
9. `Net_RxPoll()` sends an ACK only after DMA completion, then releases the slot and starts the next queued transfer.

There is no second application-level "UDP buffer to DMA buffer" copy stage. lwIP owns the short-lived RX `pbuf`; after validation, the application copies payload directly into the persistent DMA slot buffer.

## Sliding Window and ACK Model

The link now uses a bounded sliding-window sender instead of the old stop-and-wait path:

- The host may have multiple in-flight chunks.
- The board keeps a DMA queue and a small completed-history cache.
- Retransmitted chunks are deduplicated:
  - If a chunk is already completed, the board resends `OK`.
  - If a chunk is still active or queued, the board returns `PENDING`.
  - If the queue is full and the sequence is new, the board returns `BUSY`.
- Successful `OK` ACKs are batched and cumulative from the host's point of view.

The current implementation is intended for direct or normal LAN links where chunks are sent and received in sequence. The host treats `OK seq=N` as confirmation for all outstanding chunks with `seq <= N`. If the design must tolerate strong UDP reordering, the board should be changed to ACK a true contiguous-completed sequence or to emit per-chunk `OK` ACKs.

## ACK Meanings

`OK`

- Batched ACK for successful DMA completions.
- The host treats every outstanding chunk with `chunk_seq <= ack.seq` as completed.
- This assumes the normal direct-link case where accepted chunks progress through the board in sequence.

`PENDING`

- The board has already accepted the chunk and it is either queued or currently active.
- The host should keep waiting instead of treating it as a hard error.

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
  - `NET_TX_QUEUE_DEPTH = 32`
  - Slot size = `131072 / 32 = 4096` bytes
  - `NET_DEFAULT_CHUNK_SIZE_BYTES = 1456`
  - `NET_MAX_RECOMMENDED_WINDOW_SIZE = 32`
  - `NET_ACK_BATCH_COUNT = 10`

Host defaults:

- `chunk_size = 1456`
- `window_size = 16`
- `socket_buffer_bytes = 4194304`
- `progress_interval_ms = 100`
- `verbose_events = false`
- `throughput_mode = false`

`1456` is chosen to keep `16-byte application header + 1456-byte payload = 1472-byte UDP payload`, which stays within the common Ethernet MTU without IP fragmentation.

## Throughput Limits

The dominant software limits are usually:

- lwIP receive and `pbuf` handling
- CRC32 calculation per packet
- payload copy into DMA slots
- IRQ and ACK turnaround
- queue depth and host retry behavior
- UART logging overhead if verbose logs are enabled

The DMA engine itself is normally faster than the observed end-to-end throughput. For that reason:

- packet-level UART logging stays disabled by default
- the queue depth is larger than before
- the host window is allowed to exceed `1`
- ACK handling is no longer strictly in-order
- the board emits one cumulative `OK` ACK per batch instead of one `OK` per chunk
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

Board-side `STAT ...` is printed by `src/drivers/net/net_stats.c` about once per second. It reports interval and average RX/DMA rates, packet and DMA completion counts, queue depth, ACK/NACK counts, protocol errors, duplicate/pending/busy counts, and reserved aggregation counters. If `qmax` remains near `1`, the DMA engine is not the bottleneck; the host path is feeding PS too slowly.

Example throughput command:

```bash
python tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 32 --throughput-mode
```

## Recommended Operating Range

Start with:

- `chunk_size = 1456`
- `window_size = 16`
- `target_rate_kib_s = 0`

If stable, try:

1. `window_size = 24`
2. `window_size = 32`

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

- The board still acknowledges only after DMA completion, not on queue admission.
- `PENDING` exists only to make retransmissions harmless while a chunk is already in flight.
- If throughput is still limited, inspect board UART stats first:
  - queue occupancy
  - `busy` count
  - `pending` count
  - `err` count

High `busy` means the board queue is too shallow for the offered load.
High `pending` usually means ACKs are delayed or lost but the queueing logic is still working correctly.
