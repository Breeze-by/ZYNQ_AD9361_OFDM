#ifndef AD9361_TEST2_NET_INIT_H_
#define AD9361_TEST2_NET_INIT_H_

#include "COMMON.h"

int Net_Init(const unsigned char *mac_address);
int Net_ApplyIpv4Config(const uint8_t ip_addr[4], const uint8_t netmask[4],
    const uint8_t gateway[4]);
void Net_Poll(void);

#endif /* AD9361_TEST2_NET_INIT_H_ */
