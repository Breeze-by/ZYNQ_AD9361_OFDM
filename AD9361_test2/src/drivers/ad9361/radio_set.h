#ifndef SRC_RADIO_SET_H_
#define SRC_RADIO_SET_H_

#include <stdint.h>

#include "ad9361.h"
#include "ad9361_api.h"

extern struct ad9361_rf_phy *ad9361_phy;
extern struct ad9361_rf_phy *ad9361_phy_b;
extern uint64_t rfout;
extern uint32_t val_out;
extern uint32_t idelay;
extern uint32_t qdelay;
extern uint32_t sample_rate;
extern uint64_t tx_lo_freq;
extern uint64_t rx_lo_freq;
extern uint32_t bandwidth;
extern int32_t gain;
extern uint32_t txatt;
extern uint32_t regr;

extern AD9361_InitParam default_init_param;
extern AD9361_RXFIRConfig rx_fir_config;
extern AD9361_TXFIRConfig tx_fir_config;

#endif /* SRC_RADIO_SET_H_ */
