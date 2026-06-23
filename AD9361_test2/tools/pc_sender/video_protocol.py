#!/usr/bin/env python3
import binascii
import struct
import time
from dataclasses import dataclass
from typing import Iterable, List


AIRV_MAGIC = 0x56524941
AIRV_VERSION = 1
AIRV_HEADER_BYTES = 64

AIRV_FLAG_DATA = 0x0001
AIRV_FLAG_KEYFRAME = 0x0002
AIRV_FLAG_LAST_FRAGMENT = 0x0004
AIRV_FLAG_CONFIG = 0x0008

AIRV_FRAME_UNKNOWN = 0
AIRV_FRAME_KEY = 1
AIRV_FRAME_DELTA = 2
AIRV_FRAME_CONFIG = 3

# v1 keeps the header at 64 bytes. tx_timestamp_us is carried as the low
# 32 bits; pts_us remains 64-bit for playback ordering.
AIRV_HEADER_FORMAT = "<IBBHIIIHHBBIIIHHIIQIH"
AIRV_HEADER_SIZE = struct.calcsize(AIRV_HEADER_FORMAT)
if AIRV_HEADER_SIZE != AIRV_HEADER_BYTES:
    raise RuntimeError("AIRV header format size mismatch")


@dataclass
class AirvHeader:
    magic: int
    version: int
    header_len: int
    flags: int
    session_id: int
    stream_id: int
    frame_seq: int
    frag_index: int
    frag_count: int
    frame_type: int
    reserved0: int
    header_crc32: int
    frame_size: int
    fragment_offset: int
    fragment_len: int
    chunk_bytes: int
    frame_crc32: int
    fragment_crc32: int
    pts_us: int
    tx_timestamp_us_lo: int
    reserved1: int

    @property
    def tx_timestamp_us(self) -> int:
        return self.tx_timestamp_us_lo


@dataclass
class AirvPacket:
    frame_seq: int
    frag_index: int
    payload: bytes
    frame_type: int
    fragment_len: int


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def now_us() -> int:
    return int(time.time() * 1000000)


def make_stream_id(file_size: int, file_crc32: int, session_id: int) -> int:
    return (file_crc32 ^ ((file_size & 0xFFFFFFFF) << 3) ^ (session_id << 1)) & 0xFFFFFFFF


def _pack_header(header: AirvHeader, header_crc32: int) -> bytes:
    return struct.pack(
        AIRV_HEADER_FORMAT,
        header.magic,
        header.version,
        header.header_len,
        header.flags,
        header.session_id,
        header.stream_id,
        header.frame_seq,
        header.frag_index,
        header.frag_count,
        header.frame_type,
        header.reserved0,
        header_crc32,
        header.frame_size,
        header.fragment_offset,
        header.fragment_len,
        header.chunk_bytes,
        header.frame_crc32,
        header.fragment_crc32,
        header.pts_us,
        header.tx_timestamp_us_lo,
        header.reserved1,
    )


def build_airv_packet(
    fragment: bytes,
    *,
    session_id: int,
    stream_id: int,
    frame_seq: int,
    frag_index: int,
    frag_count: int,
    frame_type: int,
    frame_size: int,
    fragment_offset: int,
    chunk_bytes: int,
    frame_crc32: int,
    pts_us: int,
) -> bytes:
    if chunk_bytes <= AIRV_HEADER_BYTES:
        raise ValueError("AIRV chunk_bytes must be greater than the fixed header")
    if len(fragment) > (chunk_bytes - AIRV_HEADER_BYTES):
        raise ValueError("AIRV fragment exceeds chunk capacity")
    if frag_count <= 0:
        raise ValueError("AIRV frag_count must be positive")
    if frag_index >= frag_count:
        raise ValueError("AIRV frag_index out of range")
    if fragment_offset + len(fragment) > frame_size:
        raise ValueError("AIRV fragment exceeds frame_size")

    flags = AIRV_FLAG_DATA
    if frame_type == AIRV_FRAME_KEY:
        flags |= AIRV_FLAG_KEYFRAME
    if frame_type == AIRV_FRAME_CONFIG:
        flags |= AIRV_FLAG_CONFIG
    if frag_index == (frag_count - 1):
        flags |= AIRV_FLAG_LAST_FRAGMENT

    header = AirvHeader(
        magic=AIRV_MAGIC,
        version=AIRV_VERSION,
        header_len=AIRV_HEADER_BYTES,
        flags=flags,
        session_id=session_id & 0xFFFFFFFF,
        stream_id=stream_id & 0xFFFFFFFF,
        frame_seq=frame_seq & 0xFFFFFFFF,
        frag_index=frag_index,
        frag_count=frag_count,
        frame_type=frame_type,
        reserved0=0,
        header_crc32=0,
        frame_size=frame_size,
        fragment_offset=fragment_offset,
        fragment_len=len(fragment),
        chunk_bytes=chunk_bytes,
        frame_crc32=frame_crc32 & 0xFFFFFFFF,
        fragment_crc32=crc32(fragment),
        pts_us=pts_us & 0xFFFFFFFFFFFFFFFF,
        tx_timestamp_us_lo=now_us() & 0xFFFFFFFF,
        reserved1=0,
    )
    raw_without_crc = _pack_header(header, 0)
    header.header_crc32 = crc32(raw_without_crc)
    return _pack_header(header, header.header_crc32) + fragment


def parse_airv_header(data: bytes) -> AirvHeader:
    if len(data) < AIRV_HEADER_BYTES:
        raise ValueError("short AIRV header")

    header = AirvHeader(*struct.unpack(AIRV_HEADER_FORMAT, data[:AIRV_HEADER_BYTES]))
    if header.magic != AIRV_MAGIC:
        raise ValueError("bad AIRV magic")
    if header.version != AIRV_VERSION:
        raise ValueError("unsupported AIRV version")
    if header.header_len != AIRV_HEADER_BYTES:
        raise ValueError("bad AIRV header length")

    raw_without_crc = bytearray(data[:AIRV_HEADER_BYTES])
    struct.pack_into("<I", raw_without_crc, 26, 0)
    if crc32(bytes(raw_without_crc)) != header.header_crc32:
        raise ValueError("bad AIRV header CRC")

    if (header.flags & AIRV_FLAG_DATA) == 0:
        raise ValueError("AIRV DATA flag is not set")
    if header.frag_count <= 0:
        raise ValueError("AIRV frag_count is zero")
    if header.frag_index >= header.frag_count:
        raise ValueError("AIRV frag_index out of range")
    if header.fragment_len > (header.chunk_bytes - header.header_len):
        raise ValueError("AIRV fragment length exceeds chunk capacity")
    if header.fragment_offset + header.fragment_len > header.frame_size:
        raise ValueError("AIRV fragment exceeds frame_size")
    has_last = (header.flags & AIRV_FLAG_LAST_FRAGMENT) != 0
    if has_last != (header.frag_index == header.frag_count - 1):
        raise ValueError("AIRV LAST_FRAGMENT flag mismatch")
    return header


def _find_start_codes(data: bytes) -> List[int]:
    offsets = []
    index = 0
    while index < len(data) - 3:
        if data[index:index + 3] == b"\x00\x00\x01":
            offsets.append(index)
            index += 3
            continue
        if data[index:index + 4] == b"\x00\x00\x00\x01":
            offsets.append(index)
            index += 4
            continue
        index += 1
    return offsets


def _nal_type(nal: bytes) -> int:
    offset = 4 if nal.startswith(b"\x00\x00\x00\x01") else 3
    if len(nal) <= offset:
        return 0
    return nal[offset] & 0x1F


def _nal_payload(nal: bytes) -> bytes:
    offset = 4 if nal.startswith(b"\x00\x00\x00\x01") else 3
    if len(nal) <= offset + 1:
        return b""
    return nal[offset + 1:]


def _ebsp_to_rbsp(data: bytes) -> bytes:
    out = bytearray()
    zero_count = 0
    for byte in data:
        if zero_count >= 2 and byte == 0x03:
            zero_count = 0
            continue
        out.append(byte)
        if byte == 0:
            zero_count += 1
        else:
            zero_count = 0
    return bytes(out)


class _BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.bit_offset = 0

    def read_bit(self) -> int:
        if self.bit_offset >= len(self.data) * 8:
            raise ValueError("end of bitstream")
        byte = self.data[self.bit_offset // 8]
        bit = (byte >> (7 - (self.bit_offset % 8))) & 1
        self.bit_offset += 1
        return bit

    def read_ue(self) -> int:
        leading_zero_bits = 0
        while self.read_bit() == 0:
            leading_zero_bits += 1
            if leading_zero_bits > 31:
                raise ValueError("ue(v) too large")
        value = (1 << leading_zero_bits) - 1
        for bit_index in range(leading_zero_bits):
            value += self.read_bit() << (leading_zero_bits - 1 - bit_index)
        return value


def _first_mb_in_slice(nal: bytes):
    nal_type = _nal_type(nal)
    if not (1 <= nal_type <= 5):
        return None
    rbsp = _ebsp_to_rbsp(_nal_payload(nal))
    if not rbsp:
        return None
    try:
        return _BitReader(rbsp).read_ue()
    except ValueError:
        return None


def _iter_frames_by_aud(nals: List[bytes]) -> Iterable[bytes]:
    prefix = []
    current = []
    has_vcl = False

    for nal in nals:
        nal_type = _nal_type(nal)
        if nal_type == 9:
            if current and has_vcl:
                yield b"".join(current)
                current = []
                has_vcl = False
            current.extend(prefix)
            prefix = []
            current.append(nal)
            continue

        is_vcl = 1 <= nal_type <= 5
        if not current and not is_vcl:
            prefix.append(nal)
            continue

        current.append(nal)
        if is_vcl:
            has_vcl = True

    if current:
        yield b"".join(current)


def iter_h264_annexb_frames(data: bytes) -> Iterable[bytes]:
    starts = _find_start_codes(data)
    if not starts:
        if data:
            yield data
        return

    nals = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(data)
        nals.append(data[start:end])

    if any(_nal_type(nal) == 9 for nal in nals):
        yield from _iter_frames_by_aud(nals)
        return

    frame_parts = []
    has_vcl = False
    for nal in nals:
        nal_type = _nal_type(nal)
        is_vcl = 1 <= nal_type <= 5
        first_mb = _first_mb_in_slice(nal) if is_vcl else None
        if is_vcl and has_vcl and (first_mb == 0 or first_mb is None):
            yield b"".join(frame_parts)
            frame_parts = []
            has_vcl = False
        frame_parts.append(nal)
        if is_vcl:
            has_vcl = True

    if frame_parts:
        yield b"".join(frame_parts)


def frame_type_for_h264_annexb(frame: bytes) -> int:
    for start in _find_start_codes(frame):
        offset = 4 if frame[start:start + 4] == b"\x00\x00\x00\x01" else 3
        if start + offset >= len(frame):
            continue
        nal_type = frame[start + offset] & 0x1F
        if nal_type == 5:
            return AIRV_FRAME_KEY
        if 1 <= nal_type <= 5:
            return AIRV_FRAME_DELTA
    return AIRV_FRAME_UNKNOWN


def build_airv_stream(
    video_bytes: bytes,
    *,
    chunk_bytes: int,
    session_id: int,
    stream_id: int,
    frame_interval_us: int = 33333,
) -> bytes:
    payload_capacity = chunk_bytes - AIRV_HEADER_BYTES
    if payload_capacity <= 0:
        raise ValueError("AIRV chunk_bytes must leave room for frame payload")

    packets = []
    for frame_seq, frame in enumerate(iter_h264_annexb_frames(video_bytes)):
        frame_crc = crc32(frame)
        frame_type = frame_type_for_h264_annexb(frame)
        frag_count = max((len(frame) + payload_capacity - 1) // payload_capacity, 1)
        pts_us = frame_seq * frame_interval_us
        for frag_index in range(frag_count):
            offset = frag_index * payload_capacity
            fragment = frame[offset:offset + payload_capacity]
            packet = build_airv_packet(
                fragment,
                session_id=session_id,
                stream_id=stream_id,
                frame_seq=frame_seq,
                frag_index=frag_index,
                frag_count=frag_count,
                frame_type=frame_type,
                frame_size=len(frame),
                fragment_offset=offset,
                chunk_bytes=chunk_bytes,
                frame_crc32=frame_crc,
                pts_us=pts_us,
            )
            packets.append(packet.ljust(chunk_bytes, b"\x00"))
    return b"".join(packets)
