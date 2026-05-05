#include "COMMON.h"
#include "AXI_DMA.h"
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

#include <math.h>
#include <stdio.h>

#define PI 3.14159265358979323846
#define ARRAY_LENGTH 2000
#define BITS 12
#define AMPLITUDE ((1 << (BITS - 1)) - 1)

#define RX_INTR_ID XPAR_FABRIC_AXIDMA_0_S2MM_INTROUT_VEC_ID
#define TX_INTR_ID XPAR_FABRIC_AXIDMA_0_MM2S_INTROUT_VEC_ID

#define TX_BUFFER_BASE 0x1200000
#define RX_BUFFER_BASE 0x1400000

int main(void)
{
    uint16_t Error_Cnt = 0;
    uint64_t *TxBufferPtr;
    uint64_t *RxBufferPtr;
    int32_t val;
    int i;

    Xil_ICacheDisable();
    Xil_DCacheDisable();

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
    (void)Error_Cnt;

    UART_Init(115200);
    for (i = 0; i < 10; i++) {
        UART_Printf("1234567\r\n");
    }

    TxBufferPtr = (uint64_t *)TX_BUFFER_BASE;
    RxBufferPtr = (uint64_t *)RX_BUFFER_BASE;

    ScuGic_Init();
    AXI_DMA_Init(&AxiDma0, XPAR_AXIDMA_0_DEVICE_ID);
    AXI_DMA_TxInt_Init(&AxiDma0, TX_INTR_ID, TxIntrHandler);
    AXI_DMA_RxInt_Init(&AxiDma0, RX_INTR_ID, RxIntrHandler);

    for (i = 0; i < ARRAY_LENGTH; i++) {
        double sin_value1 = sin(10 * PI * i / ARRAY_LENGTH);
        double scaled_value1 = sin_value1 * AMPLITUDE;
        short rounded_value1 =
            (short)((scaled_value1 > 0) ? (scaled_value1 + 0.5) : (scaled_value1 - 0.5));

        double sin_value2 = sin(100 * PI * i / ARRAY_LENGTH);
        double scaled_value2 = sin_value2 * AMPLITUDE;
        short rounded_value2 =
            (short)((scaled_value2 > 0) ? (scaled_value2 + 0.5) : (scaled_value2 - 0.5));

        TxBufferPtr[i] = ((uint64_t)(rounded_value1 & 0x0fff)) |
                         (((uint64_t)(rounded_value2 & 0x0fff)) << 12) |
                         (((uint64_t)(rounded_value1 & 0x0fff)) << 24) |
                         (((uint64_t)(rounded_value2 & 0x0fff)) << 36);
    }

    while (1) {
        TxDone = 0;
        RxDone = 0;

        Xil_DCacheFlushRange((UINTPTR)TxBufferPtr, ARRAY_LENGTH * 8);
        Xil_DCacheFlushRange((UINTPTR)RxBufferPtr, 400 * 8);

        XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)RxBufferPtr, 400 * 8,
            XAXIDMA_DEVICE_TO_DMA);
        XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)TxBufferPtr, ARRAY_LENGTH * 8,
            XAXIDMA_DMA_TO_DEVICE);

        while (!TxDone) {
        }

        while (!RxDone) {
        }
    }
}
