"""Bounded real-RF AIR0 trials. Original GUI/firmware unchanged.

All received UDP datagrams are retained before independent validation. No RF
retry, source repair, artificial errors, or merging between trials. Receiver
temporarily registers port 15003; restore the GUI's 15002 target afterwards.
"""
import argparse
import hashlib
import importlib.util
import json
import random
import socket
import struct
import sys
import time
from dataclasses import asdict
from pathlib import Path


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as fp:
        json.dump(value, fp, ensure_ascii=False, indent=2)


def analyze(datagrams, source, expected_session=None):
    from air_protocol import parse_air_header, crc32, AIR_FLAG_DATA, AIR_FLAG_LAST
    from receiver_core import parse_udp_packet
    cap, chunk = 960, 1024
    total = (len(source) + cap - 1) // cap
    packets, pending, sessions = {}, {}, set()
    rejected, duplicates, conflicts = 0, 0, 0
    for raw in datagrams:
        kind, packet = parse_udp_packet(raw)
        if kind != "loopback":
            continue
        data = packet["payload"]
        offset, length = packet["chunk_offset"], packet["block_payload_len"]
        if (len(data) != packet["chunk_len"] or crc32(data) != packet["payload_crc32"] or
                not 64 <= length <= chunk or offset + len(data) > length):
            rejected += 1
            continue
        key = (packet["block_id"], packet["stream_offset"], length)
        if key not in pending:
            if len(pending) >= 128:
                pending.pop(next(iter(pending)))
            pending[key] = (bytearray(length), bytearray(length))
        buf, filled = pending[key]
        if any(filled[i] and buf[i] != b for i, b in enumerate(data, offset)):
            rejected += 1
            del pending[key]
            continue
        buf[offset:offset + len(data)] = data
        filled[offset:offset + len(data)] = b"\1" * len(data)
        if not all(filled):
            continue
        del pending[key]
        try:
            h = parse_air_header(buf)
            start = h.packet_seq * cap
            expected = source[start:start + h.payload_len]
            if (h.chunk_bytes != chunk or h.total_packets != total or h.file_size != len(source) or
                    h.file_offset != start or h.file_crc32 != crc32(source) or
                    h.payload_len != min(cap, len(source) - start) or
                    h.payload_crc32 != crc32(expected) or packet["stream_offset"] != h.packet_seq * chunk or
                    h.flags != AIR_FLAG_DATA | (AIR_FLAG_LAST if h.packet_seq == total - 1 else 0) or
                    len(buf) < 64 + h.payload_len):
                raise ValueError("Source/header identity mismatch")
            if expected_session is not None and h.session_id != expected_session:
                raise ValueError("Wrong sender session")
            sessions.add((h.session_id, h.file_id))
            actual = bytes(buf[64:64 + h.payload_len])
            if h.packet_seq in packets:
                duplicates += 1
                conflicts += packets[h.packet_seq] != actual
            else:
                packets[h.packet_seq] = actual  # First arrival; never repair from source.
        except (ValueError, struct.error):
            rejected += 1
    missing = sorted(set(range(total)) - packets.keys())
    errors = weak_errors = compared = weak_compared = bad_payloads = 0
    reconstructed = bytearray(len(source))
    for seq, actual in packets.items():
        offset = seq * cap
        expected = source[offset:offset + len(actual)]
        difference = int.from_bytes(actual, "little") ^ int.from_bytes(expected, "little")
        count = difference.bit_count()
        errors += count
        bad_payloads += count != 0
        compared += len(actual) * 8
        weak_errors += (int.from_bytes(actual[30:], "little") ^ int.from_bytes(expected[30:], "little")).bit_count()
        weak_compared += len(actual[30:]) * 8
        reconstructed[offset:offset + len(actual)] = actual
    report = dict(expected_packets=total, received_packets=len(packets), missing=missing,
                  missing_count=len(missing), rejected_datagrams_or_blocks=rejected,
                  duplicate_packets=duplicates, conflicting_duplicates=conflicts,
                  sessions=[list(s) for s in sorted(sessions)], bad_payloads=bad_payloads,
                  compared_bits=compared, bit_errors=errors,
                  payload_ber=errors / compared if compared else None,
                  weak_compared_bits=weak_compared, weak_bit_errors=weak_errors,
                  weak_ber=weak_errors / weak_compared if weak_compared else None,
                  protected_bit_errors=errors - weak_errors,
                  zero_packet_loss=not missing and len(sessions) == 1 and conflicts == 0,
                  exact_file=not missing and errors == 0 and len(sessions) == 1 and conflicts == 0,
                  source_sha256=hashlib.sha256(source).hexdigest(),
                  received_sha256=hashlib.sha256(reconstructed).hexdigest(),
                  missing_bytes_are_zero_filled=True)
    return report, bytes(reconstructed)


def read_capture(path):
    with Path(path).open("rb") as fp:
        while True:
            header = fp.read(12)
            if not header:
                return
            if len(header) != 12:
                raise ValueError("Truncated capture header")
            timestamp, length = struct.unpack("<dI", header)
            if not 0 < length <= 65535:
                raise ValueError("Invalid capture length")
            data = fp.read(length)
            if len(data) != length:
                raise ValueError("Truncated capture datagram")
            yield data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["sender", "receiver", "verify", "restore"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seconds", type=float, default=35)
    parser.add_argument("--file")
    parser.add_argument("--expected-session", type=int)
    args = parser.parse_args()
    repo, out = Path(args.repo), Path(args.out)
    sys.path.insert(0, str(repo / "AD9361_test2/tools/pc_sender"))
    from sender_core import (SenderConfig, UdpSender, build_receiver_config_packet,
                             ACK_STATUS_OK)
    from receiver_core import parse_udp_packet
    source = Path(args.file).read_bytes() if args.file else random.Random(9361320).randbytes(1048576)
    if args.role == "verify":
        report, reconstructed = analyze(read_capture(out / "udp.bin"), source, args.expected_session)
        saved = json.loads((out / "result.json").read_text(encoding="utf-8"))
        if any(report[k] != saved[k] for k in report):
            raise RuntimeError("Offline reanalysis differs")
        if (out / "received_payload.bin").read_bytes() != reconstructed:
            raise RuntimeError("Recovered bytes differ from raw capture")
        print(json.dumps(dict(verified=True, **report)), flush=True)
        return
    if args.role == "restore":
        # RXCFG uses the UDP source port, NOT the sequence field, as its target.
        from receiver_core import LoopbackReceiver, ReceiverConfig, ReceiverStats
        receiver = LoopbackReceiver(ReceiverConfig(bind_ip="192.168.1.100", bind_port=15002,
                                   board_ip="192.168.1.50", output_dir=str(out)))
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("192.168.1.100", 15002))
                receiver._register_with_board(sock, ReceiverStats(), lambda n, p: print(n, p, flush=True))
        finally:
            receiver._discard_unsaved()
        return
    if args.seconds < 10 or args.seconds > 120 or len(source) != 1048576:
        raise ValueError("This preliminary sweep is bounded to one 1 MiB source and 10..120 seconds")
    out.mkdir(parents=True, exist_ok=False)
    (out / "source.bin").write_bytes(source)
    legacy = repo / "hardware_profiles/payload_power_20260912/test_channel.py"
    spec = importlib.util.spec_from_file_location("legacy_capture", legacy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    serial, log, err = module.capture_serial("COM4" if args.role == "sender" else "COM3", out, args.seconds + 10)
    try:
        deadline = time.monotonic() + 6
        while "SERIAL_OPEN" not in (out / "serial.log").read_text(errors="replace"):
            if time.monotonic() > deadline:
                raise RuntimeError("Serial port not available")
            time.sleep(0.1)
        if args.role == "sender":
            sender = UdpSender(SenderConfig(ip="192.168.2.50", bind_ip="192.168.2.101",
                chunk_size=1024, window_size=1, timeout=2, retries=5,
                target_rate_kib_s=400, throughput_mode=True, validate_payload_crc=True,
                rf_retry=False, air_protocol=True, transfer_protocol="air0_file", progress_interval_s=1))
            import threading
            limit = threading.Timer(args.seconds, sender.stop)
            limit.start()
            try:
                stats = sender.send(source)
            finally:
                limit.cancel()
            result = dict(stats=asdict(stats), session_id=sender._session_id,
                          source_sha256=hashlib.sha256(source).hexdigest())
            write_json(out / "result.json", result)
            print(json.dumps(result), flush=True)
            if stats.bytes_acked != len(source):
                raise RuntimeError("Sender did not deliver all bytes to board")
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
                sock.bind(("192.168.1.100", 15003))
                sock.settimeout(0.5)
                for attempt in range(4):
                    sock.sendto(build_receiver_config_packet(15003), ("192.168.1.50", 5001))
                    try:
                        ack, _ = sock.recvfrom(65535)
                        kind, packet = parse_udp_packet(ack)
                        if kind == "ack" and packet["seq"] == 15003 and packet["status"] == ACK_STATUS_OK:
                            break
                    except socket.timeout:
                        pass
                else:
                    raise RuntimeError("RXCFG registration failed")
                write_json(out / "ready.json", dict(ready=True, port=15003))
                sock.settimeout(0.2)
                deadline = time.monotonic() + args.seconds
                last_data = 0
                with (out / "udp.bin").open("xb") as capture:
                    while time.monotonic() < deadline:
                        try:
                            raw, _ = sock.recvfrom(65535)
                        except socket.timeout:
                            if last_data and time.monotonic() - last_data >= 4:
                                break
                            continue
                        stamp = time.monotonic()
                        capture.write(struct.pack("<dI", stamp, len(raw)) + raw)
                        kind, _ = parse_udp_packet(raw)
                        if kind == "loopback":
                            last_data = stamp
            report, reconstructed = analyze(read_capture(out / "udp.bin"), source)
            (out / "received_payload.bin").write_bytes(reconstructed)
            write_json(out / "result.json", report)
            print(json.dumps(report), flush=True)
    finally:
        if serial.poll() is None:
            serial.terminate()
        serial.wait(timeout=5)
        log.close()
        err.close()


if __name__ == "__main__":
    main()
