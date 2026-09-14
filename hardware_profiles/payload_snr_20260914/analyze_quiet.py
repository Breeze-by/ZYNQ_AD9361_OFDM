"""Diagnostic short-window I/Q statistics, NOT a calibrated noise/SNR estimate.

The existing 200 MHz ILA has known timing violations. Require observed strobe
edges, two stable following rows and uniform sample spacing before using data.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path


def analyze(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1024 or sum(row['TRIGGER'] == '1' for row in rows) != 1:
        raise ValueError('Invalid capture rows/trigger')
    strobe = 'System_i/rx_intf_0_sample_strobe'
    sample = 'System_i/rx_intf_0_sample0[31:0]'
    if any(int(row['System_i/openofdm_rx_0_demod_is_ongoing'], 16) or
           int(row['System_i/openofdm_rx_0_pkt_header_valid_strobe'], 16) for row in rows):
        raise ValueError('Not a quiet capture')
    points = []
    def signed16(value):
        return value - 65536 if value & 32768 else value
    for k in range(1, len(rows)-2):
        if int(rows[k-1][strobe], 16) == 0 and int(rows[k][strobe], 16) == 1:
            one, two = rows[k+1], rows[k+2]
            if one[sample] != two[sample] or int(one[strobe], 16) != 1:
                raise ValueError('Unstable ILA sample after strobe edge')
            word = int(one[sample], 16)
            points.append((k, complex(signed16(word >> 16), signed16(word & 65535))))
    intervals = Counter(b[0]-a[0] for a, b in zip(points, points[1:]))
    if len(points) < 64 or set(intervals) != {10}:
        raise ValueError('Unexpected I/Q sample count/spacing')
    iq = [point[1] for point in points]
    mean = sum(iq) / len(iq)
    power = sum(abs(x)**2 for x in iq) / len(iq)
    variance = sum(abs(x-mean)**2 for x in iq) / len(iq)
    return dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                samples=len(iq), intervals=dict(intervals), mean_i=mean.real,
                mean_q=mean.imag, power=power, short_centered_power=variance,
                short_mean_power_fraction=abs(mean)**2/power,
                note='Only a ~5 us observation; do not substitute this for calibrated Pn')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('captures', nargs='+', type=Path)
    args = parser.parse_args()
    results = [analyze(path) for path in args.captures]
    if len({item['sha256'] for item in results}) != len(results):
        raise ValueError('Duplicate/stale capture')
    print(json.dumps(results, indent=2))
