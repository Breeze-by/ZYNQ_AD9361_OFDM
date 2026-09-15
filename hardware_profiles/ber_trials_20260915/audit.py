"""Independent offline audit of this sweep's single-datagram AIR0 blocks.

No network or writes. Does not import trial.py or PC protocol parsers. Rejects
unsupported fragmentation rather than guessing. Usage: python audit.py ROOT
where ROOT contains paired rx-TAG and tx-TAG directories copied from the PCs.
"""
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path


def check(root):
    summaries = []
    for rx in sorted(Path(root).glob("rx-*/result.json")):
        tag = rx.parent.name[3:]
        tx = rx.parent.parent / ("tx-" + tag)
        sent = json.loads((tx / "result.json").read_text())
        saved = json.loads(rx.read_text())
        source = (tx / "source.bin").read_bytes()
        assert source == (rx.parent / "source.bin").read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        assert digest == saved["source_sha256"] == sent["source_sha256"]
        total = (len(source) + 959) // 960
        assert sent["stats"]["chunks_acked"] == total
        assert sent["stats"]["bytes_acked"] == len(source)
        assert sent["stats"]["retries_used"] == 0
        raw = (rx.parent / "udp.bin").read_bytes()
        cursor, packets, errors, weak, bits, weak_bits, bad = 0, {}, 0, 0, 0, 0, 0
        recovered = bytearray(len(source))
        while cursor < len(raw):
            stamp, length = struct.unpack_from("<dI", raw, cursor)
            cursor += 12
            datagram = raw[cursor:cursor + length]
            cursor += length
            assert len(datagram) == length
            if datagram[:4] != b"LBK0":
                continue
            outer = struct.unpack_from("<IIIHHHHIIIII", datagram)
            wire = datagram[40:]
            assert outer[4] == 0 and outer[3] == outer[5] == len(wire)
            assert zlib.crc32(wire) == outer[7]
            h = struct.unpack_from("<IBBHIIIIQHHQIIQI", wire)
            assert h[:3] == (0x30524941, 1, 64)
            assert zlib.crc32(wire[:60] + bytes(4)) == h[15]
            seq, count = h[6], h[9]
            assert 0 <= seq < total and h[7] == total
            assert h[4] == sent["session_id"]
            assert h[5] == ((zlib.crc32(source) ^ (len(source) << 1) ^ h[4]) & 0xffffffff)
            assert h[8] == seq * 960 and h[10] == 1024
            assert outer[2] == seq * 1024
            assert h[11] == len(source) and h[12] == zlib.crc32(source)
            assert h[3] == (5 if seq == total - 1 else 1)
            assert count == min(960, len(source) - seq * 960)
            expected = source[seq*960:seq*960 + count]
            actual = wire[64:64 + count]
            assert len(actual) == count and h[13] == zlib.crc32(expected)
            assert seq not in packets  # All trials in this sweep have no duplicates.
            packets[seq] = actual
            per_byte = [(a ^ b).bit_count() for a, b in zip(actual, expected)]
            errors += sum(per_byte)
            weak += sum(per_byte[30:])
            bits += count * 8
            weak_bits += max(0, count - 30) * 8
            bad += any(per_byte)
            recovered[seq*960:seq*960 + count] = actual
        missing = sorted(set(range(total)) - packets.keys())
        assert missing == saved["missing"]
        assert (len(packets), errors, weak, bits, weak_bits, bad) == (
            saved["received_packets"], saved["bit_errors"], saved["weak_bit_errors"],
            saved["compared_bits"], saved["weak_compared_bits"], saved["bad_payloads"])
        assert bytes(recovered) == (rx.parent / "received_payload.bin").read_bytes()
        assert hashlib.sha256(recovered).hexdigest() == saved["received_sha256"]
        assert saved["zero_packet_loss"] == (not missing)
        assert saved["exact_file"] == (not missing and errors == 0)
        summaries.append(dict(tag=tag, verified=True, receiver=saved, sender=sent,
                              capture_sha256=hashlib.sha256(raw).hexdigest()))
    return summaries


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1]), indent=2))
