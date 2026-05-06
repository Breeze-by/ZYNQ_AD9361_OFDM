#!/usr/bin/env python3
import argparse
import binascii
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Optional


DATA_MAGIC = 0x4E455430
ACK_MAGIC = 0x41434B30

ACK_STATUS_OK = 0
ACK_STATUS_BAD_MAGIC = 1
ACK_STATUS_BAD_LENGTH = 2
ACK_STATUS_BAD_CHECKSUM = 3
ACK_STATUS_BUSY = 4
ACK_STATUS_DMA_ERROR = 5

ACK_STATUS_NAMES = {
    ACK_STATUS_OK: "OK",
    ACK_STATUS_BAD_MAGIC: "BAD_MAGIC",
    ACK_STATUS_BAD_LENGTH: "BAD_LENGTH",
    ACK_STATUS_BAD_CHECKSUM: "BAD_CHECKSUM",
    ACK_STATUS_BUSY: "BUSY",
    ACK_STATUS_DMA_ERROR: "DMA_ERROR",
}

DATA_HEADER_FORMAT = "<IIHHI"
ACK_FORMAT = "<IIHHI"
DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FORMAT)
ACK_SIZE = struct.calcsize(ACK_FORMAT)


@dataclass
class SenderConfig:
    ip: str
    port: int = 5001
    chunk_size: int = 1024
    timeout: float = 1.0
    retries: int = 10
    target_rate_kib_s: float = 0.0


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


def parse_args():
    parser = argparse.ArgumentParser(description="UDP stop-and-wait sender for AD9361_test2")
    parser.add_argument("--ip", required=True, help="Zynq target IP address")
    parser.add_argument("--port", type=int, default=5001, help="Zynq UDP port")
    parser.add_argument("--chunk-size", type=int, default=1024, help="payload bytes per UDP chunk")
    parser.add_argument("--timeout", type=float, default=1.0, help="ACK timeout in seconds")
    parser.add_argument("--retries", type=int, default=10, help="max retries per chunk")
    parser.add_argument("--target-rate-kib-s", type=float, default=0.0,
        help="optional offered load cap in KiB/s, 0 means unlimited")
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


def recv_ack(sock: socket.socket, expected_seq: int):
    data, _ = sock.recvfrom(2048)
    if len(data) < ACK_SIZE:
        raise RuntimeError("received short ACK")

    magic, seq, status, _reserved, transfer_len = struct.unpack(ACK_FORMAT, data[:ACK_SIZE])
    if magic != ACK_MAGIC:
        raise RuntimeError(f"received invalid ACK magic 0x{magic:08X}")
    if seq != expected_seq:
        raise RuntimeError(f"received unexpected ACK seq {seq}, expected {expected_seq}")

    return status, transfer_len


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

        if self.config.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        stats.started_at = time.time()
        self._emit(callback, "start", {"total_size": stats.total_size, "config": self.config})

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.config.timeout)

        try:
            for seq, chunk, start, end in iter_chunks(payload, self.config.chunk_size):
                packet = build_packet(seq, chunk)
                attempts = 0

                while True:
                    if self._stop_requested:
                        self._emit(callback, "stopped", {"seq": seq, "bytes_sent": stats.bytes_sent})
                        stats.finished_at = time.time()
                        return stats

                    self._apply_rate_limit(stats.bytes_sent + len(chunk), stats.started_at)
                    attempts += 1
                    if attempts > self.config.retries:
                        raise RuntimeError(f"seq {seq} exceeded retry limit")

                    tx_time = time.time()
                    sock.sendto(packet, destination)
                    self._emit(callback, "chunk_sent", {
                        "seq": seq,
                        "payload_len": len(chunk),
                        "attempt": attempts,
                        "offset": start,
                        "end": end,
                    })

                    try:
                        status, transfer_len = recv_ack(sock, seq)
                    except socket.timeout:
                        stats.timeout_count += 1
                        stats.retries_used += 1
                        self._emit(callback, "timeout", {
                            "seq": seq,
                            "payload_len": len(chunk),
                            "attempt": attempts,
                        })
                        continue

                    ack_time = time.time()
                    rtt_ms = (ack_time - tx_time) * 1000.0
                    stats.last_seq = seq
                    stats.last_ack_status = status
                    stats.last_transfer_len = transfer_len
                    stats.last_rtt_ms = rtt_ms

                    if status == ACK_STATUS_OK:
                        stats.bytes_sent = end
                        stats.chunks_acked += 1
                        stats.ack_ok += 1
                        elapsed = max(ack_time - stats.started_at, 1e-6)
                        stats.average_rate_kib_s = (stats.bytes_sent / 1024.0) / elapsed
                        stats.current_rate_kib_s = (len(chunk) / 1024.0) / max((ack_time - tx_time), 1e-6)
                        stats.estimated_ps_rate_kib_s = (transfer_len / 1024.0) / max((ack_time - tx_time), 1e-6)
                        self._emit(callback, "ack_ok", {
                            "seq": seq,
                            "payload_len": len(chunk),
                            "transfer_len": transfer_len,
                            "offset": start,
                            "end": end,
                            "stats": stats,
                        })
                        break

                    stats.retries_used += 1
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
                        "seq": seq,
                        "payload_len": len(chunk),
                        "transfer_len": transfer_len,
                        "status": status,
                        "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                        "attempt": attempts,
                        "rtt_ms": rtt_ms,
                        "stats": stats,
                    })
                    time.sleep(0.05)

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
    ))

    def callback(event_name: str, payload_dict: dict):
        if event_name == "timeout":
            print(
                f"seq={payload_dict['seq']} payload_len={payload_dict['payload_len']} "
                f"timeout retry={payload_dict['attempt']}"
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
        elif event_name == "done":
            stats = payload_dict["stats"]
            elapsed = max(stats.finished_at - stats.started_at, 1e-6)
            print(
                f"done bytes={stats.bytes_sent} elapsed={elapsed:.3f}s "
                f"avg_rate={stats.average_rate_kib_s:.2f} KiB/s "
                f"ack_ok={stats.ack_ok} timeouts={stats.timeout_count}"
            )

    sender.send(payload, callback=callback)
    return 0

