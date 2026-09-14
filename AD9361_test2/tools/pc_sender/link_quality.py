"""Receiver-side measurements. Never infer BER/SNR from a CRC failure count.

Loss is the provisional missing fraction in [0, highest AIR packet sequence].
It includes all failures before this receiver, is corrected by late packets,
and cannot detect an unobserved trailing loss. BER is post-FEC business data
compared with an explicit source file, excluding headers, padding and losses.
The current board protocol does NOT supply payload SNR telemetry.
"""
import binascii
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from air_protocol import AIR_MAGIC, AIR_FLAG_DATA, parse_air_header
from video_protocol import AIRV_MAGIC, iter_h264_annexb_frames, parse_airv_header


def crc32(data):
    return binascii.crc32(data) & 0xFFFFFFFF


@dataclass(frozen=True)
class QualitySnapshot:
    timestamp: float = 0.0
    epoch: int = 0
    received_packets: int = 0
    expected_so_far: int = 0
    missing_packets: int = 0
    loss_pct: Optional[float] = None
    ber_pct: Optional[float] = None
    ber_total_pct: Optional[float] = None
    compared_bits: int = 0
    error_bits: int = 0
    reference_skips: int = 0
    reference_status: str = "No reference file"
    ber_skip_bytes: int = 0
    snr_db: Optional[float] = None
    snr_status: str = "N/A: board has no payload I/Q / noise telemetry"


class PayloadReference:
    def __init__(self, path, mode):
        if mode not in ("airv", "air0"):
            raise ValueError("BER reference mode must be airv or air0")
        self.mode = mode
        self.data = Path(path).read_bytes()
        if not self.data:
            raise ValueError("BER reference file is empty")
        self.file_crc = crc32(self.data)
        self.frames = []
        if mode == "airv":
            if b"\x00\x00\x01" not in self.data:
                raise ValueError("AIRV BER needs the sender's exact H.264 Annex-B file, not MP4")
            # Use exactly the sender's frame splitter. Prepare BEFORE RXCFG,
            # in the worker, not while UDP traffic is being received.
            self.frames = [(frame, crc32(frame)) for frame in iter_h264_annexb_frames(self.data)]

    def fragment(self, mode, header):
        if mode != self.mode:
            raise ValueError("Reference mode differs from received protocol")
        if mode == "airv":
            if header.frame_seq >= len(self.frames):
                raise ValueError("Reference has no matching video frame")
            frame, frame_crc = self.frames[header.frame_seq]
            if len(frame) != header.frame_size or frame_crc != header.frame_crc32:
                raise ValueError("Reference video frame size/CRC mismatch")
            expected = frame[header.fragment_offset:header.fragment_offset + header.fragment_len]
            if len(expected) != header.fragment_len or crc32(expected) != header.fragment_crc32:
                raise ValueError("Reference fragment offset/CRC mismatch")
        else:
            if len(self.data) != header.file_size or self.file_crc != header.file_crc32:
                raise ValueError("Reference source file size/CRC mismatch")
            expected = self.data[header.file_offset:header.file_offset + header.payload_len]
            if len(expected) != header.payload_len or crc32(expected) != header.payload_crc32:
                raise ValueError("Reference payload offset/CRC mismatch")
        return expected


class LinkQualityTracker:
    WINDOW_S = 1.0

    def __init__(self, reference=None, skip_bytes=0):
        if skip_bytes < 0:
            raise ValueError("BER skip bytes must not be negative")
        self.reference = reference
        self.skip_bytes = skip_bytes
        self._stream = None
        self._retired = set()
        self._epoch = 0
        self._seen = set()
        self._highest = -1
        self._samples = deque()
        self._bits = 0
        self._errors = 0
        self._reference_skips = 0
        self._reference_status = "Waiting for matching packets" if reference else "No reference file"

    def _select_stream(self, stream):
        if stream == self._stream:
            return True
        if stream in self._retired:
            return False
        if self._stream is not None:
            self._retired.add(self._stream)
        self._stream = stream
        self._epoch += 1
        self._seen.clear()
        self._samples.clear()
        self._highest = -1
        self._bits = self._errors = self._reference_skips = 0
        self._reference_status = "Waiting for matching packets" if self.reference else "No reference file"
        return True

    def observe_wire(self, wire, stream_offset, now=None):
        """Observe a complete DMA block only after its UDP CRC/length passed.

        Independent of video/file assembly: a missing earlier block must not
        suppress measurements for later blocks. Bad business CRC is accepted.
        """
        if now is None:
            now = time.monotonic()
        cursor = 0
        while cursor + 64 <= len(wire):
            chunk = wire[cursor:]
            magic = int.from_bytes(chunk[:4], "little")
            try:
                if magic == AIRV_MAGIC:
                    header = parse_airv_header(chunk[:64])
                    mode = "airv"
                    stream = (mode, header.session_id, header.stream_id, header.chunk_bytes)
                    length = header.fragment_len
                elif magic == AIR_MAGIC:
                    header = parse_air_header(chunk[:64])
                    if not (header.flags & AIR_FLAG_DATA) or not (0 <= header.packet_seq < header.total_packets):
                        return
                    mode = "air0"
                    stream = (mode, header.session_id, header.file_id, header.chunk_bytes)
                    length = header.payload_len
                else:
                    return
            except ValueError:
                return
            if header.chunk_bytes <= 64 or length < 0:
                return
            if stream_offset + cursor != header.packet_seq * header.chunk_bytes:
                return
            if 64 + length > len(chunk):
                return
            if not self._select_stream(stream):
                return
            if header.packet_seq not in self._seen:
                self._seen.add(header.packet_seq)
                self._highest = max(self._highest, header.packet_seq)
                self._compare(mode, header, chunk[64:64 + length], now)
            cursor += header.chunk_bytes

    def _compare(self, mode, header, payload, now):
        if self.reference is None:
            return
        try:
            expected = self.reference.fragment(mode, header)
        except ValueError as exc:
            self._reference_skips += 1
            self._reference_status = str(exc)
            return
        self._reference_status = "Matched source (post-FEC)"
        actual = payload[self.skip_bytes:]
        expected = expected[self.skip_bytes:]
        bits = len(actual) * 8
        if not bits:
            return
        # Integer XOR + popcount avoids Python's per-bit/per-byte loop at the
        # normal 400 KiB/s data rate. int.bit_count requires Python >= 3.10.
        difference = int.from_bytes(actual, "little") ^ int.from_bytes(expected, "little")
        errors = difference.bit_count() if hasattr(int, "bit_count") else bin(difference).count("1")
        self._bits += bits
        self._errors += errors
        self._samples.append((now, bits, errors))
        self._expire(now)

    def _expire(self, now):
        while self._samples and self._samples[0][0] <= now - self.WINDOW_S:
            self._samples.popleft()

    def snapshot(self, now=None):
        if now is None:
            now = time.monotonic()
        self._expire(now)
        expected = self._highest + 1
        received = len(self._seen)
        missing = expected - received
        bits = sum(sample[1] for sample in self._samples)
        errors = sum(sample[2] for sample in self._samples)
        matched = self._reference_status == "Matched source (post-FEC)"
        return QualitySnapshot(
            timestamp=now, epoch=self._epoch, received_packets=received,
            expected_so_far=expected, missing_packets=missing,
            loss_pct=100.0 * missing / expected if expected else None,
            ber_pct=100.0 * errors / bits if bits and matched else None,
            ber_total_pct=100.0 * self._errors / self._bits if self._bits else None,
            compared_bits=self._bits, error_bits=self._errors,
            reference_skips=self._reference_skips, reference_status=self._reference_status,
            ber_skip_bytes=self.skip_bytes,
        )
