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

static uint32_t net_ipv4_octets_to_host(const uint8_t octets[4])
{
    return ((uint32_t)octets[0] << 24) |
        ((uint32_t)octets[1] << 16) |
        ((uint32_t)octets[2] << 8) |
        (uint32_t)octets[3];
}

static int net_ipv4_config_valid(const uint8_t ip_addr[4],
    const uint8_t netmask[4], const uint8_t gateway[4])
{
    uint32_t ip_value = net_ipv4_octets_to_host(ip_addr);
    uint32_t mask_value = net_ipv4_octets_to_host(netmask);
    uint32_t gateway_value = net_ipv4_octets_to_host(gateway);
    uint32_t host_mask;

    if ((ip_addr[0] == 0U) || (ip_addr[0] == 127U) || (ip_addr[0] >= 224U) ||
        (mask_value == 0U)) {
        return 0;
    }

    host_mask = ~mask_value;
    if ((host_mask & (host_mask + 1U)) != 0U) {
        return 0;
    }
    if (((ip_value & host_mask) == 0U) ||
        ((ip_value & host_mask) == host_mask)) {
        return 0;
    }

    if ((gateway_value != 0U) &&
        ((gateway_value & mask_value) != (ip_value & mask_value))) {
        return 0;
    }

    return 1;
}

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

int Net_ApplyIpv4Config(const uint8_t ip_addr[4], const uint8_t netmask[4],
    const uint8_t gateway[4])
{
    ip_addr_t ipaddr;
    ip_addr_t mask;
    ip_addr_t gw;

    if ((ethernet_ready == 0) ||
        (net_ipv4_config_valid(ip_addr, netmask, gateway) == 0)) {
        return -1;
    }

    IP_ADDR4(&ipaddr, ip_addr[0], ip_addr[1], ip_addr[2], ip_addr[3]);
    IP_ADDR4(&mask, netmask[0], netmask[1], netmask[2], netmask[3]);
    IP_ADDR4(&gw, gateway[0], gateway[1], gateway[2], gateway[3]);
    netif_set_addr(&server_netif, &ipaddr, &mask, &gw);
    etharp_gratuitous(&server_netif);

    UART_Printf("IPCFG applied IP=%s\r\n", ip4addr_ntoa(netif_ip4_addr(&server_netif)));
    UART_Printf("IPCFG applied MASK=%s\r\n", ip4addr_ntoa(netif_ip4_netmask(&server_netif)));
    UART_Printf("IPCFG applied GW=%s\r\n", ip4addr_ntoa(netif_ip4_gw(&server_netif)));
    return 0;
}

void Net_Poll(void)
{
    uint32_t poll_count;

    if (ethernet_ready != 0) {
        for (poll_count = 0U; poll_count < NET_INPUT_POLL_BUDGET; ++poll_count) {
            if (xemacif_input(&server_netif) <= 0) {
                break;
            }
        }
    }
}
