#include "net_rx.h"

#include "AXI_DMA.h"
#include "PS_UART.h"
#include "net_protocol.h"
#include "net_stats.h"

#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "xtime_l.h"

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
static uint16_t current_session_id;
static int session_valid;

static uint64_t net_elapsed_us(XTime start_time, XTime end_time)
{
    if ((end_time <= start_time) || (COUNTS_PER_SECOND == 0U)) {
        return 0U;
    }

    return ((uint64_t)(end_time - start_time) * 1000000ULL) / (uint64_t)COUNTS_PER_SECOND;
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

static void net_reset_stream_state(uint16_t session_id)
{
    uint32_t index;

    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        agg_blocks[index].state = NET_AGG_BLOCK_FREE;
        agg_blocks[index].payload_len = 0U;
        agg_blocks[index].transfer_len = 0U;
        agg_blocks[index].submit_order = 0U;
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
    current_session_id = session_id & NET_DATA_SESSION_MASK;
    session_valid = 1;
    TxDone = 0;
    Error = 0;

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

static void net_start_dma_transfer(void)
{
    int ready_index;
    int status;
    net_agg_block_t *block;

    if ((dma_busy != 0) || (dma_fatal_error != 0)) {
        return;
    }

    ready_index = net_find_ready_block();
    if (ready_index < 0) {
        return;
    }

    block = &agg_blocks[ready_index];
    TxDone = 0;
    Error = 0;

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
        Error = 0;
        net_update_queue_stats();
        return;
    }

    block->state = NET_AGG_BLOCK_DMA_BUSY;
    dma_block_index = ready_index;
    dma_busy = 1;
    NetStats_OnDmaStart();
    net_update_queue_stats();

    if (net_should_report_packet_log() != 0) {
        UART_Printf("DMA start block=%d len=%lu\r\n",
            ready_index,
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

        if (dma_busy != 0) {
            net_send_immediate_ack(addr, port, header.seq, NET_ACK_STATUS_BUSY, 0U);
            pbuf_free(p);
            return;
        }

        net_reset_stream_state(packet_session_id);
        UART_Printf("UDP RX reset session=%u\r\n", (unsigned)current_session_id);
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
#else
    LWIP_UNUSED_ARG(actual_crc);
#endif

    block->payload_len += header.payload_len;
    XTime_GetTime(&block->last_write_time);
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

    if (tx_buffer_capacity_bytes < (NET_AGG_BLOCK_BYTES * NET_AGG_BLOCK_COUNT)) {
        UART_Printf("NET agg buffer too small capacity=%lu required=%lu\r\n",
            (unsigned long)tx_buffer_capacity_bytes,
            (unsigned long)(NET_AGG_BLOCK_BYTES * NET_AGG_BLOCK_COUNT));
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
    for (index = 0U; index < NET_AGG_BLOCK_COUNT; ++index) {
        agg_blocks[index].state = NET_AGG_BLOCK_FREE;
        agg_blocks[index].buffer_ptr = dma_tx_buffer + (index * NET_AGG_BLOCK_BYTES);
        agg_blocks[index].payload_len = 0U;
        agg_blocks[index].transfer_len = 0U;
        agg_blocks[index].submit_order = 0U;
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
    current_session_id = 0U;
    session_valid = 0;
    TxDone = 0;
    Error = 0;

    NetStats_Init();
    net_update_queue_stats();
    udp_recv(udp_control_pcb, net_udp_receive_callback, NULL);
    UART_Printf(
        "UDP RX ready, agg_blocks=%u block_bytes=%u total_bytes=%lu max_payload=%u rec_window<=%u ack=on_accept\r\n",
        (unsigned)NET_AGG_BLOCK_COUNT,
        (unsigned)NET_AGG_BLOCK_BYTES,
        (unsigned long)tx_buffer_capacity_bytes,
        (unsigned)NET_MAX_PAYLOAD_BYTES,
        (unsigned)NET_MAX_RECOMMENDED_WINDOW_SIZE);

    return 0;
}

void Net_RxPoll(void)
{
    NetStats_PrintPeriodic();
    net_check_agg_timeout();
    net_check_ack_timeout();

    if (dma_fatal_error != 0) {
        return;
    }

    if (dma_busy == 0) {
        net_start_dma_transfer();
    }

    if (dma_busy == 0) {
        return;
    }

    if (Error != 0) {
        UART_Printf("DMA error block=%d len=%lu\r\n",
            dma_block_index,
            (dma_block_index >= 0) ? (unsigned long)agg_blocks[dma_block_index].transfer_len : 0UL);
        NetStats_OnDmaError();
        dma_fatal_error = 1;
        dma_busy = 0;
        Error = 0;
        TxDone = 0;
        net_update_queue_stats();
        return;
    }

    if (TxDone != 0) {
        if (dma_block_index >= 0) {
            NetStats_OnDmaDone(agg_blocks[dma_block_index].transfer_len);
            agg_blocks[dma_block_index].state = NET_AGG_BLOCK_FREE;
            agg_blocks[dma_block_index].payload_len = 0U;
            agg_blocks[dma_block_index].transfer_len = 0U;
            agg_blocks[dma_block_index].submit_order = 0U;
        }
        dma_busy = 0;
        dma_block_index = -1;
        TxDone = 0;
        Error = 0;
        net_update_queue_stats();
        net_start_dma_transfer();
    }
}
