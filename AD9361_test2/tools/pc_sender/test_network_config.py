import ipaddress
import socket
import struct
import unittest
from unittest.mock import patch

from sender_core import (
    ACK_MAGIC,
    ACK_STATUS_OK,
    IPCFG_FORMAT,
    IPCFG_MAGIC,
    IPCFG_PACKET_SIZE,
    SenderConfig,
    UdpSender,
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

    def test_sender_broadcasts_ipcfg_from_explicit_adapter(self):
        class FakeSocket:
            def __init__(self):
                self.bound = None
                self.sent = []
                self.options = []
                self.timeout = None
                self.closed = False

            def bind(self, address):
                self.bound = address

            def setsockopt(self, level, option, value):
                self.options.append((level, option, value))

            def settimeout(self, timeout):
                self.timeout = timeout

            def sendto(self, packet, destination):
                self.sent.append((packet, destination))

            def recvfrom(self, _size):
                _magic, seq, *_rest = struct.unpack(IPCFG_FORMAT, self.sent[-1][0])
                ack = struct.pack("<IIHHI", ACK_MAGIC, seq, ACK_STATUS_OK, 0, 0)
                return ack, ("192.168.2.50", 5001)

            def close(self):
                self.closed = True

        fake_socket = FakeSocket()
        sender = UdpSender(SenderConfig(
            ip="192.168.2.50",
            bind_ip="192.168.2.101",
            configure_board_ip=True,
        ))
        events = []
        with patch("sender_core.socket.socket", return_value=fake_socket):
            sender._validate_config()
            configured = sender._configure_board_ip(
                lambda name, payload: events.append((name, payload))
            )

        self.assertTrue(configured)
        self.assertEqual(fake_socket.bound, ("192.168.2.101", 0))
        self.assertEqual(fake_socket.sent[0][1], ("255.255.255.255", 5001))
        self.assertIn(
            (socket.SOL_SOCKET, socket.SO_BROADCAST, 1),
            fake_socket.options,
        )
        self.assertTrue(fake_socket.closed)
        self.assertEqual(events[-1][0], "ip_configured")

    def test_sender_ipcfg_rejects_unspecified_or_wrong_subnet_bind(self):
        with self.assertRaisesRegex(ValueError, "PC Bind IP"):
            UdpSender(SenderConfig(
                ip="192.168.2.50",
                configure_board_ip=True,
            ))._validate_config()

        with self.assertRaisesRegex(ValueError, "same"):
            UdpSender(SenderConfig(
                ip="192.168.2.50",
                bind_ip="192.168.1.101",
                configure_board_ip=True,
            ))._validate_config()


if __name__ == "__main__":
    unittest.main()
