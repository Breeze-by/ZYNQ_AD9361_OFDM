#include "net_init.h"

#include "PS_UART.h"
#include "app_config.h"
#include "net_config.h"

#include "lwip/etharp.h"
#include "lwip/init.h"
#include "lwip/ip_addr.h"
#include "lwip/netif.h"
#include "netif/xadapter.h"

static struct netif server_netif;
static int ethernet_ready;

static void print_ip_settings(const struct netif *netif)
{
    UART_Printf("IP  : %s\r\n", ip4addr_ntoa(netif_ip4_addr(netif)));
    UART_Printf("MASK: %s\r\n", ip4addr_ntoa(netif_ip4_netmask(netif)));
    UART_Printf("GW  : %s\r\n", ip4addr_ntoa(netif_ip4_gw(netif)));
}

int Net_Init(const unsigned char *mac_address)
{
    ip_addr_t ipaddr;
    ip_addr_t netmask;
    ip_addr_t gw;

    lwip_init();

    IP_ADDR4(&ipaddr, ETH_IP_ADDR0, ETH_IP_ADDR1, ETH_IP_ADDR2, ETH_IP_ADDR3);
    IP_ADDR4(&netmask, ETH_NETMASK0, ETH_NETMASK1, ETH_NETMASK2, ETH_NETMASK3);
    IP_ADDR4(&gw, ETH_GW_ADDR0, ETH_GW_ADDR1, ETH_GW_ADDR2, ETH_GW_ADDR3);

    if (xemac_add(&server_netif, &ipaddr, &netmask, &gw, (unsigned char *)mac_address,
            XPAR_XEMACPS_0_BASEADDR) == NULL) {
        UART_Printf("Ethernet init failed\r\n");
        return -1;
    }

    netif_set_default(&server_netif);
    netif_set_up(&server_netif);
    etharp_gratuitous(&server_netif);

    UART_Printf("Ethernet ready\r\n");
    UART_Printf("MAC : %02X:%02X:%02X:%02X:%02X:%02X\r\n",
        mac_address[0], mac_address[1], mac_address[2],
        mac_address[3], mac_address[4], mac_address[5]);
    print_ip_settings(&server_netif);
    UART_Printf("UDP : listen on port %u\r\n", (unsigned)NET_UDP_PORT);
    UART_Printf("Try ping %d.%d.%d.%d from host\r\n",
        ETH_IP_ADDR0, ETH_IP_ADDR1, ETH_IP_ADDR2, ETH_IP_ADDR3);

    ethernet_ready = 1;
    return 0;
}

void Net_Poll(void)
{
    if (ethernet_ready != 0) {
        xemacif_input(&server_netif);
    }
}
