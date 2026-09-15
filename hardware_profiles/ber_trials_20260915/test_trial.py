"""Synthetic unit fixtures only; never inject errors on the real RF path."""
import sys
import json
import struct
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "AD9361_test2/tools/pc_sender"))
from air_protocol import build_air_packet, crc32
from sender_core import LOOPBACK_FORMAT, LOOPBACK_MAGIC
from trial import analyze


class TrialTests(unittest.TestCase):
    source = bytes(range(256)) * 5

    def wire(self, seq):
        return build_air_packet(self.source[seq*960:(seq+1)*960], seq, 2, seq*960,
                                len(self.source), 1024, 33, crc32(self.source), 22)

    def udp(self, seq, wire=None, offset=0, part=None, block=None):
        wire = self.wire(seq) if wire is None else wire
        part = wire if part is None else part
        return struct.pack(LOOPBACK_FORMAT, LOOPBACK_MAGIC, seq+1 if block is None else block,
                           seq*1024, len(wire), offset, len(part), 1,
                           crc32(part), 0, 0, 0, 0) + part

    def test_exact(self):
        report, data = analyze([self.udp(0), self.udp(1)], self.source)
        self.assertTrue(report["exact_file"])
        self.assertEqual(data, self.source)

    def test_bad_payload_received_not_erased(self):
        wire = bytearray(self.wire(0))
        wire[100] ^= 7
        report, data = analyze([self.udp(0, wire), self.udp(1)], self.source)
        self.assertTrue(report["zero_packet_loss"])
        self.assertFalse(report["exact_file"])
        self.assertEqual(report["bit_errors"], 3)
        self.assertEqual(report["weak_bit_errors"], 3)
        self.assertEqual(data[36], self.source[36] ^ 7)

    def test_missing_last_is_counted(self):
        report, data = analyze([self.udp(0)], self.source)
        self.assertEqual(report["missing"], [1])
        self.assertEqual(report["compared_bits"], 960*8)
        self.assertEqual(data[960:], bytes(320))

    def test_missing_first_is_counted(self):
        report, data = analyze([self.udp(1)], self.source)
        self.assertEqual(report["missing"], [0])
        self.assertEqual(data[960:], self.source[960:])

    def test_crc_bad_datagram_excluded(self):
        raw = bytearray(self.udp(0))
        raw[-1] ^= 1
        report, _ = analyze([raw, self.udp(1)], self.source)
        self.assertEqual(report["missing"], [0])

    def test_split_out_of_order(self):
        wire = self.wire(0)
        report, data = analyze([self.udp(0, wire, 500, wire[500:]),
                                self.udp(1), self.udp(0, wire, 0, wire[:500])], self.source)
        self.assertTrue(report["exact_file"])
        self.assertEqual(data, self.source)

    def test_block_ids_not_spliced(self):
        wire = self.wire(0)
        report, _ = analyze([self.udp(0, wire, 500, wire[500:], 7),
                            self.udp(0, wire, 0, wire[:500], 8)], self.source)
        self.assertEqual(report["received_packets"], 0)

    def test_duplicate_not_extra_bits(self):
        report, _ = analyze([self.udp(0), self.udp(0), self.udp(1)], self.source)
        self.assertEqual(report["duplicate_packets"], 1)
        self.assertEqual(report["compared_bits"], len(self.source)*8)

    def test_wrong_session_rejected(self):
        report, _ = analyze([self.udp(0), self.udp(1)], self.source, expected_session=34)
        self.assertEqual(report["received_packets"], 0)

    def test_report_json_round_trip(self):
        report, _ = analyze([self.udp(0), self.udp(1)], self.source)
        self.assertEqual(json.loads(json.dumps(report)), report)


if __name__ == "__main__":
    unittest.main()
