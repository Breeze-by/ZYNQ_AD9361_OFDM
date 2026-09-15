/* Temporary sender-only diagnostic. Send commands only while traffic is stopped.
 * No RF retries, artificial errors, waveform changes or receiver changes. */
#include "xil_cache.h"
volatile uint32_t file_ber_result[8] __attribute__((aligned(32))) = {0xA7250001U};
static void file_ber_control_poll(struct ad9361_rf_phy *phy)
{
    uint32_t command = Xil_In32(0x40000004U);
    uint32_t requested, actual0 = 0U, actual1 = 0U;
    int32_t status = 0;
    if ((command & 0xFFFF0000U) != 0xA7250000U) return;
    requested = ((command >> 8) & 0xFFU) * 250U;
    Xil_Out32(0x40000004U, command & 0x7FU);
    if (requested < 14000U || requested > 20000U) status = -100;
    else {
        status = ad9361_set_tx_attenuation(phy, 0, requested);
        if (!status) status = ad9361_set_tx_attenuation(phy, 1, requested);
        if (!status) status = ad9361_get_tx_attenuation(phy, 0, &actual0);
        if (!status) status = ad9361_get_tx_attenuation(phy, 1, &actual1);
        if (!status && (actual0 != requested || actual1 != requested)) status = -101;
        if (!status) txatt = requested;
    }
    file_ber_result[1]++;
    file_ber_result[2] = requested;
    file_ber_result[3] = (uint32_t)status;
    file_ber_result[4] = actual0;
    file_ber_result[5] = actual1;
    Xil_DCacheFlushRange((INTPTR)file_ber_result, sizeof(file_ber_result));
    UART_Printf("FILE_BER_ATT requested=%lu actual=%lu/%lu status=%ld\r\n",
                (unsigned long)requested, (unsigned long)actual0,
                (unsigned long)actual1, (long)status);
}
