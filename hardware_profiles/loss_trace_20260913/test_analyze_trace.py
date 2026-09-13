import io
import unittest
from unittest.mock import patch

from analyze_trace import analyze


class TraceValidation(unittest.TestCase):
    def fixture(self, observer=False, valid=1, count=0, state=0, depth=None, trigger=True):
        names = ["Sample in Buffer", "Sample in Window", "TRIGGER"]
        bases = ["openofdm_rx_0_pkt_header_valid", "openofdm_rx_0_pkt_header_valid_strobe",
                 "openofdm_rx_0_pkt_len[15:0]", "openofdm_rx_0_pkt_rate[7:0]",
                 "openofdm_rx_0_short_preamble_detected", "openofdm_rx_0_long_preamble_detected",
                 "rx_intf_0_sample_strobe", "rx_intf_0_sample0[31:0]"]
        names += ["System_i/" + b for b in bases]
        if observer:
            dot = "System_i/openofdm_rx_0/inst/dot11_i/"
            wd = "System_i/openofdm_rx_0/inst/signal_watchdog_inst/"
            names += [dot + "state[4:0]", dot + "sample_count[8:0]", wd + "receiver_rst_reg",
                      wd + "sync_short_phase_offset_monitor_rst",
                      wd + "signal_watchdog_running_sum_inst/running_sum_result0[7:0]",
                      wd + "signal_watchdog_running_sum_inst/running_sum_result1[7:0]"]
        rows = [",".join(names)]
        for i in range(depth if depth is not None else (4096 if observer else 1024)):
            event = i == 800
            values = [valid, int(event), 1028, 11, 0, 0, int(i % 5 == 0), 0]
            if observer:
                values += [state, count if event else 0, 0, 0, 0, 0]
            rows.append(",".join([str(i), str(i), str(int(event and trigger))] + [format(v, "x") for v in values]))
        return "\n".join(rows)

    def call(self, fixture, **kwargs):
        with patch("pathlib.Path.open", return_value=io.StringIO(fixture)):
            return analyze("fixture.csv", **kwargs)

    def test_normal_header(self):
        result = self.call(self.fixture())
        self.assertEqual(result["trigger_values"]["length"], 1028)

    def test_observer_bad_header(self):
        result = self.call(self.fixture(observer=True, valid=0), observer=True, mode="badheader")
        self.assertEqual(result["sample_spacing_cycles"], {5: 819})

    def test_ltf_timeout(self):
        self.call(self.fixture(observer=True, count=321, state=2), observer=True, mode="ltftimeout")

    def test_wrong_trigger(self):
        with self.assertRaises(ValueError):
            self.call(self.fixture(valid=0))

    def test_partial_buffer(self):
        with self.assertRaises(ValueError):
            self.call(self.fixture(depth=100))

    def test_no_trigger(self):
        with self.assertRaises(ValueError):
            self.call(self.fixture(trigger=False))

    def test_observer_renamed_probe(self):
        fixture = self.fixture(observer=True).replace("System_i/openofdm_rx_0/inst/dot11_i/state[4:0]", "stage21_ila_state[4:0]")
        self.call(fixture, observer=True)

    def test_split_bus(self):
        lines = [line.split(",") for line in self.fixture(observer=True).splitlines()]
        lines[0][6:7] = ["stage21_ila_openofdm_rx_0_pkt_rate[3:0]", "System_i/openofdm_rx_0_pkt_rate[6:4]", "stage21_ila_openofdm_rx_0_pkt_rate[7:7]"]
        for row in lines[1:]:
            row[6:7] = ["b", "0", "0"]
        result = self.call("\n".join(",".join(row) for row in lines), observer=True)
        self.assertEqual(result["trigger_values"]["rate"], 11)


if __name__ == "__main__":
    unittest.main()
