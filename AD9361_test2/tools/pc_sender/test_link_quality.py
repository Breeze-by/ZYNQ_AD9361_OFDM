import unittest
import socket
import struct
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from air_protocol import build_air_packet
from link_quality import LinkQualityTracker, PayloadReference, crc32
from receiver_core import LoopbackReceiver, ReceiverConfig, ReceiverStats
from sender_core import LOOPBACK_FORMAT, LOOPBACK_MAGIC
from video_protocol import build_airv_stream


class LinkQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = b"\x00\x00\x00\x01\x65" + b"\x80" * 2495
        self.path = Path(self.temp.name) / "source.h264"
        self.path.write_bytes(self.source)
        self.wire = build_airv_stream(self.source, chunk_bytes=1024, session_id=1, stream_id=2)
        self.chunks = [self.wire[n:n + 1024] for n in range(0, len(self.wire), 1024)]

    def tracker(self, skip=0):
        return LinkQualityTracker(PayloadReference(self.path, "airv"), skip_bytes=skip)

    def test_no_samples_or_source_is_unavailable_not_zero(self):
        tracker = LinkQualityTracker()
        result = tracker.snapshot(0)
        self.assertIsNone(result.loss_pct)
        self.assertIsNone(result.ber_pct)
        self.assertIsNone(result.snr_db)
        tracker.observe_wire(self.chunks[0], 0, now=1)
        result = tracker.snapshot(1)
        self.assertEqual(result.loss_pct, 0)
        self.assertIsNone(result.ber_pct)
        self.assertIsNone(result.snr_db)

    def test_initial_loss_duplicates_and_late_arrivals(self):
        tracker = self.tracker()
        tracker.observe_wire(self.chunks[2], 2048, now=1)
        result = tracker.snapshot(1)
        self.assertEqual((result.missing_packets, result.expected_so_far), (2, 3))
        self.assertAlmostEqual(result.loss_pct, 200 / 3)
        tracker.observe_wire(self.chunks[2], 2048, now=1.1)
        self.assertEqual(tracker.snapshot(1.1).received_packets, 1)
        tracker.observe_wire(self.chunks[0], 0, now=1.2)
        tracker.observe_wire(self.chunks[1], 1024, now=1.3)
        result = tracker.snapshot(1.3)
        self.assertEqual(result.loss_pct, 0)
        self.assertEqual(result.compared_bits, len(self.source) * 8)

    def test_missing_tail_not_fabricated_from_future_source_packets(self):
        tracker = self.tracker()
        tracker.observe_wire(self.chunks[0], 0, now=1)
        result = tracker.snapshot(1)
        self.assertEqual(result.expected_so_far, 1)
        self.assertEqual(result.missing_packets, 0)

    def test_bad_payload_crc_is_received_and_exact_bit_errors_counted(self):
        tracker = self.tracker()
        damaged = bytearray(self.chunks[0])
        damaged[64] ^= 0x81
        damaged[100] ^= 0xFF
        tracker.observe_wire(bytes(damaged), 0, now=1)
        result = tracker.snapshot(1)
        self.assertEqual(result.error_bits, 10)
        self.assertEqual(result.compared_bits, 960 * 8)
        self.assertEqual(result.loss_pct, 0)
        self.assertAlmostEqual(result.ber_pct, 1000 / (960 * 8))

    def test_weak_scope_skips_protected_prefix_not_header_or_padding(self):
        tracker = self.tracker(skip=30)
        damaged = bytearray(self.chunks[0])
        damaged[64] ^= 0xFF
        damaged[94] ^= 1
        tracker.observe_wire(damaged, 0, now=1)
        result = tracker.snapshot(1)
        self.assertEqual(result.error_bits, 1)
        self.assertEqual(result.compared_bits, 930 * 8)
        last = bytearray(self.chunks[2])
        last[-1] ^= 0xFF  # Padding is not business data.
        tracker.observe_wire(last, 2048, now=1.1)
        result = tracker.snapshot(1.1)
        self.assertEqual(result.error_bits, 1)
        self.assertEqual(result.compared_bits, (930 + 550) * 8)

    def test_recent_ber_expires_without_drawing_zero_and_total_is_retained(self):
        tracker = self.tracker()
        tracker.observe_wire(self.chunks[0], 0, now=1)
        self.assertEqual(tracker.snapshot(1.5).ber_pct, 0)
        result = tracker.snapshot(2.0)
        self.assertIsNone(result.ber_pct)
        self.assertEqual(result.ber_total_pct, 0)

    def test_crc_failure_is_not_used_to_guess_ber(self):
        tracker = LinkQualityTracker()
        damaged = bytearray(self.chunks[0])
        damaged[100] ^= 1
        tracker.observe_wire(damaged, 0, now=1)
        self.assertIsNone(tracker.snapshot(1).ber_pct)

    def test_wrong_reference_rejected_without_false_ber(self):
        self.path.write_bytes(self.source[:-1] + b"\x81")
        tracker = self.tracker()
        tracker.observe_wire(self.chunks[0], 0, now=1)
        result = tracker.snapshot(1)
        self.assertIsNone(result.ber_pct)
        self.assertEqual(result.compared_bits, 0)
        self.assertEqual(result.reference_skips, 1)
        self.assertIn("mismatch", result.reference_status)
        self.assertEqual(result.received_packets, 1)

    def test_bad_header_and_offset_mismatch_do_not_pollute_sequence_counts(self):
        tracker = self.tracker()
        damaged = bytearray(self.chunks[0])
        damaged[58] ^= 1
        tracker.observe_wire(damaged, 0, now=1)
        tracker.observe_wire(self.chunks[0], 1024, now=1)
        self.assertIsNone(tracker.snapshot(1).loss_pct)

    def test_new_stream_resets_and_old_stream_late_packet_ignored(self):
        tracker = self.tracker()
        tracker.observe_wire(self.chunks[2], 2048, now=1)
        next_wire = build_airv_stream(self.source, chunk_bytes=1024, session_id=3, stream_id=4)
        tracker.observe_wire(next_wire[:1024], 0, now=2)
        tracker.observe_wire(self.chunks[0], 0, now=2.1)
        result = tracker.snapshot(2.1)
        self.assertEqual(result.epoch, 2)
        self.assertEqual(result.received_packets, 1)
        self.assertEqual(result.missing_packets, 0)

    def test_reference_requires_annexb_for_video(self):
        self.path.write_bytes(b"not MP4 or a valid Annex-B source")
        with self.assertRaisesRegex(ValueError, "Annex-B"):
            PayloadReference(self.path, "airv")

    def test_air0_comparison_counts_bad_payload_as_received(self):
        source = b"\xAA" * 960
        self.path.write_bytes(source)
        tracker = LinkQualityTracker(PayloadReference(self.path, "air0"))
        packet = build_air_packet(source, session_id=1, file_id=2, packet_seq=0,
                                  total_packets=1, file_offset=0, chunk_bytes=1024,
                                  file_size=len(source), file_crc32=crc32(source))
        damaged = bytearray(packet)
        damaged[65] ^= 1
        tracker.observe_wire(damaged, 0, now=1)
        result = tracker.snapshot(1)
        self.assertEqual(result.received_packets, 1)
        self.assertEqual(result.error_bits, 1)

    def packet(self, index, payload=None, chunk_offset=0, block_len=1024):
        payload = self.chunks[index] if payload is None else payload
        return dict(payload=payload, stream_offset=index * 1024, chunk_offset=chunk_offset,
                    chunk_len=len(payload), block_id=index + 1, flags=1,
                    payload_crc32=crc32(payload), block_payload_len=block_len)

    def receiver(self):
        receiver = LoopbackReceiver(ReceiverConfig(output_dir=self.temp.name))
        receiver._quality = self.tracker()
        self.addCleanup(receiver._discard_unsaved)
        return receiver

    def test_receiver_measurement_survives_playback_gap_and_out_of_order(self):
        receiver = self.receiver()
        stats = ReceiverStats()
        receiver._process_loopback(self.packet(2), stats, None)
        receiver._emit_progress(None, stats, force=True)
        self.assertEqual(stats.quality.missing_packets, 2)
        receiver._process_loopback(self.packet(0), stats, None)
        receiver._process_loopback(self.packet(1), stats, None)
        receiver._emit_progress(None, stats, force=True)
        self.assertEqual(stats.quality.missing_packets, 0)
        self.assertEqual(stats.quality.compared_bits, len(self.source) * 8)

    def test_split_udp_return_is_measured_once_only_when_complete(self):
        receiver = self.receiver()
        stats = ReceiverStats()
        first = self.packet(0, self.chunks[0][:500])
        second = self.packet(0, self.chunks[0][500:], chunk_offset=500)
        receiver._process_loopback(second, stats, None)
        self.assertEqual(receiver._quality.snapshot().received_packets, 0)
        receiver._process_loopback(first, stats, None)
        receiver._process_loopback(second, stats, None)
        self.assertEqual(receiver._quality.snapshot().received_packets, 1)

    def test_bad_outer_crc_is_not_a_ber_sample(self):
        receiver = self.receiver()
        stats = ReceiverStats()
        packet = self.packet(0)
        packet["payload_crc32"] ^= 1
        receiver._process_loopback(packet, stats, None)
        result = receiver._quality.snapshot()
        self.assertEqual(result.received_packets, 0)
        self.assertEqual(result.compared_bits, 0)
        self.assertEqual(stats.crc_errors, 1)

    def test_local_udp_end_to_end_quality_with_source_reference(self):
        # Local synthetic test only: no board/RF traffic or production flips.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        receiver = LoopbackReceiver(ReceiverConfig(
            bind_ip="127.0.0.1", bind_port=port, register_with_board=False,
            output_dir=self.temp.name, idle_finish_s=0.1, progress_interval_s=0.05,
            ber_reference_path=str(self.path), ber_reference_mode="airv"))
        started = threading.Event()
        outcome = []

        def worker():
            try:
                outcome.append(receiver.run(lambda name, _payload: started.set() if name == "start" else None))
            except Exception as exc:
                outcome.append(exc)
                started.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                for seq in (0, 2, 2):
                    payload = bytearray(self.chunks[seq])
                    if seq == 2:
                        payload[100] ^= 7
                    header = struct.pack(LOOPBACK_FORMAT, LOOPBACK_MAGIC, seq + 1,
                                         seq * 1024, 1024, 0, 1024, 1, crc32(payload), 0, 0, 0, 0)
                    sender.sendto(header + payload, ("127.0.0.1", port))
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(outcome)
            if isinstance(outcome[0], Exception):
                raise outcome[0]
            quality = outcome[0].quality
            self.assertEqual(quality.received_packets, 2)
            self.assertEqual(quality.missing_packets, 1)
            self.assertEqual(quality.error_bits, 3)
            self.assertEqual(quality.compared_bits, (960 + 580) * 8)
            self.assertIsNone(quality.snr_db)
        finally:
            receiver.stop()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
