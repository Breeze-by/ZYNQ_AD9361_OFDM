"""Short-window digital headroom only, not calibrated RF power or SNR."""
import csv
import cmath
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import sys


def signed16(x):
    return x - 65536 if x & 32768 else x


def analyze(path):
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1024, len(rows)
    assert sum(int(r['TRIGGER']) for r in rows) == 1
    key = 'System_i/rx_intf_0_sample0[31:0]'
    stb = 'System_i/rx_intf_0_sample_strobe'
    edges = [n for n in range(1, len(rows)-2)
             if int(rows[n][stb], 16) and not int(rows[n-1][stb], 16)]
    # Data changes at the sampled strobe edge. Verify the next two rows agree.
    assert all(rows[n+1][key] == rows[n+2][key] for n in edges)
    words = [int(rows[n+1][key], 16) for n in edges]
    samples = [(signed16(x >> 16), signed16(x & 65535)) for x in words]
    peak = max(abs(v) for iq in samples for v in iq)
    result = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  rows=len(rows), samples=len(samples), peak_component=peak,
                  peak_headroom_to_signed16_db=20*math.log10(32767/peak),
                  at_or_above_95pct=sum(abs(v)>=0.95*32767 for iq in samples for v in iq),
                  strobe_intervals=dict(Counter(b-a for a,b in zip(edges,edges[1:]))),
                  full_scale_reference='signed16 digital only; does not exclude analog compression')
    trigger = next(n for n,r in enumerate(rows) if int(r['TRIGGER']))
    pre = [complex(*iq) for n,iq in zip(edges,samples) if n<trigger][-48:]
    if '_data_' in path.name:
        result['data_mean_iq_power']=sum(i*i+q*q for i,q in samples)/len(samples)
        result['data_metric_note']='short random-DATA window; digital power proxy, not calibrated RF/SNR'
    if '_short_' in path.name and len(pre)==48:
        a,b=pre[:32],pre[16:]
        cross=sum(y*x.conjugate() for x,y in zip(a,b))
        pa=sum(abs(x)**2 for x in a);pb=sum(abs(y)**2 for y in b)
        correlation=abs(cross)/math.sqrt(pa*pb) if pa*pb else 0
        result['pretrigger_lag16_correlation']=correlation
        # Only report a short-preamble power proxy for clearly periodic samples.
        if correlation>0.9:
            result['stf_mean_iq_power']=sum(abs(x)**2 for x in pre)/48
            result['stf_cfo_hz_short_window']=cmath.phase(cross)*20e6/(2*math.pi*16)
            result['stf_metric_note']='48-sample window; digital power proxy, not calibrated RF/SNR'
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    for name in sys.argv[1:]:
        analyze(Path(name))
