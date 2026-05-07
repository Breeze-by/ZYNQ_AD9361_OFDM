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

#include <stdio.h>

static unsigned char mac_ethernet_address[] = { 0x02, 0x00, 0x00, 0x00, 0x00, 0x01 };

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

    TxBufferPtr = (uint8_t *)TX_BUFFER_BASE;

    ScuGic_Init();
    AXI_DMA_Init(&AxiDma0, XPAR_AXIDMA_0_DEVICE_ID);
    AXI_DMA_TxInt_Init(&AxiDma0, TX_INTR_ID, TxIntrHandler);
    AXI_DMA_RxInt_Init(&AxiDma0, RX_INTR_ID, RxIntrHandler);

    if (Net_Init(mac_ethernet_address) != 0) {
        while (1) {
        }
    }

    if (Net_RxInit(TxBufferPtr, TX_TRANSFER_LENGTH_BYTES) != 0) {
        while (1) {
        }
    }

    while (1) {
        Net_Poll();
        Net_RxPoll();
    }
}
