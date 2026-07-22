import ipaddress
import struct
import unittest

from sender_core import (
    IPCFG_FORMAT,
    IPCFG_MAGIC,
    IPCFG_PACKET_SIZE,
    build_board_ip_config_packet,
)


class NetworkConfigPacketTests(unittest.TestCase):
    def test_builds_fixed_size_packet(self):
        packet = build_board_ip_config_packet(
            0x12345678,
            "192.168.2.50",
            "255.255.255.0",
            "0.0.0.0",
        )
        self.assertEqual(len(packet), IPCFG_PACKET_SIZE)
        magic, seq, ip_raw, mask_raw, gateway_raw, reserved = struct.unpack(
            IPCFG_FORMAT, packet
        )
        self.assertEqual(magic, IPCFG_MAGIC)
        self.assertEqual(seq, 0x12345678)
        self.assertEqual(ipaddress.IPv4Address(ip_raw), ipaddress.IPv4Address("192.168.2.50"))
        self.assertEqual(ipaddress.IPv4Address(mask_raw), ipaddress.IPv4Address("255.255.255.0"))
        self.assertEqual(ipaddress.IPv4Address(gateway_raw), ipaddress.IPv4Address("0.0.0.0"))
        self.assertEqual(reserved, 0)

    def test_rejects_network_address(self):
        with self.assertRaises(ValueError):
            build_board_ip_config_packet(1, "192.168.2.0", "255.255.255.0")

    def test_rejects_broadcast_address(self):
        with self.assertRaises(ValueError):
            build_board_ip_config_packet(1, "192.168.2.255", "255.255.255.0")

    def test_rejects_gateway_outside_subnet(self):
        with self.assertRaises(ValueError):
            build_board_ip_config_packet(
                1,
                "192.168.2.50",
                "255.255.255.0",
                "192.168.1.1",
            )


if __name__ == "__main__":
    unittest.main()
