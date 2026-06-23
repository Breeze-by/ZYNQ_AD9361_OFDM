#!/usr/bin/env python3
import argparse
import bisect
import binascii
import os
import random
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from air_protocol import (
    AIR_FLAG_DATA,
    AIR_FLAG_LAST,
    AIR_HEADER_BYTES,
    AIR_MAGIC,
    crc32 as air_crc32,
    parse_air_header,
)
from video_protocol import (
    AIRV_HEADER_BYTES,
    AIRV_MAGIC,
    crc32 as airv_crc32,
    parse_airv_header,
)
from video_receiver_core import VideoStreamAssembler
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
DEFAULT_IDLE_FINISH_S = 10.0
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_SOCKET_BUFFER_BYTES = 16 * 1024 * 1024


@dataclass
class ReceiverConfig:
    bind_ip: str = "0.0.0.0"
    bind_port: int = DEFAULT_RECEIVER_PORT
    board_ip: str = DEFAULT_BOARD_IP
    board_port: int = DEFAULT_BOARD_PORT
    register_with_board: bool = True
    socket_buffer_bytes: int = DEFAULT_SOCKET_BUFFER_BYTES
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
    incomplete_reason: str = ""
    air_mode: bool = False
    air_packets: int = 0
    air_total_packets: int = 0
    air_missing_packets: int = 0
    air_bad_header: int = 0
    air_bad_payload_crc: int = 0
    air_duplicates: int = 0
    air_bad_meta: int = 0
    air_file_size: int = 0
    air_file_crc32: int = 0
    air_file_id: int = 0
    air_session_id: int = 0
    air_chunk_bytes: int = 0
    air_got_last: bool = False
    air_last_seq: int = -1
    air_file_crc_ok: bool = False
    air_missing_ranges: str = ""
    air_bad_payload_ranges: str = ""
    air_bad_meta_ranges: str = ""
    airv_mode: bool = False
    airv_frames_rx: int = 0
    airv_frames_show: int = 0
    airv_frames_drop: int = 0
    airv_frag_rx: int = 0
    airv_frag_missing: int = 0
    airv_bad_header: int = 0
    airv_bad_meta: int = 0
    airv_bad_frag_crc: int = 0
    airv_bad_frame_crc: int = 0
    airv_keyframe_rx: int = 0
    airv_waiting_keyframe: int = 0
    airv_latency_ms: float = 0.0
    airv_fps: float = 0.0
    airv_last_frame_seq: int = -1


def parse_args():
    parser = argparse.ArgumentParser(description="UDP loopback receiver for AD9361_test2")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="local IP to bind")
    parser.add_argument("--bind-port", type=int, default=DEFAULT_RECEIVER_PORT,
        help="local UDP port for loopback packets")
    parser.add_argument("--board-ip", default=DEFAULT_BOARD_IP, help="Zynq board IP")
    parser.add_argument("--board-port", type=int, default=DEFAULT_BOARD_PORT, help="Zynq UDP port")
    parser.add_argument("--no-register", action="store_true",
        help="listen only; do not send RXCFG registration to the board")
    parser.add_argument("--socket-buffer-bytes", type=int, default=DEFAULT_SOCKET_BUFFER_BYTES,
        help="host socket receive buffer size")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="output directory")
    parser.add_argument("--output-name", default="", help="output file name; extension is inferred if omitted")
    parser.add_argument("--expected-bytes", type=int, default=0,
        help="raw-mode expected contiguous bytes; AIR0 uses file_size from its header, so 0 is normal")
    parser.add_argument("--idle-finish-s", type=float, default=DEFAULT_IDLE_FINISH_S,
        help="finish after this many idle seconds when data remains incomplete")
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
    _instance_counter = 0

    def __init__(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        SparseFileAssembler._instance_counter += 1
        self.temp_path = output_dir / (
            f".rx_{os.getpid()}_{int(time.time() * 1000)}_"
            f"{SparseFileAssembler._instance_counter}.part"
        )
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
        self._add_range(offset, end)

    def _add_range(self, start: int, end: int):
        index = bisect.bisect_left(self.ranges, (start, end))
        if index > 0 and self.ranges[index - 1][1] >= start:
            index -= 1
            start = min(start, self.ranges[index][0])
            end = max(end, self.ranges[index][1])
            self.ranges.pop(index)

        while index < len(self.ranges) and self.ranges[index][0] <= end:
            start = min(start, self.ranges[index][0])
            end = max(end, self.ranges[index][1])
            self.ranges.pop(index)

        self.ranges.insert(index, (start, end))

    def coverage(self) -> Tuple[int, int]:
        contiguous = 0
        gaps = 0
        for start, end in self.ranges:
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

    def read_at(self, offset: int, length: int) -> bytes:
        self.fp.flush()
        self.fp.seek(offset)
        return self.fp.read(length)

    def crc32_prefix(self, byte_count: int) -> int:
        remaining = byte_count
        crc = 0
        self.fp.flush()
        self.fp.seek(0)
        while remaining > 0:
            chunk = self.fp.read(min(remaining, 1024 * 1024))
            if not chunk:
                break
            crc = binascii.crc32(chunk, crc)
            remaining -= len(chunk)
        return crc & 0xFFFFFFFF

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
        output_dir = Path(config.output_dir)
        self._raw_assembler = SparseFileAssembler(output_dir)
        self._file_assembler = SparseFileAssembler(output_dir)
        self._air_checked = False
        self._air_mode = False
        self._airv_mode = False
        self._air_parse_offset = 0
        self._airv_parse_offset = 0
        self._air_received_seqs = set()
        self._air_bad_payload_seqs = set()
        self._air_bad_meta_seqs = set()
        self._air_meta = None
        self._video = VideoStreamAssembler()

    def stop(self):
        self._stop_requested = True

    def _active_assembler(self):
        return self._file_assembler if self._air_mode else self._raw_assembler

    def _discard_unsaved(self):
        if not self._saved:
            self._raw_assembler.discard()
            self._file_assembler.discard()

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
        active = self._active_assembler()
        contiguous, gaps = active.coverage()
        stats.contiguous_bytes = contiguous
        stats.highest_end = active.highest_end
        stats.gap_count = gaps
        if self._airv_mode:
            self._refresh_airv_stats(stats)
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

    def _update_air_missing(self, stats: ReceiverStats):
        if stats.air_total_packets > 0:
            stats.air_missing_packets = max(
                stats.air_total_packets - len(self._air_received_seqs),
                0,
            )

    def _format_air_missing_ranges(self, stats: ReceiverStats, max_ranges: int = 16) -> str:
        if stats.air_total_packets <= 0 or stats.air_missing_packets <= 0:
            return ""
        return self._format_missing_seq_ranges(stats.air_total_packets, max_ranges=max_ranges)

    def _format_seq_ranges(self, seqs, max_ranges: int = 16) -> str:
        if not seqs:
            return ""
        ranges = []
        omitted_ranges = 0
        range_start = None
        previous_missing = None

        sorted_seqs = sorted(seqs)
        sentinel = None
        for seq in sorted_seqs + [sentinel]:
            if seq is not sentinel and (
                range_start is None or seq == previous_missing + 1
            ):
                if range_start is None:
                    range_start = seq
                previous_missing = seq
                continue

            if range_start is None:
                continue

            if len(ranges) < max_ranges:
                if range_start == previous_missing:
                    ranges.append(str(range_start))
                else:
                    ranges.append(f"{range_start}-{previous_missing}")
            else:
                omitted_ranges += 1

            range_start = None
            previous_missing = None

        if omitted_ranges != 0:
            ranges.append(f"...(+{omitted_ranges} ranges)")
        return ",".join(ranges)

    def _format_missing_seq_ranges(self, total_packets: int, max_ranges: int = 16) -> str:
        ranges = []
        omitted_ranges = 0
        range_start = None
        previous_missing = None

        for seq in range(total_packets + 1):
            is_missing = seq < total_packets and seq not in self._air_received_seqs
            if is_missing:
                if range_start is None:
                    range_start = seq
                previous_missing = seq
                continue

            if range_start is None:
                continue

            if len(ranges) < max_ranges:
                if range_start == previous_missing:
                    ranges.append(str(range_start))
                else:
                    ranges.append(f"{range_start}-{previous_missing}")
            else:
                omitted_ranges += 1

            range_start = None
            previous_missing = None

        if omitted_ranges != 0:
            ranges.append(f"...(+{omitted_ranges} ranges)")
        return ",".join(ranges)

    def _refresh_air_missing_ranges(self, stats: ReceiverStats):
        self._update_air_missing(stats)
        stats.air_missing_ranges = self._format_air_missing_ranges(stats)
        stats.air_bad_payload_ranges = self._format_seq_ranges(self._air_bad_payload_seqs)
        stats.air_bad_meta_ranges = self._format_seq_ranges(self._air_bad_meta_seqs)

    def _set_air_meta(self, header, stats: ReceiverStats):
        self._air_meta = (
            header.session_id,
            header.file_id,
            header.total_packets,
            header.file_size,
            header.file_crc32,
            header.chunk_bytes,
        )
        stats.air_session_id = header.session_id
        stats.air_file_id = header.file_id
        stats.air_total_packets = header.total_packets
        stats.air_file_size = header.file_size
        stats.air_file_crc32 = header.file_crc32
        stats.air_chunk_bytes = header.chunk_bytes

    def _header_meta_matches(self, header) -> bool:
        return self._air_meta == (
            header.session_id,
            header.file_id,
            header.total_packets,
            header.file_size,
            header.file_crc32,
            header.chunk_bytes,
        )

    def _reject_air_meta(self, header, stats: ReceiverStats):
        stats.air_bad_meta += 1
        self._air_bad_meta_seqs.add(header.packet_seq)
        self._update_air_missing(stats)

    def _validate_air_meta(self, header, stats: ReceiverStats) -> bool:
        if self._air_meta is None:
            self._set_air_meta(header, stats)
        elif not self._header_meta_matches(header):
            self._reject_air_meta(header, stats)
            return False

        is_last_seq = header.packet_seq == (header.total_packets - 1)
        has_last_flag = (header.flags & AIR_FLAG_LAST) != 0
        if (header.flags & AIR_FLAG_DATA) == 0:
            self._reject_air_meta(header, stats)
            return False
        if has_last_flag != is_last_seq:
            self._reject_air_meta(header, stats)
            return False

        if has_last_flag:
            stats.air_got_last = True
            stats.air_last_seq = header.packet_seq
        return True

    def _try_enable_air_mode(self, stats: ReceiverStats):
        if self._air_checked:
            return

        contiguous, _gaps = self._raw_assembler.coverage()
        if contiguous < 4:
            return

        first_word = struct.unpack("<I", self._raw_assembler.read_at(0, 4))[0]
        self._air_checked = True
        if first_word == AIR_MAGIC:
            self._air_mode = True
            stats.air_mode = True
            self._air_parse_offset = 0
        elif first_word == AIRV_MAGIC:
            self._airv_mode = True
            stats.airv_mode = True
            self._airv_parse_offset = 0

    def _refresh_airv_stats(self, stats: ReceiverStats):
        metrics = self._video.metrics()
        stats.airv_frames_rx = metrics["frame_rx"]
        stats.airv_frames_show = metrics["frame_show"]
        stats.airv_frames_drop = metrics["frame_drop"]
        stats.airv_frag_rx = metrics["frag_rx"]
        stats.airv_frag_missing = metrics["frag_missing"]
        stats.airv_bad_meta = metrics["bad_meta"]
        stats.airv_bad_frag_crc = metrics["bad_frag_crc"]
        stats.airv_bad_frame_crc = metrics["bad_frame_crc"]
        stats.airv_keyframe_rx = metrics["keyframe_rx"]
        stats.airv_waiting_keyframe = metrics["waiting_keyframe"]
        stats.airv_latency_ms = metrics["latency_ms"]
        stats.airv_fps = metrics["fps"]
        stats.airv_last_frame_seq = self._video.latest_frame_seq

    def _parse_air_stream(self, stats: ReceiverStats):
        contiguous, _gaps = self._raw_assembler.coverage()

        self._try_enable_air_mode(stats)
        if not self._air_mode:
            return

        while self._air_parse_offset + AIR_HEADER_BYTES <= contiguous:
            header_bytes = self._raw_assembler.read_at(self._air_parse_offset, AIR_HEADER_BYTES)
            if len(header_bytes) < AIR_HEADER_BYTES:
                return

            if struct.unpack("<I", header_bytes[:4])[0] != AIR_MAGIC:
                scan_len = min(contiguous - self._air_parse_offset, 4096)
                scan_data = self._raw_assembler.read_at(self._air_parse_offset, scan_len)
                next_magic = scan_data.find(struct.pack("<I", AIR_MAGIC), 1)
                if next_magic < 0:
                    self._air_parse_offset = max(contiguous - 3, self._air_parse_offset)
                    return
                stats.air_bad_header += 1
                self._air_parse_offset += next_magic
                continue

            try:
                header = parse_air_header(header_bytes)
            except ValueError:
                stats.air_bad_header += 1
                self._air_parse_offset += 1
                continue

            packet_len = header.header_len + header.payload_len
            if self._air_parse_offset + packet_len > contiguous:
                return

            payload = self._raw_assembler.read_at(
                self._air_parse_offset + header.header_len,
                header.payload_len,
            )
            if len(payload) != header.payload_len:
                return

            if not self._validate_air_meta(header, stats):
                self._air_parse_offset += packet_len
                continue

            if air_crc32(payload) != header.payload_crc32:
                stats.air_bad_payload_crc += 1
                self._air_bad_payload_seqs.add(header.packet_seq)
                self._air_parse_offset += packet_len
                self._update_air_missing(stats)
                continue

            if header.packet_seq in self._air_received_seqs:
                stats.air_duplicates += 1
            else:
                self._air_received_seqs.add(header.packet_seq)
                self._file_assembler.write(header.file_offset, payload)
                stats.air_packets += 1

            self._air_parse_offset += packet_len
            self._update_air_missing(stats)

    def _parse_airv_stream(self, stats: ReceiverStats, callback):
        contiguous, _gaps = self._raw_assembler.coverage()

        self._try_enable_air_mode(stats)
        if not self._airv_mode:
            return

        while self._airv_parse_offset + AIRV_HEADER_BYTES <= contiguous:
            header_bytes = self._raw_assembler.read_at(
                self._airv_parse_offset,
                AIRV_HEADER_BYTES,
            )
            if len(header_bytes) < AIRV_HEADER_BYTES:
                return

            if struct.unpack("<I", header_bytes[:4])[0] != AIRV_MAGIC:
                scan_len = min(contiguous - self._airv_parse_offset, 4096)
                scan_data = self._raw_assembler.read_at(self._airv_parse_offset, scan_len)
                next_magic = scan_data.find(struct.pack("<I", AIRV_MAGIC), 1)
                if next_magic < 0:
                    self._airv_parse_offset = max(contiguous - 3, self._airv_parse_offset)
                    return
                stats.airv_bad_header += 1
                self._airv_parse_offset += next_magic
                continue

            try:
                header = parse_airv_header(header_bytes)
            except ValueError:
                stats.airv_bad_header += 1
                self._airv_parse_offset += 1
                continue

            if self._airv_parse_offset + header.chunk_bytes > contiguous:
                return

            payload = self._raw_assembler.read_at(
                self._airv_parse_offset + header.header_len,
                header.fragment_len,
            )
            if len(payload) != header.fragment_len:
                return

            fragment_crc_ok = airv_crc32(payload) == header.fragment_crc32
            frames = self._video.process_fragment(header, payload, fragment_crc_ok)
            self._refresh_airv_stats(stats)
            for frame in frames:
                self._emit(callback, "video_frame", {
                    "frame_seq": frame.frame_seq,
                    "frame_type": frame.frame_type,
                    "bytes": len(frame.payload),
                    "bad_fragment_crc": frame.bad_fragment_crc,
                    "bad_frame_crc": frame.bad_frame_crc,
                    "latency_ms": frame.latency_ms,
                    "stats": stats,
                })

            self._airv_parse_offset += header.chunk_bytes

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
            self._raw_assembler.write(absolute_offset, payload)
            if absolute_offset + payload_len > stats.highest_end:
                stats.highest_end = absolute_offset + payload_len
            self._parse_air_stream(stats)
            self._parse_airv_stream(stats, callback)

        self._refresh_rates(stats)
        if status != "OK":
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

    def _mark_incomplete(self, stats: ReceiverStats, callback, reason: str):
        if stats.air_mode:
            self._refresh_air_missing_ranges(stats)
        stats.incomplete_reason = reason
        self._emit(callback, "incomplete", {"reason": reason, "stats": stats})

    def _save_if_ready(self, stats: ReceiverStats, callback, force: bool = False) -> bool:
        if self._saved:
            return True

        if self._airv_mode:
            if force and not stats.incomplete_reason:
                self._video.flush_missing()
                self._refresh_airv_stats(stats)
                stats.incomplete_reason = "AIRV stream idle finish; realtime mode does not save an exact file"
                self._emit(callback, "video_done", {"stats": stats})
            return False

        active = self._active_assembler()
        contiguous, gaps = active.coverage()
        stats.contiguous_bytes = contiguous
        stats.highest_end = active.highest_end
        stats.gap_count = gaps

        if self._air_mode:
            expected_bytes = stats.air_file_size or self.config.expected_bytes
            if expected_bytes <= 0:
                return False
            if contiguous < expected_bytes:
                if force:
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"AIR0 expected {expected_bytes} contiguous bytes, got {contiguous}",
                    )
                return False
            if gaps != 0:
                if force:
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"AIR0 received data has gaps: contiguous={contiguous}, highest={active.highest_end}, gaps={gaps}",
                    )
                return False
            if stats.air_missing_packets != 0:
                if force:
                    self._refresh_air_missing_ranges(stats)
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"AIR0 missing {stats.air_missing_packets} packets of {stats.air_total_packets}",
                    )
                return False
            if not stats.air_got_last:
                if force:
                    self._mark_incomplete(stats, callback, "AIR0 LAST packet was not received")
                return False
            if stats.air_bad_meta != 0:
                if force:
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"AIR0 metadata mismatch on {stats.air_bad_meta} packets",
                    )
                return False
            if stats.air_bad_payload_crc != 0:
                if force:
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"AIR0 payload CRC failed on {stats.air_bad_payload_crc} packets",
                    )
                return False
            actual_crc = active.crc32_prefix(expected_bytes)
            stats.air_file_crc_ok = (actual_crc == stats.air_file_crc32)
            if not stats.air_file_crc_ok:
                if force:
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"AIR0 file CRC mismatch rx=0x{actual_crc:08X} expected=0x{stats.air_file_crc32:08X}",
                    )
                return False
            byte_count = expected_bytes
        elif self.config.expected_bytes > 0:
            if contiguous < self.config.expected_bytes:
                if force:
                    self._mark_incomplete(
                        stats,
                        callback,
                        f"expected {self.config.expected_bytes} contiguous bytes, got {contiguous}",
                    )
                return False
            byte_count = self.config.expected_bytes
        else:
            if not force:
                return False
            if contiguous <= 0:
                return False
            if gaps != 0 or contiguous < active.highest_end:
                self._mark_incomplete(
                    stats,
                    callback,
                    f"received data has gaps: contiguous={contiguous}, highest={active.highest_end}, gaps={gaps}",
                )
                return False

            byte_count = contiguous
        if byte_count <= 0:
            return False

        output_dir = Path(self.config.output_dir)
        target_path = active.finalize(output_dir, self.config.output_name, byte_count)
        stats.saved_path = str(target_path)
        stats.finished_at = time.time()
        self._saved = True
        if self._air_mode:
            self._raw_assembler.discard()
        else:
            self._file_assembler.discard()
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
                        if (last_payload_time > 0.0 and self.config.idle_finish_s > 0.0 and
                            (now - last_payload_time) >= self.config.idle_finish_s):
                            if self._save_if_ready(stats, callback, force=True):
                                if self.config.stop_after_save:
                                    break
                            elif stats.incomplete_reason:
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
            self._discard_unsaved()
            raise

        if stats.air_mode:
            self._refresh_air_missing_ranges(stats)
        if stats.airv_mode:
            self._refresh_airv_stats(stats)
        self._discard_unsaved()
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
                f"output={payload['output_dir']} raw_expected={payload['expected_bytes']}"
            )
        elif event_name == "registered":
            print(
                f"registered board={payload['board_ip']}:{payload['board_port']} "
                f"receiver_port={payload['bind_port']}"
            )
        elif event_name == "progress":
            stats = payload["stats"]
            if stats.airv_mode:
                print(
                    f"VIDEO frame_rx={stats.airv_frames_rx} frame_show={stats.airv_frames_show} "
                    f"frame_drop={stats.airv_frames_drop} frag_rx={stats.airv_frag_rx} "
                    f"frag_missing={stats.airv_frag_missing} bad_hdr={stats.airv_bad_header} "
                    f"bad_meta={stats.airv_bad_meta} bad_frag_crc={stats.airv_bad_frag_crc} "
                    f"bad_frame_crc={stats.airv_bad_frame_crc} keyframe_rx={stats.airv_keyframe_rx} "
                    f"waiting_keyframe={stats.airv_waiting_keyframe} fps={stats.airv_fps:.1f} "
                    f"latency_ms={stats.airv_latency_ms:.1f} pkt={stats.packets} "
                    f"rate={stats.rate_kib_s:.2f}KiB/s"
                )
            else:
                print(
                    f"PROGRESS rx={stats.contiguous_bytes} high={stats.highest_end} "
                    f"pkt={stats.packets} blk={stats.blocks} rate={stats.rate_kib_s:.2f}KiB/s "
                    f"crc={stats.crc_errors} len={stats.length_errors} gaps={stats.gap_count} "
                    f"air={int(stats.air_mode)} air_rx={stats.air_packets}/{stats.air_total_packets} "
                    f"pending_air={stats.air_missing_packets} bad_hdr={stats.air_bad_header} "
                    f"bad_payload={stats.air_bad_payload_crc} bad_meta={stats.air_bad_meta} "
                    f"dup={stats.air_duplicates} got_last={int(stats.air_got_last)}"
                )
        elif event_name == "packet" and payload["status"] != "OK":
            print(
                f"PACKET {payload['status']} block={payload['block_id']} "
                f"off={payload['stream_offset']}+{payload['chunk_offset']} len={payload['payload_len']}"
            )
        elif event_name == "saved":
            print(f"SAVED {payload['path']}")
        elif event_name == "video_frame":
            if payload["bad_fragment_crc"] or payload["bad_frame_crc"]:
                print(
                    f"VIDEO_FRAME frame={payload['frame_seq']} bytes={payload['bytes']} "
                    f"bad_frag_crc={int(payload['bad_fragment_crc'])} "
                    f"bad_frame_crc={int(payload['bad_frame_crc'])} "
                    f"latency_ms={payload['latency_ms']:.1f}"
                )
        elif event_name == "video_done":
            stats = payload["stats"]
            print(
                f"VIDEO_DONE frame_rx={stats.airv_frames_rx} frame_show={stats.airv_frames_show} "
                f"frame_drop={stats.airv_frames_drop} frag_rx={stats.airv_frag_rx} "
                f"frag_missing={stats.airv_frag_missing} bad_hdr={stats.airv_bad_header} "
                f"bad_meta={stats.airv_bad_meta} bad_frag_crc={stats.airv_bad_frag_crc} "
                f"bad_frame_crc={stats.airv_bad_frame_crc} keyframe_rx={stats.airv_keyframe_rx} "
                f"fps={stats.airv_fps:.1f} latency_ms={stats.airv_latency_ms:.1f}"
            )
        elif event_name == "incomplete":
            stats = payload["stats"]
            missing_ranges = f" missing_seq={stats.air_missing_ranges}" if stats.air_missing_ranges else ""
            bad_payload_ranges = (
                f" bad_payload_seq={stats.air_bad_payload_ranges}"
                if stats.air_bad_payload_ranges else ""
            )
            bad_meta_ranges = (
                f" bad_meta_seq={stats.air_bad_meta_ranges}"
                if stats.air_bad_meta_ranges else ""
            )
            print(
                f"INCOMPLETE {payload['reason']} rx={stats.contiguous_bytes} "
                f"high={stats.highest_end} gaps={stats.gap_count} "
                f"air={int(stats.air_mode)} miss={stats.air_missing_packets} "
                f"file_size={stats.air_file_size} total_packets={stats.air_total_packets} "
                f"file_id=0x{stats.air_file_id:08X} file_crc=0x{stats.air_file_crc32:08X} "
                f"got_last={int(stats.air_got_last)} bad_meta={stats.air_bad_meta} "
                f"bad_payload={stats.air_bad_payload_crc}{missing_ranges}"
                f"{bad_payload_ranges}{bad_meta_ranges}"
            )
        elif event_name == "done":
            stats = payload["stats"]
            if stats.airv_mode:
                print(
                    f"DONE VIDEO frame_rx={stats.airv_frames_rx} frame_show={stats.airv_frames_show} "
                    f"frame_drop={stats.airv_frames_drop} frag_rx={stats.airv_frag_rx} "
                    f"frag_missing={stats.airv_frag_missing} bad_hdr={stats.airv_bad_header} "
                    f"bad_meta={stats.airv_bad_meta} bad_frag_crc={stats.airv_bad_frag_crc} "
                    f"bad_frame_crc={stats.airv_bad_frame_crc} keyframe_rx={stats.airv_keyframe_rx} "
                    f"waiting_keyframe={stats.airv_waiting_keyframe} fps={stats.airv_fps:.1f} "
                    f"latency_ms={stats.airv_latency_ms:.1f} reason={stats.incomplete_reason}"
                )
                return
            missing_ranges = f" missing_seq={stats.air_missing_ranges}" if stats.air_missing_ranges else ""
            bad_payload_ranges = (
                f" bad_payload_seq={stats.air_bad_payload_ranges}"
                if stats.air_bad_payload_ranges else ""
            )
            bad_meta_ranges = (
                f" bad_meta_seq={stats.air_bad_meta_ranges}"
                if stats.air_bad_meta_ranges else ""
            )
            print(
                f"DONE rx={stats.contiguous_bytes} high={stats.highest_end} "
                f"pkt={stats.packets} blk={stats.blocks} gaps={stats.gap_count} "
                f"air={int(stats.air_mode)} air_rx={stats.air_packets}/{stats.air_total_packets} "
                f"miss={stats.air_missing_packets} bad_hdr={stats.air_bad_header} "
                f"bad_payload={stats.air_bad_payload_crc} bad_meta={stats.air_bad_meta} "
                f"dup={stats.air_duplicates} file_crc={int(stats.air_file_crc_ok)} "
                f"file_size={stats.air_file_size} total_packets={stats.air_total_packets} "
                f"file_id=0x{stats.air_file_id:08X} file_crc32=0x{stats.air_file_crc32:08X} "
                f"session={stats.air_session_id} chunk={stats.air_chunk_bytes} "
                f"got_last={int(stats.air_got_last)} last_seq={stats.air_last_seq} "
                f"saved={stats.saved_path} reason={stats.incomplete_reason}"
                f"{missing_ranges}{bad_payload_ranges}{bad_meta_ranges}"
            )

    receiver.run(callback=callback)
    return 0
