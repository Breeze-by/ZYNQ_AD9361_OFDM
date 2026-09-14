import math
import tkinter as tk
import unittest
from unittest.mock import patch

from link_quality import QualitySnapshot
from quality_chart import QualityChart
from receiver_core import ReceiverStats
from receiver_gui import ReceiverGui
from snr_telemetry import SNRPoint


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

    def test_measured_snr_is_independent_of_ber_and_loss_epochs(self):
        gui = ReceiverGui(self.root)
        point = SNRPoint(100, -2.5, "Measured", 156.234, 100, 20000, 7500)
        gui._handle_event("snr", {"generation": gui.snr_generation, "point": point})
        gui._update_quality(QualitySnapshot(timestamp=101, epoch=1))
        gui._update_quality(QualitySnapshot(timestamp=102, epoch=2))
        self.assertEqual(list(gui.snr_chart.points), [(100, -2.5)])
        self.assertIn("SNR=-2.50 dB", gui.quality_snr_var.get())
        self.assertIn("noise age=7.5s", gui.quality_snr_var.get())
        gui._update_snr(SNRPoint(103, status="No new samples"))
        self.assertIsNone(gui.snr_chart.points[-1][1])
        self.assertIn("SNR=N/A", gui.quality_snr_var.get())

    def test_stale_snr_worker_events_cannot_update_new_session(self):
        gui = ReceiverGui(self.root)
        old_generation = gui.snr_generation
        gui._stop_snr_worker()
        gui._handle_event("snr", {"generation": old_generation, "point": SNRPoint(100, 99)})
        gui._handle_event("snr_calibrated", {"generation": old_generation, "message": "stale"})
        self.assertFalse(gui.snr_chart.points)
        self.assertNotEqual(gui.quality_snr_var.get(), "stale")

    def test_noise_calibration_requires_stopped_receiver_and_confirmation(self):
        gui = ReceiverGui(self.root)
        with patch("receiver_gui.SNRClient") as client, \
                patch("receiver_gui.messagebox.showinfo") as info, \
                patch("receiver_gui.messagebox.askyesno", return_value=False) as ask:
            gui.receiver = object()
            gui._calibrate_snr()
            info.assert_called_once()
            ask.assert_not_called()
            gui.receiver = None
            gui._calibrate_snr()
            ask.assert_called_once()
            client.assert_not_called()
            self.assertFalse(gui.snr_calibrating)

    def test_snr_does_not_start_for_disabled_or_stopping_receiver(self):
        gui = ReceiverGui(self.root)
        gui.receiver = object()
        with patch("receiver_gui.threading.Thread") as thread:
            gui.snr_enabled_var.set(False)
            gui._start_snr_worker()
            gui.snr_enabled_var.set(True)
            gui.status_var.set("Stopping")
            gui._start_snr_worker()
            thread.assert_not_called()

    def test_calibration_completion_reenables_start_and_records_result(self):
        gui = ReceiverGui(self.root)
        gui.snr_calibrating = True
        gui.start_button.configure(state=tk.DISABLED)
        gui._handle_event("snr_calibrated", {"generation": gui.snr_generation,
                                           "message": "Noise calibrated"})
        self.assertFalse(gui.snr_calibrating)
        self.assertEqual(str(gui.start_button["state"]), tk.NORMAL)
        self.assertEqual(gui.quality_snr_var.get(), "Noise calibrated")


if __name__ == "__main__":
    unittest.main()
