#include "app_config.h"
#include "COMMON.h"
#include "AXI_DMA.h"
#include "net_init.h"
#include "net_rx.h"
#include "PS_UART.h"
#include "SCU_GIC.h"

#include "config.h"
#include "ad9361.h"
#include "ad9361_api.h"
#include "ad9361_config.h"
#include "gpio_initial.h"
#include "io_control.h"
#include "parameters.h"
#include "platform.h"
#include "radio_set.h"
#include "spi_ctrl.h"
#include "xil_io.h"
#include "xscugic.h"

#include <stdint.h>
#include <stdio.h>

#define OPENOFDM_TX_BASE  0x40000000U
#define TX_INTF_BASE      0x40001000U
#define OPENOFDM_RX_BASE  0x40002000U
#define RX_INTF_BASE      0x40003000U
#define REG(base, n)      ((base) + ((n) * 4U))
#define DEFAULT_PSDU_LEN_BYTES 3000U
#define OPENOFDM_RX_STATE_HISTORY_ADDR REG(OPENOFDM_RX_BASE, 20)
#define OPENOFDM_RX_WATCHDOG_EVENT_SEL_ADDR REG(OPENOFDM_RX_BASE, 17)
#define OPENOFDM_RX_WATCHDOG_EVENT_COUNTER_ADDR REG(OPENOFDM_RX_BASE, 30)
#define DEBUG_PRINT_INTERVAL 10000U

#define TX_INTF_S_AXIS_FIFO_TH_SMALL  (4096U - (210U * 2U))
#define TX_INTF_CTS_WAIT_SIFS_TOP     (((16U * 10U) << 16) | (16U * 10U))
#define TX_INTF_INTERRUPT_PHY_DONE    0x00000103U

#define OPENOFDM_RX_ENABLE_LOOPBACK   0x00010001U
#define OPENOFDM_RX_POWER_THRES_LB    ((127U << 16) | 0U)
#define OPENOFDM_RX_MIN_PLATEAU 100U
#define OPENOFDM_RX_SIGNAL_LEN_CFG    ((4095U << 16) | (14U << 12) | 1U)
#define OPENOFDM_RX_FFT_WIN_CFG       ((48U << 4) | 4U)
#define OPENOFDM_RX_PHASE_ABS_TH      0x0001FFFFU

#define RX_INTF_START_TRANS_MODE_AUTO 0x00010025U
#define RX_INTF_MAX_SIGNAL_LEN_CFG    (4095U << 16)
#define RX_INTF_CFG_DATA_TO_ANT       (1U << 8)
#define RX_INTF_BB_GAIN               0U
#define RX_INTF_TLAST_TIMEOUT_TOP     7000U
#define RX_INTF_S2MM_INTR_DELAY       (30U * 10U)

static unsigned char mac_ethernet_address[] = {
    0x02, 0x00, 0x00, 0x00, 0x00, 0x01
};

static uint32_t OpenWifi_RxWatchdogEventCount(uint32_t event_sel)
{
    volatile uint32_t delay;

    Xil_Out32(OPENOFDM_RX_WATCHDOG_EVENT_SEL_ADDR, event_sel);
    for (delay = 0U; delay < 32U; delay++) {
    }
    return Xil_In32(OPENOFDM_RX_WATCHDOG_EVENT_COUNTER_ADDR);
}

static void OpenWifi_RxDebugPrint(void)
{
    UART_Printf("rx_state_history=0x%08lX wd_evt[0..4]=%lu,%lu,%lu,%lu,%lu\r\n",
        (unsigned long)Xil_In32(OPENOFDM_RX_STATE_HISTORY_ADDR),
        (unsigned long)OpenWifi_RxWatchdogEventCount(0U),
        (unsigned long)OpenWifi_RxWatchdogEventCount(1U),
        (unsigned long)OpenWifi_RxWatchdogEventCount(2U),
        (unsigned long)OpenWifi_RxWatchdogEventCount(3U),
        (unsigned long)OpenWifi_RxWatchdogEventCount(4U));
}

static void OpenWifi_TxStaticRegs_Init(void)
{
    /*
     * openofdm_tx_0 @ 0x40000000
     */
    Xil_Out32(REG(OPENOFDM_TX_BASE, 1), 0x0000007F);
    Xil_Out32(REG(OPENOFDM_TX_BASE, 2), 0x0000005D);

    /*
     * tx_intf_0 @ 0x40001000
     * Static tx_intf parameters. Per-frame reset/length is handled by
     * OpenWifi_Tx_Rearm().
     */
    Xil_Out32(REG(TX_INTF_BASE, 4),  0x00000000);
    Xil_Out32(REG(TX_INTF_BASE, 5),  0x00000000);
    Xil_Out32(REG(TX_INTF_BASE, 6),  TX_INTF_CTS_WAIT_SIFS_TOP);
    Xil_Out32(REG(TX_INTF_BASE, 7),  0x00000000);
    Xil_Out32(REG(TX_INTF_BASE, 8),  0x00000177);
    Xil_Out32(REG(TX_INTF_BASE, 10), 0x00000000);
    Xil_Out32(REG(TX_INTF_BASE, 11), TX_INTF_S_AXIS_FIFO_TH_SMALL);
    Xil_Out32(REG(TX_INTF_BASE, 12), 0x00000190);
    Xil_Out32(REG(TX_INTF_BASE, 13), 0x00000040);
    Xil_Out32(REG(TX_INTF_BASE, 14), TX_INTF_INTERRUPT_PHY_DONE);
    Xil_Out32(REG(TX_INTF_BASE, 15), 0x00000000);
    Xil_Out32(REG(TX_INTF_BASE, 16), 0x00000000);
}

/*
 * Call this once before each MM2S DMA transfer.
 * psdu_len is the real wireless PSDU length in bytes, not the large DDR buffer
 * capacity. For the current fixed test, use 3000.
 */
void OpenWifi_Tx_Rearm(uint32_t psdu_len)
{
    uint32_t tx_intf_len_cfg;

    tx_intf_len_cfg = (psdu_len << 1) + 24U;

    /*
     * Reset/re-arm openofdm_tx and tx_intf internal TX state machines.
     * Do this before starting DMA, not continuously in while(1).
     */
    Xil_Out32(REG(OPENOFDM_TX_BASE, 0), 0x00000001);
    Xil_Out32(REG(OPENOFDM_TX_BASE, 0), 0x00000000);

    Xil_Out32(REG(TX_INTF_BASE, 0), 0x000000EC);
    Xil_Out32(REG(TX_INTF_BASE, 0), 0x00000000);

    /*
     * slv_reg2 and slv_reg17 must match this frame length.
     * For psdu_len = 3000:
     *   slv_reg2  = 2 * 3000 + 24 = 6024 = 0x1788
     *   slv_reg17 = 3000 = 0x0BB8
     */
    Xil_Out32(REG(TX_INTF_BASE, 2), tx_intf_len_cfg);
    Xil_Out32(REG(TX_INTF_BASE, 17), psdu_len);
}

static void OpenWifi_RxRegs_Init_Loopback(void)
{
    /*
     * openofdm_rx_0 @ 0x40002000
     */
    Xil_Out32(REG(OPENOFDM_RX_BASE, 0), 0x00000001);
    Xil_Out32(REG(OPENOFDM_RX_BASE, 0), 0x00000000);

    /*
     * bit0  = 1 keeps the openwifi driver default force_ht_smoothing.
     * bit16 = 1 disables the equalizer monitor watchdog.
     *
     * Keep bit13 at 0. Disabling the whole signal watchdog on this loopback
     * design can prevent long_preamble_detected.
     */
    Xil_Out32(REG(OPENOFDM_RX_BASE, 1), OPENOFDM_RX_ENABLE_LOOPBACK);
    /*
     * Digital loopback has no meaningful RSSI input in this design, so keep
     * the RSSI trigger threshold at 0. Use the largest positive DC watchdog
     * threshold to avoid false resets on the loopback stream.
     */
    Xil_Out32(REG(OPENOFDM_RX_BASE, 2), OPENOFDM_RX_POWER_THRES_LB);
    /*
     * slv_reg3 is sync_short min_plateau. The openofdm_rx testbench uses
     * 100; leaving this at 0 makes the short-preamble detector window too
     * short to reliably accumulate both positive and negative I samples.
     */
    Xil_Out32(REG(OPENOFDM_RX_BASE, 3), OPENOFDM_RX_MIN_PLATEAU);
    Xil_Out32(REG(OPENOFDM_RX_BASE, 4), OPENOFDM_RX_SIGNAL_LEN_CFG);
    Xil_Out32(REG(OPENOFDM_RX_BASE, 5), OPENOFDM_RX_FFT_WIN_CFG);
    Xil_Out32(REG(OPENOFDM_RX_BASE, 18), OPENOFDM_RX_PHASE_ABS_TH);

    /*
     * rx_intf_0 @ 0x40003000
     */
    Xil_Out32(REG(RX_INTF_BASE, 0), 0x000001B8);
    Xil_Out32(REG(RX_INTF_BASE, 0), 0x00000000);

    Xil_Out32(REG(RX_INTF_BASE, 2), 0x00000000);

    /*
     * slv_reg3 bit8:
     * 1 = digital loopback from tx_intf IQ.
     * 0 = real ADC/AD9361 RX path.
     */
    Xil_Out32(REG(RX_INTF_BASE, 3), 0x00000010);

    /*
     * slv_reg4:
     * bit1 = 0 enables FIFO input.
     * bit2 = 0 enables FIFO output.
     * bit3 = 1 enables 20 MHz baseband mode.
     */
    Xil_Out32(REG(RX_INTF_BASE, 4), 0x00000008);

    /*
     * slv_reg5:
     * bit5  = 1 uses decoded packet length/symbol count.
     * bit16 = 1 enables m_axis auto reset.
     */
    Xil_Out32(REG(RX_INTF_BASE, 5), RX_INTF_START_TRANS_MODE_AUTO);
    Xil_Out32(REG(RX_INTF_BASE, 6), RX_INTF_MAX_SIGNAL_LEN_CFG);
    Xil_Out32(REG(RX_INTF_BASE, 7), 0x00000000);

    /*
     * slv_reg9 is a fallback fixed symbol count. It is normally ignored
     * because slv_reg5[5] is set.
     */
    Xil_Out32(REG(RX_INTF_BASE, 9), 0x00000400);

    Xil_Out32(REG(RX_INTF_BASE, 10), RX_INTF_CFG_DATA_TO_ANT);
    Xil_Out32(REG(RX_INTF_BASE, 11), RX_INTF_BB_GAIN);

    /*
     * Keep tlast auto recover enabled, matching the openwifi driver default.
     */
    Xil_Out32(REG(RX_INTF_BASE, 12), RX_INTF_TLAST_TIMEOUT_TOP);

    Xil_Out32(REG(RX_INTF_BASE, 13), RX_INTF_S2MM_INTR_DELAY);
    Xil_Out32(REG(RX_INTF_BASE, 16), 0x00000000);
}

int main(void)
{
    uint8_t *TxBufferPtr;
    int32_t val;

#if APP_ENABLE_ICACHE
    Xil_ICacheEnable();
#else
    Xil_ICacheDisable();
#endif

#if APP_ENABLE_DCACHE
    Xil_DCacheEnable();
#else
    Xil_DCacheDisable();
#endif

    gpio_initial();

    default_init_param.gpio_resetb = RESETB;
    default_init_param.gpio_sync = -1;
    default_init_param.gpio_cal_sw1 = -1;
    default_init_param.gpio_cal_sw2 = -1;

    spi_init(SPI_DEVICE_ID, 1, 0);
    ad9361_init(&ad9361_phy, &default_init_param);
    ad9361_spi_write(ad9361_phy->spi, REG_TX_CLOCK_DATA_DELAY, 0x40);
    val = ad9361_config(ad9361_phy);
    (void)val;

    UART_Init(115200);
    UART_Printf("main start\r\n");

    TxBufferPtr = (uint8_t *)TX_BUFFER_BASE;

    ScuGic_Init();

    OpenWifi_TxStaticRegs_Init();
    OpenWifi_Tx_Rearm(DEFAULT_PSDU_LEN_BYTES);
    OpenWifi_RxRegs_Init_Loopback();
    UART_Printf("regs done\r\n");
//    OpenWifi_RxDebugPrint();

    AXI_DMA_Init(&AxiDma0, XPAR_AXIDMA_0_DEVICE_ID);
    AXI_DMA_TxInt_Init(&AxiDma0, TX_INTR_ID, TxIntrHandler);
    AXI_DMA_RxInt_Init(&AxiDma0, RX_INTR_ID, RxIntrHandler);

    if (Net_Init(mac_ethernet_address) != 0) {
        UART_Printf("Net_Init failed\r\n");
        while (1) {
        }
    }

    if (Net_RxInit(TxBufferPtr, TX_TRANSFER_LENGTH_BYTES) != 0) {
        UART_Printf("Net_RxInit failed\r\n");
        while (1) {
        }
    }

    UART_Printf("net ready\r\n");

    while (1) {
        static uint32_t debug_print_count = 0U;

        Net_Poll();
        Net_RxPoll();

        debug_print_count++;
        if (debug_print_count >= DEBUG_PRINT_INTERVAL) {
            debug_print_count = 0U;
//            OpenWifi_RxDebugPrint();
        }
    }
}
