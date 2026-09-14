import math
import socket
import struct
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from snr_telemetry import (Moments, Telemetry, SNRTracker, SNRClient, SNRPoint,
                           crc32, parse_response, RESPONSE_MAGIC, REQUEST_MAGIC, QUIET_CONFIRM)


def wire_response(request_id=1):
    words = [0] * 65
    words[:6] = [RESPONSE_MAGIC, 1, request_id, 3, 7, 500]
    words[6:13] = [66, 0, 18000000, 40000000, 2200000000, 0, 0xA7048304]
    words[13] = 2
    words[15] = 1
    words[16] = 10000
    words[18] = 60000
    words[28] = 25000000
    words[30] = 100000
    words[32] = 200000
    data = struct.pack('<64I', *words[:64])
    return data + struct.pack('<I', crc32(data))


class SNRTests(unittest.TestCase):
    def series(self, count=0, power=0, ticks=1, **kwargs):
        return replace(parse_response(wire_response(), 1),
                       signal=Moments(count, power, 0, 0), ticks=ticks, **kwargs)

    def test_dc_removed_from_mean_squared_magnitude(self):
        # Signal alternates +/-1 about DC=(10,20); total raw mean power=501.
        self.assertEqual(Moments(100, 50100, 1000, 2000).variance(), 1)
        self.assertIsNone(Moments(0, 0, 0, 0).variance())

    def test_wire_roundtrip_and_signed_sums(self):
        value = parse_response(wire_response(), 1)
        self.assertEqual(value.signal.count, 10000)
        self.assertEqual(value.noise.variance(), 2)
        self.assertEqual(value.ticks, 25000000)
        self.assertEqual(Moments.from_words([1, 0, 10, 0, 0xFFFFFFFE, 0xFFFFFFFF, 0, 0, 0]).i, -2)

    def test_wire_rejects_length_crc_version_id_and_reserved(self):
        raw = wire_response()
        for damaged in (raw[:-1], raw + b'x', raw[:30] + bytes([raw[30] ^ 1]) + raw[31:]):
            with self.assertRaises(ValueError):
                parse_response(damaged, 1)
        with self.assertRaises(ValueError):
            parse_response(raw, 2)
        for index in (1, 14, 15, 50):
            words = list(struct.unpack('<65I', raw))
            words[index] = 9
            body = struct.pack('<64I', *words[:64])
            with self.assertRaises(ValueError):
                parse_response(body + struct.pack('<I', crc32(body)), 1)

    def test_linear_noise_subtraction_not_total_power_ratio(self):
        tracker = SNRTracker()
        tracker.observe(self.series(), 1)
        result = tracker.observe(self.series(10000, 60000, 25000001), 1.25)
        self.assertAlmostEqual(result.db, 10 * math.log10(2))  # (6-2)/2
        self.assertEqual(result.noise_power, 2)
        self.assertEqual(result.signal_plus_noise, 6)
        self.assertIn('wideband', result.status)
        self.assertIn('DC/tones', result.status)

    def test_negative_db_is_valid(self):
        tracker = SNRTracker()
        tracker.observe(self.series(), 1)
        result = tracker.observe(self.series(10000, 30000, 25000001), 1.25)
        self.assertAlmostEqual(result.db, -10 * math.log10(2))

    def test_window_is_sample_weighted_not_average_db(self):
        tracker = SNRTracker()
        tracker.observe(self.series(), 1)
        tracker.observe(self.series(10000, 30000, 25000001), 1.25)
        result = tracker.observe(self.series(40000, 210000, 50000001), 1.5)
        self.assertAlmostEqual(result.db, 10 * math.log10((210000 / 40000 - 2) / 2))
        self.assertEqual(result.samples, 40000)

    def test_idle_no_samples_and_old_window_expiry(self):
        tracker = SNRTracker()
        tracker.observe(self.series(), 1)
        tracker.observe(self.series(10000, 60000, 25000001), 1.25)
        for n in range(2, 6):
            result = tracker.observe(self.series(10000, 60000, n * 25000000 + 1), 1 + n * 0.25)
        self.assertIsNone(result.db)
        self.assertEqual(result.samples, 0)

    def test_invalid_noise_or_unresolved_signal_is_not_fake_zero_db(self):
        for power, noise in ((10000, Moments(10000, 20000, 0, 0)),
                             (20000, Moments(10000, 20000, 0, 0)),
                             (20000, Moments(10000, 0, 0, 0)),
                             (20000, Moments(10000, 10000, 20000, 0))):
            tracker = SNRTracker()
            tracker.observe(self.series(noise=noise), 1)
            result = tracker.observe(self.series(10000, power, 25000001, noise=noise), 1.25)
            self.assertIsNone(result.db)

    def test_clipping_invalidates_snr(self):
        tracker = SNRTracker()
        tracker.observe(self.series(), 1)
        value = replace(self.series(10000, 60000, 25000001), signal=Moments(10000, 60000, 0, 0, 1))
        result = tracker.observe(value, 1.25)
        self.assertIsNone(result.db)
        self.assertIn('clipped', result.status)

    def test_all_board_failure_flags_report_unavailable(self):
        for flags in (0, 1, 5, 1 | 8, 1 | 16, 1 | 32, 1 | 64, 1 | 128, 1 | 512):
            result = SNRTracker().observe(self.series(flags=flags), 1)
            self.assertIsNone(result.db)
            self.assertTrue(result.status)

    def test_recalibration_context_changes_and_hardware_resets_clear_history(self):
        for update in (dict(epoch=8), dict(context=(65, 0, 18000000, 40000000, 2200000000, 0, 0xA7048304)), dict(ticks=0)):
            tracker = SNRTracker()
            tracker.observe(self.series(), 1)
            tracker.observe(self.series(10000, 60000, 25000001), 1.25)
            value = replace(self.series(20000, 120000, 50000001), **update)
            self.assertIsNone(tracker.observe(value, 1.5).db)
            self.assertFalse(tracker.samples)

    def test_long_telemetry_gap_and_impossible_counter_delta_rejected(self):
        for value in (self.series(10000, 60000, 200000001), self.series(999999999, 60000, 25000001)):
            tracker = SNRTracker()
            tracker.observe(self.series(), 1)
            self.assertIsNone(tracker.observe(value, 1.25).db)

    def test_moment_delta_preserves_signed_sum_and_counter_wrap(self):
        old = Moments((1 << 64) - 5, (1 << 64) - 50, 10, -20, 0xFFFFFFFF)
        new = Moments(5, 50, -10, 20, 0)
        self.assertEqual(new.delta(old), Moments(10, 100, -20, 40, 1))

    def test_client_local_udp_checks_crc_and_uses_separate_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0))
            server.settimeout(2)
            outcome = []
            def reply():
                data, peer = server.recvfrom(256)
                outcome.append(struct.unpack('<5I', data))
                request_id = outcome[0][1]
                server.sendto(wire_response(request_id ^ 1), peer)  # stale response
                server.sendto(wire_response(request_id), peer)
            worker = threading.Thread(target=reply)
            worker.start()
            client = SNRClient('127.0.0.1', '127.0.0.1', server.getsockname()[1])
            try:
                value = client.request(1)
                self.assertEqual(value.flags, 3)
                self.assertNotEqual(client.sock.getsockname()[1], 15002)
            finally:
                client.close()
                worker.join(2)
            self.assertEqual(outcome[0][0], REQUEST_MAGIC)
            self.assertEqual(outcome[0][2:4], (1, QUIET_CONFIRM))
            self.assertEqual(outcome[0][4], crc32(struct.pack('<4I', *outcome[0][:4])))

    def test_calibration_needs_supported_hardware_and_valid_noise(self):
        client = object.__new__(SNRClient)
        good = self.series()
        with patch.object(client, 'request', return_value=replace(good, flags=0)):
            with self.assertRaises(ValueError):
                client.calibrate(threading.Event())
        with patch.object(client, 'request', side_effect=[good, replace(good, flags=5), good]):
            self.assertEqual(client.calibrate(threading.Event()), good)


if __name__ == '__main__':
    unittest.main()
