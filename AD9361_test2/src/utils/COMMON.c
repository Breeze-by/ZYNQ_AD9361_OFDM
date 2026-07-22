#include "COMMON.h"

#include "ad9361.h"
#include "ad9361_api.h"
#include "ad9361_config.h"
#include "gpio_initial.h"
#include "parameters.h"
#include "platform.h"
#include "radio_set.h"

/*
 * AD9361/openwifi waveform contract for this board.
 *
 * The physical AD9361 reference clock is 26 MHz. The PL bridge is fixed to
 * 2R2T LVDS at 40 MSPS, which gives a 160 MHz DATA_CLK. Keep those three
 * values aligned; changing only one of them breaks the custom PL unpacker.
 */
#define OPENWIFI_REFERENCE_CLK_HZ  26000000UL
#define OPENWIFI_CENTER_FREQ_HZ    2000000000ULL
#define OPENWIFI_SAMPLE_RATE_HZ    40000000U
#define OPENWIFI_RX_BW_HZ          25215513U
#define OPENWIFI_TX_BW_HZ          25215414U

/*
 * Initial SMA-loopback values for an external 10 dB attenuator.
 * If no frame is detected, reduce on-chip TX attenuation one step at a time:
 * 60 -> 50 -> 40 -> 30 dB. Never use 0 dB for a direct cable connection.
 */
#define OPENWIFI_TX_ATT_MDB        30000U
#define OPENWIFI_RX_GAIN_DB        20
#define OPENWIFI_RX_GAIN_MODE      RF_GAIN_MGC

struct ad9361_rf_phy *ad9361_phy;
struct ad9361_rf_phy *ad9361_phy_b;
uint64_t rfout;
uint32_t val_out;
uint32_t idelay;
uint32_t qdelay;
uint32_t sample_rate = OPENWIFI_SAMPLE_RATE_HZ;
uint64_t tx_lo_freq = OPENWIFI_CENTER_FREQ_HZ;
uint64_t rx_lo_freq = OPENWIFI_CENTER_FREQ_HZ;
/* Legacy global retained for source compatibility; it represents RX BW. */
uint32_t bandwidth = OPENWIFI_RX_BW_HZ;
int32_t gain = OPENWIFI_RX_GAIN_DB;
uint32_t txatt = OPENWIFI_TX_ATT_MDB;
uint32_t regr = REG_PRODUCT_ID;

static const uint32_t tx_bandwidth = OPENWIFI_TX_BW_HZ;

AD9361_InitParam default_init_param = {
    .dev_sel = ID_AD9361,
    .id_no = 0,
    .reference_clk_rate = OPENWIFI_REFERENCE_CLK_HZ,
    .two_rx_two_tx_mode_enable = 1,
    .one_rx_one_tx_mode_use_rx_num = 1,
    .one_rx_one_tx_mode_use_tx_num = 1,
    .frequency_division_duplex_mode_enable = 1,
    .frequency_division_duplex_independent_mode_enable = 0,
    .tdd_use_dual_synth_mode_enable = 0,
    .tdd_skip_vco_cal_enable = 0,
    .tx_fastlock_delay_ns = 0,
    .rx_fastlock_delay_ns = 0,
    .rx_fastlock_pincontrol_enable = 0,
    .tx_fastlock_pincontrol_enable = 0,
    .external_rx_lo_enable = 0,
    .external_tx_lo_enable = 0,
    .dc_offset_tracking_update_event_mask = 5,
    .dc_offset_attenuation_high_range = 6,
    .dc_offset_attenuation_low_range = 5,
    .dc_offset_count_high_range = 0x28,
    .dc_offset_count_low_range = 0x32,
    .split_gain_table_mode_enable = 0,
    .trx_synthesizer_target_fref_overwrite_hz = MAX_SYNTH_FREF,
    .qec_tracking_slow_mode_enable = 0,
    .ensm_enable_pin_pulse_mode_enable = 0,
    .ensm_enable_txnrx_control_enable = 0,
    .rx_synthesizer_frequency_hz = OPENWIFI_CENTER_FREQ_HZ,
    .tx_synthesizer_frequency_hz = OPENWIFI_CENTER_FREQ_HZ,
    .rx_path_clock_frequencies = { 1280000000U, 320000000U, 160000000U, 80000000U, 40000000U, 40000000U },
    .tx_path_clock_frequencies = { 1280000000U, 320000000U, 160000000U, 80000000U, 40000000U, 40000000U },
    .rf_rx_bandwidth_hz = OPENWIFI_RX_BW_HZ,
    .rf_tx_bandwidth_hz = OPENWIFI_TX_BW_HZ,
    .rx_rf_port_input_select = 0,
    .tx_rf_port_input_select = 0,
    .tx_attenuation_mdB = OPENWIFI_TX_ATT_MDB,
    .update_tx_gain_in_alert_enable = 0,
    .xo_disable_use_ext_refclk_enable = 0,
    .dcxo_coarse_and_fine_tune = { 8U, 5920U },
    .clk_output_mode_select = ADC_CLK_DIV_16,
    .gc_rx1_mode = OPENWIFI_RX_GAIN_MODE,
    .gc_rx2_mode = OPENWIFI_RX_GAIN_MODE,
    .gc_adc_large_overload_thresh = 58,
    .gc_adc_ovr_sample_size = 4,
    .gc_adc_small_overload_thresh = 47,
    .gc_dec_pow_measurement_duration = 1,
    .gc_dig_gain_enable = 1,
    .gc_lmt_overload_high_thresh = 800,
    .gc_lmt_overload_low_thresh = 704,
    .gc_low_power_thresh = 24,
    .gc_max_dig_gain = 15,
    .mgc_dec_gain_step = 2,
    .mgc_inc_gain_step = 2,
    .mgc_rx1_ctrl_inp_enable = 0,
    .mgc_rx2_ctrl_inp_enable = 0,
    .mgc_split_table_ctrl_inp_gain_mode = 0,
    .agc_adc_large_overload_exceed_counter = 32,
    .agc_adc_large_overload_inc_steps = 5,
    .agc_adc_lmt_small_overload_prevent_gain_inc_enable = 0,
    .agc_adc_small_overload_exceed_counter = 32,
    .agc_dig_gain_step_size = 4,
    .agc_dig_saturation_exceed_counter = 3,
    .agc_gain_update_interval_us = 5,
    .agc_immed_gain_change_if_large_adc_overload_enable = 0,
    .agc_immed_gain_change_if_large_lmt_overload_enable = 0,
    .agc_inner_thresh_high = 10,
    .agc_inner_thresh_high_dec_steps = 1,
    .agc_inner_thresh_low = 12,
    .agc_inner_thresh_low_inc_steps = 1,
    .agc_lmt_overload_large_exceed_counter = 20,
    .agc_lmt_overload_large_inc_steps = 5,
    .agc_lmt_overload_small_exceed_counter = 20,
    .agc_outer_thresh_high = 5,
    .agc_outer_thresh_high_dec_steps = 2,
    .agc_outer_thresh_low = 18,
    .agc_outer_thresh_low_inc_steps = 2,
    .agc_attack_delay_extra_margin_us = 1,
    .agc_sync_for_gain_counter_enable = 0,
    .fagc_dec_pow_measuremnt_duration = 4,
    .fagc_state_wait_time_ns = 1,
    .fagc_allow_agc_gain_increase = 0,
    .fagc_lp_thresh_increment_time = 5,
    .fagc_lp_thresh_increment_steps = 5,
    .fagc_lock_level = 10,
    .fagc_lock_level_lmt_gain_increase_en = 1,
    .fagc_lock_level_gain_increase_upper_limit = 3,
    .fagc_lpf_final_settling_steps = 3,
    .fagc_lmt_final_settling_steps = 3,
    .fagc_final_overrange_count = 3,
    .fagc_gain_increase_after_gain_lock_en = 0,
    .fagc_gain_index_type_after_exit_rx_mode = 2,
    .fagc_use_last_lock_level_for_set_gain_en = 1,
    .fagc_rst_gla_stronger_sig_thresh_exceeded_en = 1,
    .fagc_optimized_gain_offset = 5,
    .fagc_rst_gla_stronger_sig_thresh_above_ll = 5,
    .fagc_rst_gla_engergy_lost_sig_thresh_exceeded_en = 0,
    .fagc_rst_gla_engergy_lost_goto_optim_gain_en = 0,
    .fagc_rst_gla_engergy_lost_sig_thresh_below_ll = 20,
    .fagc_energy_lost_stronger_sig_gain_lock_exit_cnt = 8,
    .fagc_rst_gla_large_adc_overload_en = 1,
    .fagc_rst_gla_large_lmt_overload_en = 0,
    .fagc_rst_gla_en_agc_pulled_high_en = 1,
    .fagc_rst_gla_if_en_agc_pulled_high_mode = 2,
    .fagc_power_measurement_duration_in_state5 = 8,
    .rssi_delay = 1,
    .rssi_duration = 10,
    .rssi_restart_mode = 1,
    .rssi_unit_is_rx_samples_enable = 0,
    .rssi_wait = 1,
    .aux_adc_decimation = 256,
    .aux_adc_rate = 40000000UL,
    .aux_dac_manual_mode_enable = 1,
    .aux_dac1_default_value_mV = 0,
    .aux_dac1_active_in_rx_enable = 0,
    .aux_dac1_active_in_tx_enable = 0,
    .aux_dac1_active_in_alert_enable = 0,
    .aux_dac1_rx_delay_us = 0,
    .aux_dac1_tx_delay_us = 0,
    .aux_dac2_default_value_mV = 0,
    .aux_dac2_active_in_rx_enable = 0,
    .aux_dac2_active_in_tx_enable = 0,
    .aux_dac2_active_in_alert_enable = 0,
    .aux_dac2_rx_delay_us = 0,
    .aux_dac2_tx_delay_us = 0,
    .temp_sense_decimation = 256,
    .temp_sense_measurement_interval_ms = 1000,
    .temp_sense_offset_signed = 0xCE,
    .temp_sense_periodic_measurement_enable = 1,
    .ctrl_outs_enable_mask = 0xFF,
    .ctrl_outs_index = 0x16,
    .elna_settling_delay_ns = 0,
    .elna_gain_mdB = 0,
    .elna_bypass_loss_mdB = 0,
    .elna_rx1_gpo0_control_enable = 0,
    .elna_rx2_gpo1_control_enable = 0,
    .elna_gaintable_all_index_enable = 0,
    .digital_interface_tune_skip_mode = 0,
    .digital_interface_tune_fir_disable = 0,
    .pp_tx_swap_enable = 1,
    .pp_rx_swap_enable = 1,
    .tx_channel_swap_enable = 0,
    .rx_channel_swap_enable = 0,
    .rx_frame_pulse_mode_enable = 1,
    .two_t_two_r_timing_enable = 0,
    .invert_data_bus_enable = 0,
    .invert_data_clk_enable = 0,
    .fdd_alt_word_order_enable = 0,
    .invert_rx_frame_enable = 0,
    .fdd_rx_rate_2tx_enable = 0,
    .swap_ports_enable = 0,
    .single_data_rate_enable = 0,
    .lvds_mode_enable = 1,
    .half_duplex_mode_enable = 0,
    .single_port_mode_enable = 0,
    .full_port_enable = 0,
    .full_duplex_swap_bits_enable = 0,
    .delay_rx_data = 0,
    .rx_data_clock_delay = 0,
    .rx_data_delay = 5,
    /* 4 taps = about 1.2 ns; this matches the TX timing constraint model. */
    .tx_fb_clock_delay = 7,
    .tx_data_delay = 0,
    .lvds_bias_mV = 150,
    .lvds_rx_onchip_termination_enable = 1,
    .rx1rx2_phase_inversion_en = 0,
    .lvds_invert1_control = 0xFF,
    .lvds_invert2_control = 0x0F,
    .gpo0_inactive_state_high_enable = 0,
    .gpo1_inactive_state_high_enable = 0,
    .gpo2_inactive_state_high_enable = 0,
    .gpo3_inactive_state_high_enable = 0,
    .gpo0_slave_rx_enable = 0,
    .gpo0_slave_tx_enable = 0,
    .gpo1_slave_rx_enable = 0,
    .gpo1_slave_tx_enable = 0,
    .gpo2_slave_rx_enable = 0,
    .gpo2_slave_tx_enable = 0,
    .gpo3_slave_rx_enable = 0,
    .gpo3_slave_tx_enable = 0,
    .gpo0_rx_delay_us = 0,
    .gpo0_tx_delay_us = 0,
    .gpo1_rx_delay_us = 0,
    .gpo1_tx_delay_us = 0,
    .gpo2_rx_delay_us = 0,
    .gpo2_tx_delay_us = 0,
    .gpo3_rx_delay_us = 0,
    .gpo3_tx_delay_us = 0,
    .low_high_gain_threshold_mdB = 37000,
    .low_gain_dB = 0,
    .high_gain_dB = 24,
    .tx_mon_track_en = 0,
    .one_shot_mode_en = 0,
    .tx_mon_delay = 511,
    .tx_mon_duration = 8192,
    .tx1_mon_front_end_gain = 2,
    .tx2_mon_front_end_gain = 2,
    .tx1_mon_lo_cm = 48,
    .tx2_mon_lo_cm = 48
};

AD9361_RXFIRConfig rx_fir_config = {
    .rx = 3,
    .rx_gain = -6,
    .rx_dec = 1,
    .rx_coef = {
        56, 70, -148, -500, -434, 169, 436, -208,
        -674, 137, 956, -14, -1325, -214, 1799, 598,
        -2437, -1255, 3389, 2507, -5127, -5623, 10560, 29674,
        29674, 10560, -5623, -5127, 2507, 3389, -1255, -2437,
        598, 1799, -214, -1325, -14, 956, 137, -674,
        -208, 436, 169, -434, -500, -148, 70, 56
    },
    .rx_coef_size = 48,
    .rx_path_clks = {
        1280000000U, 320000000U, 160000000U,
        80000000U, 40000000U, 40000000U
    },
    .rx_bandwidth = OPENWIFI_RX_BW_HZ
};

AD9361_TXFIRConfig tx_fir_config = {
    .tx = 3,
    .tx_gain = -6,
    .tx_int = 1,
    .tx_coef = {
        41, 31, -187, -496, -395, 183, 412, -201,
        -619, 148, 886, -38, -1232, -166, 1680, 513,
        -2284, -1107, 3197, 2238, -4904, -5068, 10562, 28812,
        28812, 10562, -5068, -4904, 2238, 3197, -1107, -2284,
        513, 1680, -166, -1232, -38, 886, 148, -619,
        -201, 412, 183, -395, -496, -187, 31, 41
    },
    .tx_coef_size = 48,
    .tx_path_clks = {
        1280000000U, 320000000U, 160000000U,
        80000000U, 40000000U, 40000000U
    },
    .tx_bandwidth = OPENWIFI_TX_BW_HZ
};

void gpio_initial(void)
{
    gpio_init(GPIO_DEVICE_ID);
    gpio_direction(TXNRX, 1);
    gpio_direction(ENABLE1, 1);
    gpio_direction(RESETB, 1);
    gpio_direction(SYNC_IN, 1);
    gpio_direction(EN_AGC, 1);
    gpio_direction(CTRL_IN3, 1);
    gpio_direction(CTRL_IN2, 1);
    gpio_direction(CTRL_IN1, 1);
    gpio_direction(CTRL_IN0, 1);
    gpio_direction(USER_IO5, 1);
    gpio_direction(USER_IO4, 1);
    gpio_direction(USER_IO3, 1);
    gpio_direction(USER_IO2, 1);
    gpio_direction(USER_IO1, 1);
    gpio_direction(USER_IO0, 1);
    gpio_direction(TX_BAND_SEL, 1);
    gpio_direction(TRX_SW, 1);
    gpio_direction(FDD_TDD_SEL, 1);
    gpio_direction(RX2_BAND_SEL_B, 1);
    gpio_direction(RX2_BAND_SEL_A, 1);
    gpio_direction(RX1_BAND_SEL_B, 1);
    gpio_direction(RX1_BAND_SEL_A, 1);
    gpio_direction(VCO_CAL_SELECT, 1);
    gpio_direction(REF_SELECT, 1);

    gpio_set_value(TXNRX, 1);
    gpio_set_value(ENABLE1, 1);
    gpio_set_value(RESETB, 1);
    gpio_set_value(SYNC_IN, 1);
    gpio_set_value(EN_AGC, 0);
    gpio_set_value(CTRL_IN3, 0);
    gpio_set_value(CTRL_IN2, 0);
    gpio_set_value(CTRL_IN1, 0);
    gpio_set_value(CTRL_IN0, 0);
    gpio_set_value(USER_IO5, 0);
    gpio_set_value(USER_IO4, 0);
    gpio_set_value(USER_IO3, 0);
    gpio_set_value(USER_IO2, 0);
    gpio_set_value(USER_IO1, 0);
    gpio_set_value(USER_IO0, 0);
    gpio_set_value(TX_BAND_SEL, 0);
    gpio_set_value(TRX_SW, 1);
    gpio_set_value(FDD_TDD_SEL, 1);
    gpio_set_value(RX2_BAND_SEL_B, 0);
    gpio_set_value(RX2_BAND_SEL_A, 1);
    gpio_set_value(RX1_BAND_SEL_B, 1);
    gpio_set_value(RX1_BAND_SEL_A, 1);
    gpio_set_value(VCO_CAL_SELECT, 1);
    gpio_set_value(REF_SELECT, 0);
}

static int32_t ad9361_config_result(const char *step, int32_t status)
{
    if (status != 0) {
        printf("AD9361 config failed: %s status=%ld\r\n",
            step, (long)status);
    }
    return status;
}

static uint32_t ad9361_abs_diff_u32(uint32_t a, uint32_t b)
{
    return (a > b) ? (a - b) : (b - a);
}

int32_t ad9361_config(struct ad9361_rf_phy *phy)
{
    int32_t val;
    int32_t rx1_gain_db;
    int32_t rx2_gain_db;
    int32_t rx_delay_reg;
    int32_t tx_delay_reg;
    uint8_t rx1_gain_mode;
    uint8_t rx2_gain_mode;
    uint32_t tx_sampling_freq_hz;
    uint32_t rx_sampling_freq_hz;
    uint32_t tx_bandwidth_hz;
    uint32_t rx_bandwidth_hz;
    uint32_t tx1_attenuation_mdb;
    uint32_t tx2_attenuation_mdb;
    uint32_t rx_path_clks[6];
    uint32_t tx_path_clks[6];
    uint64_t tx_lo_readback_hz;
    uint64_t rx_lo_readback_hz;

    if ((phy == NULL) || (phy->spi == NULL)) {
        printf("AD9361 config failed: invalid phy\r\n");
        return -EINVAL;
    }

    val = ad9361_config_result("fir_disable",
        ad9361_set_trx_fir_en_dis(phy, 0));
    if (val != 0) return val;

    val = ad9361_config_result("tx_fir",
        ad9361_set_tx_fir_config(phy, tx_fir_config));
    if (val != 0) return val;
    val = ad9361_config_result("rx_fir",
        ad9361_set_rx_fir_config(phy, rx_fir_config));
    if (val != 0) return val;

    /*
     * In this no-OS driver either API recalculates both RX and TX clock chains.
     * Call both explicitly so the intended contract is visible and then verify
     * both readbacks below.
     */
    val = ad9361_config_result("tx_sample_rate",
        ad9361_set_tx_sampling_freq(phy, sample_rate));
    if (val != 0) return val;
    val = ad9361_config_result("rx_sample_rate",
        ad9361_set_rx_sampling_freq(phy, sample_rate));
    if (val != 0) return val;

    val = ad9361_config_result("rx_bandwidth",
        ad9361_set_rx_rf_bandwidth(phy, bandwidth));
    if (val != 0) return val;
    val = ad9361_config_result("tx_bandwidth",
        ad9361_set_tx_rf_bandwidth(phy, tx_bandwidth));
    if (val != 0) return val;

    val = ad9361_config_result("tx_lo",
        ad9361_set_tx_lo_freq(phy, tx_lo_freq));
    if (val != 0) return val;
    val = ad9361_config_result("rx_lo",
        ad9361_set_rx_lo_freq(phy, rx_lo_freq));
    if (val != 0) return val;

    /* Use deterministic manual gain during the direct-cable bring-up. */
    val = ad9361_config_result("rx1_gain_mode",
        ad9361_set_rx_gain_control_mode(phy, 0, OPENWIFI_RX_GAIN_MODE));
    if (val != 0) return val;
    val = ad9361_config_result("rx2_gain_mode",
        ad9361_set_rx_gain_control_mode(phy, 1, OPENWIFI_RX_GAIN_MODE));
    if (val != 0) return val;
    val = ad9361_config_result("rx1_gain",
        ad9361_set_rx_rf_gain(phy, 0, gain));
    if (val != 0) return val;
    val = ad9361_config_result("rx2_gain",
        ad9361_set_rx_rf_gain(phy, 1, gain));
    if (val != 0) return val;

    val = ad9361_config_result("tx1_attenuation",
        ad9361_set_tx_attenuation(phy, 0, txatt));
    if (val != 0) return val;
    val = ad9361_config_result("tx2_attenuation",
        ad9361_set_tx_attenuation(phy, 1, txatt));
    if (val != 0) return val;

    /*
     * Preserve the board-specific RF switch and port routing. At 2.412 GHz
     * this board selects TX port 1 and RX port 1.
     */
    if (tx_lo_freq >= 70000000ULL && tx_lo_freq < 3000000000ULL) {
        gpio_set_value(TX_BAND_SEL, 0);
        val = ad9361_config_result("tx_rf_port",
            ad9361_set_tx_rf_port_output(phy, 1));
    } else {
        gpio_set_value(TX_BAND_SEL, 1);
        val = ad9361_config_result("tx_rf_port",
            ad9361_set_tx_rf_port_output(phy, 0));
    }
    if (val != 0) return val;

    if (rx_lo_freq >= 70000000ULL && rx_lo_freq < 2000000000ULL) {
        gpio_set_value(RX1_BAND_SEL_A, 0);
        gpio_set_value(RX1_BAND_SEL_B, 1);
        gpio_set_value(RX2_BAND_SEL_A, 0);
        gpio_set_value(RX2_BAND_SEL_B, 1);
        val = ad9361_config_result("rx_rf_port",
            ad9361_set_rx_rf_port_input(phy, 2));
    } else if (rx_lo_freq >= 2000000000ULL && rx_lo_freq < 3500000000ULL) {
        gpio_set_value(RX1_BAND_SEL_A, 1);
        gpio_set_value(RX1_BAND_SEL_B, 1);
        gpio_set_value(RX2_BAND_SEL_A, 1);
        gpio_set_value(RX2_BAND_SEL_B, 0);
        val = ad9361_config_result("rx_rf_port",
            ad9361_set_rx_rf_port_input(phy, 1));
    } else {
        gpio_set_value(RX1_BAND_SEL_A, 1);
        gpio_set_value(RX1_BAND_SEL_B, 0);
        gpio_set_value(RX2_BAND_SEL_A, 1);
        gpio_set_value(RX2_BAND_SEL_B, 1);
        val = ad9361_config_result("rx_rf_port",
            ad9361_set_rx_rf_port_input(phy, 0));
    }
    if (val != 0) return val;

    val = ad9361_config_result("fir_enable",
        ad9361_set_trx_fir_en_dis(phy, 1));
    if (val != 0) return val;

    val = ad9361_spi_read(phy->spi, regr);
    if (val < 0) {
        return ad9361_config_result("product_id_read", val);
    }
    if ((val & PRODUCT_ID_MASK) != PRODUCT_ID_9361) {
        printf("AD9361 config failed: product_id=0x%02lX\r\n",
            (unsigned long)val);
        return -ENODEV;
    }

    val = ad9361_config_result("get_tx_sample_rate",
        ad9361_get_tx_sampling_freq(phy, &tx_sampling_freq_hz));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx_sample_rate",
        ad9361_get_rx_sampling_freq(phy, &rx_sampling_freq_hz));
    if (val != 0) return val;
    val = ad9361_config_result("get_tx_bandwidth",
        ad9361_get_tx_rf_bandwidth(phy, &tx_bandwidth_hz));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx_bandwidth",
        ad9361_get_rx_rf_bandwidth(phy, &rx_bandwidth_hz));
    if (val != 0) return val;
    val = ad9361_config_result("get_tx_lo",
        ad9361_get_tx_lo_freq(phy, &tx_lo_readback_hz));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx_lo",
        ad9361_get_rx_lo_freq(phy, &rx_lo_readback_hz));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx1_gain_mode",
        ad9361_get_rx_gain_control_mode(phy, 0, &rx1_gain_mode));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx2_gain_mode",
        ad9361_get_rx_gain_control_mode(phy, 1, &rx2_gain_mode));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx1_gain",
        ad9361_get_rx_rf_gain(phy, 0, &rx1_gain_db));
    if (val != 0) return val;
    val = ad9361_config_result("get_rx2_gain",
        ad9361_get_rx_rf_gain(phy, 1, &rx2_gain_db));
    if (val != 0) return val;
    val = ad9361_config_result("get_tx1_attenuation",
        ad9361_get_tx_attenuation(phy, 0, &tx1_attenuation_mdb));
    if (val != 0) return val;
    val = ad9361_config_result("get_tx2_attenuation",
        ad9361_get_tx_attenuation(phy, 1, &tx2_attenuation_mdb));
    if (val != 0) return val;
    val = ad9361_config_result("get_path_clocks",
        ad9361_get_trx_path_clks(phy, rx_path_clks, tx_path_clks));
    if (val != 0) return val;

    rx_delay_reg = ad9361_spi_read(phy->spi, REG_RX_CLOCK_DATA_DELAY);
    if (rx_delay_reg < 0) {
        return ad9361_config_result("rx_clock_data_delay_read", rx_delay_reg);
    }
    tx_delay_reg = ad9361_spi_read(phy->spi, REG_TX_CLOCK_DATA_DELAY);
    if (tx_delay_reg < 0) {
        return ad9361_config_result("tx_clock_data_delay_read", tx_delay_reg);
    }

    if ((ad9361_abs_diff_u32(tx_sampling_freq_hz, sample_rate) >
            AD9361_SAMPLE_RATE_TOLERANCE_HZ) ||
        (ad9361_abs_diff_u32(rx_sampling_freq_hz, sample_rate) >
            AD9361_SAMPLE_RATE_TOLERANCE_HZ)) {
        printf("AD9361 config failed: sample rate tx=%lu rx=%lu expected=%lu\r\n",
            (unsigned long)tx_sampling_freq_hz,
            (unsigned long)rx_sampling_freq_hz,
            (unsigned long)sample_rate);
        return -EINVAL;
    }
    if ((phy->bypass_rx_fir != 0) || (phy->bypass_tx_fir != 0)) {
        printf("AD9361 config failed: FIR not enabled rx_bypass=%u tx_bypass=%u\r\n",
            (unsigned int)phy->bypass_rx_fir,
            (unsigned int)phy->bypass_tx_fir);
        return -EINVAL;
    }

    printf("AD9361 configured: ref=%luHz mode=2R2T-LVDS rx_fs=%luHz tx_fs=%luHz\r\n",
        (unsigned long)OPENWIFI_REFERENCE_CLK_HZ,
        (unsigned long)rx_sampling_freq_hz,
        (unsigned long)tx_sampling_freq_hz);
    printf("AD9361 RF: rx_lo=%luHz tx_lo=%luHz rx_bw=%luHz tx_bw=%luHz\r\n",
        (unsigned long)rx_lo_readback_hz,
        (unsigned long)tx_lo_readback_hz,
        (unsigned long)rx_bandwidth_hz,
        (unsigned long)tx_bandwidth_hz);
    printf("AD9361 gain: rx1_mode=%u rx1=%lddB rx2_mode=%u rx2=%lddB tx1_att=%lumdB tx2_att=%lumdB\r\n",
        (unsigned int)rx1_gain_mode, (long)rx1_gain_db,
        (unsigned int)rx2_gain_mode, (long)rx2_gain_db,
        (unsigned long)tx1_attenuation_mdb,
        (unsigned long)tx2_attenuation_mdb);
    printf("AD9361 FIR: rx=on tx=on taps=48 dec=1 int=1 gain=-6dB\r\n");
    printf("AD9361 clocks RX: %lu %lu %lu %lu %lu %lu\r\n",
        (unsigned long)rx_path_clks[0], (unsigned long)rx_path_clks[1],
        (unsigned long)rx_path_clks[2], (unsigned long)rx_path_clks[3],
        (unsigned long)rx_path_clks[4], (unsigned long)rx_path_clks[5]);
    printf("AD9361 clocks TX: %lu %lu %lu %lu %lu %lu\r\n",
        (unsigned long)tx_path_clks[0], (unsigned long)tx_path_clks[1],
        (unsigned long)tx_path_clks[2], (unsigned long)tx_path_clks[3],
        (unsigned long)tx_path_clks[4], (unsigned long)tx_path_clks[5]);
    printf("AD9361 digital delay: rx=0x%02lX tx=0x%02lX\r\n",
        (unsigned long)((uint32_t)rx_delay_reg & 0xFFU),
        (unsigned long)((uint32_t)tx_delay_reg & 0xFFU));

    return 0;
}

