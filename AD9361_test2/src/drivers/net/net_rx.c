#include "net_rx.h"

#include "AXI_DMA.h"
#include "PS_UART.h"
#include "net_protocol.h"

#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "xtime_l.h"

typedef struct {
    int valid;
    uint32_t seq;
    uint32_t transfer_len;
    ip_addr_t peer_addr;
    u16_t peer_port;
    XTime accept_time;
    uint64_t recv_gap_us;
} net_pending_chunk_t;

static struct udp_pcb *udp_control_pcb;
static uint8_t *dma_tx_buffer;
static uint32_t dma_tx_capacity_bytes;

static net_pending_chunk_t pending_chunk;
static net_pending_chunk_t active_chunk;
static uint32_t last_completed_seq;
static uint32_t last_completed_len;
static int has_last_completed_seq;
static int dma_busy;
static uint64_t total_completed_bytes;
static uint32_t total_completed_chunks;
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
        return;
    }

    memcpy(ack_pbuf->payload, &ack_packet, sizeof(ack_packet));
    udp_sendto(udp_control_pcb, ack_pbuf, addr, port);
    pbuf_free(ack_pbuf);
}

static void net_start_dma_transfer(void)
{
    int status;

    TxDone = 0;
    Error = 0;

    Xil_DCacheFlushRange((UINTPTR)dma_tx_buffer, pending_chunk.transfer_len);
    status = XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)dma_tx_buffer,
        pending_chunk.transfer_len, XAXIDMA_DMA_TO_DEVICE);
    if (status != XST_SUCCESS) {
        UART_Printf("DMA start failed seq=%lu len=%lu status=%d\r\n",
            (unsigned long)pending_chunk.seq,
            (unsigned long)pending_chunk.transfer_len,
            status);
        net_send_ack(&pending_chunk.peer_addr, pending_chunk.peer_port, pending_chunk.seq,
            NET_ACK_STATUS_DMA_ERROR, pending_chunk.transfer_len);
        pending_chunk.valid = 0;
        return;
    }

    UART_Printf("DMA start seq=%lu len=%lu\r\n",
        (unsigned long)pending_chunk.seq,
        (unsigned long)pending_chunk.transfer_len);
    XTime_GetTime(&active_dma_start_time);

    active_chunk = pending_chunk;
    pending_chunk.valid = 0;
    dma_busy = 1;
}

static void net_udp_receive_callback(void *arg, struct udp_pcb *pcb, struct pbuf *p,
    const ip_addr_t *addr, u16_t port)
{
    net_data_header_t header;
    uint32_t aligned_len;
    uint32_t actual_crc;
    LWIP_UNUSED_ARG(arg);
    LWIP_UNUSED_ARG(pcb);

    if (p == NULL) {
        return;
    }

    if (p->tot_len < sizeof(header)) {
        UART_Printf("UDP drop reason=short_packet len=%lu\r\n", (unsigned long)p->tot_len);
        net_send_ack(addr, port, 0U, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    pbuf_copy_partial(p, &header, sizeof(header), 0U);

    if (header.magic != NET_DATA_MAGIC) {
        UART_Printf("UDP drop seq=%lu reason=bad_magic magic=0x%08lX\r\n",
            (unsigned long)header.seq,
            (unsigned long)header.magic);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_MAGIC, 0U);
        pbuf_free(p);
        return;
    }

    if (has_last_completed_seq != 0 && header.seq == last_completed_seq) {
        UART_Printf("UDP duplicate seq=%lu ack_resend len=%lu\r\n",
            (unsigned long)header.seq,
            (unsigned long)last_completed_len);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_OK, last_completed_len);
        pbuf_free(p);
        return;
    }

    if (dma_busy != 0 || pending_chunk.valid != 0) {
        UART_Printf("UDP busy seq=%lu dma_busy=%d pending=%d\r\n",
            (unsigned long)header.seq,
            dma_busy,
            pending_chunk.valid);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BUSY, 0U);
        pbuf_free(p);
        return;
    }

    if ((uint32_t)p->tot_len != (uint32_t)sizeof(header) + (uint32_t)header.payload_len) {
        UART_Printf("UDP drop seq=%lu reason=bad_length pkt=%lu payload=%u\r\n",
            (unsigned long)header.seq,
            (unsigned long)p->tot_len,
            (unsigned)header.payload_len);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    if ((header.payload_len == 0U) || ((uint32_t)header.payload_len > dma_tx_capacity_bytes)) {
        UART_Printf("UDP drop seq=%lu reason=payload_range payload=%u max=%lu\r\n",
            (unsigned long)header.seq,
            (unsigned)header.payload_len,
            (unsigned long)dma_tx_capacity_bytes);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    pbuf_copy_partial(p, dma_tx_buffer, header.payload_len, sizeof(header));
    actual_crc = Net_Protocol_Crc32(dma_tx_buffer, header.payload_len);
    if (actual_crc != header.payload_crc32) {
        UART_Printf("UDP drop seq=%lu reason=bad_crc rx=0x%08lX calc=0x%08lX\r\n",
            (unsigned long)header.seq,
            (unsigned long)header.payload_crc32,
            (unsigned long)actual_crc);
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_CHECKSUM, 0U);
        pbuf_free(p);
        return;
    }

    aligned_len = Net_Protocol_Align8(header.payload_len);
    if (aligned_len > header.payload_len) {
        memset(&dma_tx_buffer[header.payload_len], 0, aligned_len - header.payload_len);
    }

    pending_chunk.valid = 1;
    pending_chunk.seq = header.seq;
    pending_chunk.transfer_len = aligned_len;
    ip_addr_copy(pending_chunk.peer_addr, *addr);
    pending_chunk.peer_port = port;
    XTime_GetTime(&pending_chunk.accept_time);
    if (has_recv_time == 0) {
        first_recv_time = pending_chunk.accept_time;
        pending_chunk.recv_gap_us = 0U;
        has_recv_time = 1;
    } else {
        pending_chunk.recv_gap_us = net_elapsed_us(last_recv_time, pending_chunk.accept_time);
    }
    last_recv_time = pending_chunk.accept_time;

    UART_Printf("UDP recv seq=%lu payload=%u aligned=%lu from_port=%u\r\n",
        (unsigned long)header.seq,
        (unsigned)header.payload_len,
        (unsigned long)aligned_len,
        (unsigned)port);

    pbuf_free(p);
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
    dma_tx_capacity_bytes = tx_buffer_capacity_bytes;
    pending_chunk.valid = 0;
    active_chunk.valid = 0;
    has_last_completed_seq = 0;
    dma_busy = 0;
    TxDone = 0;
    Error = 0;
    total_completed_bytes = 0U;
    total_completed_chunks = 0U;
    has_recv_time = 0;

    udp_recv(udp_control_pcb, net_udp_receive_callback, NULL);
    UART_Printf("UDP RX ready, max payload %u bytes\r\n", dma_tx_capacity_bytes);

    return 0;
}

void Net_RxPoll(void)
{
    if (dma_busy == 0 && pending_chunk.valid != 0) {
        net_start_dma_transfer();
    }

    if (dma_busy == 0) {
        return;
    }

    if (Error != 0) {
        UART_Printf("DMA error seq=%lu len=%lu\r\n",
            (unsigned long)active_chunk.seq,
            (unsigned long)active_chunk.transfer_len);
        net_send_ack(&active_chunk.peer_addr, active_chunk.peer_port, active_chunk.seq,
            NET_ACK_STATUS_DMA_ERROR, active_chunk.transfer_len);
        dma_busy = 0;
        active_chunk.valid = 0;
        Error = 0;
        TxDone = 0;
        return;
    }

    if (TxDone != 0) {
        XTime now_time;
        uint64_t dma_elapsed_us;
        uint64_t app_elapsed_us;
        uint64_t avg_recv_elapsed_us;
        uint32_t recent_rate_x100_kib;
        uint32_t avg_rate_x100_kib;

        last_completed_seq = active_chunk.seq;
        last_completed_len = active_chunk.transfer_len;
        has_last_completed_seq = 1;
        total_completed_bytes += active_chunk.transfer_len;
        total_completed_chunks += 1U;

        XTime_GetTime(&now_time);
        dma_elapsed_us = net_elapsed_us(active_dma_start_time, now_time);
        app_elapsed_us = net_elapsed_us(active_chunk.accept_time, now_time);
        recent_rate_x100_kib = net_rate_x100_kib(active_chunk.transfer_len, active_chunk.recv_gap_us);
        avg_recv_elapsed_us = net_elapsed_us(first_recv_time, active_chunk.accept_time);
        avg_rate_x100_kib = net_rate_x100_kib((uint32_t)total_completed_bytes, avg_recv_elapsed_us);

        net_send_ack(&active_chunk.peer_addr, active_chunk.peer_port, active_chunk.seq,
            NET_ACK_STATUS_OK, active_chunk.transfer_len);
        net_print_rate_line("ACK", active_chunk.seq, active_chunk.transfer_len,
            dma_elapsed_us, app_elapsed_us, active_chunk.recv_gap_us,
            recent_rate_x100_kib, avg_rate_x100_kib);

        dma_busy = 0;
        active_chunk.valid = 0;
        TxDone = 0;
        Error = 0;
    }
}
