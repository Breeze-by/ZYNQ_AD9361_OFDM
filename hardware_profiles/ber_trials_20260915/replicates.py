"""Audit and publish three independent samples per source/BER, retaining old six.

No network or RF control. Existing output directories are never overwritten.
Repeated hashes are allowed: independent real trials can produce identical bytes.
Repeated acquisition identities are never counted as independent samples.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from audit import check
from publish import SOURCES, TARGETS, eligible
from verify_files import verify as verify_baseline


BOUNDARY_SCOPE = dict(
    kind="h265_1e6_three_bit_boundary_v1",
    source_sha256="beeccd8ec4deabc9c5a7fcbe252f518b8f765eb6e773a3c97f9d767143ebbf53",
    target_ber=1e-6, compared_bits=1443376, bit_errors=3, expected_packets=188)


def validate_acceptance(acceptance):
    if acceptance is not None:
        if (acceptance.get("approved") is not True
                or not acceptance.get("user_decision")
                or any(acceptance.get(k) != v for k, v in BOUNDARY_SCOPE.items())):
            raise ValueError("Unsupported or unapproved boundary acceptance")


def acceptance_reason(report, target, acceptance=None):
    if eligible(report, target):
        return "within_original_range"
    if acceptance is None:
        return None
    validate_acceptance(acceptance)
    if (target == BOUNDARY_SCOPE["target_ber"]
            and report.get("source_sha256") == BOUNDARY_SCOPE["source_sha256"]
            and report.get("compared_bits") == BOUNDARY_SCOPE["compared_bits"]
            and report.get("bit_errors") == 3
            and report.get("payload_ber") == 3 / 1443376
            and report.get("zero_packet_loss") is True
            and report.get("missing_count") == 0 and report.get("missing") == []
            and report.get("expected_packets") == report.get("received_packets") == 188
            and report.get("duplicate_packets") == 0):
        return "user_approved_boundary_3bit"
    return None


def identity(row):
    return (row["receiver"]["source_sha256"], row["sender"]["session_id"],
            row["sender"]["stats"]["started_at"], row["capture_sha256"])


def choose(baseline, rows, count=3, acceptance=None):
    validate_acceptance(acceptance)
    if count < 1:
        raise ValueError("Positive sample count required")
    chosen = {(source, target): [] for source in SOURCES.values() for target in TARGETS}
    seen = set()
    for row in baseline["outputs"]:
        key = (SOURCES[row["receiver"]["source_sha256"]], row["target_ber"])
        if key not in chosen or chosen[key] or not eligible(row["receiver"], key[1]):
            raise ValueError("Invalid original six-sample baseline")
        uid = identity(row)
        if uid in seen:
            raise ValueError("Duplicate baseline acquisition")
        seen.add(uid)
        chosen[key].append(dict(row, origin="original_six", acceptance_reason="within_original_range"))
    if any(len(v) != 1 for v in chosen.values()):
        raise ValueError("All six original groups required")
    for row in sorted(rows, key=lambda r: r["sender"]["stats"]["started_at"]):
        uid = identity(row)
        if uid in seen:
            raise ValueError("Duplicate acquisition cannot count as a repeat")
        seen.add(uid)
        if row.get("invalid_reason"):
            continue
        source = SOURCES[row["receiver"]["source_sha256"]]
        for target in TARGETS:
            reason = acceptance_reason(row["receiver"], target, acceptance)
            if len(chosen[source, target]) < count and reason:
                chosen[source, target].append(dict(row, origin="new_repeat", acceptance_reason=reason))
    return chosen


def brief(row):
    r = row["receiver"]
    return dict(tag=row["tag"], source=SOURCES[r["source_sha256"]],
                sent=r["expected_packets"], received=r["received_packets"],
                missing=r["missing_count"], errors=r["bit_errors"], ber=r["payload_ber"],
                invalid_reason=row.get("invalid_reason"), conditions=row.get("conditions"))


def validate_counts(counts, manifest):
    required = manifest["samples_per_group"]
    assert all(1 <= n <= required for n in counts.values())
    assert manifest["complete"] == all(n == required for n in counts.values())
    declared = {(g["source"], g["target"]): g["count"] for g in manifest["groups"]}
    assert declared == counts


def verify(directory, references):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    acceptance = manifest.get("boundary_acceptance")
    validate_acceptance(acceptance)
    counts = {(source, target): 0 for source in SOURCES.values() for target in TARGETS}
    seen, files, result = set(), set(), []
    for row in manifest["outputs"]:
        r = row["receiver"]
        source_name = SOURCES[r["source_sha256"]]
        key = (source_name, row["target_ber"])
        uid = identity(row)
        assert key in counts and uid not in seen and row["file"] not in files
        seen.add(uid)
        files.add(row["file"])
        assert Path(row["file"]).name == row["file"]
        reason = acceptance_reason(r, row["target_ber"], acceptance)
        assert not row.get("invalid_reason") and reason is not None
        assert row.get("acceptance_reason", "within_original_range") == reason
        source = (references / source_name).read_bytes()
        actual = (directory / row["file"]).read_bytes()
        assert hashlib.sha256(source).hexdigest() == r["source_sha256"]
        assert hashlib.sha256(actual).hexdigest() == r["received_sha256"]
        assert len(source) == len(actual) and len(actual)*8 == r["compared_bits"]
        errors = sum((a ^ b).bit_count() for a, b in zip(source, actual))
        assert errors == r["bit_errors"] and errors / (len(actual)*8) == r["payload_ber"]
        assert r["received_packets"] == r["expected_packets"] == (len(actual)+959)//960
        assert r["missing"] == [] and r["duplicate_packets"] == 0
        counts[key] += 1
        result.append(dict(file=row["file"], errors=errors, ber=r["payload_ber"], acceptance_reason=reason,
                           sha256=r["received_sha256"]))
    validate_counts(counts, manifest)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--references", type=Path, required=True)
    p.add_argument("--campaign", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--acceptance", type=Path,
                   help="Explicit recorded approval for the narrowly scoped H265 three-bit exception")
    p.add_argument("--partial", action="store_true",
                   help="Allow explicitly incomplete delivery; never relax BER or loss criteria")
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    if args.verify:
        print(json.dumps(dict(verified=verify(args.root, args.references)), indent=2))
        return
    if not args.baseline or not args.campaign:
        p.error("--baseline and --campaign required for collection")
    verify_baseline(args.baseline, args.references)
    baseline = json.loads((args.baseline / "manifest.json").read_text(encoding="utf-8"))
    campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
    acceptance = json.loads(args.acceptance.read_text(encoding="utf-8")) if args.acceptance else None
    validate_acceptance(acceptance)
    rows = check(args.root)
    for row in rows:
        row["conditions"] = campaign["trials"][row["tag"]]
        row["invalid_reason"] = row["conditions"].get("invalid_reason")
    chosen = choose(baseline, rows, acceptance=acceptance)
    summary = dict(groups=[dict(source=s, target=t, count=len(v),
                               tags=[r["tag"] for r in v], bers=[r["receiver"]["payload_ber"] for r in v])
                           for (s, t), v in chosen.items()], trials=[brief(r) for r in rows])
    complete = all(len(v) == 3 for v in chosen.values())
    summary["complete"] = complete
    if args.out:
        if not complete and not args.partial:
            raise RuntimeError("Three independent samples not yet available for all six groups")
        args.out.mkdir(parents=True, exist_ok=False)
        outputs = []
        for (source, target), group in chosen.items():
            name = Path(source)
            for index, row in enumerate(group, 1):
                filename = f"{name.stem}_BER_{target:.0e}_sample{index:02d}{name.suffix}"
                raw = (args.baseline / row["file"] if row["origin"] == "original_six"
                       else args.root / ("rx-"+row["tag"]) / "received_payload.bin")
                shutil.copyfile(raw, args.out / filename)
                outputs.append(dict(row, file=filename, target_ber=target, sample=index))
        manifest = dict(samples_per_group=3, definition=baseline["definition"],
                        boundary_acceptance=acceptance,
                        no_source_repair=True, no_cross_trial_merging=True,
                        baseline_manifest_sha256=hashlib.sha256((args.baseline/"manifest.json").read_bytes()).hexdigest(),
                        campaign=campaign, **summary, outputs=outputs)
        with (args.out/"manifest.json").open("x", encoding="utf-8") as fp:
            json.dump(manifest, fp, indent=2)
        verify(args.out, args.references)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
