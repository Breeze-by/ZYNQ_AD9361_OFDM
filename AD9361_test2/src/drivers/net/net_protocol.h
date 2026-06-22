#ifndef AD9361_TEST2_NET_PROTOCOL_H_
#define AD9361_TEST2_NET_PROTOCOL_H_

#include "COMMON.h"
#include "net_config.h"

typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint16_t payload_len;
    uint16_t reserved;
    uint32_t payload_crc32;
} net_data_header_t;

typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint16_t status;
    uint16_t reserved;
    uint32_t transfer_len;
} net_ack_packet_t;

typedef struct {
    uint32_t magic;
    uint32_t block_id;
    uint32_t stream_offset;
    uint16_t block_payload_len;
    uint16_t chunk_offset;
    uint16_t chunk_len;
    uint16_t flags;
    uint32_t payload_crc32;
    uint32_t timestamp_lo;
    uint32_t timestamp_hi;
    uint32_t meta0;
    uint32_t meta1;
} net_loopback_packet_header_t;

uint32_t Net_Protocol_Crc32(const uint8_t *data, uint32_t length);
uint32_t Net_Protocol_Align8(uint32_t length);

#endif /* AD9361_TEST2_NET_PROTOCOL_H_ */
