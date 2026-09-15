"""Publish six independently audited real-RF results. No source repair.

Inputs: paired rx-TAG/tx-TAG directories. Output must not exist. Original
files, zero-BER trials and missing-packet trials cannot substitute for a target.
"""
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

from audit import check

SOURCES = {
    "beeccd8ec4deabc9c5a7fcbe252f518b8f765eb6e773a3c97f9d767143ebbf53": "h265_payload.h265",
    "6bb8cfea7002f6cf832c3e6a657d4e4a5b16a57203877a1b1b2484cc83fbd6cc": "tx_payload.vqpk",
}
TARGETS = (1e-6, 1e-5, 1e-4)


def eligible(report, target):
    value = report["payload_ber"]
    return (report["zero_packet_loss"] and report["missing_count"] == 0
            and report["compared_bits"] > 0 and report["bit_errors"] > 0
            and value is not None and 0.5 * target <= value <= 2 * target)


def select(rows):
    chosen = {}
    for row in sorted(rows, key=lambda r: r["sender"]["stats"]["started_at"]):
        if row.get("invalid_reason"):
            continue
        report = row["receiver"]
        source = SOURCES[report["source_sha256"]]
        for target in TARGETS:
            if eligible(report, target):
                chosen.setdefault((source, target), row)
    return chosen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--campaign", type=Path, help="Recorded conditions and invalid acquisition attempts")
    args = p.parse_args()
    rows = check(args.root)
    campaign = json.loads(args.campaign.read_text(encoding="utf-8")) if args.campaign else {}
    if campaign:
        for row in rows:
            row["conditions"] = campaign["trials"][row["tag"]]
            row["invalid_reason"] = row["conditions"].get("invalid_reason")
    chosen = select(rows)
    brief = [dict(tag=r["tag"], source=SOURCES[r["receiver"]["source_sha256"]],
                  sent=r["sender"]["stats"]["chunks_acked"],
                  received=r["receiver"]["received_packets"], missing=r["receiver"]["missing_count"],
                  bit_errors=r["receiver"]["bit_errors"], ber=r["receiver"]["payload_ber"],
                  invalid_reason=r.get("invalid_reason"))
             for r in rows]
    missing = [dict(source=s, target=t) for s in SOURCES.values() for t in TARGETS if (s, t) not in chosen]
    summary = dict(trials=brief, missing_targets=missing, selected=[
        dict(source=s, target=t, tag=r["tag"], measured_ber=r["receiver"]["payload_ber"])
        for (s, t), r in chosen.items()])
    if args.out:
        if not campaign:
            raise RuntimeError("Publishing requires recorded campaign conditions")
        if missing:
            raise RuntimeError("Cannot publish all six results: some targets not met")
        args.out.mkdir(parents=True, exist_ok=False)
        outputs = []
        for (name, target), row in chosen.items():
            original = Path(name)
            dest = args.out / f"{original.stem}_BER_1e-{round(-math.log10(target))}{original.suffix}"
            raw = args.root / ("rx-" + row["tag"]) / "received_payload.bin"
            shutil.copyfile(raw, dest)
            assert hashlib.sha256(dest.read_bytes()).hexdigest() == row["receiver"]["received_sha256"]
            outputs.append(dict(file=dest.name, target_ber=target, allowed_range=[0.5*target, 2*target],
                                **row))
        with (args.out / "manifest.json").open("x", encoding="utf-8") as fp:
            json.dump(dict(definition="Post-decoder whole business payload BER; all packets present; original errors retained.",
                           no_source_repair=True, no_cross_trial_merging=True, campaign=campaign,
                           **summary, outputs=outputs), fp, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
