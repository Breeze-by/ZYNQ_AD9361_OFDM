#include "net_stats.h"

#include "PS_UART.h"
#include "xtime_l.h"

static net_stats_t net_stats;
static XTime stats_start_time;
static XTime stats_last_print_time;
static uint64_t last_rx_bytes;
static uint64_t last_accepted_bytes;
static uint64_t last_dma_bytes;
static uint64_t last_rx_packets;
static uint64_t last_accepted_packets;
static uint64_t last_dma_done;

static uint64_t stats_elapsed_us(XTime start_time, XTime end_time)
{
    if ((end_time <= start_time) || (COUNTS_PER_SECOND == 0U)) {
        return 0U;
    }

    return ((uint64_t)(end_time - start_time) * 1000000ULL) / (uint64_t)COUNTS_PER_SECOND;
}

static uint32_t stats_rate_x100_kib(uint64_t bytes, uint64_t elapsed_us)
{
    if (elapsed_us == 0U) {
        return 0U;
    }

    return (uint32_t)((bytes * 100ULL * 1000000ULL) / (1024ULL * elapsed_us));
}

static uint32_t stats_avg_agg_bytes(void)
{
    if (net_stats.agg_block_submit_count == 0U) {
        return 0U;
    }

    return (uint32_t)(net_stats.agg_bytes_total / net_stats.agg_block_submit_count);
}

void NetStats_Init(void)
{
    memset(&net_stats, 0, sizeof(net_stats));
    XTime_GetTime(&stats_start_time);
    stats_last_print_time = stats_start_time;
    last_rx_bytes = 0U;
    last_accepted_bytes = 0U;
    last_dma_bytes = 0U;
    last_rx_packets = 0U;
    last_accepted_packets = 0U;
    last_dma_done = 0U;
}

const net_stats_t *NetStats_Get(void)
{
    return &net_stats;
}

void NetStats_OnRxPacket(uint32_t packet_bytes, uint32_t payload_bytes)
{
    net_stats.rx_packets += 1U;
    net_stats.rx_bytes += packet_bytes;
    net_stats.rx_payload_bytes += payload_bytes;
}

void NetStats_OnAcceptedPacket(uint32_t payload_bytes)
{
    net_stats.accepted_packets += 1U;
    net_stats.accepted_payload_bytes += payload_bytes;
}

void NetStats_OnBadMagic(void)
{
    net_stats.bad_magic_count += 1U;
    net_stats.dropped_count += 1U;
}

void NetStats_OnBadLength(void)
{
    net_stats.bad_length_count += 1U;
    net_stats.dropped_count += 1U;
}

void NetStats_OnCrcError(void)
{
    net_stats.crc_error_count += 1U;
    net_stats.dropped_count += 1U;
}

void NetStats_OnDuplicate(void)
{
    net_stats.duplicate_count += 1U;
    net_stats.retransmit_rx_count += 1U;
}

void NetStats_OnPending(void)
{
    net_stats.pending_count += 1U;
    net_stats.retransmit_rx_count += 1U;
}

void NetStats_OnBusy(void)
{
    net_stats.busy_count += 1U;
}

void NetStats_OnDropped(void)
{
    net_stats.dropped_count += 1U;
}

void NetStats_OnDmaStart(void)
{
    net_stats.dma_start_count += 1U;
}

void NetStats_OnDmaDone(uint32_t dma_bytes)
{
    net_stats.dma_done_count += 1U;
    net_stats.dma_bytes_total += dma_bytes;
}

void NetStats_OnDmaError(void)
{
    net_stats.dma_error_count += 1U;
}

void NetStats_OnAck(net_ack_status_t status)
{
    net_stats.ack_tx_count += 1U;
    if (status != NET_ACK_STATUS_OK) {
        net_stats.nack_tx_count += 1U;
    }
}

void NetStats_SetQueue(uint32_t current, uint32_t max_seen)
{
    net_stats.queue_occupancy_current = current;
    if (max_seen > net_stats.queue_occupancy_max) {
        net_stats.queue_occupancy_max = max_seen;
    }
}

void NetStats_OnAggSubmit(uint32_t block_bytes)
{
    net_stats.agg_block_submit_count += 1U;
    net_stats.agg_bytes_total += block_bytes;
    if ((net_stats.agg_min_block_bytes == 0U) || (block_bytes < net_stats.agg_min_block_bytes)) {
        net_stats.agg_min_block_bytes = block_bytes;
    }
    if (block_bytes > net_stats.agg_max_block_bytes) {
        net_stats.agg_max_block_bytes = block_bytes;
    }
}

void NetStats_OnAggFlushFull(void)
{
    net_stats.agg_flush_full_count += 1U;
}

void NetStats_OnAggFlushTimeout(void)
{
    net_stats.agg_flush_timeout_count += 1U;
}

void NetStats_PrintPeriodic(void)
{
    XTime now_time;
    uint64_t interval_us;
    uint64_t total_us;
    uint64_t interval_rx_bytes;
    uint64_t interval_accepted_bytes;
    uint64_t interval_dma_bytes;
    uint64_t interval_rx_packets;
    uint64_t interval_accepted_packets;
    uint64_t interval_dma_done;
    uint32_t rx_rate_x100_kib;
    uint32_t accepted_rate_x100_kib;
    uint32_t dma_rate_x100_kib;
    uint32_t avg_rx_rate_x100_kib;
    uint32_t avg_accepted_rate_x100_kib;
    uint32_t avg_dma_rate_x100_kib;

    XTime_GetTime(&now_time);
    interval_us = stats_elapsed_us(stats_last_print_time, now_time);
    if (interval_us < NET_STATS_PRINT_INTERVAL_US) {
        return;
    }

    total_us = stats_elapsed_us(stats_start_time, now_time);
    interval_rx_bytes = net_stats.rx_payload_bytes - last_rx_bytes;
    interval_accepted_bytes = net_stats.accepted_payload_bytes - last_accepted_bytes;
    interval_dma_bytes = net_stats.dma_bytes_total - last_dma_bytes;
    interval_rx_packets = net_stats.rx_packets - last_rx_packets;
    interval_accepted_packets = net_stats.accepted_packets - last_accepted_packets;
    interval_dma_done = net_stats.dma_done_count - last_dma_done;
    rx_rate_x100_kib = stats_rate_x100_kib(interval_rx_bytes, interval_us);
    accepted_rate_x100_kib = stats_rate_x100_kib(interval_accepted_bytes, interval_us);
    dma_rate_x100_kib = stats_rate_x100_kib(interval_dma_bytes, interval_us);
    avg_rx_rate_x100_kib = stats_rate_x100_kib(net_stats.rx_payload_bytes, total_us);
    avg_accepted_rate_x100_kib = stats_rate_x100_kib(net_stats.accepted_payload_bytes, total_us);
    avg_dma_rate_x100_kib = stats_rate_x100_kib(net_stats.dma_bytes_total, total_us);

    UART_Printf(
        "STAT rate rx=%lu.%02lu acc=%lu.%02lu dma=%lu.%02lu "
        "avg_rx=%lu.%02lu avg_acc=%lu.%02lu avg_dma=%lu.%02lu "
        "rx_pkt=%lu acc_pkt=%lu dma_done=%lu\r\n",
        (unsigned long)(rx_rate_x100_kib / 100U),
        (unsigned long)(rx_rate_x100_kib % 100U),
        (unsigned long)(accepted_rate_x100_kib / 100U),
        (unsigned long)(accepted_rate_x100_kib % 100U),
        (unsigned long)(dma_rate_x100_kib / 100U),
        (unsigned long)(dma_rate_x100_kib % 100U),
        (unsigned long)(avg_rx_rate_x100_kib / 100U),
        (unsigned long)(avg_rx_rate_x100_kib % 100U),
        (unsigned long)(avg_accepted_rate_x100_kib / 100U),
        (unsigned long)(avg_accepted_rate_x100_kib % 100U),
        (unsigned long)(avg_dma_rate_x100_kib / 100U),
        (unsigned long)(avg_dma_rate_x100_kib % 100U),
        (unsigned long)interval_rx_packets,
        (unsigned long)interval_accepted_packets,
        (unsigned long)interval_dma_done);

    UART_Printf(
        "STAT state q=%lu/%u qmax=%lu ack=%lu nack=%lu "
        "crc=%lu badlen=%lu badmagic=%lu busy=%lu pend=%lu dup=%lu drop=%lu dma_err=%lu "
        "agg=%lu agg_full=%lu agg_to=%lu agg_avg=%lu agg_min=%lu agg_max=%lu\r\n",
        (unsigned long)net_stats.queue_occupancy_current,
        (unsigned)NET_DMA_QUEUE_CAPACITY,
        (unsigned long)net_stats.queue_occupancy_max,
        (unsigned long)net_stats.ack_tx_count,
        (unsigned long)net_stats.nack_tx_count,
        (unsigned long)net_stats.crc_error_count,
        (unsigned long)net_stats.bad_length_count,
        (unsigned long)net_stats.bad_magic_count,
        (unsigned long)net_stats.busy_count,
        (unsigned long)net_stats.pending_count,
        (unsigned long)net_stats.duplicate_count,
        (unsigned long)net_stats.dropped_count,
        (unsigned long)net_stats.dma_error_count,
        (unsigned long)net_stats.agg_block_submit_count,
        (unsigned long)net_stats.agg_flush_full_count,
        (unsigned long)net_stats.agg_flush_timeout_count,
        (unsigned long)stats_avg_agg_bytes(),
        (unsigned long)net_stats.agg_min_block_bytes,
        (unsigned long)net_stats.agg_max_block_bytes);

    stats_last_print_time = now_time;
    last_rx_bytes = net_stats.rx_payload_bytes;
    last_accepted_bytes = net_stats.accepted_payload_bytes;
    last_dma_bytes = net_stats.dma_bytes_total;
    last_rx_packets = net_stats.rx_packets;
    last_accepted_packets = net_stats.accepted_packets;
    last_dma_done = net_stats.dma_done_count;
}
