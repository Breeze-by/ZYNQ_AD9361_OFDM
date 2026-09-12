"""Independently recheck captured RF-return blocks, including a short final AIR0 packet."""
import argparse
import binascii
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys

sdk = Path(__file__).resolve().parents[2]
if not (sdk / 'AD9361_test2/tools/pc_sender').is_dir():
    sdk = Path(r'E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk')
sys.path.insert(0, str(sdk / 'AD9361_test2/tools/pc_sender'))
from air_protocol import parse_air_header


def analyze(path, size, chunk=1024):
    source = random.Random(9361320).randbytes(size)
    source_crc = binascii.crc32(source) & 0xffffffff
    total = math.ceil(size / (chunk - 64))
    seen = set()
    invalid = []
    errors = [0, 0]
    checked = [0, 0]
    bad = []
    raw = path.read_bytes()
    cursor = 0
    while cursor < len(raw):
        offset, length = struct.unpack_from('<QI', raw, cursor)
        cursor += 12
        packet = raw[cursor:cursor + length]
        cursor += length
        if len(packet) != length:
            raise ValueError('Truncated capture')
        try:
            h = parse_air_header(packet)
            if (not 0 <= h.packet_seq < total or h.total_packets != total or
                h.file_size != size or h.file_crc32 != source_crc or h.chunk_bytes != chunk or
                h.file_offset != h.packet_seq * (chunk - 64) or offset != h.packet_seq * chunk or
                h.payload_len != min(chunk - 64, size - h.file_offset) or
                length != 64 + h.payload_len or h.packet_seq in seen):
                raise ValueError('Source metadata, length, or duplicate mismatch')
            payload = packet[64:]
            expected = source[h.file_offset:h.file_offset + h.payload_len]
            differences = [(a ^ b).bit_count() for a, b in zip(payload, expected)]
            errors[0] += sum(differences[:30])
            errors[1] += sum(differences[30:])
            checked[0] += min(30, len(payload))
            checked[1] += max(0, len(payload) - 30)
            seen.add(h.packet_seq)
            if any(differences):
                bad.append({'seq': h.packet_seq, 'bit_errors': sum(differences),
                            'first_bad_byte': next(i for i, v in enumerate(differences) if v)})
        except ValueError as exc:
            invalid.append({'offset': offset, 'error': str(exc)})
    missing = sorted(set(range(total)) - seen)
    return {'expected_packets': total, 'received_packets': len(seen), 'missing_count': len(missing),
            'missing': missing, 'invalid': invalid, 'bad_payloads': len(bad), 'bad_details': bad,
            'checked_bytes': sum(checked), 'bit_errors': sum(errors),
            'received_payload_ber': sum(errors)/(8*sum(checked)) if sum(checked) else None,
            'protected_payload_bytes': checked[0], 'protected_payload_bit_errors': errors[0],
            'weak_payload_bytes': checked[1], 'weak_payload_bit_errors': errors[1],
            'weak_payload_ber': errors[1]/(8*checked[1]) if checked[1] else None,
            'source_sha256': hashlib.sha256(source).hexdigest(),
            'capture_sha256': hashlib.sha256(raw).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('capture', type=Path)
    parser.add_argument('--bytes', type=int, required=True)
    args = parser.parse_args()
    result = analyze(args.capture, args.bytes)
    args.capture.with_suffix('.summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    result = {k: v for k, v in result.items() if k not in ('bad_details', 'missing')}
    print(json.dumps(result))
