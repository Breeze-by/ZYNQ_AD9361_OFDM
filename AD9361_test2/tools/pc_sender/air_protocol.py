#!/usr/bin/env python3
import binascii
import struct
import time
from dataclasses import dataclass


AIR_MAGIC = 0x30524941
AIR_VERSION = 1
AIR_HEADER_BYTES = 64
AIR_FLAG_DATA = 0x0001
AIR_FLAG_LAST = 0x0004
AIR_HEADER_FORMAT = "<IBBHIIIIQHHQIIQI"
AIR_HEADER_SIZE = struct.calcsize(AIR_HEADER_FORMAT)
if AIR_HEADER_SIZE != AIR_HEADER_BYTES:
    raise RuntimeError("AIR header format size mismatch")


@dataclass
class AirHeader:
    magic: int
    version: int
    header_len: int
    flags: int
    session_id: int
    file_id: int
    packet_seq: int
    total_packets: int
    file_offset: int
    payload_len: int
    chunk_bytes: int
    file_size: int
    file_crc32: int
    payload_crc32: int
    tx_timestamp_us: int
    header_crc32: int


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def make_file_id(file_size: int, file_crc32: int, session_id: int) -> int:
    return (file_crc32 ^ ((file_size & 0xFFFFFFFF) << 1) ^ session_id) & 0xFFFFFFFF


def now_us() -> int:
    return int(time.time() * 1000000) & 0xFFFFFFFFFFFFFFFF


def _pack_header(header: AirHeader, header_crc32: int) -> bytes:
    return struct.pack(
        AIR_HEADER_FORMAT,
        header.magic,
        header.version,
        header.header_len,
        header.flags,
        header.session_id,
        header.file_id,
        header.packet_seq,
        header.total_packets,
        header.file_offset,
        header.payload_len,
        header.chunk_bytes,
        header.file_size,
        header.file_crc32,
        header.payload_crc32,
        header.tx_timestamp_us,
        header_crc32,
    )


def build_air_packet(
    payload: bytes,
    packet_seq: int,
    total_packets: int,
    file_offset: int,
    file_size: int,
    chunk_bytes: int,
    session_id: int,
    file_crc32: int,
    file_id: int,
) -> bytes:
    if chunk_bytes < AIR_HEADER_BYTES:
        raise ValueError("AIR chunk_bytes must fit the fixed header")
    if len(payload) > (chunk_bytes - AIR_HEADER_BYTES):
        raise ValueError("AIR payload exceeds chunk capacity")

    flags = AIR_FLAG_DATA
    if total_packets > 0 and packet_seq == (total_packets - 1):
        flags |= AIR_FLAG_LAST

    header = AirHeader(
        magic=AIR_MAGIC,
        version=AIR_VERSION,
        header_len=AIR_HEADER_BYTES,
        flags=flags,
        session_id=session_id & 0xFFFFFFFF,
        file_id=file_id & 0xFFFFFFFF,
        packet_seq=packet_seq & 0xFFFFFFFF,
        total_packets=total_packets & 0xFFFFFFFF,
        file_offset=file_offset & 0xFFFFFFFFFFFFFFFF,
        payload_len=len(payload),
        chunk_bytes=chunk_bytes,
        file_size=file_size & 0xFFFFFFFFFFFFFFFF,
        file_crc32=file_crc32 & 0xFFFFFFFF,
        payload_crc32=crc32(payload),
        tx_timestamp_us=now_us(),
        header_crc32=0,
    )
    raw_without_crc = _pack_header(header, 0)
    header.header_crc32 = crc32(raw_without_crc)
    return _pack_header(header, header.header_crc32) + payload


def parse_air_header(data: bytes) -> AirHeader:
    if len(data) < AIR_HEADER_BYTES:
        raise ValueError("short AIR header")

    fields = struct.unpack(AIR_HEADER_FORMAT, data[:AIR_HEADER_BYTES])
    header = AirHeader(*fields)
    if header.magic != AIR_MAGIC:
        raise ValueError("bad AIR magic")
    if header.version != AIR_VERSION:
        raise ValueError("unsupported AIR version")
    if header.header_len != AIR_HEADER_BYTES:
        raise ValueError("bad AIR header length")

    raw_without_crc = bytearray(data[:AIR_HEADER_BYTES])
    struct.pack_into("<I", raw_without_crc, AIR_HEADER_BYTES - 4, 0)
    if crc32(bytes(raw_without_crc)) != header.header_crc32:
        raise ValueError("bad AIR header CRC")

    if header.payload_len > (header.chunk_bytes - header.header_len):
        raise ValueError("AIR payload length exceeds chunk capacity")
    if header.total_packets == 0:
        raise ValueError("AIR total_packets is zero")
    if header.packet_seq >= header.total_packets:
        raise ValueError("AIR packet_seq out of range")

    return header
