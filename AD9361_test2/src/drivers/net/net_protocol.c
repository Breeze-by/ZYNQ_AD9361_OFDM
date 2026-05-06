#include "net_protocol.h"

uint32_t Net_Protocol_Crc32(const uint8_t *data, uint32_t length)
{
    uint32_t crc = 0xFFFFFFFFU;
    uint32_t i;

    for (i = 0; i < length; ++i) {
        uint32_t bit;

        crc ^= data[i];
        for (bit = 0; bit < 8U; ++bit) {
            if ((crc & 1U) != 0U) {
                crc = (crc >> 1) ^ 0xEDB88320U;
            } else {
                crc >>= 1;
            }
        }
    }

    return ~crc;
}

uint32_t Net_Protocol_Align8(uint32_t length)
{
    return (length + 7U) & ~7U;
}
