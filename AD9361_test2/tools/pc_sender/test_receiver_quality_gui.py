import math
import tkinter as tk
import unittest

from link_quality import QualitySnapshot
from quality_chart import QualityChart
from receiver_core import ReceiverStats
from receiver_gui import ReceiverGui


class QualityGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_chart_keeps_negative_db_and_missing_samples(self):
        chart = QualityChart(self.root, unit="dB")
        chart.add_point(100, -3)
        chart.add_point(101, None, "no telemetry")
        chart.add_point(102, math.nan)
        self.assertEqual(list(chart.points), [(100, -3), (101, None), (102, None)])
        chart.add_point(102, 99)  # Do not duplicate/reorder chart timestamps.
        chart.add_point(math.inf, 99)
        self.assertEqual(len(chart.points), 3)
        chart.reset()
        self.assertFalse(chart.points)

    def test_history_is_bounded_to_sixty_seconds(self):
        chart = QualityChart(self.root)
        for timestamp in range(100):
            chart.add_point(timestamp, timestamp / 100)
        self.assertEqual(chart.points[0][0], 39)
        self.assertEqual(chart.points[-1][0], 99)

    def test_gui_receives_quality_and_does_not_invent_snr(self):
        gui = ReceiverGui(self.root)
        sample = QualitySnapshot(timestamp=100, epoch=1, received_packets=997,
                                 expected_so_far=1000, missing_packets=3,
                                 loss_pct=1, loss_total_pct=0.3,
                                 window_expected_packets=100, window_received_packets=99,
                                 window_missing_packets=1, ber_pct=7.5, ber_total_pct=7.5,
                                 compared_bits=8000, error_bits=600)
        gui._update_stats(ReceiverStats(quality=sample))
        self.assertEqual(gui.loss_chart.points[-1][1], 1)
        self.assertIn("Loss last 1s=1.0000% (1/100)", gui.quality_loss_var.get())
        self.assertIn("total=0.3000% (3/1000)", gui.quality_loss_var.get())
        self.assertEqual(gui.ber_chart.points[-1][1], 7.5)
        self.assertIsNone(gui.snr_chart.points[-1][1])
        gui._update_stats(ReceiverStats(quality=sample))
        self.assertEqual(len(gui.loss_chart.points), 1)
        gui._update_quality(QualitySnapshot(timestamp=101, epoch=1,
                                           received_packets=997, expected_so_far=1000,
                                           missing_packets=3, loss_total_pct=0.3))
        self.assertIsNone(gui.loss_chart.points[-1][1])
        self.assertIn("Loss last 1s=N/A", gui.quality_loss_var.get())
        self.assertIn("total=0.3000% (3/1000)", gui.quality_loss_var.get())
        gui._update_quality(QualitySnapshot(timestamp=102, epoch=2))
        self.assertEqual(len(gui.loss_chart.points), 1)
        self.assertIsNone(gui.loss_chart.points[-1][1])
        gui._reset_runtime_state()
        self.assertFalse(gui.ber_chart.points)

    def test_queued_stats_are_snapshots_not_reused_mutable_worker_state(self):
        gui = ReceiverGui(self.root)
        stats = ReceiverStats(packets=2)
        gui._receiver_callback("progress", {"stats": stats})
        stats.packets = 9
        event, payload = gui.event_queue.get_nowait()
        self.assertEqual(event, "progress")
        self.assertEqual(payload["stats"].packets, 2)

    def test_reference_config_and_status_event(self):
        gui = ReceiverGui(self.root)
        gui.ber_skip_var.set("30")
        gui.ber_reference_mode_var.set("air0")
        config = gui._build_config_object()
        self.assertEqual(config.ber_skip_bytes, 30)
        self.assertEqual(config.ber_reference_mode, "air0")
        gui._handle_event("quality_status", {"message": "Preparing reference"})
        self.assertEqual(gui.quality_reference_var.get(), "Preparing reference")
        gui._open_quality_settings()
        gui.quality_settings_window.withdraw()
        self.assertTrue(gui.quality_settings_window.winfo_exists())


if __name__ == "__main__":
    unittest.main()
