#!/usr/bin/env python3
import argparse
import binascii
import errno
import random
import shutil
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from air_protocol import (
    AIR_HEADER_BYTES,
    build_air_packet,
    crc32 as air_crc32,
    make_file_id,
)
from video_protocol import (
    AIRV_HEADER_BYTES,
    build_airv_stream,
    crc32 as airv_crc32,
    make_stream_id as make_airv_stream_id,
)


DATA_MAGIC = 0x4E455430
ACK_MAGIC = 0x41434B30
LOOPBACK_MAGIC = 0x304B424C
RXCFG_MAGIC = 0x52435830

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
LOOPBACK_FORMAT = "<IIIHHHHIIIII"
DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FORMAT)
ACK_SIZE = struct.calcsize(ACK_FORMAT)
LOOPBACK_HEADER_SIZE = struct.calcsize(LOOPBACK_FORMAT)

DATA_FLAG_RESET = 0x8000
DATA_FLAG_NO_CRC = 0x4000
DATA_SESSION_MASK = 0x1FFF
LOOPBACK_FLAG_LAST_CHUNK = 0x0001

DEFAULT_CHUNK_SIZE = 1440
DEFAULT_WINDOW_SIZE = 1
DEFAULT_ACK_TIMEOUT_S = 2.0
DEFAULT_RETRIES = 200
DEFAULT_TARGET_RATE_KIB_S = 400.0
TRANSFER_PROTOCOL_AIR0 = "air0_file"
TRANSFER_PROTOCOL_AIRV = "airv_video"
TRANSFER_PROTOCOL_RAW = "raw"
TRANSFER_PROTOCOL_CHOICES = (
    TRANSFER_PROTOCOL_AIR0,
    TRANSFER_PROTOCOL_AIRV,
    TRANSFER_PROTOCOL_RAW,
)
AIRV_SOURCE_SUFFIXES = (".h264", ".264")


@dataclass
class SenderConfig:
    ip: str
    port: int = 5001
    chunk_size: int = DEFAULT_CHUNK_SIZE
    timeout: float = DEFAULT_ACK_TIMEOUT_S
    retries: int = DEFAULT_RETRIES
    target_rate_kib_s: float = DEFAULT_TARGET_RATE_KIB_S
    window_size: int = DEFAULT_WINDOW_SIZE
    socket_buffer_bytes: int = 4 * 1024 * 1024
    progress_interval_s: float = 0.1
    verbose_events: bool = False
    throughput_mode: bool = False
    validate_payload_crc: bool = False
    air_protocol: bool = True
    transfer_protocol: str = TRANSFER_PROTOCOL_AIR0


@dataclass
class SenderStats:
    total_size: int = 0
    bytes_sent: int = 0
    bytes_acked: int = 0
    wire_bytes_sent: int = 0
    wire_bytes_acked: int = 0
    udp_app_bytes_sent: int = 0
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
    last_wire_payload_len: int = 0
    last_rtt_ms: float = 0.0
    current_rate_kib_s: float = 0.0
    current_wire_rate_kib_s: float = 0.0
    average_rate_kib_s: float = 0.0
    ack_pending: int = 0
    delivered_rate_kib_s: float = 0.0
    wire_delivered_rate_kib_s: float = 0.0
    udp_app_tx_rate_kib_s: float = 0.0
    ack_batches: int = 0
    packets_sent: int = 0
    ack_received: int = 0
    packets_sent_per_second: float = 0.0
    ack_received_per_second: float = 0.0
    send_loop_sleep_time_s: float = 0.0
    socket_timeout_wakeups: int = 0
    outstanding_window_avg: float = 0.0
    outstanding_window_max: int = 0
    outstanding_window_samples: int = 0
    effective_window_size: int = 0


def parse_args():
    parser = argparse.ArgumentParser(description="UDP sliding-window sender for AD9361_test2")
    parser.add_argument("--ip", required=True, help="Zynq target IP address")
    parser.add_argument("--port", type=int, default=5001, help="Zynq UDP port")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
        help="payload bytes per UDP chunk; 1440 fits a 1500 byte MTU")
    parser.add_argument("--timeout", type=float, default=DEFAULT_ACK_TIMEOUT_S,
        help="ACK timeout in seconds")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
        help="max retries per chunk")
    parser.add_argument("--target-rate-kib-s", type=float, default=DEFAULT_TARGET_RATE_KIB_S,
        help="optional offered load cap in KiB/s, 0 means unlimited")
    parser.add_argument("--window-size", type=int, default=DEFAULT_WINDOW_SIZE,
        help="number of in-flight chunks allowed before waiting for ACKs")
    parser.add_argument("--socket-buffer-bytes", type=int, default=4 * 1024 * 1024,
        help="host socket send/recv buffer size")
    parser.add_argument("--progress-interval-ms", type=int, default=100,
        help="minimum GUI/CLI progress update interval in ms")
    parser.add_argument("--verbose-events", action="store_true",
        help="print or emit per-packet events instead of throttled summaries")
    parser.add_argument("--throughput-mode", action="store_true",
        help="suppress packet events and print lightweight aggregate progress")
    parser.add_argument("--payload-crc", dest="validate_payload_crc",
        action="store_true", default=False,
        help="enable PC-generated and PS-validated application payload CRC32")
    parser.add_argument("--no-payload-crc", dest="validate_payload_crc",
        action="store_false",
        help="disable PC-generated and PS-validated application payload CRC32 for this transfer")
    parser.add_argument("--air-protocol", dest="air_protocol", action="store_true", default=True,
        help="wrap payload chunks in a PC-only AIR0 header for loss/error accounting")
    parser.add_argument("--no-air-protocol", dest="air_protocol", action="store_false",
        help="send raw file/test bytes without the PC-only AIR0 header")
    parser.add_argument("--transfer-protocol", choices=TRANSFER_PROTOCOL_CHOICES, default=None,
        help="PC-only wire payload protocol: air0_file, airv_video, or raw")
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


def _candidate_h264_paths(source_path: Path):
    candidates = []
    for suffix in AIRV_SOURCE_SUFFIXES:
        candidates.append(source_path.with_suffix(suffix))
    candidates.append(source_path.with_name(f"{source_path.stem}_airv.h264"))

    seen = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def find_existing_airv_h264(source_path: Path) -> Optional[Path]:
    if source_path.suffix.lower() in AIRV_SOURCE_SUFFIXES:
        return source_path
    for candidate in _candidate_h264_paths(source_path):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _run_ffmpeg(command):
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    message = stderr_text.strip() or stdout_text.strip()
    return completed.returncode, message


def ensure_airv_h264_source(file_path: str) -> Path:
    source_path = Path(file_path)
    if not source_path.exists():
        raise ValueError(f"source file does not exist: {source_path}")

    existing = find_existing_airv_h264(source_path)
    if existing is not None:
        return existing

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "AIRV selected an MP4/container source but no same-name .h264/.264 file exists, "
            "and ffmpeg was not found in PATH"
        )

    output_path = source_path.with_suffix(".h264")
    temp_path = output_path.with_suffix(".h264.tmp")

    copy_command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "copy",
        "-bsf:v",
        "h264_mp4toannexb,h264_metadata=aud=insert",
        "-f",
        "h264",
        str(temp_path),
    ]
    return_code, copy_error = _run_ffmpeg(copy_command)
    if return_code != 0:
        transcode_command = [
            ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "baseline",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "30",
            "-bf",
            "0",
            "-x264-params",
            "aud=1",
            "-f",
            "h264",
            str(temp_path),
        ]
        return_code, transcode_error = _run_ffmpeg(transcode_command)
        if return_code != 0:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise RuntimeError(
                "ffmpeg could not extract or generate an AIRV H.264 elementary stream. "
                f"copy error: {copy_error[-800:]} transcode error: {transcode_error[-800:]}"
            )

    if not temp_path.exists() or temp_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg completed but did not create a non-empty H.264 file")
    temp_path.replace(output_path)
    return output_path


def align8(length: int) -> int:
    return (length + 7) & ~7


def build_packet(seq: int, payload: bytes, config: Optional[SenderConfig] = None,
    session_id: int = 0, total_chunks: int = 0, total_size: int = 0,
    byte_offset: int = 0, file_crc32: int = 0, file_id: int = 0) -> bytes:
    wire_payload = payload
    use_air0 = False
    if config is not None:
        protocol = getattr(config, "transfer_protocol", TRANSFER_PROTOCOL_AIR0)
        use_air0 = config.air_protocol and protocol == TRANSFER_PROTOCOL_AIR0
    if use_air0:
        wire_payload = build_air_packet(
            payload,
            packet_seq=seq,
            total_packets=total_chunks,
            file_offset=byte_offset,
            file_size=total_size,
            chunk_bytes=config.chunk_size,
            session_id=session_id,
            file_crc32=file_crc32,
            file_id=file_id,
        )

    if len(wire_payload) > 0xFFFF:
        raise ValueError("PC->PS payload exceeds 16-bit payload_len field")

    validate_payload_crc = False if config is None else config.validate_payload_crc
    crc32 = (binascii.crc32(wire_payload) & 0xFFFFFFFF) if validate_payload_crc else 0
    header = struct.pack(
        DATA_HEADER_FORMAT,
        DATA_MAGIC,
        seq,
        len(wire_payload),
        session_id & DATA_SESSION_MASK,
        crc32,
    )
    return header + wire_payload


def build_reset_packet(session_id: int, validate_payload_crc: bool = False) -> bytes:
    flags = DATA_FLAG_RESET
    if not validate_payload_crc:
        flags |= DATA_FLAG_NO_CRC

    return struct.pack(
        DATA_HEADER_FORMAT,
        DATA_MAGIC,
        0,
        0,
        flags | (session_id & DATA_SESSION_MASK),
        0,
    )


def build_receiver_config_packet(seq: int = 0) -> bytes:
    return struct.pack(
        DATA_HEADER_FORMAT,
        RXCFG_MAGIC,
        seq,
        0,
        0,
        0,
    )


def recv_any_ack(sock: socket.socket):
    data, _ = sock.recvfrom(2048)
    if len(data) < ACK_SIZE:
        raise RuntimeError("received short ACK")

    magic, seq, status, _reserved, transfer_len = struct.unpack(ACK_FORMAT, data[:ACK_SIZE])
    if magic != ACK_MAGIC:
        raise RuntimeError(f"received invalid ACK magic 0x{magic:08X}")

    return seq, status, transfer_len


def recv_any_packet(sock: socket.socket):
    data, _ = sock.recvfrom(4096)
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

    return "unknown", {
        "length": len(data),
        "magic": magic,
    }


def iter_chunks(payload: bytes, chunk_size: int):
    offset = 0
    seq = 0

    while offset < len(payload):
        next_offset = min(offset + chunk_size, len(payload))
        yield seq, payload[offset:next_offset], offset, next_offset
        seq += 1
        offset = next_offset


def is_socket_would_block(exc: OSError) -> bool:
    return exc.errno in (
        errno.EAGAIN,
        errno.EWOULDBLOCK,
        getattr(errno, "WSAEWOULDBLOCK", 10035),
    )


class UdpSender:
    def __init__(self, config: SenderConfig):
        self.config = config
        self._stop_requested = False
        self._last_progress_emit = 0.0
        self._config_lock = threading.Lock()
        self._session_id = 0
        self._active_total_size = 0
        self._active_total_chunks = 0
        self._active_file_crc32 = 0
        self._active_file_id = 0
        self._active_source_size = 0
        self._active_stream_id = 0

    def _transfer_protocol(self) -> str:
        protocol = getattr(self.config, "transfer_protocol", TRANSFER_PROTOCOL_AIR0)
        if protocol not in TRANSFER_PROTOCOL_CHOICES:
            raise ValueError(f"unsupported transfer_protocol {protocol}")
        if protocol == TRANSFER_PROTOCOL_RAW:
            return TRANSFER_PROTOCOL_RAW
        if protocol == TRANSFER_PROTOCOL_AIRV:
            return TRANSFER_PROTOCOL_AIRV
        if not self.config.air_protocol:
            return TRANSFER_PROTOCOL_RAW
        return TRANSFER_PROTOCOL_AIR0

    def _payload_chunk_size(self) -> int:
        protocol = self._transfer_protocol()
        if protocol == TRANSFER_PROTOCOL_AIR0:
            return self.config.chunk_size - AIR_HEADER_BYTES
        if protocol == TRANSFER_PROTOCOL_AIRV:
            return self.config.chunk_size
        return self.config.chunk_size

    def stop(self):
        self._stop_requested = True

    def _validate_config(self):
        with self._config_lock:
            chunk_size = self.config.chunk_size
            window_size = self.config.window_size
            protocol = self._transfer_protocol()

        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if protocol == TRANSFER_PROTOCOL_AIR0:
            if chunk_size <= AIR_HEADER_BYTES:
                raise ValueError(f"chunk_size must be greater than AIR header size {AIR_HEADER_BYTES}")
        if protocol == TRANSFER_PROTOCOL_AIRV:
            if chunk_size <= AIRV_HEADER_BYTES:
                raise ValueError(f"chunk_size must be greater than AIRV header size {AIRV_HEADER_BYTES}")

    def _prepare_transfer(self, payload: bytes):
        protocol = self._transfer_protocol()
        self._active_source_size = len(payload)

        if protocol == TRANSFER_PROTOCOL_AIRV:
            video_crc = airv_crc32(payload)
            self._active_stream_id = make_airv_stream_id(
                len(payload),
                video_crc,
                self._session_id,
            )
            prepared_payload = build_airv_stream(
                payload,
                chunk_bytes=self.config.chunk_size,
                session_id=self._session_id,
                stream_id=self._active_stream_id,
            )
            total_chunks = (
                (len(prepared_payload) + self.config.chunk_size - 1) //
                self.config.chunk_size
            )
            self._active_total_size = len(prepared_payload)
            self._active_total_chunks = total_chunks
            self._active_file_crc32 = video_crc
            self._active_file_id = self._active_stream_id
            return prepared_payload

        payload_chunk_size = self._payload_chunk_size()
        total_chunks = (len(payload) + payload_chunk_size - 1) // payload_chunk_size
        self._active_total_size = len(payload)
        self._active_total_chunks = total_chunks
        self._active_file_crc32 = air_crc32(payload)
        self._active_file_id = make_file_id(
            self._active_total_size,
            self._active_file_crc32,
            self._session_id,
        )

        return payload

    def _build_packet(self, seq: int, payload: bytes) -> bytes:
        with self._config_lock:
            validate_payload_crc = self.config.validate_payload_crc
            session_id = self._session_id
            protocol = self._transfer_protocol()

        config = SenderConfig(
            ip=self.config.ip,
            port=self.config.port,
            chunk_size=self.config.chunk_size,
            timeout=self.config.timeout,
            retries=self.config.retries,
            target_rate_kib_s=self.config.target_rate_kib_s,
            window_size=self.config.window_size,
            socket_buffer_bytes=self.config.socket_buffer_bytes,
            progress_interval_s=self.config.progress_interval_s,
            verbose_events=self.config.verbose_events,
            throughput_mode=self.config.throughput_mode,
            validate_payload_crc=validate_payload_crc,
            air_protocol=(protocol == TRANSFER_PROTOCOL_AIR0),
            transfer_protocol=protocol,
        )
        return build_packet(
            seq,
            payload,
            config,
            session_id=session_id,
            total_chunks=self._active_total_chunks,
            total_size=self._active_total_size,
            byte_offset=seq * self._payload_chunk_size(),
            file_crc32=self._active_file_crc32,
            file_id=self._active_file_id,
        )

    def _begin_new_session(self):
        destination = (self.config.ip, self.config.port)
        reset_timeout_s = min(max(self.config.timeout, 0.2), 1.0)
        retries = max(self.config.retries, 3)
        session_id = random.randint(1, DATA_SESSION_MASK)
        with self._config_lock:
            validate_payload_crc = self.config.validate_payload_crc
        packet = build_reset_packet(session_id, validate_payload_crc)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(reset_timeout_s)
            for attempt in range(retries + 1):
                sock.sendto(packet, destination)
                try:
                    ack_seq, status, _transfer_len = recv_any_ack(sock)
                except socket.timeout:
                    continue

                if ack_seq != 0:
                    continue
                if status == ACK_STATUS_OK:
                    with self._config_lock:
                        self._session_id = session_id
                    return session_id
                if status == ACK_STATUS_BUSY:
                    time.sleep(0.02)
                    continue
                if status == ACK_STATUS_DMA_ERROR:
                    raise RuntimeError("target reported DMA_ERROR during session reset")

            raise RuntimeError("target did not accept session reset")

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

    def _packet_wire_payload_len(self, packet: bytes) -> int:
        return max(len(packet) - DATA_HEADER_SIZE, 0)

    def _record_packet_send(self, stats: SenderStats, packet: bytes):
        stats.packets_sent += 1
        stats.wire_bytes_sent += self._packet_wire_payload_len(packet)
        stats.udp_app_bytes_sent += len(packet)

    def _update_rates(self, stats: SenderStats, payload_len: int, wire_payload_len: int,
        ack_time: float, tx_time: float):
        ack_elapsed = max(ack_time - tx_time, 1e-6)

        stats.last_rtt_ms = ack_elapsed * 1000.0
        stats.last_wire_payload_len = wire_payload_len
        stats.current_rate_kib_s = (payload_len / 1024.0) / ack_elapsed
        stats.current_wire_rate_kib_s = (wire_payload_len / 1024.0) / ack_elapsed
        self._refresh_cumulative_rates(stats, ack_time)

    def _refresh_cumulative_rates(self, stats: SenderStats, event_time: Optional[float] = None):
        if event_time is None:
            event_time = time.time()
        elapsed = max(event_time - stats.started_at, 1e-6)

        stats.average_rate_kib_s = (stats.bytes_sent / 1024.0) / elapsed
        stats.delivered_rate_kib_s = (stats.bytes_acked / 1024.0) / elapsed
        stats.wire_delivered_rate_kib_s = (stats.wire_bytes_acked / 1024.0) / elapsed
        stats.udp_app_tx_rate_kib_s = (stats.udp_app_bytes_sent / 1024.0) / elapsed
        stats.packets_sent_per_second = stats.packets_sent / elapsed
        stats.ack_received_per_second = stats.ack_received / elapsed

    def _drain_loopback(self, sock: socket.socket, payload: bytes, stats: SenderStats,
        callback: Optional[Callable[[str, dict], None]]):
        return

    def _sample_outstanding(self, stats: SenderStats, window_used: int):
        stats.outstanding_window_samples += 1
        samples = stats.outstanding_window_samples
        stats.outstanding_window_avg += (window_used - stats.outstanding_window_avg) / samples
        if window_used > stats.outstanding_window_max:
            stats.outstanding_window_max = window_used

    def _should_emit_progress(self, now: float) -> bool:
        if self.config.verbose_events:
            return True
        if (now - self._last_progress_emit) >= self.config.progress_interval_s:
            self._last_progress_emit = now
            return True
        return False

    def _emit_progress(self, callback: Optional[Callable[[str, dict], None]], stats: SenderStats,
        window_used: int, force: bool = False):
        now = time.monotonic()
        if not force and not self._should_emit_progress(now):
            return
        if force:
            self._last_progress_emit = now
        self._emit(callback, "progress", {
            "window_used": window_used,
            "stats": stats,
        })

    def _build_cached_packet(self, payload: bytes, packet_cache: list, seq: int):
        packet = packet_cache[seq]
        payload_chunk_size = self._payload_chunk_size()
        start = seq * payload_chunk_size
        end = min(start + payload_chunk_size, len(payload))
        if packet is None:
            packet = self._build_packet(seq, payload[start:end])
            packet_cache[seq] = packet
        return packet, start, end

    def _process_ack(self, ack_seq: int, status: int, transfer_len: int, ack_time: float,
        outstanding: Dict[int, dict], acked: list, packet_cache: list, stats: SenderStats,
        callback: Optional[Callable[[str, dict], None]], busy_retry_delay: float) -> int:
        stats.ack_received += 1

        if ack_seq not in outstanding:
            self._emit(callback, "ack_ignored", {
                "seq": ack_seq,
                "status": status,
                "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                "transfer_len": transfer_len,
            })
            return 0

        entry = outstanding[ack_seq]
        rtt_ms = (ack_time - entry["tx_time"]) * 1000.0
        stats.last_seq = ack_seq
        stats.last_ack_status = status
        stats.last_transfer_len = transfer_len

        if status == ACK_STATUS_OK:
            completed_seqs = sorted(seq for seq in outstanding.keys() if seq <= ack_seq)
            if not completed_seqs:
                self._emit(callback, "ack_ignored", {
                    "seq": ack_seq,
                    "status": status,
                    "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                    "transfer_len": transfer_len,
                })
                return 0

            last_completed_seq = completed_seqs[-1]
            last_entry = outstanding[last_completed_seq]

            for completed_seq in completed_seqs:
                completed_entry = outstanding.pop(completed_seq)
                acked[completed_seq] = True
                packet_cache[completed_seq] = None
                stats.bytes_sent = max(stats.bytes_sent, completed_entry["end"])
                stats.bytes_acked += completed_entry["payload_len"]
                stats.wire_bytes_acked += completed_entry["wire_payload_len"]
                stats.chunks_acked += 1

            if outstanding:
                next_oldest_seq = min(outstanding.keys())
                next_oldest_entry = outstanding[next_oldest_seq]
                if next_oldest_entry.get("blocked_by_gap", False):
                    next_oldest_entry["retry_deadline"] = min(
                        next_oldest_entry["retry_deadline"], ack_time)
                    next_oldest_entry["retry_reason"] = "gap"

            stats.ack_ok += len(completed_seqs)
            stats.ack_batches += 1
            stats.last_seq = last_completed_seq
            stats.last_transfer_len = transfer_len
            self._update_rates(
                stats,
                last_entry["payload_len"],
                last_entry["wire_payload_len"],
                ack_time,
                last_entry["tx_time"],
            )
            if self.config.verbose_events:
                self._emit(callback, "ack_ok", {
                    "seq": last_completed_seq,
                    "payload_len": last_entry["payload_len"],
                    "transfer_len": transfer_len,
                    "offset": last_entry["start"],
                    "end": last_entry["end"],
                    "acked_count": len(completed_seqs),
                    "window_used": len(outstanding),
                    "stats": stats,
                })
            return len(completed_seqs)

        if status == ACK_STATUS_PENDING:
            stats.ack_pending += 1
            entry["blocked_by_gap"] = True
            if outstanding:
                oldest_seq = min(outstanding.keys())
                oldest_entry = outstanding[oldest_seq]
                if (ack_time - oldest_entry["tx_time"]) >= busy_retry_delay:
                    oldest_entry["retry_deadline"] = min(oldest_entry["retry_deadline"], ack_time)
                    oldest_entry["retry_reason"] = "gap"
            self._update_rates(stats, entry["payload_len"], entry["wire_payload_len"],
                ack_time, entry["tx_time"])
            if self.config.verbose_events:
                self._emit(callback, "ack_status", {
                    "seq": ack_seq,
                    "payload_len": entry["payload_len"],
                    "transfer_len": transfer_len,
                    "status": status,
                    "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                    "attempt": entry["attempts"],
                    "rtt_ms": rtt_ms,
                    "window_used": len(outstanding),
                    "stats": stats,
                })
            return 0

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

        if self.config.verbose_events:
            self._emit(callback, "ack_status", {
                "seq": ack_seq,
                "payload_len": entry["payload_len"],
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
        return 0

    def _send_throughput(self, payload: bytes,
        callback: Optional[Callable[[str, dict], None]] = None) -> SenderStats:
        stats = SenderStats(total_size=len(payload))
        stats.effective_window_size = self.config.window_size
        destination = (self.config.ip, self.config.port)
        payload_chunk_size = self._payload_chunk_size()
        total_chunks = (len(payload) + payload_chunk_size - 1) // payload_chunk_size
        packet_cache = [None] * total_chunks
        acked = [False] * total_chunks
        outstanding: Dict[int, dict] = {}
        base_seq = 0
        next_seq = 0

        stats.started_at = time.time()
        self._last_progress_emit = 0.0
        self._emit(callback, "start", {"total_size": stats.total_size, "config": self.config})

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.config.socket_buffer_bytes)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.config.socket_buffer_bytes)
        sock.setblocking(False)
        busy_retry_delay = max(min(self.config.timeout / 8.0, 0.02), 0.002)
        idle_sleep_s = 0.0005
        effective_window_size = self.config.window_size
        stable_ack_batches = 0
        stats.effective_window_size = effective_window_size

        try:
            while base_seq < total_chunks:
                made_progress = False

                while next_seq < total_chunks and len(outstanding) < effective_window_size:
                    if self._stop_requested:
                        self._emit(callback, "stopped", {"seq": next_seq, "bytes_sent": stats.bytes_sent})
                        stats.finished_at = time.time()
                        return stats

                    packet, start, end = self._build_cached_packet(payload, packet_cache, next_seq)
                    self._apply_rate_limit(stats.bytes_sent + (end - start), stats.started_at)
                    tx_time = time.time()
                    sock.sendto(packet, destination)
                    wire_payload_len = self._packet_wire_payload_len(packet)
                    outstanding[next_seq] = {
                        "start": start,
                        "end": end,
                        "payload_len": end - start,
                        "wire_payload_len": wire_payload_len,
                        "attempts": 1,
                        "tx_time": tx_time,
                        "retry_deadline": tx_time + self.config.timeout,
                        "retry_reason": "timeout",
                        "blocked_by_gap": False,
                    }
                    self._record_packet_send(stats, packet)
                    stats.bytes_sent = max(stats.bytes_sent, end)
                    made_progress = True
                    if self.config.verbose_events:
                        self._emit(callback, "chunk_sent", {
                            "seq": next_seq,
                            "payload_len": end - start,
                            "attempt": 1,
                            "offset": start,
                            "end": end,
                            "window_used": len(outstanding),
                        })
                    next_seq += 1

                while True:
                    try:
                        packet_type, packet = recv_any_packet(sock)
                    except BlockingIOError:
                        break
                    except OSError as exc:
                        if is_socket_would_block(exc):
                            break
                        raise

                    if packet_type == "loopback":
                        if self.config.verbose_events:
                            self._emit(callback, "packet_ignored", {"reason": "loopback_moved_to_receiver"})
                        made_progress = True
                        continue
                    if packet_type != "ack":
                        if self.config.verbose_events:
                            self._emit(callback, "packet_ignored", packet)
                        continue

                    ack_seq = packet["seq"]
                    status = packet["status"]
                    transfer_len = packet["transfer_len"]
                    completed = self._process_ack(
                        ack_seq,
                        status,
                        transfer_len,
                        time.time(),
                        outstanding,
                        acked,
                        packet_cache,
                        stats,
                        callback,
                        busy_retry_delay,
                    )
                    while base_seq < total_chunks and acked[base_seq]:
                        base_seq += 1
                    made_progress = True
                    if status == ACK_STATUS_BUSY:
                        effective_window_size = max(1, max(effective_window_size // 2, 1))
                        stable_ack_batches = 0
                    elif status == ACK_STATUS_PENDING:
                        if effective_window_size > 1:
                            effective_window_size -= 1
                        stable_ack_batches = 0
                    elif completed > 0:
                        stable_ack_batches += 1
                        if (stable_ack_batches >= effective_window_size and
                            effective_window_size < self.config.window_size):
                            effective_window_size += 1
                            stable_ack_batches = 0
                    stats.effective_window_size = effective_window_size
                    if completed > 0:
                        self._emit_progress(callback, stats, len(outstanding))

                now = time.time()
                if outstanding:
                    oldest_seq = min(outstanding.keys())
                    entry = outstanding[oldest_seq]
                else:
                    oldest_seq = None
                    entry = None
                if entry is not None and now >= entry["retry_deadline"]:
                    entry["attempts"] += 1
                    if entry["attempts"] > self.config.retries:
                        raise RuntimeError(f"seq {oldest_seq} exceeded retry limit")

                    packet, _start, _end = self._build_cached_packet(payload, packet_cache, oldest_seq)
                    reason = entry.get("retry_reason", "timeout")
                    entry["tx_time"] = now
                    entry["retry_deadline"] = now + self.config.timeout
                    entry["retry_reason"] = "timeout"
                    entry["blocked_by_gap"] = False
                    sock.sendto(packet, destination)
                    self._record_packet_send(stats, packet)
                    stats.retries_used += 1
                    if reason == "timeout":
                        stats.timeout_count += 1
                    effective_window_size = max(1, max(effective_window_size // 2, 1))
                    stable_ack_batches = 0
                    stats.effective_window_size = effective_window_size
                    made_progress = True
                    if self.config.verbose_events:
                        self._emit(callback, "timeout" if reason == "timeout" else "retry", {
                            "seq": oldest_seq,
                            "payload_len": entry["payload_len"],
                            "attempt": entry["attempts"],
                            "reason": reason,
                            "window_used": len(outstanding),
                        })
                    self._emit_progress(callback, stats, len(outstanding))

                self._sample_outstanding(stats, len(outstanding))
                self._emit_progress(callback, stats, len(outstanding))

                if not made_progress and outstanding:
                    stats.socket_timeout_wakeups += 1
                    sleep_start = time.time()
                    time.sleep(idle_sleep_s)
                    stats.send_loop_sleep_time_s += time.time() - sleep_start

            self._drain_loopback(sock, payload, stats, callback)
            stats.finished_at = time.time()
            self._refresh_cumulative_rates(stats, stats.finished_at)
            self._emit_progress(callback, stats, len(outstanding), force=True)
            self._emit(callback, "done", {"stats": stats})
            return stats
        finally:
            sock.close()

    def send(self, payload: bytes, callback: Optional[Callable[[str, dict], None]] = None) -> SenderStats:
        self._validate_config()
        self._begin_new_session()
        payload = self._prepare_transfer(payload)

        if self.config.throughput_mode:
            return self._send_throughput(payload, callback=callback)

        stats = SenderStats(total_size=self._active_total_size)
        stats.effective_window_size = self.config.window_size
        destination = (self.config.ip, self.config.port)
        chunks = list(iter_chunks(payload, self._payload_chunk_size()))
        total_chunks = len(chunks)
        acked = [False] * total_chunks
        outstanding: Dict[int, dict] = {}
        base_seq = 0
        next_seq = 0

        stats.started_at = time.time()
        self._last_progress_emit = 0.0
        self._emit(callback, "start", {"total_size": stats.total_size, "config": self.config})

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.config.socket_buffer_bytes)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.config.socket_buffer_bytes)
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
                    packet = self._build_packet(seq, chunk)
                    sock.sendto(packet, destination)
                    wire_payload_len = self._packet_wire_payload_len(packet)
                    self._record_packet_send(stats, packet)
                    stats.bytes_sent = max(stats.bytes_sent, end)
                    outstanding[seq] = {
                        "packet": packet,
                        "chunk": chunk,
                        "wire_payload_len": wire_payload_len,
                        "start": start,
                        "end": end,
                        "attempts": 1,
                        "tx_time": tx_time,
                        "retry_deadline": tx_time + self.config.timeout,
                        "retry_reason": "timeout",
                        "blocked_by_gap": False,
                    }
                    if self.config.verbose_events:
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

                    packet_type, packet = recv_any_packet(sock)
                    if packet_type == "loopback":
                        if self.config.verbose_events:
                            self._emit(callback, "packet_ignored", {"reason": "loopback_moved_to_receiver"})
                        continue
                    if packet_type != "ack":
                        if self.config.verbose_events:
                            self._emit(callback, "packet_ignored", packet)
                        continue

                    ack_seq = packet["seq"]
                    status = packet["status"]
                    transfer_len = packet["transfer_len"]
                    ack_time = time.time()
                    stats.ack_received += 1
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

                    if status == ACK_STATUS_OK:
                        completed_seqs = sorted(seq for seq in outstanding.keys() if seq <= ack_seq)
                        if not completed_seqs:
                            self._emit(callback, "ack_ignored", {
                                "seq": ack_seq,
                                "status": status,
                                "status_name": ACK_STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
                                "transfer_len": transfer_len,
                            })
                            continue

                        last_completed_seq = completed_seqs[-1]
                        last_entry = outstanding[last_completed_seq]

                        for completed_seq in completed_seqs:
                            completed_entry = outstanding.pop(completed_seq)
                            acked[completed_seq] = True
                            stats.bytes_sent = max(stats.bytes_sent, completed_entry["end"])
                            stats.bytes_acked += len(completed_entry["chunk"])
                            stats.wire_bytes_acked += completed_entry["wire_payload_len"]
                            stats.chunks_acked += 1

                        while base_seq < total_chunks and acked[base_seq]:
                            base_seq += 1

                        if outstanding:
                            next_oldest_seq = min(outstanding.keys())
                            next_oldest_entry = outstanding[next_oldest_seq]
                            if next_oldest_entry.get("blocked_by_gap", False):
                                next_oldest_entry["retry_deadline"] = min(
                                    next_oldest_entry["retry_deadline"], ack_time)
                                next_oldest_entry["retry_reason"] = "gap"

                        stats.ack_ok += len(completed_seqs)
                        stats.ack_batches += 1
                        stats.last_seq = last_completed_seq
                        stats.last_transfer_len = transfer_len
                        self._update_rates(
                            stats,
                            len(last_entry["chunk"]),
                            last_entry["wire_payload_len"],
                            ack_time,
                            last_entry["tx_time"],
                        )
                        self._sample_outstanding(stats, len(outstanding))
                        if self.config.verbose_events:
                            self._emit(callback, "ack_ok", {
                                "seq": last_completed_seq,
                                "payload_len": len(last_entry["chunk"]),
                                "transfer_len": transfer_len,
                                "offset": last_entry["start"],
                                "end": last_entry["end"],
                                "acked_count": len(completed_seqs),
                                "window_used": len(outstanding),
                                "stats": stats,
                            })
                        self._emit_progress(callback, stats, len(outstanding))
                    elif status == ACK_STATUS_PENDING:
                        stats.ack_pending += 1
                        entry["blocked_by_gap"] = True
                        if outstanding:
                            oldest_seq = min(outstanding.keys())
                            oldest_entry = outstanding[oldest_seq]
                            if (ack_time - oldest_entry["tx_time"]) >= busy_retry_delay:
                                oldest_entry["retry_deadline"] = min(oldest_entry["retry_deadline"], ack_time)
                                oldest_entry["retry_reason"] = "gap"
                        self._update_rates(stats, len(chunk), entry["wire_payload_len"],
                            ack_time, entry["tx_time"])
                        if self.config.verbose_events:
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

                        if self.config.verbose_events:
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
                    stats.socket_timeout_wakeups += 1
                    if not outstanding:
                        continue

                    now = time.time()
                    oldest_seq = min(outstanding.keys())
                    entry = outstanding[oldest_seq]
                    if now < entry["retry_deadline"]:
                        continue
                    entry["attempts"] += 1
                    if entry["attempts"] > self.config.retries:
                        raise RuntimeError(f"seq {oldest_seq} exceeded retry limit")
                    stats.retries_used += 1
                    entry["tx_time"] = now
                    entry["retry_deadline"] = now + self.config.timeout
                    reason = entry.get("retry_reason", "timeout")
                    entry["retry_reason"] = "timeout"
                    entry["blocked_by_gap"] = False
                    sock.sendto(entry["packet"], destination)
                    self._record_packet_send(stats, entry["packet"])
                    if reason == "timeout":
                        stats.timeout_count += 1
                    if self.config.verbose_events:
                        self._emit(callback, "timeout" if reason == "timeout" else "retry", {
                            "seq": oldest_seq,
                            "payload_len": len(entry["chunk"]),
                            "attempt": entry["attempts"],
                            "reason": reason,
                            "window_used": len(outstanding),
                        })
                    self._emit_progress(callback, stats, len(outstanding))
                    self._sample_outstanding(stats, len(outstanding))

            self._drain_loopback(sock, payload, stats, callback)
            stats.finished_at = time.time()
            self._refresh_cumulative_rates(stats, stats.finished_at)
            self._emit_progress(callback, stats, len(outstanding), force=True)
            self._emit(callback, "done", {"stats": stats})
            return stats
        finally:
            sock.close()


def run_cli(args) -> int:
    transfer_protocol = args.transfer_protocol
    if transfer_protocol is None:
        transfer_protocol = TRANSFER_PROTOCOL_AIR0 if args.air_protocol else TRANSFER_PROTOCOL_RAW
    file_path = args.file
    if transfer_protocol == TRANSFER_PROTOCOL_AIRV:
        if args.test_size > 0:
            raise ValueError("AIRV realtime video requires --file, not --test-size")
        if not file_path:
            raise ValueError("AIRV realtime video requires --file")
        airv_path = ensure_airv_h264_source(file_path)
        if Path(file_path) != airv_path:
            print(f"AIRV source prepared {airv_path}")
        file_path = str(airv_path)
    payload = load_payload(test_size=args.test_size, file_path=file_path)
    sender = UdpSender(SenderConfig(
        ip=args.ip,
        port=args.port,
        chunk_size=args.chunk_size,
        timeout=args.timeout,
        retries=args.retries,
        target_rate_kib_s=args.target_rate_kib_s,
        window_size=args.window_size,
        socket_buffer_bytes=args.socket_buffer_bytes,
        progress_interval_s=(
            max(args.progress_interval_ms, 1000) if args.throughput_mode
            else max(args.progress_interval_ms, 10)
        ) / 1000.0,
        verbose_events=False if args.throughput_mode else args.verbose_events,
        throughput_mode=args.throughput_mode,
        validate_payload_crc=args.validate_payload_crc,
        air_protocol=(transfer_protocol == TRANSFER_PROTOCOL_AIR0),
        transfer_protocol=transfer_protocol,
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
                f"ack_payload={payload_dict['transfer_len']} progress={stats.bytes_sent}/{stats.total_size} "
                f"rtt_ms={stats.last_rtt_ms:.2f} app_deliv={stats.delivered_rate_kib_s:.2f} KiB/s "
                f"wire_acc={stats.wire_delivered_rate_kib_s:.2f} KiB/s udp_tx={stats.udp_app_tx_rate_kib_s:.2f} KiB/s"
            )
        elif event_name == "ack_status":
            print(
                f"seq={payload_dict['seq']} payload_len={payload_dict['payload_len']} "
                f"ack_status={payload_dict['status_name']} ack_payload={payload_dict['transfer_len']} "
                f"retry={payload_dict['attempt']} rtt_ms={payload_dict['rtt_ms']:.2f}"
            )
        elif event_name == "ack_ignored":
            print(
                f"ack_ignored seq={payload_dict['seq']} status={payload_dict['status_name']} "
                f"ack_payload={payload_dict['transfer_len']}"
            )
        elif event_name == "progress":
            stats = payload_dict["stats"]
            if args.throughput_mode:
                print(
                    f"THR app_ack={stats.bytes_acked}/{stats.total_size} app_sched={stats.bytes_sent}/{stats.total_size} "
                    f"wire_ack={stats.wire_bytes_acked} udp_tx={stats.udp_app_bytes_sent} "
                    f"inflight={payload_dict['window_used']} app_sched_rate={stats.average_rate_kib_s:.2f} KiB/s "
                    f"app_deliv={stats.delivered_rate_kib_s:.2f} KiB/s "
                    f"wire_acc={stats.wire_delivered_rate_kib_s:.2f} KiB/s udp_tx={stats.udp_app_tx_rate_kib_s:.2f} KiB/s "
                    f"tx_pkt={stats.packets_sent_per_second:.1f}/s ack_rx={stats.ack_received_per_second:.1f}/s "
                    f"rtt={stats.last_rtt_ms:.2f} ms retry={stats.retries_used} timeout={stats.timeout_count} "
                    f"busy={stats.ack_busy} pending={stats.ack_pending} "
                    f"window={stats.effective_window_size}/{sender.config.window_size} "
                    f"occ_avg={stats.outstanding_window_avg:.1f} occ_max={stats.outstanding_window_max} "
                    f"idle_sleep={stats.send_loop_sleep_time_s:.3f}s empty={stats.socket_timeout_wakeups}"
                )
            else:
                print(
                    f"progress app_ack={stats.bytes_acked}/{stats.total_size} app_sched={stats.bytes_sent}/{stats.total_size} "
                    f"wire_ack={stats.wire_bytes_acked} udp_tx={stats.udp_app_bytes_sent} "
                    f"inflight={payload_dict['window_used']} app_deliv={stats.delivered_rate_kib_s:.2f} KiB/s "
                    f"wire_acc={stats.wire_delivered_rate_kib_s:.2f} KiB/s udp_tx_rate={stats.udp_app_tx_rate_kib_s:.2f} KiB/s "
                    f"tx_pkt={stats.packets_sent_per_second:.1f}/s ack_rx={stats.ack_received_per_second:.1f}/s "
                    f"rtt={stats.last_rtt_ms:.2f} ms busy={stats.ack_busy} pending={stats.ack_pending}"
                )
        elif event_name == "done":
            stats = payload_dict["stats"]
            elapsed = max(stats.finished_at - stats.started_at, 1e-6)
            print(
                f"done app_sched={stats.bytes_sent} app_ack={stats.bytes_acked} "
                f"wire_ack={stats.wire_bytes_acked} udp_tx={stats.udp_app_bytes_sent} elapsed={elapsed:.3f}s "
                f"app_sched_rate={stats.average_rate_kib_s:.2f} KiB/s app_deliv={stats.delivered_rate_kib_s:.2f} KiB/s "
                f"wire_acc={stats.wire_delivered_rate_kib_s:.2f} KiB/s udp_tx={stats.udp_app_tx_rate_kib_s:.2f} KiB/s "
                f"tx_pkt={stats.packets_sent_per_second:.1f}/s ack_rx={stats.ack_received_per_second:.1f}/s "
                f"ack_ok={stats.ack_ok} ack_pending={stats.ack_pending} timeouts={stats.timeout_count}"
            )

    sender.send(payload, callback=callback)
    return 0
