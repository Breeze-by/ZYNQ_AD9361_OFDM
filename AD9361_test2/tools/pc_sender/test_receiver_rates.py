#!/usr/bin/env python3
import unittest
from tempfile import TemporaryDirectory

from receiver_core import LoopbackReceiver, ReceiverConfig, ReceiverStats


class ReceiverRateTests(unittest.TestCase):
    def test_rate_uses_recent_window_instead_of_receiver_start_time(self):
        with TemporaryDirectory() as temp_dir:
            receiver = LoopbackReceiver(ReceiverConfig(output_dir=temp_dir))
            stats = ReceiverStats(started_at=1.0)
            try:
                receiver._rate_samples.append((100.0, 0, 0))

                stats.received_bytes = 1024
                stats.packets = 1
                receiver._refresh_rates(stats, 100.5)
                self.assertAlmostEqual(stats.rate_kib_s, 2.0)
                self.assertAlmostEqual(stats.packet_rate_s, 2.0)

                stats.received_bytes = 3072
                stats.packets = 3
                receiver._refresh_rates(stats, 101.0)
                self.assertAlmostEqual(stats.rate_kib_s, 3.0)
                self.assertAlmostEqual(stats.packet_rate_s, 3.0)
            finally:
                receiver._discard_unsaved()

    def test_rate_falls_to_zero_after_window_has_no_new_packets(self):
        with TemporaryDirectory() as temp_dir:
            receiver = LoopbackReceiver(ReceiverConfig(output_dir=temp_dir))
            stats = ReceiverStats(started_at=1.0)
            try:
                receiver._rate_samples.append((100.0, 0, 0))
                stats.received_bytes = 2048
                stats.packets = 2
                receiver._refresh_rates(stats, 100.5)
                self.assertGreater(stats.rate_kib_s, 0.0)

                receiver._refresh_rates(stats, 101.6)
                self.assertEqual(stats.rate_kib_s, 0.0)
                self.assertEqual(stats.packet_rate_s, 0.0)
            finally:
                receiver._discard_unsaved()


if __name__ == "__main__":
    unittest.main()
