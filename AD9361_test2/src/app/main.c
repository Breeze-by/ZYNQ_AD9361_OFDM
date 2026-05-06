#include "app_config.h"
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

#include "lwip/etharp.h"
#include "lwip/init.h"
#include "lwip/ip_addr.h"
#include "lwip/netif.h"
#include "netif/xadapter.h"

#include <math.h>
#include <stdio.h>

static struct netif server_netif;
static unsigned char mac_ethernet_address[] = { 0x02, 0x00, 0x00, 0x00, 0x00, 0x01 };
static int ethernet_ready;

static void print_ip_settings(const struct netif *netif)
{
    UART_Printf("IP  : %s\r\n", ip4addr_ntoa(netif_ip4_addr(netif)));
    UART_Printf("MASK: %s\r\n", ip4addr_ntoa(netif_ip4_netmask(netif)));
    UART_Printf("GW  : %s\r\n", ip4addr_ntoa(netif_ip4_gw(netif)));
}

static int ethernet_init(void)
{
    ip_addr_t ipaddr;
    ip_addr_t netmask;
    ip_addr_t gw;

    lwip_init();

    IP_ADDR4(&ipaddr, ETH_IP_ADDR0, ETH_IP_ADDR1, ETH_IP_ADDR2, ETH_IP_ADDR3);
    IP_ADDR4(&netmask, ETH_NETMASK0, ETH_NETMASK1, ETH_NETMASK2, ETH_NETMASK3);
    IP_ADDR4(&gw, ETH_GW_ADDR0, ETH_GW_ADDR1, ETH_GW_ADDR2, ETH_GW_ADDR3);

    if (xemac_add(&server_netif, &ipaddr, &netmask, &gw, mac_ethernet_address,
            XPAR_XEMACPS_0_BASEADDR) == NULL) {
        UART_Printf("Ethernet init failed\r\n");
        return -1;
    }

    netif_set_default(&server_netif);
    netif_set_up(&server_netif);
    etharp_gratuitous(&server_netif);

    UART_Printf("Ethernet ready\r\n");
    UART_Printf("MAC : %02X:%02X:%02X:%02X:%02X:%02X\r\n",
        mac_ethernet_address[0], mac_ethernet_address[1], mac_ethernet_address[2],
        mac_ethernet_address[3], mac_ethernet_address[4], mac_ethernet_address[5]);
    print_ip_settings(&server_netif);
    UART_Printf("Try ping %d.%d.%d.%d from host\r\n",
        ETH_IP_ADDR0, ETH_IP_ADDR1, ETH_IP_ADDR2, ETH_IP_ADDR3);

    ethernet_ready = 1;
    return 0;
}

static void ethernet_poll(void)
{
    if (ethernet_ready != 0) {
        xemacif_input(&server_netif);
    }
}

int main(void)
{
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

    ethernet_init();

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

        Xil_DCacheFlushRange((UINTPTR)TxBufferPtr, TX_TRANSFER_LENGTH_BYTES);
        Xil_DCacheFlushRange((UINTPTR)RxBufferPtr, RX_TRANSFER_LENGTH_BYTES);

        XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)RxBufferPtr, RX_TRANSFER_LENGTH_BYTES,
            XAXIDMA_DEVICE_TO_DMA);
        XAxiDma_SimpleTransfer(&AxiDma0, (UINTPTR)TxBufferPtr, TX_TRANSFER_LENGTH_BYTES,
            XAXIDMA_DMA_TO_DEVICE);

        while (!TxDone) {
            ethernet_poll();
        }

        while (!RxDone) {
            ethernet_poll();
        }

        ethernet_poll();
    }
}
