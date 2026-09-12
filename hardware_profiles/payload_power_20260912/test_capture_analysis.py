"""Offline checker tests only; synthetic flips here never enter RF experiments."""
import binascii
from pathlib import Path
import random
import struct
import tempfile
import unittest

from analyze_capture import analyze
from air_protocol import build_air_packet, make_file_id


class CaptureAnalysisTests(unittest.TestCase):
    def packets(self):
        source = random.Random(9361320).randbytes(2048)
        crc = binascii.crc32(source) & 0xffffffff
        return [build_air_packet(source[i*960:(i+1)*960], i, 3, i*960,
                                 2048, 1024, 1, crc, make_file_id(2048, crc, 1)) for i in range(3)]

    def run_capture(self, packets):
        with tempfile.TemporaryDirectory(prefix='ad9361-checker-test-') as tmp:
            path = Path(tmp) / 'capture.bin'
            path.write_bytes(b''.join(struct.pack('<QI', i*1024, len(p)) + p for i, p in packets))
            return analyze(path, 2048)

    def test_complete_short_last_packet(self):
        result = self.run_capture(enumerate(self.packets()))
        self.assertEqual((result['received_packets'], result['missing_count'], result['checked_bytes']), (3, 0, 2048))
        self.assertEqual(result['invalid'], [])
        self.assertEqual(result['bit_errors'], 0)

    def test_missing_packet_does_not_hide_later_payload(self):
        packets = self.packets()
        result = self.run_capture([(0, packets[0]), (2, packets[2])])
        self.assertEqual(result['missing'], [1])
        self.assertEqual(result['checked_bytes'], 1088)

    def test_region_counts_use_actual_bit_differences(self):
        packets = self.packets()
        packet = bytearray(packets[1])
        packet[64+10] ^= 1
        packet[64+50] ^= 7
        packets[1] = bytes(packet)
        result = self.run_capture(enumerate(packets))
        self.assertEqual((result['bad_payloads'], result['bit_errors']), (1, 4))
        self.assertEqual((result['protected_payload_bit_errors'], result['weak_payload_bit_errors']), (1, 3))
        self.assertEqual(result['missing_count'], 0)

    def test_bad_header_is_invalid_not_payload_ber(self):
        packets = self.packets()
        packet = bytearray(packets[1])
        packet[12] ^= 1
        packets[1] = bytes(packet)
        result = self.run_capture(enumerate(packets))
        self.assertEqual(len(result['invalid']), 1)
        self.assertEqual(result['missing'], [1])
        self.assertEqual(result['bit_errors'], 0)


if __name__ == '__main__':
    unittest.main()
