#include "net_rx.h"

#include "AXI_DMA.h"
#include "PS_UART.h"
#include "net_protocol.h"
#include "net_stats.h"

#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "xtime_l.h"

typedef struct {
    int valid;
    uint32_t seq;
    uint32_t transfer_len;
    uint8_t *buffer_ptr;
    ip_addr_t peer_addr;
    u16_t peer_port;
    XTime accept_time;
    uint64_t recv_gap_us;
} net_pending_chunk_t;

typedef struct {
    int valid;
    uint32_t seq;
    uint32_t transfer_len;
} net_completed_chunk_t;

static struct udp_pcb *udp_control_pcb;
static uint8_t *dma_tx_buffer;
static uint32_t dma_tx_slot_capacity_bytes;

static net_pending_chunk_t active_chunk;
static net_pending_chunk_t tx_queue[NET_TX_QUEUE_DEPTH];
static net_completed_chunk_t completed_history[NET_COMPLETED_HISTORY_DEPTH];
static uint32_t queue_head_index;
static uint32_t queue_tail_index;
static uint32_t queue_count;
static uint32_t queue_max_depth;
static uint32_t completed_history_head_index;
static int dma_busy;
static uint64_t total_completed_bytes;
static uint32_t total_completed_chunks;
static uint32_t total_busy_acks;
static uint32_t total_error_acks;
static uint32_t total_pending_acks;
static uint32_t total_duplicate_acks;
static uint32_t total_ok_acks;
static uint32_t ack_batch_fill_count;
static uint32_t ack_batch_last_seq;
static uint32_t ack_batch_last_len;
static ip_addr_t ack_batch_peer_addr;
static u16_t ack_batch_peer_port;
static int ack_batch_valid;
static XTime active_dma_start_time;
static XTime first_recv_time;
static XTime last_recv_time;
static int has_recv_time;

static uint64_t net_elapsed_us(XTime start_time, XTime end_time)
{
    if ((end_time <= start_time) || (COUNTS_PER_SECOND == 0U)) {
        return 0U;
    }

    return ((uint64_t)(end_time - start_time) * 1000000ULL) / (uint64_t)COUNTS_PER_SECOND;
}

static uint32_t net_rate_x100_kib(uint32_t bytes, uint64_t elapsed_us)
{
    if (elapsed_us == 0U) {
        return 0U;
    }

    return (uint32_t)(((uint64_t)bytes * 100ULL * 1000000ULL) / (1024ULL * elapsed_us));
}

static void net_print_rate_line(const char *prefix, uint32_t seq, uint32_t transfer_len,
    uint64_t dma_elapsed_us, uint64_t app_elapsed_us, uint64_t recv_gap_us,
    uint32_t recent_rate_x100_kib, uint32_t avg_rate_x100_kib)
{
    UART_Printf(
        "%s seq=%lu len=%lu dma_us=%lu app_us=%lu gap_us=%lu rate=%lu.%02lu avg=%lu.%02lu total=%lu\r\n",
        prefix,
        (unsigned long)seq,
        (unsigned long)transfer_len,
        (unsigned long)dma_elapsed_us,
        (unsigned long)app_elapsed_us,
        (unsigned long)recv_gap_us,
        (unsigned long)(recent_rate_x100_kib / 100U),
        (unsigned long)(recent_rate_x100_kib % 100U),
        (unsigned long)(avg_rate_x100_kib / 100U),
        (unsigned long)(avg_rate_x100_kib % 100U),
        (unsigned long)total_completed_bytes);
}

static int net_should_report_packet_log(void)
{
#if NET_VERBOSE_PACKET_LOG
    return 1;
#else
    return 0;
#endif
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

static void net_send_ok_ack_batch_if_needed(int force_send)
{
    if (ack_batch_valid == 0) {
        return;
    }

    if (force_send == 0 && ack_batch_fill_count < NET_ACK_BATCH_COUNT) {
        return;
    }

    net_send_ack(&ack_batch_peer_addr, ack_batch_peer_port, ack_batch_last_seq,
        NET_ACK_STATUS_OK, ack_batch_last_len);
    total_ok_acks += 1U;
    ack_batch_valid = 0;
    ack_batch_fill_count = 0U;
}

static net_pending_chunk_t *net_find_queued_chunk_by_seq(uint32_t seq)
{
    uint32_t scan_index;
    uint32_t scan_count;

    for (scan_count = 0U, scan_index = queue_head_index;
        scan_count < queue_count;
        ++scan_count, scan_index = (scan_index + 1U) % NET_TX_QUEUE_DEPTH) {
        if (tx_queue[scan_index].valid != 0 && tx_queue[scan_index].seq == seq) {
            return &tx_queue[scan_index];
        }
    }

    return NULL;
}

static int net_find_completed_len(uint32_t seq, uint32_t *transfer_len)
{
    uint32_t index;

    for (index = 0U; index < NET_COMPLETED_HISTORY_DEPTH; ++index) {
        if (completed_history[index].valid != 0 && completed_history[index].seq == seq) {
            if (transfer_len != NULL) {
                *transfer_len = completed_history[index].transfer_len;
            }
            return 1;
        }
    }

    return 0;
}

static void net_record_completed_chunk(uint32_t seq, uint32_t transfer_len)
{
    net_completed_chunk_t *entry = &completed_history[completed_history_head_index];

    entry->valid = 1;
    entry->seq = seq;
    entry->transfer_len = transfer_len;
    completed_history_head_index =
        (completed_history_head_index + 1U) % NET_COMPLETED_HISTORY_DEPTH;
}

static void net_release_queue_head(void)
{
    tx_queue[queue_head_index].valid = 0;
    queue_head_index = (queue_head_index + 1U) % NET_TX_QUEUE_DEPTH;
    if (queue_count != 0U) {
        queue_count -= 1U;
    }
}

static void net_start_dma_transfer(void)
{
    int status;
    net_pending_chunk_t *queued_chunk;

    if (queue_count == 0U) {
        return;
    }

    TxDone = 0;
    Error = 0;
    queued_chunk = &tx_queue[queue_head_index];

    Xil_DCacheFlushRange((UINTPTR)queued_chunk->buffer_ptr, queued_chunk->transfer_len);
    status = XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)queued_chunk->buffer_ptr,
        queued_chunk->transfer_len, XAXIDMA_DMA_TO_DEVICE);
    if (status != XST_SUCCESS) {
        UART_Printf("DMA start failed seq=%lu len=%lu status=%d\r\n",
            (unsigned long)queued_chunk->seq,
            (unsigned long)queued_chunk->transfer_len,
            status);
        total_error_acks += 1U;
        NetStats_OnDmaError();
        net_send_ack(&queued_chunk->peer_addr, queued_chunk->peer_port, queued_chunk->seq,
            NET_ACK_STATUS_DMA_ERROR, queued_chunk->transfer_len);
        net_release_queue_head();
        NetStats_SetQueue(queue_count, queue_max_depth);
        return;
    }

    if (net_should_report_packet_log() != 0) {
        UART_Printf("DMA start seq=%lu len=%lu q=%lu\r\n",
            (unsigned long)queued_chunk->seq,
            (unsigned long)queued_chunk->transfer_len,
            (unsigned long)queue_count);
    }
    if (net_should_report_packet_log() != 0) {
        XTime_GetTime(&active_dma_start_time);
    }
    NetStats_OnDmaStart();

    active_chunk = *queued_chunk;
    dma_busy = 1;
}

static void net_udp_receive_callback(void *arg, struct udp_pcb *pcb, struct pbuf *p,
    const ip_addr_t *addr, u16_t port)
{
    net_data_header_t header;
    uint32_t aligned_len;
    uint32_t actual_crc;
    uint32_t completed_transfer_len;
    net_pending_chunk_t *duplicate_chunk;
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
        net_send_ack(addr, port, 0U, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    pbuf_copy_partial(p, &header, sizeof(header), 0U);

    if (header.magic != NET_DATA_MAGIC) {
        UART_Printf("UDP drop seq=%lu reason=bad_magic magic=0x%08lX\r\n",
            (unsigned long)header.seq,
            (unsigned long)header.magic);
        NetStats_OnBadMagic();
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_MAGIC, 0U);
        pbuf_free(p);
        return;
    }

    if (net_find_completed_len(header.seq, &completed_transfer_len) != 0) {
        total_duplicate_acks += 1U;
        NetStats_OnDuplicate();
        if (net_should_report_packet_log() != 0) {
            UART_Printf("UDP duplicate_done seq=%lu len=%lu\r\n",
                (unsigned long)header.seq,
                (unsigned long)completed_transfer_len);
        }
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_OK, completed_transfer_len);
        pbuf_free(p);
        return;
    }

    if (active_chunk.valid != 0 && header.seq == active_chunk.seq) {
        total_pending_acks += 1U;
        NetStats_OnPending();
        if (net_should_report_packet_log() != 0) {
            UART_Printf("UDP duplicate_active seq=%lu len=%lu\r\n",
                (unsigned long)header.seq,
                (unsigned long)active_chunk.transfer_len);
        }
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_PENDING, active_chunk.transfer_len);
        pbuf_free(p);
        return;
    }

    duplicate_chunk = net_find_queued_chunk_by_seq(header.seq);
    if (duplicate_chunk != NULL) {
        total_pending_acks += 1U;
        NetStats_OnPending();
        if (net_should_report_packet_log() != 0) {
            UART_Printf("UDP duplicate_queued seq=%lu len=%lu\r\n",
                (unsigned long)header.seq,
                (unsigned long)duplicate_chunk->transfer_len);
        }
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_PENDING, duplicate_chunk->transfer_len);
        pbuf_free(p);
        return;
    }

    if (queue_count >= NET_TX_QUEUE_DEPTH) {
        total_busy_acks += 1U;
        NetStats_OnBusy();
        if (net_should_report_packet_log() != 0) {
            UART_Printf("UDP busy seq=%lu q=%lu/%u\r\n",
                (unsigned long)header.seq,
                (unsigned long)queue_count,
                (unsigned)NET_TX_QUEUE_DEPTH);
        }
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BUSY, 0U);
        pbuf_free(p);
        return;
    }

    if ((uint32_t)p->tot_len != (uint32_t)sizeof(header) + (uint32_t)header.payload_len) {
        UART_Printf("UDP drop seq=%lu reason=bad_length pkt=%lu payload=%u\r\n",
            (unsigned long)header.seq,
            (unsigned long)p->tot_len,
            (unsigned)header.payload_len);
        NetStats_OnBadLength();
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    if ((header.payload_len == 0U) || ((uint32_t)header.payload_len > dma_tx_slot_capacity_bytes)) {
        UART_Printf("UDP drop seq=%lu reason=payload_range payload=%u max=%lu\r\n",
            (unsigned long)header.seq,
            (unsigned)header.payload_len,
            (unsigned long)dma_tx_slot_capacity_bytes);
        NetStats_OnBadLength();
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    {
        net_pending_chunk_t *slot = &tx_queue[queue_tail_index];
        uint8_t *slot_buffer = dma_tx_buffer + (queue_tail_index * dma_tx_slot_capacity_bytes);

        pbuf_copy_partial(p, slot_buffer, header.payload_len, sizeof(header));
        actual_crc = Net_Protocol_Crc32(slot_buffer, header.payload_len);
        if (actual_crc != header.payload_crc32) {
            UART_Printf("UDP drop seq=%lu reason=bad_crc rx=0x%08lX calc=0x%08lX\r\n",
                (unsigned long)header.seq,
                (unsigned long)header.payload_crc32,
                (unsigned long)actual_crc);
            NetStats_OnCrcError();
            net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_CHECKSUM, 0U);
            pbuf_free(p);
            return;
        }

        aligned_len = Net_Protocol_Align8(header.payload_len);
        if (aligned_len > header.payload_len) {
            memset(&slot_buffer[header.payload_len], 0, aligned_len - header.payload_len);
        }

        slot->valid = 1;
        slot->seq = header.seq;
        slot->transfer_len = aligned_len;
        slot->buffer_ptr = slot_buffer;
        ip_addr_copy(slot->peer_addr, *addr);
        slot->peer_port = port;
        if (net_should_report_packet_log() != 0) {
            XTime_GetTime(&slot->accept_time);
            if (has_recv_time == 0) {
                first_recv_time = slot->accept_time;
                slot->recv_gap_us = 0U;
                has_recv_time = 1;
            } else {
                slot->recv_gap_us = net_elapsed_us(last_recv_time, slot->accept_time);
            }
            last_recv_time = slot->accept_time;
        } else {
            slot->accept_time = 0U;
            slot->recv_gap_us = 0U;
        }

        queue_tail_index = (queue_tail_index + 1U) % NET_TX_QUEUE_DEPTH;
        queue_count += 1U;
        if (queue_count > queue_max_depth) {
            queue_max_depth = queue_count;
        }
        NetStats_SetQueue(queue_count, queue_max_depth);

        if (net_should_report_packet_log() != 0) {
            UART_Printf("UDP recv seq=%lu payload=%u aligned=%lu from_port=%u q=%lu\r\n",
                (unsigned long)header.seq,
                (unsigned)header.payload_len,
                (unsigned long)aligned_len,
                (unsigned)port,
                (unsigned long)queue_count);
        }
    }

    pbuf_free(p);

    if (dma_busy == 0) {
        net_start_dma_transfer();
    }
}

int Net_RxInit(uint8_t *tx_buffer, uint32_t tx_buffer_capacity_bytes)
{
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
    dma_tx_slot_capacity_bytes = tx_buffer_capacity_bytes / NET_TX_QUEUE_DEPTH;
    active_chunk.valid = 0;
    memset(tx_queue, 0, sizeof(tx_queue));
    queue_head_index = 0U;
    queue_tail_index = 0U;
    queue_count = 0U;
    queue_max_depth = 0U;
    memset(completed_history, 0, sizeof(completed_history));
    completed_history_head_index = 0U;
    dma_busy = 0;
    TxDone = 0;
    Error = 0;
    total_completed_bytes = 0U;
    total_completed_chunks = 0U;
    total_busy_acks = 0U;
    total_error_acks = 0U;
    total_pending_acks = 0U;
    total_duplicate_acks = 0U;
    total_ok_acks = 0U;
    ack_batch_fill_count = 0U;
    ack_batch_last_seq = 0U;
    ack_batch_last_len = 0U;
    ack_batch_peer_port = 0U;
    ack_batch_valid = 0;
    has_recv_time = 0;

    udp_recv(udp_control_pcb, net_udp_receive_callback, NULL);
    NetStats_Init();
    NetStats_SetQueue(queue_count, queue_max_depth);
    UART_Printf("UDP RX ready, slot_count=%u slot_bytes=%u max_payload=%u rec_window<=%u\r\n",
        (unsigned)NET_TX_QUEUE_DEPTH,
        (unsigned)dma_tx_slot_capacity_bytes,
        (unsigned)dma_tx_slot_capacity_bytes,
        (unsigned)NET_MAX_RECOMMENDED_WINDOW_SIZE);

    return 0;
}

void Net_RxPoll(void)
{
    NetStats_PrintPeriodic();

    if (dma_busy == 0 && queue_count != 0U) {
        net_start_dma_transfer();
    }

    if (dma_busy == 0) {
        return;
    }

    if (Error != 0) {
        UART_Printf("DMA error seq=%lu len=%lu\r\n",
            (unsigned long)active_chunk.seq,
            (unsigned long)active_chunk.transfer_len);
        total_error_acks += 1U;
        NetStats_OnDmaError();
        net_send_ack(&active_chunk.peer_addr, active_chunk.peer_port, active_chunk.seq,
            NET_ACK_STATUS_DMA_ERROR, active_chunk.transfer_len);
        dma_busy = 0;
        active_chunk.valid = 0;
        net_send_ok_ack_batch_if_needed(1);
        net_release_queue_head();
        NetStats_SetQueue(queue_count, queue_max_depth);
        Error = 0;
        TxDone = 0;
        if (queue_count != 0U) {
            net_start_dma_transfer();
        }
        return;
    }

    if (TxDone != 0) {
        net_record_completed_chunk(active_chunk.seq, active_chunk.transfer_len);
        total_completed_bytes += active_chunk.transfer_len;
        total_completed_chunks += 1U;
        NetStats_OnDmaDone(active_chunk.transfer_len);

        ack_batch_last_seq = active_chunk.seq;
        ack_batch_last_len = active_chunk.transfer_len;
        ip_addr_copy(ack_batch_peer_addr, active_chunk.peer_addr);
        ack_batch_peer_port = active_chunk.peer_port;
        ack_batch_fill_count += 1U;
        ack_batch_valid = 1;
        if (net_should_report_packet_log() != 0) {
            XTime now_time;
            uint64_t dma_elapsed_us;
            uint64_t app_elapsed_us;
            uint64_t avg_recv_elapsed_us;
            uint32_t recent_rate_x100_kib;
            uint32_t avg_rate_x100_kib;

            XTime_GetTime(&now_time);
            dma_elapsed_us = net_elapsed_us(active_dma_start_time, now_time);
            app_elapsed_us = net_elapsed_us(active_chunk.accept_time, now_time);
            recent_rate_x100_kib = net_rate_x100_kib(active_chunk.transfer_len, active_chunk.recv_gap_us);
            avg_recv_elapsed_us = net_elapsed_us(first_recv_time, active_chunk.accept_time);
            avg_rate_x100_kib = net_rate_x100_kib((uint32_t)total_completed_bytes, avg_recv_elapsed_us);

            net_print_rate_line("ACK", active_chunk.seq, active_chunk.transfer_len,
                dma_elapsed_us, app_elapsed_us, active_chunk.recv_gap_us,
                recent_rate_x100_kib, avg_rate_x100_kib);
        }

        dma_busy = 0;
        active_chunk.valid = 0;
        net_release_queue_head();
        NetStats_SetQueue(queue_count, queue_max_depth);
        TxDone = 0;
        Error = 0;

        if ((queue_count == 0U) || (ack_batch_fill_count >= NET_ACK_BATCH_COUNT)) {
            net_send_ok_ack_batch_if_needed(1);
        }

        if (queue_count != 0U) {
            net_start_dma_transfer();
        }
    }
}
