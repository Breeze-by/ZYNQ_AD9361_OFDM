#ifndef AD9361_TEST2_APP_CONFIG_H_
#define AD9361_TEST2_APP_CONFIG_H_

#define RX_INTR_ID XPAR_FABRIC_AXIDMA_0_S2MM_INTROUT_VEC_ID
#define TX_INTR_ID XPAR_FABRIC_AXIDMA_0_MM2S_INTROUT_VEC_ID

#define APP_ENABLE_ICACHE 1
#define APP_ENABLE_DCACHE 1

/*
 * RX source selected by rx_intf slv_reg3[8]. Keep the choice in one place so
 * an RF build cannot accidentally retain the old digital-loopback register
 * literal from main.c.
 */
#define APP_RX_SOURCE_AD9361 0U
#define APP_RX_SOURCE_DIGITAL_LOOPBACK 1U
#define APP_RX_SOURCE APP_RX_SOURCE_AD9361

/* Unequal-power RF experiment, matched TX/RX legacy BPSK 1/2 PHY only.
 * STF/LTF/SIGNAL and the first 32 DATA symbols remain at full amplitude;
 * later DATA amplitude is 1/16. Set ENABLE=0 on BOTH peers to bypass.
 * Digital loopback always bypasses this experiment. Requires A7170002 RTL.
 */
#define APP_RF_PAYLOAD_POWER_ENABLE 1U
#define APP_RF_PAYLOAD_POWER_SHIFT 4U
#define APP_RF_PAYLOAD_PROTECTED_SYMBOLS 32U

#if (APP_RF_PAYLOAD_POWER_ENABLE > 1U) || (APP_RF_PAYLOAD_POWER_SHIFT > 4U) || (APP_RF_PAYLOAD_PROTECTED_SYMBOLS > 63U)
#error "Invalid unequal-power PHY configuration"
#endif

#if (APP_RX_SOURCE != APP_RX_SOURCE_AD9361) && (APP_RX_SOURCE != APP_RX_SOURCE_DIGITAL_LOOPBACK)
#error "Unsupported APP_RX_SOURCE"
#endif

#define TX_BUFFER_WORD_COUNT ((2U * 1024U * 1024U) / 8U)
#define TX_BUFFER_BASE 0x1200000
#define RX_BUFFER_BASE 0x1400000
#define RX_TRANSFER_LENGTH_BYTES (8192U)
#define TX_TRANSFER_LENGTH_BYTES (TX_BUFFER_WORD_COUNT * 8U)

#define ETH_IP_ADDR0 192
#define ETH_IP_ADDR1 168
#define ETH_IP_ADDR2 1
#define ETH_IP_ADDR3 50

#define ETH_NETMASK0 255
#define ETH_NETMASK1 255
#define ETH_NETMASK2 255
#define ETH_NETMASK3 0

#define ETH_GW_ADDR0 192
#define ETH_GW_ADDR1 168
#define ETH_GW_ADDR2 1
#define ETH_GW_ADDR3 1

#endif /* AD9361_TEST2_APP_CONFIG_H_ */
