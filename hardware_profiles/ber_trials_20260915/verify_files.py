"""Read-only verification of the delivered files, including whole-file bit errors."""
import argparse
import hashlib
import json
from pathlib import Path

from publish import SOURCES, TARGETS, eligible


def verify(directory, references):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected = {(s, t) for s in SOURCES.values() for t in TARGETS}
    seen = set()
    reports = []
    for entry in manifest["outputs"]:
        report = entry["receiver"]
        name = SOURCES[report["source_sha256"]]
        key = (name, entry["target_ber"])
        assert key in expected and key not in seen
        seen.add(key)
        assert not entry.get("invalid_reason") and eligible(report, entry["target_ber"])
        filename = entry["file"]
        assert Path(filename).name == filename
        source = (references / name).read_bytes()
        received = (directory / filename).read_bytes()
        assert len(source) == len(received)
        assert hashlib.sha256(source).hexdigest() == report["source_sha256"]
        assert hashlib.sha256(received).hexdigest() == report["received_sha256"]
        errors = sum((a ^ b).bit_count() for a, b in zip(source, received))
        assert errors == report["bit_errors"] and errors > 0
        assert len(source) * 8 == report["compared_bits"]
        assert errors / (len(source) * 8) == report["payload_ber"]
        assert report["expected_packets"] == report["received_packets"] == (len(source) + 959) // 960
        assert report["missing"] == [] and report["duplicate_packets"] == 0
        reports.append(dict(file=filename, bytes=len(received), errors=errors,
                            ber=report["payload_ber"], sha256=report["received_sha256"]))
    assert seen == expected
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--references", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(dict(verified_files=verify(args.directory, args.references)), indent=2))
