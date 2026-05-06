#include "net_rx.h"

#include "AXI_DMA.h"
#include "PS_UART.h"
#include "net_protocol.h"

#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"

typedef struct {
    int valid;
    uint32_t seq;
    uint32_t transfer_len;
    ip_addr_t peer_addr;
    u16_t peer_port;
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
        net_send_ack(&pending_chunk.peer_addr, pending_chunk.peer_port, pending_chunk.seq,
            NET_ACK_STATUS_DMA_ERROR, pending_chunk.transfer_len);
        pending_chunk.valid = 0;
        return;
    }

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
        net_send_ack(addr, port, 0U, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    pbuf_copy_partial(p, &header, sizeof(header), 0U);

    if (header.magic != NET_DATA_MAGIC) {
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_MAGIC, 0U);
        pbuf_free(p);
        return;
    }

    if (has_last_completed_seq != 0 && header.seq == last_completed_seq) {
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_OK, last_completed_len);
        pbuf_free(p);
        return;
    }

    if (dma_busy != 0 || pending_chunk.valid != 0) {
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BUSY, 0U);
        pbuf_free(p);
        return;
    }

    if ((uint32_t)p->tot_len != (uint32_t)sizeof(header) + (uint32_t)header.payload_len) {
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    if ((header.payload_len == 0U) || ((uint32_t)header.payload_len > dma_tx_capacity_bytes)) {
        net_send_ack(addr, port, header.seq, NET_ACK_STATUS_BAD_LENGTH, 0U);
        pbuf_free(p);
        return;
    }

    pbuf_copy_partial(p, dma_tx_buffer, header.payload_len, sizeof(header));
    actual_crc = Net_Protocol_Crc32(dma_tx_buffer, header.payload_len);
    if (actual_crc != header.payload_crc32) {
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
        net_send_ack(&active_chunk.peer_addr, active_chunk.peer_port, active_chunk.seq,
            NET_ACK_STATUS_DMA_ERROR, active_chunk.transfer_len);
        dma_busy = 0;
        active_chunk.valid = 0;
        Error = 0;
        TxDone = 0;
        return;
    }

    if (TxDone != 0) {
        last_completed_seq = active_chunk.seq;
        last_completed_len = active_chunk.transfer_len;
        has_last_completed_seq = 1;

        net_send_ack(&active_chunk.peer_addr, active_chunk.peer_port, active_chunk.seq,
            NET_ACK_STATUS_OK, active_chunk.transfer_len);

        dma_busy = 0;
        active_chunk.valid = 0;
        TxDone = 0;
        Error = 0;
    }
}
