"""Offline selection tests; synthetic metadata are never RF test results."""
import copy
import unittest
from collect30 import SOURCES, TARGETS, SAMPLES, eligible, choose


def trial(digest, target, number):
    _, size = SOURCES[digest]
    count = (size + 959) // 960
    errors = round(size * 8 * target)
    return dict(tag=f"b30-test-{number}", verified=True, capture_sha256=f"capture-{number}",
                sender=dict(source_sha256=digest, session_id=number,
                            stats=dict(started_at=number*10+1, finished_at=number*10+2,
                                       bytes_acked=size, chunks_acked=count, retries_used=0)),
                receiver=dict(source_sha256=digest, zero_packet_loss=True, missing_count=0,
                              missing=[], duplicate_packets=0, conflicting_duplicates=0,
                              received_packets=count, expected_packets=count,
                              compared_bits=size*8, bit_errors=errors, payload_ber=errors/(size*8),
                              capture_started_at=number*10, capture_finished_at=number*10+3))


class Collect30Tests(unittest.TestCase):
    def setUp(self):
        self.digest = next(iter(SOURCES))
        self.row = trial(self.digest, 1e-4, 1)

    def test_six_groups_of_five(self):
        rows = [trial(d, t, i*5+j) for i, (d, t) in enumerate(
                (d, t) for d in SOURCES for t in TARGETS) for j in range(5)]
        chosen = choose(rows)
        self.assertEqual(len(chosen), 6)
        self.assertTrue(all(len(v) == SAMPLES == 5 for v in chosen.values()))

    def test_first_five_chronological(self):
        rows = [trial(self.digest, 1e-4, i) for i in (7, 6, 5, 4, 3, 2, 1)]
        self.assertEqual([r["sender"]["session_id"] for r in choose(rows)["indices.bin", 1e-4]],
                         [1, 2, 3, 4, 5])

    def test_duplicate_trial_rejected_even_if_capture_hash_changed(self):
        duplicate = dict(copy.deepcopy(self.row), capture_sha256="different")
        with self.assertRaises(ValueError):
            choose([self.row, duplicate])

    def test_reused_capture_rejected(self):
        duplicate = trial(self.digest, 1e-4, 2)
        duplicate["capture_sha256"] = self.row["capture_sha256"]
        with self.assertRaises(ValueError):
            choose([self.row, duplicate])

    def test_loss_duplicates_and_partial_denominator_rejected(self):
        for changed in (dict(missing=[1], missing_count=1), dict(zero_packet_loss=False),
                        dict(duplicate_packets=1), dict(conflicting_duplicates=1),
                        dict(received_packets=539), dict(compared_bits=1)):
            with self.subTest(changed=changed):
                r = copy.deepcopy(self.row)
                r["receiver"].update(changed)
                self.assertFalse(eligible(r, 1e-4))

    def test_ber_zero_outside_and_rounded_rejected(self):
        for errors in (0, 1, 10000):
            r = copy.deepcopy(self.row)
            r["receiver"].update(bit_errors=errors, payload_ber=errors/(SOURCES[self.digest][1]*8))
            self.assertFalse(eligible(r, 1e-4))
        r["receiver"]["payload_ber"] = 1e-4
        self.assertFalse(eligible(r, 1e-4))

    def test_expired_capture_or_host_retry_rejected(self):
        r = copy.deepcopy(self.row)
        r["receiver"]["capture_finished_at"] = 10.5
        self.assertFalse(eligible(r, 1e-4))
        r = copy.deepcopy(self.row)
        r["sender"]["stats"]["retries_used"] = 1
        self.assertFalse(eligible(r, 1e-4))

    def test_old_band_and_old_approval_not_accepted(self):
        self.assertFalse(eligible(self.row, 1e-6))
        r = copy.deepcopy(self.row)
        r["invalid_reason"] = "not an independent valid trial"
        self.assertFalse(eligible(r, 1e-4))

    def test_empty_campaign_is_explicitly_empty(self):
        self.assertEqual(sum(map(len, choose([]).values())), 0)


if __name__ == "__main__":
    unittest.main()
