"""Independent DFT/SIGNAL check of a TX simulation fixture (not an RF test)."""
import cmath
import json
from pathlib import Path
import sys

def signed16(x):
    return (x & 0x7fff) - (x & 0x8000)

def dft(values):
    return [sum(v * cmath.exp(-2j * cmath.pi * k * n / 64)
                for n, v in enumerate(values)) for k in range(64)]

def encode(bits):
    state = 0
    out = []
    for bit in bits:
        # dot11_tx sends bits_out[1] before bits_out[0].
        out += [bit ^ ((state & 0b110110).bit_count() & 1),
                bit ^ ((state & 0b100111).bit_count() & 1)]
        state = ((state << 1) | bit) & 63
    return out

def main(path):
    words = [int(line, 16) for line in Path(path).read_text().splitlines()]
    samples = [complex(signed16(w >> 16), signed16(w & 65535)) for w in words]
    ltf1, ltf2 = samples[192:256], samples[256:320]
    cp_error = sum(a != b for a, b in zip(samples[320:336], samples[384:400]))
    ltf_error = sum(a != b for a, b in zip(ltf1, ltf2))
    spec = dft(samples[336:400])
    bins = [k for k in range(-26, 27) if k not in (0, -21, -7, 7, 21)]
    signal = (132 << 5) | 11
    signal |= ((signal & 0x1ffff).bit_count() & 1) << 17
    coded = encode([(signal >> n) & 1 for n in range(24)])
    interleaved = [None] * 48
    for k, bit in enumerate(coded):
        interleaved[3 * (k % 16) + k // 16] = bit
    got = [int(spec[k % 64].real >= 0) for k in bins]
    print(json.dumps({'samples': len(samples), 'ltf_repeat_mismatch': ltf_error,
                      'signal_cp_mismatch': cp_error,
                      'signal_encoded_bit_errors': sum(a != b for a, b in zip(got, interleaved)),
                      'signal_quadrature_to_inphase_energy': sum(spec[k % 64].imag**2 for k in bins) /
                          sum(spec[k % 64].real**2 for k in bins),
                      'expected_signal_hex': f'{signal:06x}'}))

if __name__ == '__main__':
    main(sys.argv[1])
