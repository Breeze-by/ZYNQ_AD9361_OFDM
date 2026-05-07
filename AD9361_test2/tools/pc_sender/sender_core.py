#!/usr/bin/env python3
import argparse
import binascii
import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional


DATA_MAGIC = 0x4E455430
ACK_MAGIC = 0x41434B30

ACK_STATUS_OK = 0
ACK_STATUS_BAD_MAGIC = 1
ACK_STATUS_BAD_LENGTH = 2
ACK_STATUS_BAD_CHECKSUM = 3
ACK_STATUS_BUSY = 4
ACK_STATUS_DMA_ERROR = 5
ACK_STATUS_PENDING = 6

ACK_STATUS_NAMES = {
    ACK_STATUS_OK: "OK",
    ACK_STATUS_BAD_MAGIC: "BAD_MAGIC",
    ACK_STATUS_BAD_LENGTH: "BAD_LENGTH",
    ACK_STATUS_BAD_CHECKSUM: "BAD_CHECKSUM",
    ACK_STATUS_BUSY: "BUSY",
    ACK_STATUS_DMA_ERROR: "DMA_ERROR",
    ACK_STATUS_PENDING: "PENDING",
}

DATA_HEADER_FORMAT = "<IIHHI"
ACK_FORMAT = "<IIHHI"
DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FORMAT)
ACK_SIZE = struct.calcsize(ACK_FORMAT)


@dataclass
class SenderConfig:
    ip: str
    port: int = 5001
    chunk_size: int = 1456
    timeout: float = 1.0
    retries: int = 10
    target_rate_kib_s: float = 0.0
    window_size: int = 16


@dataclass
class SenderStats:
    total_size: int = 0
    bytes_sent: int = 0
    chunks_acked: int = 0
    retries_used: int = 0
    ack_ok: int = 0
    ack_busy: int = 0
    ack_bad_magic: int = 0
    ack_bad_length: int = 0
    ack_bad_checksum: int = 0
    ack_dma_error: int = 0
    timeout_count: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    last_seq: int = -1
    last_ack_status: int = -1
    last_transfer_len: int = 0
    last_rtt_ms: float = 0.0
    current_rate_kib_s: float = 0.0
    average_rate_kib_s: float = 0.0
    estimated_ps_rate_kib_s: float = 0.0
    ack_pending: int = 0


def parse_args():
    parser = argparse.ArgumentParser(description="UDP sliding-window sender for AD9361_test2")
    parser.add_argument("--ip", required=True, help="Zynq target IP address")
    parser.add_argument("--port", type=int, default=5001, help="Zynq UDP port")
    parser.add_argument("--chunk-size", type=int, default=1456, help="payload bytes per UDP chunk")
    parser.add_argument("--timeout", type=float, default=1.0, help="ACK timeout in seconds")
    parser.add_argument("--retries", type=int, default=10, help="max retries per chunk")
    parser.add_argument("--target-rate-kib-s", type=float, default=0.0,
        help="optional offered load cap in KiB/s, 0 means unlimited")
    parser.add_argument("--window-size", type=int, default=16,
        help="number of in-flight chunks allowed before waiting for ACKs")
    parser.add_argument("--test-size", type=int, default=0, help="send generated test payload of this size")
    parser.add_argument("--file", help="send payload read from file")
    return parser.parse_args()


def load_payload(test_size: int = 0, file_path: Optional[str] = None) -> bytes:
    if test_size > 0 and file_path:
        raise ValueError("use either test_size or file_path")
    if test_size > 0:
        return bytes((index & 0xFF) for index in range(test_size))
    if file_path:
        with open(file_path, "rb") as fp:
            return fp.read()
    raise ValueError("one of test_size or file_path is required")


def build_packet(seq: int, payload: bytes) -> bytes:
    crc32 = binascii.crc32(payload) & 0xFFFFFFFF
    header = struct.pack(DATA_HEADER_FORMAT, DATA_MAGIC, seq, len(payload), 0, crc32)
    return header + payload


def recv_any_ack(sock: socket.socket):
    data, _ = sock.recvfrom(2048)
    if len(data) < ACK_SIZE:
        raise RuntimeError("received short ACK")

    magic, seq, status, _reserved, transfer_len = struct.unpack(ACK_FORMAT, data[:ACK_SIZE])
    if magic != ACK_MAGIC:
        raise RuntimeError(f"received invalid ACK magic 0x{magic:08X}")

    return seq, status, transfer_len


def iter_chunks(payload: bytes, chunk_size: int):
    offset = 0
    seq = 0

    while offset < len(payload):
        next_offset = min(offset + chunk_size, len(payload))
        yield seq, payload[offset:next_offset], offset, next_offset
        seq += 1
        offset = next_offset


class UdpSender:
    def __init__(self, config: SenderConfig):
        self.config = config
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _emit(self, callback: Optional[Callable[[str, dict], None]], event_name: str, payload: dict):
        if callback is not None:
            callback(event_name, payload)

    def _apply_rate_limit(self, expected_bytes: int, start_time: float):
        if self.config.target_rate_kib_s <= 0.0:
            return

        expected_elapsed = (expected_bytes / 1024.0) / self.config.target_rate_kib_s
        actual_elapsed = time.time() - start_time
        sleep_time = expected_elapsed - actual_elapsed
        if sleep_time > 0.0:
            time.sleep(sleep_time)

    def send(self, payload: bytes, callback: Optional[Callable[[str, dict], None]] = None) -> SenderStats:
        stats = SenderStats(total_size=len(payload))
        destination = (self.config.ip, self.config.port)
        chunks = list(iter_chunks(payload, self.config.chunk_size))
        total_chunks = len(chunks)
        acked = [False] * total_chunks
        outstanding: Dict[int, dict] = {}
        base_seq = 0
        next_seq = 0

        if self.config.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self.config.window_size <= 0:
            raise ValueError("window_size must be positive")

        stats.started_at = time.time()
        self._emit(callback, "start", {"total_size": stats.total_size, "config": self.config})

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        poll_timeout = min(max(self.config.timeout / 8.0, 0.01), 0.05)
        busy_retry_delay = max(min(self.config.timeout / 8.0, 0.02), 0.002)
        sock.settimeout(poll_timeout)

        try:
            while base_seq < total_chunks:
                while next_seq < total_chunks and len(outstanding) < self.config.window_size:
                    if self._stop_requested:
                        self._emit(callback, "stopped", {"seq": next_seq, "bytes_sent": stats.bytes_sent})
                        stats.finished_at = time.time()
                        return stats

                    seq, chunk, start, end = chunks[next_seq]
                    self._apply_rate_limit(stats.bytes_sent + len(chunk), stats.started_at)
                    tx_time = time.time()
                    packet = build_packet(seq, chunk)
                    sock.sendto(packet, destination)
                    outstanding[seq] = {
                        "packet": packet,
                        "chunk": chunk,
                        "start": start,
                        "end": end,
                        "attempts": 1,
                        "tx_time": tx_time,
                        "retry_deadline": tx_time + self.config.timeout,
                        "retry_reason": "timeout",
                    }
                    self._emit(callback, "chunk_sent", {
                        "seq": seq,
                        "payload_len": len(chunk),
                        "attempt": 1,
                        "offset": start,
                        "end": end,
                        "window_used": len(outstanding),
                    })
                    next_seq += 1

                try:
                    if not outstanding:
                        continue

                    ack_seq, status, transfer_len = recv_any_ack(sock)
                    ack_time = time.time()
                    if ack_seq not in outstanding:
                        self._emit(callback, "ack_ignored", {
                            "seq": ack_seq,
                            "status": status,
                            "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                            "transfer_len": transfer_len,
                        })
                        continue

                    entry = outstanding[ack_seq]
                    chunk = entry["chunk"]
                    rtt_ms = (ack_time - entry["tx_time"]) * 1000.0
                    stats.last_seq = ack_seq
                    stats.last_ack_status = status
                    stats.last_transfer_len = transfer_len
                    stats.last_rtt_ms = rtt_ms

                    if status == ACK_STATUS_OK:
                        outstanding.pop(ack_seq)
                        acked[ack_seq] = True
                        while base_seq < total_chunks and acked[base_seq]:
                            base_seq += 1

                        stats.bytes_sent = max(stats.bytes_sent, entry["end"])
                        stats.chunks_acked += 1
                        stats.ack_ok += 1
                        elapsed = max(ack_time - stats.started_at, 1e-6)
                        stats.average_rate_kib_s = (stats.bytes_sent / 1024.0) / elapsed
                        stats.current_rate_kib_s = (len(chunk) / 1024.0) / max((ack_time - entry["tx_time"]), 1e-6)
                        stats.estimated_ps_rate_kib_s = (transfer_len / 1024.0) / max((ack_time - entry["tx_time"]), 1e-6)
                        self._emit(callback, "ack_ok", {
                            "seq": ack_seq,
                            "payload_len": len(chunk),
                            "transfer_len": transfer_len,
                            "offset": entry["start"],
                            "end": entry["end"],
                            "window_used": len(outstanding),
                            "stats": stats,
                        })
                    elif status == ACK_STATUS_PENDING:
                        stats.ack_pending += 1
                        entry["retry_deadline"] = ack_time + self.config.timeout
                        entry["retry_reason"] = "timeout"
                        self._emit(callback, "ack_status", {
                            "seq": ack_seq,
                            "payload_len": len(chunk),
                            "transfer_len": transfer_len,
                            "status": status,
                            "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                            "attempt": entry["attempts"],
                            "rtt_ms": rtt_ms,
                            "window_used": len(outstanding),
                            "stats": stats,
                        })
                    else:
                        if status == ACK_STATUS_BAD_MAGIC:
                            stats.ack_bad_magic += 1
                        elif status == ACK_STATUS_BAD_LENGTH:
                            stats.ack_bad_length += 1
                        elif status == ACK_STATUS_BAD_CHECKSUM:
                            stats.ack_bad_checksum += 1
                        elif status == ACK_STATUS_BUSY:
                            stats.ack_busy += 1
                        elif status == ACK_STATUS_DMA_ERROR:
                            stats.ack_dma_error += 1

                        self._emit(callback, "ack_status", {
                            "seq": ack_seq,
                            "payload_len": len(chunk),
                            "transfer_len": transfer_len,
                            "status": status,
                            "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                            "attempt": entry["attempts"],
                            "rtt_ms": rtt_ms,
                            "window_used": len(outstanding),
                            "stats": stats,
                        })
                        if entry["attempts"] >= self.config.retries:
                            raise RuntimeError(f"seq {ack_seq} exceeded retry limit")
                        if status == ACK_STATUS_BUSY:
                            entry["retry_deadline"] = ack_time + busy_retry_delay
                            entry["retry_reason"] = "busy"
                        else:
                            entry["retry_deadline"] = ack_time
                            entry["retry_reason"] = "ack_status"
                except socket.timeout:
                    if not outstanding:
                        continue

                    now = time.time()
                    expired_items = [
                        (seq, entry)
                        for seq, entry in outstanding.items()
                        if now >= entry["retry_deadline"]
                    ]
                    if not expired_items:
                        continue

                    expired_items.sort(key=lambda item: (item[1]["retry_deadline"], item[0]))
                    oldest_seq, entry = expired_items[0]
                    entry["attempts"] += 1
                    if entry["attempts"] > self.config.retries:
                        raise RuntimeError(f"seq {oldest_seq} exceeded retry limit")
                    stats.retries_used += 1
                    entry["tx_time"] = now
                    entry["retry_deadline"] = now + self.config.timeout
                    reason = entry.get("retry_reason", "timeout")
                    entry["retry_reason"] = "timeout"
                    sock.sendto(entry["packet"], destination)
                    if reason == "timeout":
                        stats.timeout_count += 1
                    self._emit(callback, "timeout" if reason == "timeout" else "retry", {
                        "seq": oldest_seq,
                        "payload_len": len(entry["chunk"]),
                        "attempt": entry["attempts"],
                        "reason": reason,
                        "window_used": len(outstanding),
                    })

            stats.finished_at = time.time()
            self._emit(callback, "done", {"stats": stats})
            return stats
        finally:
            sock.close()


def run_cli(args) -> int:
    payload = load_payload(test_size=args.test_size, file_path=args.file)
    sender = UdpSender(SenderConfig(
        ip=args.ip,
        port=args.port,
        chunk_size=args.chunk_size,
        timeout=args.timeout,
        retries=args.retries,
        target_rate_kib_s=args.target_rate_kib_s,
        window_size=args.window_size,
    ))

    def callback(event_name: str, payload_dict: dict):
        if event_name == "timeout":
            print(
                f"seq={payload_dict['seq']} payload_len={payload_dict['payload_len']} "
                f"timeout retry={payload_dict['attempt']}"
            )
        elif event_name == "retry":
            print(
                f"seq={payload_dict['seq']} payload_len={payload_dict['payload_len']} "
                f"retry reason={payload_dict['reason']} attempt={payload_dict['attempt']}"
            )
        elif event_name == "ack_ok":
            stats = payload_dict["stats"]
            print(
                f"seq={payload_dict['seq']} payload_len={payload_dict['payload_len']} ack=OK "
                f"transfer_len={payload_dict['transfer_len']} progress={stats.bytes_sent}/{stats.total_size} "
                f"rtt_ms={stats.last_rtt_ms:.2f} avg_rate={stats.average_rate_kib_s:.2f} KiB/s "
                f"est_ps_rate={stats.estimated_ps_rate_kib_s:.2f} KiB/s"
            )
        elif event_name == "ack_status":
            print(
                f"seq={payload_dict['seq']} payload_len={payload_dict['payload_len']} "
                f"ack_status={payload_dict['status_name']} transfer_len={payload_dict['transfer_len']} "
                f"retry={payload_dict['attempt']} rtt_ms={payload_dict['rtt_ms']:.2f}"
            )
        elif event_name == "ack_ignored":
            print(
                f"ack_ignored seq={payload_dict['seq']} status={payload_dict['status_name']} "
                f"transfer_len={payload_dict['transfer_len']}"
            )
        elif event_name == "done":
            stats = payload_dict["stats"]
            elapsed = max(stats.finished_at - stats.started_at, 1e-6)
            print(
                f"done bytes={stats.bytes_sent} elapsed={elapsed:.3f}s "
                f"avg_rate={stats.average_rate_kib_s:.2f} KiB/s "
                f"ack_ok={stats.ack_ok} ack_pending={stats.ack_pending} timeouts={stats.timeout_count}"
            )

    sender.send(payload, callback=callback)
    return 0
