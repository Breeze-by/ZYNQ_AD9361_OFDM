"""Offline audit/publication for 30 NEW independent AIR0 RF samples.

Does not transmit, change firmware, reuse previous campaigns, or repair bits.
Keep raw paired rx-TAG/tx-TAG directories outside the SDK Git repository.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from audit import check

SOURCES = {
    "9a1f399db98698ccf15e232288c9644af28b676eb7f842bd827cd255bc9e1675": ("indices.bin", 517980),
    "beeccd8ec4deabc9c5a7fcbe252f518b8f765eb6e773a3c97f9d767143ebbf53": ("h265_payload.h265", 180422),
}
TARGETS = (1e-3, 1e-4, 1e-5)
SAMPLES = 5


def identity(row):
    return (row["sender"]["source_sha256"], row["sender"]["session_id"],
            row["sender"]["stats"]["started_at"])


def eligible(row, target):
    r, s = row["receiver"], row["sender"]
    source = SOURCES.get(r["source_sha256"])
    if source is None or target not in TARGETS:
        return False
    size = source[1]
    count = (size + 959) // 960
    return (row.get("verified") is True and not row.get("invalid_reason")
            and r["source_sha256"] == s["source_sha256"]
            and r["zero_packet_loss"] is True and r["missing_count"] == 0
            and r["missing"] == [] and r["duplicate_packets"] == 0
            and r["conflicting_duplicates"] == 0
            and r["received_packets"] == r["expected_packets"] == count
            and r["compared_bits"] == size * 8 and r["bit_errors"] > 0
            and r["payload_ber"] == r["bit_errors"] / (size * 8)
            and target * 0.5 <= r["payload_ber"] <= target * 2
            and s["stats"]["bytes_acked"] == size
            and s["stats"]["chunks_acked"] == count and s["stats"]["retries_used"] == 0
            and r["capture_started_at"] <= s["stats"]["started_at"]
            < s["stats"]["finished_at"] <= r["capture_finished_at"])


def choose(rows):
    groups = {(name, target): [] for name, _ in SOURCES.values() for target in TARGETS}
    seen, captures = set(), set()
    for row in sorted(rows, key=lambda r: r["sender"]["stats"]["started_at"]):
        uid = identity(row)
        if uid in seen or row["capture_sha256"] in captures:
            raise ValueError("Repeated acquisition/capture cannot count as independent")
        seen.add(uid)
        captures.add(row["capture_sha256"])
        name = SOURCES[row["receiver"]["source_sha256"]][0]
        for target in TARGETS:
            if len(groups[name, target]) < SAMPLES and eligible(row, target):
                groups[name, target].append(row)
    return groups


def verify(directory, references):
    m = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert m["samples_per_group"] == SAMPLES and m["accepted_target_multipliers"] == [0.5, 2]
    assert m["new_acquisitions_only"] is True and m.get("boundary_acceptance") is None
    counts = {(name, target): 0 for name, _ in SOURCES.values() for target in TARGETS}
    seen, captures, filenames, reports = set(), set(), set(), []
    for row in m["outputs"]:
        uid = identity(row)
        assert uid not in seen and row["capture_sha256"] not in captures
        assert row["file"] not in filenames and Path(row["file"]).name == row["file"]
        seen.add(uid)
        captures.add(row["capture_sha256"])
        filenames.add(row["file"])
        r = row["receiver"]
        name, size = SOURCES[r["source_sha256"]]
        assert eligible(row, row["target_ber"])
        source = (references / name).read_bytes()
        actual = (directory / row["file"]).read_bytes()
        assert len(source) == len(actual) == size
        assert hashlib.sha256(source).hexdigest() == r["source_sha256"]
        assert hashlib.sha256(actual).hexdigest() == r["received_sha256"]
        errors = sum((a ^ b).bit_count() for a, b in zip(source, actual))
        assert errors == r["bit_errors"]
        counts[name, row["target_ber"]] += 1
        reports.append(dict(file=row["file"], bit_errors=errors, ber=r["payload_ber"],
                            packets=r["received_packets"], sha256=r["received_sha256"]))
    assert all(0 <= n <= SAMPLES for n in counts.values())
    assert {(g["source"], g["target"]): g["count"] for g in m["groups"]} == counts
    assert m["complete"] == all(n == SAMPLES for n in counts.values())
    return reports


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--references", type=Path, required=True)
    p.add_argument("--campaign", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--partial", action="store_true")
    p.add_argument("--verify", action="store_true")
    a = p.parse_args()
    if a.verify:
        print(json.dumps(dict(verified=verify(a.root, a.references)), indent=2))
        return
    if not a.campaign:
        p.error("--campaign required")
    campaign = json.loads(a.campaign.read_text(encoding="utf-8"))
    assert campaign["samples_per_group"] == SAMPLES
    assert campaign["targets"] == list(TARGETS)
    assert campaign["accepted_target_multipliers"] == [0.5, 2]
    rows = check(a.root)
    assert {r["tag"] for r in rows} == set(campaign["trials"]), "Missing or unrecorded acquisition"
    for row in rows:
        row["conditions"] = campaign["trials"][row["tag"]]
        row["invalid_reason"] = row["conditions"].get("invalid_reason")
        assert row["tag"].startswith("b30-")
    groups = choose(rows)
    summary = dict(groups=[dict(source=s, target=t, count=len(v), tags=[r["tag"] for r in v],
                              bers=[r["receiver"]["payload_ber"] for r in v])
                          for (s, t), v in groups.items()],
                   complete=all(len(v) == SAMPLES for v in groups.values()),
                   audited_trials=len(rows))
    if a.out:
        if not summary["complete"] and not a.partial:
            raise RuntimeError("Need five NEW zero-loss samples for each source/BER")
        a.out.mkdir(parents=True, exist_ok=False)
        outputs = []
        for (source, target), selected in groups.items():
            name = Path(source)
            for index, row in enumerate(selected, 1):
                filename = f"{name.stem}_BER_{target:.0e}_sample{index:02d}{name.suffix}"
                shutil.copyfile(a.root / ("rx-" + row["tag"]) / "received_payload.bin", a.out / filename)
                outputs.append(dict(row, file=filename, target_ber=target, sample=index))
        manifest = dict(**summary, samples_per_group=SAMPLES, accepted_target_multipliers=[0.5, 2],
                        new_acquisitions_only=True, no_source_repair=True, no_cross_trial_merging=True,
                        campaign=campaign, trials=rows, outputs=outputs)
        with (a.out / "manifest.json").open("x", encoding="utf-8") as fp:
            json.dump(manifest, fp, indent=2)
        verify(a.out, a.references)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
