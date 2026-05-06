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

uint32_t Net_Protocol_Crc32(const uint8_t *data, uint32_t length);
uint32_t Net_Protocol_Align8(uint32_t length);

#endif /* AD9361_TEST2_NET_PROTOCOL_H_ */
