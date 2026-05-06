#ifndef AD9361_TEST2_NET_RX_H_
#define AD9361_TEST2_NET_RX_H_

#include "COMMON.h"

int Net_RxInit(uint8_t *tx_buffer, uint32_t tx_buffer_capacity_bytes);
void Net_RxPoll(void);

#endif /* AD9361_TEST2_NET_RX_H_ */
