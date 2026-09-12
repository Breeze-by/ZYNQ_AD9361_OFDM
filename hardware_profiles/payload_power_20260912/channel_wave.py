"""Simulation-only linear phase/gain channel; never used by the RF sender."""
import argparse
import cmath
from pathlib import Path
from check_ofdm_fixture import signed16

p=argparse.ArgumentParser()
p.add_argument('source',type=Path)
p.add_argument('destination',type=Path)
p.add_argument('--phase',type=float,required=True)
p.add_argument('--gain',type=float,default=1.0)
p.add_argument('--cfo',type=float,default=0.0)
a=p.parse_args()
if a.source.resolve()==a.destination.resolve():
    raise ValueError('Keep original TX waveform inputs unchanged')
for level in range(5):
    words=[int(x,16) for x in (a.source/f'wave{level}.mem').read_text().splitlines()]
    out=[]
    for n,w in enumerate(words):
        x=complex(signed16(w>>16),signed16(w&65535))
        y=x*a.gain*cmath.exp(1j*(a.phase*cmath.pi/180+2*cmath.pi*a.cfo*n/20e6))
        i,q=round(y.real),round(y.imag)
        if not(-32768<=i<=32767 and -32768<=q<=32767):
            raise ValueError('Simulation channel clipping')
        out.append(f'{i&65535:04x}{q&65535:04x}\n')
    (a.destination/f'wave{level}.mem').write_text(''.join(out),encoding='ascii')
print(f'STAGE17_SIM_CHANNEL phase_deg={a.phase} gain={a.gain} cfo_hz={a.cfo}')
