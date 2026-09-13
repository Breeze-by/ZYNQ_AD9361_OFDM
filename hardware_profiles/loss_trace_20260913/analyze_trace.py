"""Validate an exported ILA window before interpreting its event or I/Q history."""
import argparse
import collections
import csv
import json
import re
from pathlib import Path


def analyze(path, observer=False, mode="goodheader"):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        raw = list(csv.DictReader(stream))
    depth = 4096 if observer else 1024
    if len(raw) != depth:
        raise ValueError(f"Expected {depth} rows, got {len(raw)}")
    names = list(raw[0])

    def columns(base, width):
        aliases = [base]
        if observer:
            aliases.append("stage21_ila_" + base.rsplit("/", 1)[-1])
        parts, covered = [], 0
        for name in names:
            for alias in aliases:
                match = re.fullmatch(re.escape(alias) + r"(?:\[(\d+):(\d+)\])?", name)
                if not match:
                    continue
                high, low = (map(int, match.groups()) if match.group(1) else (width-1, 0))
                if low > high or high >= width:
                    raise ValueError(f"Invalid bit range {name}")
                mask = ((1 << (high-low+1))-1) << low
                if covered & mask:
                    raise ValueError(f"Overlapping probe bits {base}")
                covered |= mask
                parts.append((name, low, high-low+1))
        if covered != (1 << width)-1:
            raise ValueError(f"Missing probe bits {base}: mask={covered:x}")
        return parts

    bases = {
        "valid": "System_i/openofdm_rx_0_pkt_header_valid",
        "header": "System_i/openofdm_rx_0_pkt_header_valid_strobe",
        "length": "System_i/openofdm_rx_0_pkt_len",
        "rate": "System_i/openofdm_rx_0_pkt_rate",
        "short": "System_i/openofdm_rx_0_short_preamble_detected",
        "long": "System_i/openofdm_rx_0_long_preamble_detected",
        "sample": "System_i/rx_intf_0_sample_strobe",
        "iq": "System_i/rx_intf_0_sample0",
    }
    if observer:
        dot = "System_i/openofdm_rx_0/inst/dot11_i/"
        wd = "System_i/openofdm_rx_0/inst/signal_watchdog_inst/"
        bases.update(state=dot + "state", count=dot + "sample_count",
                     dc=wd + "receiver_rst_reg", cfo=wd + "sync_short_phase_offset_monitor_rst",
                     sign_i=wd + "signal_watchdog_running_sum_inst/running_sum_result0",
                     sign_q=wd + "signal_watchdog_running_sum_inst/running_sum_result1")
    widths = dict(length=16, rate=8, iq=32, state=5, count=9, sign_i=8, sign_q=8)
    cols = {k: columns(v, widths.get(k, 1)) for k, v in bases.items()}
    def value(row, parts):
        answer = 0
        for name, low, width in parts:
            bits = int(row[name], 16)
            if bits >= 1 << width:
                raise ValueError(f"Out-of-range probe {name}")
            answer |= bits << low
        return answer
    data = [{k: value(row, parts) for k, parts in cols.items()} for row in raw]
    triggers = [i for i, r in enumerate(raw) if int(r["TRIGGER"]) == 1]
    if len(triggers) != 1:
        raise ValueError(f"Expected exactly one trigger, got {triggers}")
    for i, row in enumerate(raw):
        if int(row["Sample in Buffer"]) != i:
            raise ValueError("Discontinuous buffer rows")
    t = triggers[0]
    event = data[t]
    checks = {
        "goodheader": event["header"] == 1 and event["valid"] == 1,
        "badheader": event["header"] == 1 and event["valid"] == 0,
    }
    if observer:
        checks.update(ltftimeout=event["state"] == 2 and event["count"] == 321,
                      dc_ltf=event["state"] == 2 and event["dc"] == 1,
                      dc_signal=event["state"] == 3 and event["dc"] == 1)
    if mode not in checks or not checks[mode]:
        raise ValueError(f"Selected trigger does not match {mode}: {event}")
    # Rising strobes: original 200 MHz ILA can sample one 100 MHz pulse twice.
    samples = [i for i, row in enumerate(data) if row["sample"] and (i == 0 or not data[i-1]["sample"])]
    spacing = collections.Counter(b-a for a, b in zip(samples, samples[1:]))
    transitions = []
    if observer:
        transitions = [[i, row["state"], row["count"], row["dc"]]
                       for i, row in enumerate(data)
                       if i == 0 or row["state"] != data[i-1]["state"]]
    events = {key: [i for i, row in enumerate(data) if row[key] and (i == 0 or not data[i-1][key])]
              for key in ("short", "long", "header")}
    return dict(path=str(path), rows=depth, trigger=t, mode=mode, trigger_values=event,
                sample_count=len(samples), sample_spacing_cycles=dict(spacing),
                state_transitions=transitions, event_rows=events,
                caveat="Window event only; not automatically matched to a missing source sequence. Original ILA has timing violations." if not observer else
                       "Window event only; not automatically matched to a missing source sequence. Check build timing separately.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--observer", action="store_true")
    parser.add_argument("--mode", default="goodheader")
    args = parser.parse_args()
    print(json.dumps(analyze(args.path, args.observer, args.mode), indent=2))
