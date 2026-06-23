#include "net_rx.h"

#include "AXI_DMA.h"
#include "PS_UART.h"
#include "net_protocol.h"
#include "net_stats.h"

#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "xil_io.h"
#include "xtime_l.h"
extern void OpenWifi_Tx_Rearm(uint32_t psdu_len);
typedef enum {
    NET_AGG_BLOCK_FREE = 0,
    NET_AGG_BLOCK_FILLING,
    NET_AGG_BLOCK_READY,
    NET_AGG_BLOCK_DMA_BUSY
} net_agg_block_state_t;

typedef struct {
    net_agg_block_state_t state;
    uint8_t *buffer_ptr;
    uint32_t payload_len;
    uint32_t transfer_len;
    uint32_t submit_order;
    uint32_t stream_offset;
    XTime first_write_time;
    XTime last_write_time;
} net_agg_block_t;

typedef struct {
    int valid;
    uint32_t seq;
    uint32_t payload_len;
} net_accepted_chunk_t;

static struct udp_pcb *udp_control_pcb;
static uint8_t *dma_tx_buffer;
static net_agg_block_t agg_blocks[NET_AGG_BLOCK_COUNT];
static net_accepted_chunk_t accepted_history[NET_COMPLETED_HISTORY_DEPTH];
static uint32_t accepted_history_head_index;
static int fill_block_index;
static int dma_block_index;
static int dma_busy;
static int dma_fatal_error;
static uint32_t queue_occupancy_max;
static uint64_t total_accepted_bytes;
static uint32_t next_expected_seq;
static uint32_t next_agg_submit_order;
static int pending_ok_ack_valid;
static ip_addr_t pending_ok_ack_addr;
static u16_t pending_ok_ack_port;
static uint32_t pending_ok_ack_seq;
static uint32_t pending_ok_ack_transfer_len;
static uint32_t pending_ok_ack_count;
static XTime pending_ok_ack_first_time;
static ip_addr_t loopback_return_addr;
static u16_t loopback_return_port;
static int loopback_return_peer_valid;
static int loopback_return_peer_locked;
static uint32_t loopback_return_packet_count;
static uint32_t loopback_return_byte_count;
static uint16_t current_session_id;
static int session_valid;
static int current_session_validate_crc;
static uint8_t *loopback_rx_buffer;
static uint32_t loopback_rx_expected_len;
static uint32_t loopback_tx_expected_len;
static uint32_t loopback_rx_transfer_id;
static uint32_t loopback_rx_done_count;
static uint32_t loopback_rx_error_count;
static XTime loopback_rx_start_time;
static XTime loopback_rx_last_wait_log_time;
static int loopback_rx_busy;
static int loopback_rx_done_for_current;

#define TX_INTF_BASE_ADDR 0x40001000U
#define TX_INTF_REG2_OFFSET 0x08U
#define TX_INTF_REG8_OFFSET 0x20U
#define TX_INTF_REG17_OFFSET 0x44U
#define TX_INTF_LEN_MASK 0x1FFFU
#define TX_INTF_AUTO_START_EN_MASK (1U << 3)
#define TX_INTF_AUTO_START_TH_SHIFT 4U
#define TX_INTF_AUTO_START_TH_MASK (0x3FFU << TX_INTF_AUTO_START_TH_SHIFT)

static int net_should_report_packet_log(void);
static void net_start_dma_transfer(void);

static uint64_t net_elapsed_us(XTime start_time, XTime end_time)
{
    if ((end_time <= start_time) || (COUNTS_PER_SECOND == 0U)) {
        return 0U;
    }

    return ((uint64_t)(end_time - start_time) * 1000000ULL) / (uint64_t)COUNTS_PER_SECOND;
}

static int net_configure_tx_frame(uint32_t psdu_len, uint32_t transfer_len)
{
    uint32_t expected_transfer_len;
    uint32_t dma_words;
    uint32_t auto_start_threshold;
    uint32_t reg_value;

    if ((psdu_len == 0U) || (psdu_len > NET_OFDM_MAX_PSDU_BYTES)) {
        return -1;
    }

    expected_transfer_len = Net_Protocol_Align8(psdu_len);
    if (transfer_len != expected_transfer_len) {
        return -1;
    }

    dma_words = transfer_len / 8U;
    auto_start_threshold = dma_words + 1U;
    if ((dma_words == 0U) || (dma_words > NET_OFDM_MAX_DMA_WORDS) ||
        (auto_start_threshold > 0x3FFU)) {
        return -1;
    }

    reg_value = Xil_In32(TX_INTF_BASE_ADDR + TX_INTF_REG17_OFFSET);
    reg_value = (reg_value & ~TX_INTF_LEN_MASK) | (psdu_len & TX_INTF_LEN_MASK);
    Xil_Out32(TX_INTF_BASE_ADDR + TX_INTF_REG17_OFFSET, reg_value);

    reg_value = Xil_In32(TX_INTF_BASE_ADDR + TX_INTF_REG8_OFFSET);
    reg_value = (reg_value & ~TX_INTF_LEN_MASK) | (dma_words & TX_INTF_LEN_MASK);
    Xil_Out32(TX_INTF_BASE_ADDR + TX_INTF_REG8_OFFSET, reg_value);

    reg_value = Xil_In32(TX_INTF_BASE_ADDR + TX_INTF_REG2_OFFSET);
    reg_value = (reg_value & ~(TX_INTF_AUTO_START_TH_MASK | TX_INTF_AUTO_START_EN_MASK)) |
        ((auto_start_threshold << TX_INTF_AUTO_START_TH_SHIFT) & TX_INTF_AUTO_START_TH_MASK) |
        TX_INTF_AUTO_START_EN_MASK;
    Xil_Out32(TX_INTF_BASE_ADDR + TX_INTF_REG2_OFFSET, reg_value);

    if (net_should_report_packet_log() != 0) {
        UART_Printf("TX frame cfg psdu=%lu transfer=%lu words=%lu threshold=%lu\r\n",
            (unsigned long)psdu_len,
            (unsigned long)transfer_len,
            (unsigned long)dma_words,
            (unsigned long)auto_start_threshold);
    }

    return 0;
}

static int net_should_report_packet_log(void)
{
#if NET_VERBOSE_PACKET_LOG
    return 1;
#else
    return 0;
#endif
}

static uint32_t net_count_nonfree_blocks(void)
{
    uint32_t index;
    uint32_t count = 0U;

    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        if (agg_blocks[index].state != NET_AGG_BLOCK_FREE) {
            count += 1U;
        }
    }

    return count;
}

static void net_update_queue_stats(void)
{
    uint32_t current = net_count_nonfree_blocks();

    if (current > queue_occupancy_max) {
        queue_occupancy_max = current;
    }
    NetStats_SetQueue(current, queue_occupancy_max);
}

static void net_release_empty_fill_block(void)
{
    net_agg_block_t *block;

    if (fill_block_index < 0) {
        return;
    }

    block = &agg_blocks[fill_block_index];
    if ((block->state != NET_AGG_BLOCK_FILLING) || (block->payload_len != 0U)) {
        return;
    }

    block->state = NET_AGG_BLOCK_FREE;
    block->transfer_len = 0U;
    block->submit_order = 0U;
    block->stream_offset = 0U;
    block->first_write_time = 0U;
    block->last_write_time = 0U;
    fill_block_index = -1;
    net_update_queue_stats();
}

static void net_send_ack(const ip_addr_t *addr, u16_t port, uint32_t seq,
    net_ack_status_t status, uint32_t transfer_len)
{
    net_ack_packet_t ack_packet;
    struct pbuf *ack_pbuf;

    if (udp_control_pcb == NULL) {
        return;
    }

    ack_packet.magic = NET_ACK_MAGIC;
    ack_packet.seq = seq;
    ack_packet.status = (uint16_t)status;
    ack_packet.reserved = 0U;
    ack_packet.transfer_len = transfer_len;

    ack_pbuf = pbuf_alloc(PBUF_TRANSPORT, sizeof(ack_packet), PBUF_RAM);
    if (ack_pbuf == NULL) {
        NetStats_OnDropped();
        return;
    }

    memcpy(ack_pbuf->payload, &ack_packet, sizeof(ack_packet));
    udp_sendto(udp_control_pcb, ack_pbuf, addr, port);
    NetStats_OnAck(status);
    pbuf_free(ack_pbuf);
}

static void net_flush_pending_ok_ack(void)
{
#if NET_ACK_COALESCE_ENABLE
    if (pending_ok_ack_valid == 0) {
        return;
    }

    net_send_ack(&pending_ok_ack_addr, pending_ok_ack_port, pending_ok_ack_seq,
        NET_ACK_STATUS_OK, pending_ok_ack_transfer_len);
    pending_ok_ack_valid = 0;
    pending_ok_ack_count = 0U;
    pending_ok_ack_seq = 0U;
    pending_ok_ack_transfer_len = 0U;
    pending_ok_ack_first_time = 0U;
#endif
}

static void net_send_immediate_ack(const ip_addr_t *addr, u16_t port, uint32_t seq,
    net_ack_status_t status, uint32_t transfer_len)
{
    net_flush_pending_ok_ack();
    net_send_ack(addr, port, seq, status, transfer_len);
}

static void net_queue_ok_ack(const ip_addr_t *addr, u16_t port, uint32_t seq,
    uint32_t transfer_len)
{
#if NET_ACK_COALESCE_ENABLE
    if ((pending_ok_ack_valid != 0) &&
        ((pending_ok_ack_port != port) || !ip_addr_cmp(&pending_ok_ack_addr, addr))) {
        net_flush_pending_ok_ack();
    }

    if (pending_ok_ack_valid == 0) {
        XTime_GetTime(&pending_ok_ack_first_time);
        pending_ok_ack_addr = *addr;
        pending_ok_ack_port = port;
        pending_ok_ack_count = 0U;
        pending_ok_ack_valid = 1;
    }

    pending_ok_ack_seq = seq;
    pending_ok_ack_transfer_len = transfer_len;
    pending_ok_ack_count += 1U;

    if (pending_ok_ack_count >= NET_ACK_COALESCE_PACKET_COUNT) {
        net_flush_pending_ok_ack();
    }
#else
    net_send_ack(addr, port, seq, NET_ACK_STATUS_OK, transfer_len);
#endif
}

static void net_check_ack_timeout(void)
{
#if NET_ACK_COALESCE_ENABLE
    XTime now_time;

    if (pending_ok_ack_valid == 0) {
        return;
    }

    XTime_GetTime(&now_time);
    if (net_elapsed_us(pending_ok_ack_first_time, now_time) >= NET_ACK_COALESCE_TIMEOUT_US) {
        net_flush_pending_ok_ack();
    }
#endif
}

static int net_find_accepted_len(uint32_t seq, uint32_t *payload_len)
{
    uint32_t index;

    for (index = 0U; index < NET_COMPLETED_HISTORY_DEPTH; ++index) {
        if (accepted_history[index].valid != 0 && accepted_history[index].seq == seq) {
            if (payload_len != NULL) {
                *payload_len = accepted_history[index].payload_len;
            }
            return 1;
        }
    }

    return 0;
}

static void net_record_accepted_chunk(uint32_t seq, uint32_t payload_len)
{
    net_accepted_chunk_t *entry = &accepted_history[accepted_history_head_index];

    entry->valid = 1;
    entry->seq = seq;
    entry->payload_len = payload_len;
    accepted_history_head_index =
        (accepted_history_head_index + 1U) % NET_COMPLETED_HISTORY_DEPTH;
}

static void net_reset_stream_state(uint16_t session_id, int validate_crc)
{
    uint32_t index;

    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        agg_blocks[index].state = NET_AGG_BLOCK_FREE;
        agg_blocks[index].payload_len = 0U;
        agg_blocks[index].transfer_len = 0U;
        agg_blocks[index].submit_order = 0U;
        agg_blocks[index].stream_offset = 0U;
        agg_blocks[index].first_write_time = 0U;
        agg_blocks[index].last_write_time = 0U;
    }

    memset(accepted_history, 0, sizeof(accepted_history));
    accepted_history_head_index = 0U;
    fill_block_index = -1;
    dma_block_index = -1;
    dma_busy = 0;
    queue_occupancy_max = 0U;
    total_accepted_bytes = 0U;
    next_expected_seq = 0U;
    next_agg_submit_order = 0U;
    pending_ok_ack_valid = 0;
    pending_ok_ack_port = 0U;
    pending_ok_ack_seq = 0U;
    pending_ok_ack_transfer_len = 0U;
    pending_ok_ack_count = 0U;
    pending_ok_ack_first_time = 0U;
    if (loopback_return_peer_locked == 0) {
        loopback_return_peer_valid = 0;
        loopback_return_port = 0U;
    }
    loopback_return_packet_count = 0U;
    loopback_return_byte_count = 0U;
    current_session_id = session_id & NET_DATA_SESSION_MASK;
    session_valid = 1;
    current_session_validate_crc = validate_crc;
    TxDone = 0;
    RxDone = 0;
    Error = 0;
    TxError = 0;
    RxError = 0;
    TxIrqStatusLast = 0U;
    RxIrqStatusLast = 0U;
    TxDmaSrLast = 0U;
    RxDmaSrLast = 0U;
    TxDmaCrLast = 0U;
    RxDmaCrLast = 0U;
    TxDmaBuffLenLast = 0U;
    RxDmaBuffLenLast = 0U;
    loopback_rx_expected_len = 0U;
    loopback_tx_expected_len = 0U;
    loopback_rx_transfer_id = 0U;
    loopback_rx_done_count = 0U;
    loopback_rx_error_count = 0U;
    loopback_rx_start_time = 0U;
    loopback_rx_last_wait_log_time = 0U;
    loopback_rx_busy = 0;
    loopback_rx_done_for_current = 0;

    NetStats_Init();
    net_update_queue_stats();
}

static int net_seq_before(uint32_t seq_a, uint32_t seq_b)
{
    return ((int32_t)(seq_a - seq_b) < 0);
}

static int net_find_free_block(void)
{
    uint32_t index;

    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        if (agg_blocks[index].state == NET_AGG_BLOCK_FREE) {
            return (int)index;
        }
    }

    return -1;
}

static void net_submit_fill_block(int timeout_flush)
{
    net_agg_block_t *block;
    uint32_t aligned_len;

    if (fill_block_index < 0) {
        return;
    }

    block = &agg_blocks[fill_block_index];
    if (block->payload_len == 0U) {
        block->state = NET_AGG_BLOCK_FREE;
        fill_block_index = -1;
        block->submit_order = 0U;
        net_update_queue_stats();
        return;
    }

    aligned_len = Net_Protocol_Align8(block->payload_len);
    if (aligned_len > block->payload_len) {
        memset(&block->buffer_ptr[block->payload_len], 0, aligned_len - block->payload_len);
    }

    block->transfer_len = aligned_len;
    block->submit_order = next_agg_submit_order++;
    block->state = NET_AGG_BLOCK_READY;
    NetStats_OnAggSubmit(block->payload_len);
    if (timeout_flush != 0) {
        NetStats_OnAggFlushTimeout();
    } else {
        NetStats_OnAggFlushFull();
    }

    if (net_should_report_packet_log() != 0) {
        UART_Printf("AGG submit block=%d payload=%lu transfer=%lu reason=%s\r\n",
            fill_block_index,
            (unsigned long)block->payload_len,
            (unsigned long)block->transfer_len,
            (timeout_flush != 0) ? "timeout" : "full");
    }

    fill_block_index = -1;
    net_update_queue_stats();
}

static int net_ensure_fill_block(uint32_t append_len)
{
    int free_index;
    net_agg_block_t *block;

    if (append_len > NET_AGG_BLOCK_BYTES) {
        return -1;
    }

    if (fill_block_index >= 0) {
        block = &agg_blocks[fill_block_index];
        if ((block->payload_len + append_len) <= NET_AGG_BLOCK_BYTES) {
            return 0;
        }
        net_submit_fill_block(0);
    }

    free_index = net_find_free_block();
    if (free_index < 0) {
        return -1;
    }

    block = &agg_blocks[free_index];
    block->state = NET_AGG_BLOCK_FILLING;
    block->payload_len = 0U;
    block->transfer_len = 0U;
    block->stream_offset = (uint32_t)total_accepted_bytes;
    XTime_GetTime(&block->first_write_time);
    block->last_write_time = block->first_write_time;
    fill_block_index = free_index;
    net_update_queue_stats();
    return 0;
}

static int net_find_ready_block(void)
{
    uint32_t index;
    uint32_t best_order = 0U;
    int best_index = -1;

    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        if (agg_blocks[index].state == NET_AGG_BLOCK_READY) {
            if ((best_index < 0) || (agg_blocks[index].submit_order < best_order)) {
                best_order = agg_blocks[index].submit_order;
                best_index = (int)index;
            }
        }
    }

    return best_index;
}

static int net_loopback_should_log(uint32_t transfer_id)
{
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    if (transfer_id <= NET_LOOPBACK_S2MM_LOG_FIRST_BLOCKS) {
        return 1;
    }
    if ((NET_LOOPBACK_S2MM_LOG_INTERVAL_BLOCKS != 0U) &&
        ((transfer_id % NET_LOOPBACK_S2MM_LOG_INTERVAL_BLOCKS) == 0U)) {
        return 1;
    }
#endif
    return 0;
}

static uint32_t net_load_le32(const uint8_t *ptr)
{
    return ((uint32_t)ptr[0]) |
        ((uint32_t)ptr[1] << 8) |
        ((uint32_t)ptr[2] << 16) |
        ((uint32_t)ptr[3] << 24);
}

static void net_loopback_print_rx_header(const uint8_t *buffer, uint32_t length,
    uint32_t tx_transfer_len, uint32_t tx_payload_len)
{
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    uint32_t timestamp_lo;
    uint32_t timestamp_hi;
    uint32_t meta0;
    uint32_t meta1;
    uint32_t length_field;
    uint32_t payload_len_guess;
    uint32_t rate_guess;

    if (length < NET_LOOPBACK_RX_PREFIX_BYTES) {
        UART_Printf("S2MM rx_hdr short len=%lu prefix=%u\r\n",
            (unsigned long)length,
            (unsigned)NET_LOOPBACK_RX_PREFIX_BYTES);
        return;
    }

    timestamp_lo = net_load_le32(&buffer[0]);
    timestamp_hi = net_load_le32(&buffer[4]);
    meta0 = net_load_le32(&buffer[8]);
    meta1 = net_load_le32(&buffer[12]);
    length_field = meta1 & 0xFFFFU;
    payload_len_guess = (length_field >= 4U) ? (length_field - 4U) : length_field;
    rate_guess = (meta1 >> 16) & 0xFFU;

    UART_Printf(
        "S2MM rx_hdr ts=%08lX_%08lX meta0=0x%08lX meta1=0x%08lX "
        "len_field=%lu payload_guess=%lu rate_guess=0x%02lX "
        "tx_payload=%lu tx_transfer=%lu match=%s\r\n",
        (unsigned long)timestamp_hi,
        (unsigned long)timestamp_lo,
        (unsigned long)meta0,
        (unsigned long)meta1,
        (unsigned long)length_field,
        (unsigned long)payload_len_guess,
        (unsigned long)rate_guess,
        (unsigned long)tx_payload_len,
        (unsigned long)tx_transfer_len,
        (payload_len_guess == tx_payload_len) ? "yes" : "no");
#else
    (void)buffer;
    (void)length;
    (void)tx_transfer_len;
    (void)tx_payload_len;
#endif
}

static void net_loopback_return_udp(const net_agg_block_t *block, const uint8_t *payload,
    uint32_t payload_len, uint32_t timestamp_lo, uint32_t timestamp_hi,
    uint32_t meta0, uint32_t meta1)
{
#if NET_LOOPBACK_UDP_RETURN_ENABLE
    uint32_t chunk_offset = 0U;
    uint32_t chunk_len;
    net_loopback_packet_header_t header;
    struct pbuf *packet_pbuf;
    uint8_t *packet_payload;
    err_t err;

    if ((udp_control_pcb == NULL) || (loopback_return_peer_valid == 0)) {
        UART_Printf("LB UDP skip reason=no_peer block=%lu len=%lu\r\n",
            (unsigned long)loopback_rx_transfer_id,
            (unsigned long)payload_len);
        return;
    }

    while (chunk_offset < payload_len) {
        chunk_len = payload_len - chunk_offset;
        if (chunk_len > NET_LOOPBACK_UDP_PAYLOAD_BYTES) {
            chunk_len = NET_LOOPBACK_UDP_PAYLOAD_BYTES;
        }

        header.magic = NET_LOOPBACK_MAGIC;
        header.block_id = loopback_rx_transfer_id;
        header.stream_offset = block->stream_offset;
        header.block_payload_len = (uint16_t)payload_len;
        header.chunk_offset = (uint16_t)chunk_offset;
        header.chunk_len = (uint16_t)chunk_len;
        header.flags = ((chunk_offset + chunk_len) >= payload_len) ?
            NET_LOOPBACK_FLAG_LAST_CHUNK : 0U;
        header.payload_crc32 = Net_Protocol_Crc32(&payload[chunk_offset], chunk_len);
        header.timestamp_lo = timestamp_lo;
        header.timestamp_hi = timestamp_hi;
        header.meta0 = meta0;
        header.meta1 = meta1;

        packet_pbuf = pbuf_alloc(PBUF_TRANSPORT,
            (u16_t)(sizeof(header) + chunk_len), PBUF_RAM);
        if (packet_pbuf == NULL) {
            UART_Printf("LB UDP alloc failed block=%lu chunk_off=%lu len=%lu\r\n",
                (unsigned long)header.block_id,
                (unsigned long)chunk_offset,
                (unsigned long)chunk_len);
            NetStats_OnDropped();
            return;
        }

        packet_payload = (uint8_t *)packet_pbuf->payload;
        memcpy(packet_payload, &header, sizeof(header));
        memcpy(&packet_payload[sizeof(header)], &payload[chunk_offset], chunk_len);
        err = udp_sendto(udp_control_pcb, packet_pbuf, &loopback_return_addr,
            loopback_return_port);
        pbuf_free(packet_pbuf);

        if (err != ERR_OK) {
            UART_Printf("LB UDP send failed block=%lu chunk_off=%lu len=%lu err=%d\r\n",
                (unsigned long)header.block_id,
                (unsigned long)chunk_offset,
                (unsigned long)chunk_len,
                (int)err);
            NetStats_OnDropped();
            return;
        }

        loopback_return_packet_count += 1U;
        loopback_return_byte_count += chunk_len;
        chunk_offset += chunk_len;
    }

    if (net_loopback_should_log(loopback_rx_transfer_id) != 0) {
        UART_Printf("LB UDP sent block=%lu stream_off=%lu payload=%lu packets=%lu total_bytes=%lu peer_port=%u\r\n",
            (unsigned long)loopback_rx_transfer_id,
            (unsigned long)block->stream_offset,
            (unsigned long)payload_len,
            (unsigned long)loopback_return_packet_count,
            (unsigned long)loopback_return_byte_count,
            (unsigned)loopback_return_port);
    }
#else
    (void)block;
    (void)payload;
    (void)payload_len;
    (void)timestamp_lo;
    (void)timestamp_hi;
    (void)meta0;
    (void)meta1;
#endif
}

static void net_loopback_print_words(const char *tag, const uint8_t *buffer, uint32_t length)
{
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    uint32_t word_count;
    uint32_t index;

    word_count = length / 4U;
    if (word_count > NET_LOOPBACK_S2MM_DUMP_WORDS) {
        word_count = NET_LOOPBACK_S2MM_DUMP_WORDS;
    }

    UART_Printf("%s", tag);
    for (index = 0U; index < word_count; ++index) {
        UART_Printf(" %08lX", (unsigned long)net_load_le32(&buffer[index * 4U]));
    }
    UART_Printf("\r\n");
#else
    (void)tag;
    (void)buffer;
    (void)length;
#endif
}

static void net_loopback_release_dma_block_if_done(void)
{
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    if ((dma_busy != 0) || (loopback_rx_busy != 0) ||
        (loopback_rx_done_for_current == 0) || (dma_block_index < 0)) {
        return;
    }
#else
    if ((dma_busy != 0) || (dma_block_index < 0)) {
        return;
    }
#endif

    agg_blocks[dma_block_index].state = NET_AGG_BLOCK_FREE;
    agg_blocks[dma_block_index].payload_len = 0U;
    agg_blocks[dma_block_index].transfer_len = 0U;
    agg_blocks[dma_block_index].submit_order = 0U;
    agg_blocks[dma_block_index].stream_offset = 0U;
    dma_block_index = -1;
    loopback_rx_expected_len = 0U;
    loopback_tx_expected_len = 0U;
    loopback_rx_done_for_current = 0;
    net_update_queue_stats();
    net_start_dma_transfer();
}

static int net_loopback_start_s2mm(const net_agg_block_t *block, int block_index)
{
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    int status;

    if (loopback_rx_busy != 0) {
        return -1;
    }

    if ((block->transfer_len == 0U) || (block->transfer_len > RX_TRANSFER_LENGTH_BYTES)) {
        UART_Printf("S2MM arm failed block=%d tx_transfer=%lu rx_capacity=%u\r\n",
            block_index,
            (unsigned long)block->transfer_len,
            (unsigned)RX_TRANSFER_LENGTH_BYTES);
        return -1;
    }

    loopback_tx_expected_len = block->transfer_len;
    loopback_rx_expected_len = RX_TRANSFER_LENGTH_BYTES;
    loopback_rx_transfer_id += 1U;
    loopback_rx_done_for_current = 0;
    XTime_GetTime(&loopback_rx_start_time);
    loopback_rx_last_wait_log_time = loopback_rx_start_time;
    RxDone = 0;
    RxError = 0;
    RxIrqStatusLast = 0U;
    RxDmaSrLast = 0U;
    RxDmaCrLast = 0U;
    RxDmaBuffLenLast = 0U;
    Xil_DCacheInvalidateRange((UINTPTR)loopback_rx_buffer, loopback_rx_expected_len);

    status = XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)loopback_rx_buffer,
        loopback_rx_expected_len, XAXIDMA_DEVICE_TO_DMA);
    if (status != XST_SUCCESS) {
        UART_Printf("S2MM start failed id=%lu block=%d len=%lu status=%d\r\n",
            (unsigned long)loopback_rx_transfer_id,
            block_index,
            (unsigned long)loopback_rx_expected_len,
            status);
        return -1;
    }

    loopback_rx_busy = 1;
    if (net_loopback_should_log(loopback_rx_transfer_id) != 0) {
        UART_Printf("S2MM start id=%lu block=%d capture=%lu tx_transfer=%lu tx_payload=%lu\r\n",
            (unsigned long)loopback_rx_transfer_id,
            block_index,
            (unsigned long)loopback_rx_expected_len,
            (unsigned long)loopback_tx_expected_len,
            (unsigned long)block->payload_len);
    }
    return 0;
#else
    (void)block;
    (void)block_index;
    return 0;
#endif
}

static void net_loopback_poll_s2mm(void)
{
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    const net_agg_block_t *block;
    uint32_t rx_crc;
    uint32_t tx_crc;
    uint32_t mismatch_index;
    uint32_t compare_len;
    uint32_t return_len;
    uint32_t rx_prefix_len;
    uint32_t timestamp_lo = 0U;
    uint32_t timestamp_hi = 0U;
    uint32_t rx_meta0 = 0U;
    uint32_t rx_meta1 = 0U;
    const uint8_t *rx_payload_ptr;
    int mismatch_found;
    int should_log;
    XTime now_time;
    uint64_t wait_elapsed_us;
    uint64_t total_wait_us;

    if (loopback_rx_busy == 0) {
        return;
    }

    if (RxError != 0) {
        loopback_rx_error_count += 1U;
        UART_Printf("S2MM error id=%lu irq=0x%08lX sr=0x%08lX cr=0x%08lX buflen=%lu "
            "err_int=%u err_slv=%u err_dec=%u err_sg_int=%u err_sg_slv=%u err_sg_dec=%u errors=%lu\r\n",
            (unsigned long)loopback_rx_transfer_id,
            (unsigned long)RxIrqStatusLast,
            (unsigned long)RxDmaSrLast,
            (unsigned long)RxDmaCrLast,
            (unsigned long)RxDmaBuffLenLast,
            (unsigned)((RxDmaSrLast & XAXIDMA_ERR_INTERNAL_MASK) != 0U),
            (unsigned)((RxDmaSrLast & XAXIDMA_ERR_SLAVE_MASK) != 0U),
            (unsigned)((RxDmaSrLast & XAXIDMA_ERR_DECODE_MASK) != 0U),
            (unsigned)((RxDmaSrLast & XAXIDMA_ERR_SG_INT_MASK) != 0U),
            (unsigned)((RxDmaSrLast & XAXIDMA_ERR_SG_SLV_MASK) != 0U),
            (unsigned)((RxDmaSrLast & XAXIDMA_ERR_SG_DEC_MASK) != 0U),
            (unsigned long)loopback_rx_error_count);
        RxError = 0;
        Error = 0;
        loopback_rx_busy = 0;
        loopback_rx_done_for_current = 1;
        dma_fatal_error = 1;
        dma_busy = 0;
        TxDone = 0;
        TxError = 0;
        NetStats_OnDmaError();
        net_update_queue_stats();
        return;
    }

    if (RxDone == 0) {
        XTime_GetTime(&now_time);
        wait_elapsed_us = net_elapsed_us(loopback_rx_last_wait_log_time, now_time);
        if (wait_elapsed_us >= NET_LOOPBACK_S2MM_WAIT_LOG_US) {
            total_wait_us = net_elapsed_us(loopback_rx_start_time, now_time);
            loopback_rx_last_wait_log_time = now_time;
            UART_Printf("S2MM wait id=%lu capture=%lu tx_transfer=%lu waited_ms=%lu txdone=%d rxdone=%d "
                "tx_irq=0x%08lX rx_irq=0x%08lX rx_sr=0x%08lX rx_cr=0x%08lX rx_buflen=%lu\r\n",
                (unsigned long)loopback_rx_transfer_id,
                (unsigned long)loopback_rx_expected_len,
                (unsigned long)loopback_tx_expected_len,
                (unsigned long)(total_wait_us / 1000ULL),
                TxDone,
                RxDone,
                (unsigned long)TxIrqStatusLast,
                (unsigned long)RxIrqStatusLast,
                (unsigned long)XAxiDma_ReadReg(AxiDma0.RegBase + XAXIDMA_RX_OFFSET, XAXIDMA_SR_OFFSET),
                (unsigned long)XAxiDma_ReadReg(AxiDma0.RegBase + XAXIDMA_RX_OFFSET, XAXIDMA_CR_OFFSET),
                (unsigned long)XAxiDma_ReadReg(AxiDma0.RegBase + XAXIDMA_RX_OFFSET, XAXIDMA_BUFFLEN_OFFSET));
        }
        return;
    }

    RxDone = 0;
    loopback_rx_busy = 0;
    loopback_rx_done_for_current = 1;
    loopback_rx_done_count += 1U;
    Xil_DCacheInvalidateRange((UINTPTR)loopback_rx_buffer, loopback_rx_expected_len);

    should_log = net_loopback_should_log(loopback_rx_transfer_id);
    rx_prefix_len = NET_LOOPBACK_RX_PREFIX_BYTES;
    if (rx_prefix_len > loopback_rx_expected_len) {
        rx_prefix_len = loopback_rx_expected_len;
    }
    rx_payload_ptr = &loopback_rx_buffer[rx_prefix_len];
    if (rx_prefix_len >= 16U) {
        timestamp_lo = net_load_le32(&loopback_rx_buffer[0]);
        timestamp_hi = net_load_le32(&loopback_rx_buffer[4]);
        rx_meta0 = net_load_le32(&loopback_rx_buffer[8]);
        rx_meta1 = net_load_le32(&loopback_rx_buffer[12]);
    }
    compare_len = loopback_tx_expected_len;
    if (compare_len > (loopback_rx_expected_len - rx_prefix_len)) {
        compare_len = loopback_rx_expected_len - rx_prefix_len;
    }
    tx_crc = 0U;
    mismatch_index = 0U;
    mismatch_found = 0;

    if (dma_block_index >= 0) {
        block = &agg_blocks[dma_block_index];
        if (compare_len > block->payload_len) {
            compare_len = block->payload_len;
        }
        tx_crc = Net_Protocol_Crc32(block->buffer_ptr, compare_len);
        for (mismatch_index = 0U; mismatch_index < compare_len; ++mismatch_index) {
            if (rx_payload_ptr[mismatch_index] != block->buffer_ptr[mismatch_index]) {
                mismatch_found = 1;
                break;
            }
        }
    }
    rx_crc = Net_Protocol_Crc32(rx_payload_ptr, compare_len);

    if (mismatch_found != 0) {
        should_log = 1;
    }

    if (should_log != 0) {
        UART_Printf("S2MM done id=%lu capture=%lu tx_transfer=%lu rx_prefix=%lu cmp_len=%lu irq=0x%08lX sr=0x%08lX rx_crc=0x%08lX tx_crc=0x%08lX cmp=%s",
            (unsigned long)loopback_rx_transfer_id,
            (unsigned long)loopback_rx_expected_len,
            (unsigned long)loopback_tx_expected_len,
            (unsigned long)rx_prefix_len,
            (unsigned long)compare_len,
            (unsigned long)RxIrqStatusLast,
            (unsigned long)RxDmaSrLast,
            (unsigned long)rx_crc,
            (unsigned long)tx_crc,
            (mismatch_found != 0) ? "DIFF" : "OK");
        if (mismatch_found != 0) {
            UART_Printf(" first_diff=%lu rx=0x%02X tx=0x%02X",
                (unsigned long)mismatch_index,
                (unsigned)rx_payload_ptr[mismatch_index],
                (unsigned)agg_blocks[dma_block_index].buffer_ptr[mismatch_index]);
        }
        UART_Printf(" done=%lu\r\n", (unsigned long)loopback_rx_done_count);
        net_loopback_print_words("S2MM rx_head", loopback_rx_buffer, loopback_rx_expected_len);
        net_loopback_print_rx_header(loopback_rx_buffer, loopback_rx_expected_len,
            loopback_tx_expected_len,
            (dma_block_index >= 0) ? agg_blocks[dma_block_index].payload_len : compare_len);
        net_loopback_print_words("S2MM rx_payload_head", rx_payload_ptr, compare_len);
        if (dma_block_index >= 0) {
            net_loopback_print_words("S2MM tx_head", agg_blocks[dma_block_index].buffer_ptr,
                agg_blocks[dma_block_index].transfer_len);
        }
    }

    if (dma_block_index >= 0) {
        return_len = compare_len;
        if (return_len > agg_blocks[dma_block_index].payload_len) {
            return_len = agg_blocks[dma_block_index].payload_len;
        }
        net_loopback_return_udp(&agg_blocks[dma_block_index], rx_payload_ptr, return_len,
            timestamp_lo, timestamp_hi, rx_meta0, rx_meta1);
    }

    net_loopback_release_dma_block_if_done();
#endif
}

static void net_start_dma_transfer(void)
{
    int ready_index;
    int status;
    net_agg_block_t *block;

    if ((dma_busy != 0) || (dma_fatal_error != 0) || (loopback_rx_busy != 0)) {
        return;
    }

    ready_index = net_find_ready_block();
    if (ready_index < 0) {
        return;
    }

    block = &agg_blocks[ready_index];
    TxDone = 0;
    TxError = 0;
    TxIrqStatusLast = 0U;
    TxDmaSrLast = 0U;
    TxDmaCrLast = 0U;
    TxDmaBuffLenLast = 0U;

    OpenWifi_Tx_Rearm(block->payload_len);
    if (net_configure_tx_frame(block->payload_len, block->transfer_len) != 0) {
        UART_Printf("TX frame config failed block=%d payload=%lu transfer=%lu max=%u\r\n",
            ready_index,
            (unsigned long)block->payload_len,
            (unsigned long)block->transfer_len,
            (unsigned)NET_OFDM_MAX_PSDU_BYTES);
        NetStats_OnDmaError();
        dma_fatal_error = 1;
        dma_block_index = ready_index;
        dma_busy = 0;
        TxDone = 0;
        TxError = 0;
        net_update_queue_stats();
        return;
    }

    if (net_loopback_start_s2mm(block, ready_index) != 0) {
        UART_Printf("S2MM arm failed before MM2S block=%d payload=%lu transfer=%lu\r\n",
            ready_index,
            (unsigned long)block->payload_len,
            (unsigned long)block->transfer_len);
        NetStats_OnDmaError();
        dma_fatal_error = 1;
        dma_block_index = ready_index;
        dma_busy = 0;
        TxDone = 0;
        TxError = 0;
        net_update_queue_stats();
        return;
    }

    Xil_DCacheFlushRange((UINTPTR)block->buffer_ptr, block->transfer_len);
    status = XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)block->buffer_ptr,
        block->transfer_len, XAXIDMA_DMA_TO_DEVICE);
    if (status != XST_SUCCESS) {
        UART_Printf("DMA start failed block=%d len=%lu status=%d\r\n",
            ready_index,
            (unsigned long)block->transfer_len,
            status);
        NetStats_OnDmaError();
        dma_fatal_error = 1;
        dma_block_index = ready_index;
        dma_busy = 0;
        TxDone = 0;
        TxError = 0;
        loopback_rx_busy = 0;
        loopback_rx_done_for_current = 1;
        net_update_queue_stats();
        return;
    }

    block->state = NET_AGG_BLOCK_DMA_BUSY;
    dma_block_index = ready_index;
    dma_busy = 1;
    NetStats_OnDmaStart();
    net_update_queue_stats();

    if (net_should_report_packet_log() != 0) {
        UART_Printf("DMA start block=%d payload=%lu transfer=%lu\r\n",
            ready_index,
            (unsigned long)block->payload_len,
            (unsigned long)block->transfer_len);
    }
}

static void net_check_agg_timeout(void)
{
    XTime now_time;
    net_agg_block_t *block;
    uint64_t fill_elapsed_us;
    uint64_t idle_elapsed_us;

    if (fill_block_index < 0) {
        return;
    }

    block = &agg_blocks[fill_block_index];
    if (block->payload_len == 0U) {
        return;
    }

    XTime_GetTime(&now_time);
    fill_elapsed_us = net_elapsed_us(block->first_write_time, now_time);
    idle_elapsed_us = net_elapsed_us(block->last_write_time, now_time);

    if ((block->payload_len >= NET_AGG_MIN_FLUSH_BYTES) &&
        (fill_elapsed_us >= NET_AGG_FLUSH_TIMEOUT_US)) {
        net_submit_fill_block(1);
        return;
    }

    if (idle_elapsed_us >= NET_AGG_IDLE_FLUSH_TIMEOUT_US) {
        net_submit_fill_block(1);
    }
}

static void net_udp_receive_callback(void *arg, struct udp_pcb *pcb, struct pbuf *p,
    const ip_addr_t *addr, u16_t port)
{
    net_data_header_t header;
    uint32_t actual_crc;
    uint32_t accepted_payload_len;
    uint16_t packet_flags;
    uint16_t packet_session_id;
    net_agg_block_t *block;
    uint8_t *write_ptr;
    u16_t copied_len;
    LWIP_UNUSED_ARG(arg);
    LWIP_UNUSED_ARG(pcb);

    if (p == NULL) {
        return;
    }

    NetStats_OnRxPacket((uint32_t)p->tot_len,
        (p->tot_len >= sizeof(header)) ? ((uint32_t)p->tot_len - (uint32_t)sizeof(header)) : 0U);

    if (p->tot_len < sizeof(header)) {
        UART_Printf("UDP drop reason=short_packet len=%lu\r\n", (unsigned long)p->tot_len);
        NetStats_OnBadLength();
        net_send_immediate_ack(addr, port, 0U, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    copied_len = pbuf_copy_partial(p, &header, sizeof(header), 0U);
    if (copied_len != sizeof(header)) {
        UART_Printf("UDP drop reason=header_copy len=%lu\r\n", (unsigned long)p->tot_len);
        NetStats_OnBadLength();
        net_send_immediate_ack(addr, port, 0U, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    if (header.magic == NET_RXCFG_MAGIC) {
        if (((uint32_t)p->tot_len != (uint32_t)sizeof(header)) ||
            (header.payload_len != 0U)) {
            UART_Printf("RXCFG drop seq=%lu reason=bad_length pkt=%lu payload=%u\r\n",
                (unsigned long)header.seq,
                (unsigned long)p->tot_len,
                (unsigned)header.payload_len);
            NetStats_OnBadLength();
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
            pbuf_free(p);
            return;
        }

        loopback_return_addr = *addr;
        loopback_return_port = port;
        loopback_return_peer_valid = 1;
        loopback_return_peer_locked = 1;
        UART_Printf("RXCFG loopback peer port=%u\r\n", (unsigned)loopback_return_port);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_OK, 0U);
        pbuf_free(p);
        return;
    }

    if (header.magic != NET_DATA_MAGIC) {
        UART_Printf("UDP drop seq=%lu reason=bad_magic magic=0x%08lX\r\n",
            (unsigned long)header.seq,
            (unsigned long)header.magic);
        NetStats_OnBadMagic();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_MAGIC, 0U);
        pbuf_free(p);
        return;
    }

    packet_flags = (uint16_t)(header.reserved & ~NET_DATA_SESSION_MASK);
    packet_session_id = (uint16_t)(header.reserved & NET_DATA_SESSION_MASK);

    if ((packet_flags & NET_DATA_FLAG_RESET) != 0U) {
        if ((uint32_t)p->tot_len != (uint32_t)sizeof(header)) {
            UART_Printf("UDP reset drop seq=%lu reason=bad_length pkt=%lu\r\n",
                (unsigned long)header.seq,
                (unsigned long)p->tot_len);
            NetStats_OnBadLength();
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
            pbuf_free(p);
            return;
        }

        if (dma_fatal_error != 0) {
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_DMA_ERROR, 0U);
            pbuf_free(p);
            return;
        }

        if ((dma_busy != 0) || (loopback_rx_busy != 0)) {
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BUSY, 0U);
            pbuf_free(p);
            return;
        }

        net_reset_stream_state(packet_session_id,
            ((packet_flags & NET_DATA_FLAG_NO_CRC) == 0U) ? 1 : 0);
        if (loopback_return_peer_locked == 0) {
            loopback_return_addr = *addr;
            loopback_return_port = port;
            loopback_return_peer_valid = 1;
        }
        UART_Printf("UDP RX reset session=%u crc=%s\r\n",
            (unsigned)current_session_id,
            (current_session_validate_crc != 0) ? "on" : "off");
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_OK, 0U);
        pbuf_free(p);
        return;
    }

    if ((session_valid == 0) || (packet_session_id != current_session_id)) {
        NetStats_OnPending();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_PENDING, 0U);
        pbuf_free(p);
        return;
    }

    if ((uint32_t)p->tot_len != (uint32_t)sizeof(header) + (uint32_t)header.payload_len) {
        UART_Printf("UDP drop seq=%lu reason=bad_length pkt=%lu payload=%u\r\n",
            (unsigned long)header.seq,
            (unsigned long)p->tot_len,
            (unsigned)header.payload_len);
        NetStats_OnBadLength();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    if ((header.payload_len == 0U) || ((uint32_t)header.payload_len > NET_MAX_PAYLOAD_BYTES)) {
        UART_Printf("UDP drop seq=%lu reason=payload_range payload=%u max=%u\r\n",
            (unsigned long)header.seq,
            (unsigned)header.payload_len,
            (unsigned)NET_MAX_PAYLOAD_BYTES);
        NetStats_OnBadLength();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    if (dma_fatal_error != 0) {
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_DMA_ERROR, 0U);
        pbuf_free(p);
        return;
    }

    if (net_find_accepted_len(header.seq, &accepted_payload_len) != 0) {
        NetStats_OnDuplicate();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_OK, accepted_payload_len);
        pbuf_free(p);
        return;
    }

    if (header.seq != next_expected_seq) {
        if (net_seq_before(header.seq, next_expected_seq) != 0) {
            NetStats_OnDuplicate();
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_OK,
                (uint32_t)header.payload_len);
        } else {
            NetStats_OnPending();
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_PENDING, 0U);
        }
        pbuf_free(p);
        return;
    }

    if (net_ensure_fill_block((uint32_t)header.payload_len) != 0) {
        NetStats_OnBusy();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BUSY, 0U);
        pbuf_free(p);
        return;
    }

    block = &agg_blocks[fill_block_index];
    write_ptr = block->buffer_ptr + block->payload_len;
    copied_len = pbuf_copy_partial(p, write_ptr, header.payload_len, sizeof(header));
    if (copied_len != header.payload_len) {
        UART_Printf("UDP drop seq=%lu reason=payload_copy copied=%u expected=%u\r\n",
            (unsigned long)header.seq,
            (unsigned)copied_len,
            (unsigned)header.payload_len);
        NetStats_OnBadLength();
        net_release_empty_fill_block();
        net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

#if NET_VALIDATE_PAYLOAD_CRC
    if (current_session_validate_crc != 0) {
        actual_crc = Net_Protocol_Crc32(write_ptr, header.payload_len);
        if (actual_crc != header.payload_crc32) {
            UART_Printf("UDP drop seq=%lu reason=bad_crc rx=0x%08lX calc=0x%08lX\r\n",
                (unsigned long)header.seq,
                (unsigned long)header.payload_crc32,
                (unsigned long)actual_crc);
            NetStats_OnCrcError();
            net_release_empty_fill_block();
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_CHECKSUM, 0U);
            pbuf_free(p);
            return;
        }
    }
#endif

    block->payload_len += header.payload_len;
    XTime_GetTime(&block->last_write_time);
    if (loopback_return_peer_locked == 0) {
        loopback_return_addr = *addr;
        loopback_return_port = port;
        loopback_return_peer_valid = 1;
    }
    total_accepted_bytes += header.payload_len;
    NetStats_OnAcceptedPacket(header.payload_len);
    net_record_accepted_chunk(header.seq, header.payload_len);
    next_expected_seq = header.seq + 1U;
    net_queue_ok_ack(addr, port, header.seq, header.payload_len);

    if (net_should_report_packet_log() != 0) {
        UART_Printf("UDP accept seq=%lu payload=%u block=%d fill=%lu total=%lu\r\n",
            (unsigned long)header.seq,
            (unsigned)header.payload_len,
            fill_block_index,
            (unsigned long)block->payload_len,
            (unsigned long)total_accepted_bytes);
    }

    if (block->payload_len >= NET_AGG_BLOCK_BYTES) {
        net_submit_fill_block(0);
    }

    pbuf_free(p);
    net_start_dma_transfer();
}

int Net_RxInit(uint8_t *tx_buffer, uint32_t tx_buffer_capacity_bytes)
{
    uint32_t index;

    if (tx_buffer_capacity_bytes < (NET_AGG_BLOCK_STRIDE_BYTES * NET_AGG_BLOCK_COUNT)) {
        UART_Printf("NET agg buffer too small capacity=%lu required=%lu\r\n",
            (unsigned long)tx_buffer_capacity_bytes,
            (unsigned long)(NET_AGG_BLOCK_STRIDE_BYTES * NET_AGG_BLOCK_COUNT));
        return -1;
    }

    udp_control_pcb = udp_new();
    if (udp_control_pcb == NULL) {
        UART_Printf("UDP pcb alloc failed\r\n");
        return -1;
    }

    if (udp_bind(udp_control_pcb, IP_ADDR_ANY, NET_UDP_PORT) != ERR_OK) {
        UART_Printf("UDP bind failed\r\n");
        udp_remove(udp_control_pcb);
        udp_control_pcb = NULL;
        return -1;
    }

    dma_tx_buffer = tx_buffer;
    loopback_rx_buffer = (uint8_t *)RX_BUFFER_BASE;
    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        agg_blocks[index].state = NET_AGG_BLOCK_FREE;
        agg_blocks[index].buffer_ptr = dma_tx_buffer + (index * NET_AGG_BLOCK_STRIDE_BYTES);
        agg_blocks[index].payload_len = 0U;
        agg_blocks[index].transfer_len = 0U;
        agg_blocks[index].submit_order = 0U;
        agg_blocks[index].stream_offset = 0U;
        agg_blocks[index].first_write_time = 0U;
        agg_blocks[index].last_write_time = 0U;
    }
    memset(accepted_history, 0, sizeof(accepted_history));
    accepted_history_head_index = 0U;
    fill_block_index = -1;
    dma_block_index = -1;
    dma_busy = 0;
    dma_fatal_error = 0;
    queue_occupancy_max = 0U;
    total_accepted_bytes = 0U;
    next_expected_seq = 0U;
    next_agg_submit_order = 0U;
    pending_ok_ack_valid = 0;
    pending_ok_ack_port = 0U;
    pending_ok_ack_seq = 0U;
    pending_ok_ack_transfer_len = 0U;
    pending_ok_ack_count = 0U;
    pending_ok_ack_first_time = 0U;
    loopback_return_peer_valid = 0;
    loopback_return_peer_locked = 0;
    loopback_return_port = 0U;
    loopback_return_packet_count = 0U;
    loopback_return_byte_count = 0U;
    current_session_id = 0U;
    session_valid = 0;
    current_session_validate_crc = 1;
    TxDone = 0;
    RxDone = 0;
    Error = 0;
    TxError = 0;
    RxError = 0;
    TxIrqStatusLast = 0U;
    RxIrqStatusLast = 0U;
    TxDmaSrLast = 0U;
    RxDmaSrLast = 0U;
    TxDmaCrLast = 0U;
    RxDmaCrLast = 0U;
    TxDmaBuffLenLast = 0U;
    RxDmaBuffLenLast = 0U;
    loopback_rx_expected_len = 0U;
    loopback_tx_expected_len = 0U;
    loopback_rx_transfer_id = 0U;
    loopback_rx_done_count = 0U;
    loopback_rx_error_count = 0U;
    loopback_rx_start_time = 0U;
    loopback_rx_last_wait_log_time = 0U;
    loopback_rx_busy = 0;
    loopback_rx_done_for_current = 0;

    NetStats_Init();
    net_update_queue_stats();
    udp_recv(udp_control_pcb, net_udp_receive_callback, NULL);
    UART_Printf(
        "UDP RX ready, agg_blocks=%u block_bytes=%u stride=%u total_bytes=%lu max_payload=%u rec_window<=%u ack=on_accept\r\n",
        (unsigned)NET_AGG_BLOCK_COUNT,
        (unsigned)NET_AGG_BLOCK_BYTES,
        (unsigned)NET_AGG_BLOCK_STRIDE_BYTES,
        (unsigned long)tx_buffer_capacity_bytes,
        (unsigned)NET_MAX_PAYLOAD_BYTES,
        (unsigned)NET_MAX_RECOMMENDED_WINDOW_SIZE);
#if NET_LOOPBACK_UDP_RETURN_ENABLE
    UART_Printf("Loopback UDP return ready, magic=0x%08lX chunk_bytes=%u\r\n",
        (unsigned long)NET_LOOPBACK_MAGIC,
        (unsigned)NET_LOOPBACK_UDP_PAYLOAD_BYTES);
#endif
#if NET_LOOPBACK_S2MM_DEBUG_ENABLE
    UART_Printf("S2MM loopback debug ready, rx_base=0x%08lX rx_bytes=%u log_first=%u log_interval=%u\r\n",
        (unsigned long)RX_BUFFER_BASE,
        (unsigned)RX_TRANSFER_LENGTH_BYTES,
        (unsigned)NET_LOOPBACK_S2MM_LOG_FIRST_BLOCKS,
        (unsigned)NET_LOOPBACK_S2MM_LOG_INTERVAL_BLOCKS);
#endif

    return 0;
}

void Net_RxPoll(void)
{
    NetStats_PrintPeriodic();
    net_check_agg_timeout();
    net_check_ack_timeout();
    net_loopback_poll_s2mm();

    if (dma_fatal_error != 0) {
        return;
    }

    if (dma_busy == 0) {
        net_start_dma_transfer();
    }

    if (dma_busy == 0) {
        return;
    }

    if (TxError != 0) {
        UART_Printf("MM2S error block=%d len=%lu irq=0x%08lX sr=0x%08lX cr=0x%08lX buflen=%lu "
            "err_int=%u err_slv=%u err_dec=%u err_sg_int=%u err_sg_slv=%u err_sg_dec=%u\r\n",
            dma_block_index,
            (dma_block_index >= 0) ? (unsigned long)agg_blocks[dma_block_index].transfer_len : 0UL,
            (unsigned long)TxIrqStatusLast,
            (unsigned long)TxDmaSrLast,
            (unsigned long)TxDmaCrLast,
            (unsigned long)TxDmaBuffLenLast,
            (unsigned)((TxDmaSrLast & XAXIDMA_ERR_INTERNAL_MASK) != 0U),
            (unsigned)((TxDmaSrLast & XAXIDMA_ERR_SLAVE_MASK) != 0U),
            (unsigned)((TxDmaSrLast & XAXIDMA_ERR_DECODE_MASK) != 0U),
            (unsigned)((TxDmaSrLast & XAXIDMA_ERR_SG_INT_MASK) != 0U),
            (unsigned)((TxDmaSrLast & XAXIDMA_ERR_SG_SLV_MASK) != 0U),
            (unsigned)((TxDmaSrLast & XAXIDMA_ERR_SG_DEC_MASK) != 0U));
        NetStats_OnDmaError();
        dma_fatal_error = 1;
        dma_busy = 0;
        TxError = 0;
        TxDone = 0;
        net_update_queue_stats();
        return;
    }

    if (TxDone != 0) {
        if (dma_block_index >= 0) {
            NetStats_OnDmaDone(agg_blocks[dma_block_index].transfer_len);
        }
        dma_busy = 0;
        TxDone = 0;
        TxError = 0;
        net_loopback_release_dma_block_if_done();
    }
}
