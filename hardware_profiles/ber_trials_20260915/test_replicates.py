"""Selection tests only; synthetic values never transmitted over RF."""
import copy
import unittest
from replicates import choose, validate_counts, SOURCES, TARGETS


def row(digest, target, started, tag):
    return dict(tag=tag, target_ber=target, receiver=dict(source_sha256=digest,
                zero_packet_loss=True, missing_count=0, compared_bits=10000000,
                bit_errors=round(target*10000000), payload_ber=target),
                sender=dict(session_id=started, stats=dict(started_at=started)), capture_sha256=tag)


class RepeatTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(outputs=[row(s,t,i,f"base{i}") for i,(s,t) in enumerate(
            (s,t) for s in SOURCES for t in TARGETS)])

    def test_keeps_old_six(self):
        result = choose(self.base, [])
        self.assertTrue(all(len(v) == 1 and v[0]["origin"] == "original_six" for v in result.values()))

    def test_takes_first_two_new_not_best(self):
        s=next(iter(SOURCES)); t=1e-6
        result=choose(self.base,[row(s,t,13,"c"),row(s,t,11,"a"),row(s,t,12,"b")])
        self.assertEqual([r["tag"] for r in result[SOURCES[s],t]][1:], ["a","b"])

    def test_duplicate_acquisition_is_error(self):
        with self.assertRaises(ValueError):
            choose(self.base,[copy.deepcopy(self.base["outputs"][0])])

    def test_missing_zero_and_invalid_do_not_count(self):
        s=next(iter(SOURCES)); t=1e-6
        rows=[row(s,t,i,str(i)) for i in (11,12,13)]
        rows[0]["receiver"]["missing_count"]=1
        rows[1]["receiver"].update(bit_errors=0,payload_ber=0)
        rows[2]["invalid_reason"]="Expired capture"
        self.assertEqual(len(choose(self.base,rows)[SOURCES[s],t]),1)

    def test_missing_baseline_group_is_error(self):
        self.base["outputs"].pop()
        with self.assertRaises(ValueError):
            choose(self.base,[])

    def test_partial_counts_are_explicit(self):
        counts = {("h265", 1e-6): 1, ("vqpk", 1e-6): 3}
        manifest = dict(samples_per_group=3, complete=False, groups=[
            dict(source=s, target=t, count=n) for (s,t),n in counts.items()])
        validate_counts(counts, manifest)
        manifest["complete"] = True
        with self.assertRaises(AssertionError):
            validate_counts(counts, manifest)

    def test_incorrect_declared_counts_rejected(self):
        with self.assertRaises(AssertionError):
            validate_counts({("h265", 1e-6): 1}, dict(samples_per_group=3,
                complete=False, groups=[dict(source="h265", target=1e-6, count=3)]))

    def test_completed_counts_verified(self):
        validate_counts({("h265", 1e-6): 3}, dict(samples_per_group=3,
            complete=True, groups=[dict(source="h265", target=1e-6, count=3)]))


if __name__ == "__main__":
    unittest.main()
