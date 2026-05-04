/*
 * ad9361_config.h
 *
 *  Created on: 2018Äê3ÔÂ25ÈÕ
 *      Author: liche
 */

#ifndef SRC_AD9361_CONFIG_H_
#define SRC_AD9361_CONFIG_H_
int32_t ad9361_config(struct ad9361_rf_phy *ad9361_phy) {
	ad9361_set_tx_fir_config(ad9361_phy, tx_fir_config);
	ad9361_set_rx_fir_config(ad9361_phy, rx_fir_config);
	ad9361_set_tx_sampling_freq(ad9361_phy, sample_rate);
	ad9361_set_tx_lo_freq(ad9361_phy, tx_lo_freq);
	ad9361_set_rx_lo_freq(ad9361_phy, rx_lo_freq);
//	ad9361_set_tx_fir_en_dis(ad9361_phy, 0);
//	ad9361_set_rx_fir_en_dis(ad9361_phy, 0);
	ad9361_set_rx_rf_bandwidth(ad9361_phy, bandwidth);
	ad9361_set_tx_rf_bandwidth(ad9361_phy, bandwidth);
	ad9361_set_rx_rf_gain(ad9361_phy, 0, gain);
	ad9361_set_rx_rf_gain(ad9361_phy, 1, gain);
	ad9361_set_rx_gain_control_mode (ad9361_phy,0,1);//mgc=0,fast_agc=1
	ad9361_set_rx_gain_control_mode (ad9361_phy,1,1);//mgc=0,fast_agc=1
	ad9361_set_tx_attenuation(ad9361_phy, 0, txatt);
	ad9361_set_tx_attenuation(ad9361_phy, 1, txatt);
	int32_t val;
	val = ad9361_spi_read(ad9361_phy->spi, regr);
//	ad9361_spi_write(ad9361_phy->spi, 0x3F4, 0x0B);
//	ad9361_spi_write(ad9361_phy->spi, 0x3F5, 0x41);
	uint32_t sampling_freq_hz;
	ad9361_get_tx_sampling_freq(ad9361_phy, &sampling_freq_hz);
	printf("sampling_freq=%fMHz\n",((double)sampling_freq_hz)/1e6);
	// ad9361 port_sel
	if (tx_lo_freq >= 70000000 && tx_lo_freq < 3000000000) {
		gpio_set_value(TX_BAND_SEL, 0);
		ad9361_set_tx_rf_port_output(ad9361_phy, 1);
	} else {
		gpio_set_value(TX_BAND_SEL, 1);
		ad9361_set_tx_rf_port_output(ad9361_phy, 0);
	}
	if (rx_lo_freq >= 70000000 && rx_lo_freq < 2000000000) {
		gpio_set_value(RX1_BAND_SEL_A, 0);
		gpio_set_value(RX1_BAND_SEL_B, 1);
		gpio_set_value(RX2_BAND_SEL_A, 0);
		gpio_set_value(RX2_BAND_SEL_B, 1);
		ad9361_set_rx_rf_port_input(ad9361_phy, 2);
	} else if (rx_lo_freq >= 2000000000 && rx_lo_freq < 3500000000) {
		gpio_set_value(RX1_BAND_SEL_A, 1);
		gpio_set_value(RX1_BAND_SEL_B, 1);
		gpio_set_value(RX2_BAND_SEL_A, 1);
		gpio_set_value(RX2_BAND_SEL_B, 0);
		ad9361_set_rx_rf_port_input(ad9361_phy, 1);
	} else {
		gpio_set_value(RX1_BAND_SEL_A, 1);
		gpio_set_value(RX1_BAND_SEL_B, 0);
		gpio_set_value(RX2_BAND_SEL_A, 1);
		gpio_set_value(RX2_BAND_SEL_B, 1);
		ad9361_set_rx_rf_port_input(ad9361_phy, 0);
	}
	return val;
}
#endif /* SRC_AD9361_CONFIG_H_ */
