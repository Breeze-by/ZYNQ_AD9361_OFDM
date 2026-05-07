#ifndef AD9361_TEST2_NET_STATS_H_
#define AD9361_TEST2_NET_STATS_H_

#include "COMMON.h"
#include "net_config.h"

typedef struct {
    uint64_t rx_packets;
    uint64_t rx_bytes;
    uint64_t rx_payload_bytes;
    uint64_t bad_magic_count;
    uint64_t bad_length_count;
    uint64_t crc_error_count;
    uint64_t duplicate_count;
    uint64_t pending_count;
    uint64_t busy_count;
    uint64_t dropped_count;
    uint64_t dma_start_count;
    uint64_t dma_done_count;
    uint64_t dma_error_count;
    uint64_t dma_bytes_total;
    uint32_t queue_occupancy_current;
    uint32_t queue_occupancy_max;
    uint64_t ack_tx_count;
    uint64_t nack_tx_count;
    uint64_t retransmit_rx_count;
    uint64_t agg_block_submit_count;
    uint64_t agg_flush_full_count;
    uint64_t agg_flush_timeout_count;
    uint64_t agg_bytes_total;
    uint32_t agg_min_block_bytes;
    uint32_t agg_max_block_bytes;
} net_stats_t;

void NetStats_Init(void);
const net_stats_t *NetStats_Get(void);
void NetStats_OnRxPacket(uint32_t packet_bytes, uint32_t payload_bytes);
void NetStats_OnBadMagic(void);
void NetStats_OnBadLength(void);
void NetStats_OnCrcError(void);
void NetStats_OnDuplicate(void);
void NetStats_OnPending(void);
void NetStats_OnBusy(void);
void NetStats_OnDropped(void);
void NetStats_OnDmaStart(void);
void NetStats_OnDmaDone(uint32_t dma_bytes);
void NetStats_OnDmaError(void);
void NetStats_OnAck(net_ack_status_t status);
void NetStats_SetQueue(uint32_t current, uint32_t max_seen);
void NetStats_PrintPeriodic(void);

#endif /* AD9361_TEST2_NET_STATS_H_ */
