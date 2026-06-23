#!/usr/bin/env python3
import argparse
import binascii
import os
import random
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from sender_core import (
    ACK_FORMAT,
    ACK_MAGIC,
    ACK_SIZE,
    ACK_STATUS_NAMES,
    ACK_STATUS_OK,
    LOOPBACK_FLAG_LAST_CHUNK,
    LOOPBACK_FORMAT,
    LOOPBACK_HEADER_SIZE,
    LOOPBACK_MAGIC,
    build_receiver_config_packet,
)


DEFAULT_RECEIVER_PORT = 15002
DEFAULT_BOARD_IP = "192.168.1.50"
DEFAULT_BOARD_PORT = 5001
DEFAULT_IDLE_FINISH_S = 2.0
DEFAULT_OUTPUT_DIR = "output"


@dataclass
class ReceiverConfig:
    bind_ip: str = "0.0.0.0"
    bind_port: int = DEFAULT_RECEIVER_PORT
    board_ip: str = DEFAULT_BOARD_IP
    board_port: int = DEFAULT_BOARD_PORT
    register_with_board: bool = True
    socket_buffer_bytes: int = 4 * 1024 * 1024
    output_dir: str = DEFAULT_OUTPUT_DIR
    output_name: str = ""
    expected_bytes: int = 0
    idle_finish_s: float = DEFAULT_IDLE_FINISH_S
    progress_interval_s: float = 0.5
    stop_after_save: bool = True


@dataclass
class ReceiverStats:
    started_at: float = 0.0
    finished_at: float = 0.0
    packets: int = 0
    blocks: int = 0
    received_bytes: int = 0
    highest_end: int = 0
    crc_errors: int = 0
    length_errors: int = 0
    unknown_packets: int = 0
    register_attempts: int = 0
    register_ok: bool = False
    last_block_id: int = 0
    last_stream_offset: int = 0
    last_chunk_offset: int = 0
    last_chunk_len: int = 0
    rate_kib_s: float = 0.0
    packet_rate_s: float = 0.0
    gap_count: int = 0
    contiguous_bytes: int = 0
    saved_path: str = ""


def parse_args():
    parser = argparse.ArgumentParser(description="UDP loopback receiver for AD9361_test2")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="local IP to bind")
    parser.add_argument("--bind-port", type=int, default=DEFAULT_RECEIVER_PORT,
        help="local UDP port for loopback packets")
    parser.add_argument("--board-ip", default=DEFAULT_BOARD_IP, help="Zynq board IP")
    parser.add_argument("--board-port", type=int, default=DEFAULT_BOARD_PORT, help="Zynq UDP port")
    parser.add_argument("--no-register", action="store_true",
        help="listen only; do not send RXCFG registration to the board")
    parser.add_argument("--socket-buffer-bytes", type=int, default=4 * 1024 * 1024,
        help="host socket receive buffer size")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="output directory")
    parser.add_argument("--output-name", default="", help="output file name; extension is inferred if omitted")
    parser.add_argument("--expected-bytes", type=int, default=0,
        help="finish once this many contiguous bytes are recovered; 0 means idle timeout")
    parser.add_argument("--idle-finish-s", type=float, default=DEFAULT_IDLE_FINISH_S,
        help="finish after this many idle seconds when expected bytes is 0")
    parser.add_argument("--progress-interval-ms", type=int, default=500,
        help="minimum progress print interval")
    return parser.parse_args()


def parse_udp_packet(data: bytes):
    if len(data) < 4:
        return "unknown", {"length": len(data)}

    magic = struct.unpack("<I", data[:4])[0]
    if magic == ACK_MAGIC:
        if len(data) < ACK_SIZE:
            return "unknown", {"length": len(data), "reason": "short_ack"}
        _magic, seq, status, _reserved, transfer_len = struct.unpack(ACK_FORMAT, data[:ACK_SIZE])
        return "ack", {
            "seq": seq,
            "status": status,
            "transfer_len": transfer_len,
        }

    if magic == LOOPBACK_MAGIC:
        if len(data) < LOOPBACK_HEADER_SIZE:
            return "unknown", {"length": len(data), "reason": "short_loopback"}
        fields = struct.unpack(LOOPBACK_FORMAT, data[:LOOPBACK_HEADER_SIZE])
        (
            _magic,
            block_id,
            stream_offset,
            block_payload_len,
            chunk_offset,
            chunk_len,
            flags,
            payload_crc32,
            timestamp_lo,
            timestamp_hi,
            meta0,
            meta1,
        ) = fields
        payload = data[LOOPBACK_HEADER_SIZE:]
        return "loopback", {
            "block_id": block_id,
            "stream_offset": stream_offset,
            "block_payload_len": block_payload_len,
            "chunk_offset": chunk_offset,
            "chunk_len": chunk_len,
            "flags": flags,
            "payload_crc32": payload_crc32,
            "timestamp_lo": timestamp_lo,
            "timestamp_hi": timestamp_hi,
            "meta0": meta0,
            "meta1": meta1,
            "payload": payload,
        }

    return "unknown", {"length": len(data), "magic": magic}


def infer_extension(sample: bytes) -> str:
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if sample.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if sample.startswith(b"GIF87a") or sample.startswith(b"GIF89a"):
        return ".gif"
    if sample.startswith(b"BM"):
        return ".bmp"
    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        brand = sample[8:12].lower()
        if brand in (b"qt  ", b"m4v "):
            return ".mov" if brand == b"qt  " else ".m4v"
        return ".mp4"
    if sample.startswith(b"RIFF") and len(sample) >= 12 and sample[8:12] == b"AVI ":
        return ".avi"
    if sample.startswith(b"\x1a\x45\xdf\xa3"):
        return ".mkv"
    return ".bin"


def unique_output_path(output_dir: Path, requested_name: str, sample: bytes) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    if requested_name:
        candidate = Path(requested_name)
        if candidate.suffix == "":
            candidate = candidate.with_suffix(infer_extension(sample))
        if not candidate.is_absolute():
            candidate = output_dir / candidate.name
    else:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        candidate = output_dir / f"rx_{timestamp}{infer_extension(sample)}"

    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 10000):
        numbered = candidate.with_name(f"{stem}_{index:03d}{suffix}")
        if not numbered.exists():
            return numbered
    raise RuntimeError("could not allocate a unique output file name")


class SparseFileAssembler:
    def __init__(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_path = output_dir / f".rx_{os.getpid()}_{int(time.time() * 1000)}.part"
        self.fp = open(self.temp_path, "w+b")
        self.ranges = []
        self.highest_end = 0

    def close(self):
        if not self.fp.closed:
            self.fp.flush()
            self.fp.close()

    def discard(self):
        self.close()
        try:
            os.remove(self.temp_path)
        except FileNotFoundError:
            pass

    def write(self, offset: int, payload: bytes):
        if offset < 0:
            raise ValueError("negative write offset")
        if not payload:
            return
        self.fp.seek(offset)
        self.fp.write(payload)
        end = offset + len(payload)
        if end > self.highest_end:
            self.highest_end = end
        self.ranges.append((offset, end))

    def _merged_ranges(self):
        if not self.ranges:
            return []
        merged = []
        for start, end in sorted(self.ranges):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            elif end > merged[-1][1]:
                merged[-1][1] = end
        return merged

    def coverage(self) -> Tuple[int, int]:
        contiguous = 0
        gaps = 0
        for start, end in self._merged_ranges():
            if start > contiguous:
                gaps += 1
                continue
            if end > contiguous:
                contiguous = end
        return contiguous, gaps

    def sample(self, length: int = 64) -> bytes:
        self.fp.flush()
        self.fp.seek(0)
        return self.fp.read(length)

    def finalize(self, output_dir: Path, output_name: str, byte_count: int) -> Path:
        if byte_count <= 0:
            raise RuntimeError("no contiguous payload bytes were recovered")
        self.fp.flush()
        self.fp.truncate(byte_count)
        sample = self.sample()
        self.close()
        target_path = unique_output_path(output_dir, output_name, sample)
        os.replace(self.temp_path, target_path)
        return target_path


class LoopbackReceiver:
    def __init__(self, config: ReceiverConfig):
        self.config = config
        self._stop_requested = False
        self._last_progress_emit = 0.0
        self._saved = False
        self._assembler = SparseFileAssembler(Path(config.output_dir))

    def stop(self):
        self._stop_requested = True

    def _emit(self, callback: Optional[Callable[[str, dict], None]], event_name: str, payload: dict):
        if callback is not None:
            callback(event_name, payload)

    def _refresh_rates(self, stats: ReceiverStats, event_time: Optional[float] = None):
        if event_time is None:
            event_time = time.time()
        elapsed = max(event_time - stats.started_at, 1e-6)
        stats.rate_kib_s = (stats.received_bytes / 1024.0) / elapsed
        stats.packet_rate_s = stats.packets / elapsed

    def _emit_progress(self, callback, stats: ReceiverStats, force: bool = False):
        now = time.time()
        if not force and (now - self._last_progress_emit) < self.config.progress_interval_s:
            return
        self._last_progress_emit = now
        contiguous, gaps = self._assembler.coverage()
        stats.contiguous_bytes = contiguous
        stats.gap_count = gaps
        self._refresh_rates(stats, now)
        self._emit(callback, "progress", {"stats": stats})

    def _raise_socket_bind_error(self, exc: OSError):
        raise RuntimeError(
            f"local UDP bind failed for {self.config.bind_ip}:{self.config.bind_port}: {exc}. "
            "The port is probably already occupied or blocked by Windows. "
            "Close the process using that port, or change Bind Port to another value such as 15002."
        ) from exc

    def _register_with_board(self, sock: socket.socket, stats: ReceiverStats, callback):
        if not self.config.register_with_board:
            return

        destination = (self.config.board_ip, self.config.board_port)
        seq = random.randint(1, 0xFFFFFFFF)
        packet = build_receiver_config_packet(seq)
        previous_timeout = sock.gettimeout()
        sock.settimeout(0.25)
        try:
            for attempt in range(8):
                stats.register_attempts += 1
                try:
                    sock.sendto(packet, destination)
                except OSError as exc:
                    raise RuntimeError(
                        f"failed to send RXCFG to board {self.config.board_ip}:{self.config.board_port}: {exc}. "
                        "Check Board IP, network adapter, firewall, and whether the board is reachable."
                    ) from exc
                self._emit(callback, "register_attempt", {
                    "attempt": attempt + 1,
                    "board_ip": self.config.board_ip,
                    "board_port": self.config.board_port,
                })
                deadline = time.time() + 0.25
                while time.time() < deadline:
                    try:
                        data, _addr = sock.recvfrom(4096)
                    except socket.timeout:
                        break
                    packet_type, parsed = parse_udp_packet(data)
                    if packet_type != "ack":
                        continue
                    if parsed["seq"] != seq:
                        continue
                    if parsed["status"] == ACK_STATUS_OK:
                        stats.register_ok = True
                        self._emit(callback, "registered", {
                            "board_ip": self.config.board_ip,
                            "board_port": self.config.board_port,
                            "bind_port": self.config.bind_port,
                        })
                        return
                    status_name = ACK_STATUS_NAMES.get(parsed["status"], f"UNKNOWN_{parsed['status']}")
                    raise RuntimeError(f"board rejected RXCFG with {status_name}")
        finally:
            sock.settimeout(previous_timeout)

        raise RuntimeError("board did not ACK receiver registration")

    def _process_loopback(self, packet: dict, stats: ReceiverStats, callback):
        payload = packet["payload"]
        payload_len = len(payload)
        stream_offset = packet["stream_offset"]
        chunk_offset = packet["chunk_offset"]
        absolute_offset = stream_offset + chunk_offset
        status = "OK"

        stats.packets += 1
        stats.received_bytes += payload_len
        stats.last_block_id = packet["block_id"]
        stats.last_stream_offset = stream_offset
        stats.last_chunk_offset = chunk_offset
        stats.last_chunk_len = payload_len
        if (packet["flags"] & LOOPBACK_FLAG_LAST_CHUNK) != 0:
            stats.blocks += 1

        if payload_len != packet["chunk_len"]:
            stats.length_errors += 1
            status = "LEN"

        calc_crc = binascii.crc32(payload) & 0xFFFFFFFF
        if calc_crc != packet["payload_crc32"]:
            stats.crc_errors += 1
            status = "CRC"

        if status == "OK":
            self._assembler.write(absolute_offset, payload)
            if absolute_offset + payload_len > stats.highest_end:
                stats.highest_end = absolute_offset + payload_len

        self._refresh_rates(stats)
        self._emit(callback, "packet", {
            "status": status,
            "block_id": packet["block_id"],
            "stream_offset": stream_offset,
            "chunk_offset": chunk_offset,
            "payload_len": payload_len,
            "crc": calc_crc,
            "crc_expected": packet["payload_crc32"],
            "stats": stats,
        })

    def _save_if_ready(self, stats: ReceiverStats, callback, force: bool = False) -> bool:
        if self._saved:
            return True

        contiguous, gaps = self._assembler.coverage()
        stats.contiguous_bytes = contiguous
        stats.gap_count = gaps

        if not force:
            if self.config.expected_bytes > 0:
                if contiguous < self.config.expected_bytes:
                    return False
            elif contiguous == 0:
                return False

        byte_count = self.config.expected_bytes if self.config.expected_bytes > 0 else contiguous
        if byte_count <= 0:
            return False

        output_dir = Path(self.config.output_dir)
        target_path = self._assembler.finalize(output_dir, self.config.output_name, byte_count)
        stats.saved_path = str(target_path)
        stats.finished_at = time.time()
        self._saved = True
        self._emit(callback, "saved", {"path": str(target_path), "stats": stats})
        return True

    def run(self, callback: Optional[Callable[[str, dict], None]] = None) -> ReceiverStats:
        stats = ReceiverStats(started_at=time.time())
        last_payload_time = 0.0

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.config.socket_buffer_bytes)
                    sock.bind((self.config.bind_ip, self.config.bind_port))
                except OSError as exc:
                    self._raise_socket_bind_error(exc)

                sock.settimeout(0.05)

                self._emit(callback, "start", {
                    "bind_ip": self.config.bind_ip,
                    "bind_port": self.config.bind_port,
                    "output_dir": self.config.output_dir,
                    "expected_bytes": self.config.expected_bytes,
                })
                self._register_with_board(sock, stats, callback)

                while not self._stop_requested:
                    try:
                        data, _addr = sock.recvfrom(4096)
                    except socket.timeout:
                        now = time.time()
                        if (last_payload_time > 0.0 and self.config.expected_bytes == 0 and
                            self.config.idle_finish_s > 0.0 and
                            (now - last_payload_time) >= self.config.idle_finish_s):
                            if self._save_if_ready(stats, callback):
                                if self.config.stop_after_save:
                                    break
                        continue

                    packet_type, packet = parse_udp_packet(data)
                    if packet_type == "loopback":
                        self._process_loopback(packet, stats, callback)
                        last_payload_time = time.time()
                        self._emit_progress(callback, stats)
                        if self._save_if_ready(stats, callback):
                            if self.config.stop_after_save:
                                break
                    elif packet_type == "ack":
                        self._emit(callback, "ack", {
                            "seq": packet["seq"],
                            "status": packet["status"],
                            "status_name": ACK_STATUS_NAMES.get(packet["status"], f"UNKNOWN_{packet['status']}"),
                            "transfer_len": packet["transfer_len"],
                        })
                    else:
                        stats.unknown_packets += 1
                        self._emit(callback, "unknown", packet)

                if not self._saved:
                    self._save_if_ready(stats, callback, force=True)
        except Exception:
            if not self._saved:
                self._assembler.discard()
            raise

        if not self._saved:
            self._assembler.discard()
        self._emit_progress(callback, stats, force=True)
        self._emit(callback, "done", {"stats": stats})
        return stats


def run_cli(args) -> int:
    receiver = LoopbackReceiver(ReceiverConfig(
        bind_ip=args.bind_ip,
        bind_port=args.bind_port,
        board_ip=args.board_ip,
        board_port=args.board_port,
        register_with_board=not args.no_register,
        socket_buffer_bytes=args.socket_buffer_bytes,
        output_dir=args.output_dir,
        output_name=args.output_name,
        expected_bytes=args.expected_bytes,
        idle_finish_s=args.idle_finish_s,
        progress_interval_s=max(args.progress_interval_ms, 50) / 1000.0,
    ))

    def callback(event_name: str, payload: dict):
        if event_name == "start":
            print(
                f"listening {payload['bind_ip']}:{payload['bind_port']} "
                f"output={payload['output_dir']} expected={payload['expected_bytes']}"
            )
        elif event_name == "registered":
            print(
                f"registered board={payload['board_ip']}:{payload['board_port']} "
                f"receiver_port={payload['bind_port']}"
            )
        elif event_name == "progress":
            stats = payload["stats"]
            print(
                f"PROGRESS rx={stats.contiguous_bytes} high={stats.highest_end} "
                f"pkt={stats.packets} blk={stats.blocks} rate={stats.rate_kib_s:.2f}KiB/s "
                f"crc={stats.crc_errors} len={stats.length_errors} gaps={stats.gap_count}"
            )
        elif event_name == "packet" and payload["status"] != "OK":
            print(
                f"PACKET {payload['status']} block={payload['block_id']} "
                f"off={payload['stream_offset']}+{payload['chunk_offset']} len={payload['payload_len']}"
            )
        elif event_name == "saved":
            print(f"SAVED {payload['path']}")
        elif event_name == "done":
            stats = payload["stats"]
            print(
                f"DONE rx={stats.contiguous_bytes} high={stats.highest_end} "
                f"pkt={stats.packets} blk={stats.blocks} saved={stats.saved_path}"
            )

    receiver.run(callback=callback)
    return 0
