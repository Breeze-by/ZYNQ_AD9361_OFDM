"""Bounded, non-RXCFG SNR observation using the actual installed PC tracker.

--calibrate is ONLY for explicitly confirmed quiet Sender conditions.
This does not transmit RF data or alter RF parameters. Outputs are test artifacts.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'AD9361_test2' / 'tools' / 'pc_sender'))
from snr_telemetry import SNRClient, SNRTracker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--calibrate', action='store_true')
    parser.add_argument('--gui', action='store_true', help='Also exercise the real hidden GUI event/chart path')
    args = parser.parse_args()
    if not 0 < args.seconds <= 600:
        parser.error('Observation must be bounded to 1..600 seconds')
    stop = threading.Event()
    client = SNRClient('192.168.1.100', '192.168.1.50', 5001)
    tracker = SNRTracker()
    valid = []
    reasons = {}
    first_count = None
    last_count = None
    root = gui = None
    curve_observations = 0
    try:
        if args.gui:
            import tkinter as tk
            from receiver_gui import ReceiverGui
            root = tk.Tk()
            root.withdraw()
            gui = ReceiverGui(root)
        with args.out.open('x', encoding='utf-8') as output:
            if args.calibrate:
                noise = client.calibrate(stop)
                output.write(json.dumps({'event': 'calibration', 'telemetry': asdict(noise)}) + '\n')
                output.flush()
                print('SNR_NOISE_CALIBRATED count=%d power=%f' % (noise.noise.count, noise.noise.variance()), flush=True)
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                telemetry = client.request()
                point = tracker.observe(telemetry)
                if gui is not None:
                    gui._handle_event('snr', {'generation': gui.snr_generation, 'point': point})
                    root.update()
                    if any(gui.snr_chart.type(item) == 'line' and
                           gui.snr_chart.itemcget(item, 'fill') == gui.snr_chart.color
                           for item in gui.snr_chart.find_all()):
                        curve_observations += 1
                if first_count is None:
                    first_count = telemetry.signal.count
                last_count = telemetry.signal.count
                if point.db is not None:
                    valid.append(point.db)
                reasons[point.status] = reasons.get(point.status, 0) + 1
                output.write(json.dumps({'event': 'point', 'time': time.time(),
                                         'telemetry': asdict(telemetry), 'point': asdict(point)}) + '\n')
                output.flush()
                print('SNR_LIVE samples=%d db=%s status=%s' % (point.samples, point.db, point.status), flush=True)
                stop.wait(0.25)
            summary = {'event': 'summary', 'valid_points': len(valid),
                       'min_db': min(valid) if valid else None,
                       'max_db': max(valid) if valid else None,
                       'mean_db': sum(valid)/len(valid) if valid else None,
                       'sample_delta': last_count-first_count, 'statuses': reasons,
                       'gui_curve_observations': curve_observations,
                       'gui_final_label': gui.quality_snr_var.get() if gui else None}
            output.write(json.dumps(summary) + '\n')
            print('SNR_OBSERVATION_COMPLETE ' + json.dumps(summary), flush=True)
    finally:
        client.close()
        if root is not None:
            root.destroy()


if __name__ == '__main__':
    main()
