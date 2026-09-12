"""Locate simulated FFT windows against the independently checked TX fixture."""
import csv
import json
from pathlib import Path
import sys
from check_ofdm_fixture import signed16

words = [int(line, 16) for line in Path(sys.argv[1]).read_text().splitlines()]
wave = [complex(signed16(w >> 16), signed16(w & 65535)) for w in words]
with Path(sys.argv[2]).open(newline='') as f:
    trace = [complex(int(r['i']), int(r['q'])) for r in csv.DictReader(f)]
for n in range(len(trace)//64):
    obs = trace[n*64:(n+1)*64]
    energy = sum(abs(x)**2 for x in obs)
    fits = []
    for start in range(150, 500):
        ref = wave[start:start+64]
        scale = sum(a*b.conjugate() for a,b in zip(obs,ref))/sum(abs(b)**2 for b in ref)
        mse = sum(abs(a-scale*b)**2 for a,b in zip(obs,ref))/energy
        fits.append((mse,start,scale))
    mse,start,scale = min(fits,key=lambda x:x[0])
    print(json.dumps({'fft_block':n,'best_tx_start':start,'relative_mse':mse,
                      'scale_real':scale.real,'scale_imag':scale.imag}))
