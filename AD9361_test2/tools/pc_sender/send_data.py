#!/usr/bin/env python3
import argparse
import binascii
import os
import socket
import struct
import sys
import time


DATA_MAGIC = 0x4E455430
ACK_MAGIC = 0x41434B30

ACK_STATUS_OK = 0
ACK_STATUS_BAD_MAGIC = 1
ACK_STATUS_BAD_LENGTH = 2
ACK_STATUS_BAD_CHECKSUM = 3
ACK_STATUS_BUSY = 4
ACK_STATUS_DMA_ERROR = 5

DATA_HEADER_FORMAT = "<IIHHI"
ACK_FORMAT = "<IIHHI"
DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FORMAT)
ACK_SIZE = struct.calcsize(ACK_FORMAT)


def parse_args():
    parser = argparse.ArgumentParser(description="UDP stop-and-wait sender for AD9361_test2")
    parser.add_argument("--ip", required=True, help="Zynq target IP address")
    parser.add_argument("--port", type=int, default=5001, help="Zynq UDP port")
    parser.add_argument("--chunk-size", type=int, default=1024, help="payload bytes per UDP chunk")
    parser.add_argument("--timeout", type=float, default=1.0, help="ACK timeout in seconds")
    parser.add_argument("--retries", type=int, default=10, help="max retries per chunk")
    parser.add_argument("--test-size", type=int, default=0, help="send generated test payload of this size")
    parser.add_argument("--file", help="send payload read from file")
    return parser.parse_args()


def load_payload(args):
    if args.test_size > 0 and args.file:
        raise ValueError("use either --test-size or --file")
    if args.test_size > 0:
        return bytes((index & 0xFF) for index in range(args.test_size))
    if args.file:
        with open(args.file, "rb") as fp:
            return fp.read()
    raise ValueError("one of --test-size or --file is required")


def build_packet(seq, payload):
    crc32 = binascii.crc32(payload) & 0xFFFFFFFF
    header = struct.pack(DATA_HEADER_FORMAT, DATA_MAGIC, seq, len(payload), 0, crc32)
    return header + payload


def recv_ack(sock, expected_seq):
    data, _ = sock.recvfrom(2048)
    if len(data) < ACK_SIZE:
        raise RuntimeError("received short ACK")

    magic, seq, status, _reserved, transfer_len = struct.unpack(ACK_FORMAT, data[:ACK_SIZE])
    if magic != ACK_MAGIC:
        raise RuntimeError(f"received invalid ACK magic 0x{magic:08X}")
    if seq != expected_seq:
        raise RuntimeError(f"received unexpected ACK seq {seq}, expected {expected_seq}")

    return status, transfer_len


def iter_chunks(payload, chunk_size):
    offset = 0
    seq = 0

    while offset < len(payload):
        next_offset = min(offset + chunk_size, len(payload))
        yield seq, payload[offset:next_offset], offset, next_offset
        seq += 1
        offset = next_offset


def main():
    args = parse_args()

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")
    if args.chunk_size > 1400:
        print("warning: chunk size above 1400 may trigger IP fragmentation", file=sys.stderr)

    payload = load_payload(args)
    total_size = len(payload)
    destination = (args.ip, args.port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)

    start_time = time.time()
    bytes_sent = 0

    for seq, chunk, start, end in iter_chunks(payload, args.chunk_size):
        packet = build_packet(seq, chunk)
        attempts = 0

        while True:
            attempts += 1
            if attempts > args.retries:
                raise RuntimeError(f"seq {seq} exceeded retry limit")

            sock.sendto(packet, destination)

            try:
                status, transfer_len = recv_ack(sock, seq)
            except socket.timeout:
                print(f"seq={seq} payload_len={len(chunk)} timeout retry={attempts}")
                continue

            if status == ACK_STATUS_OK:
                bytes_sent = end
                elapsed = max(time.time() - start_time, 1e-6)
                rate_kib = (bytes_sent / 1024.0) / elapsed
                print(
                    f"seq={seq} payload_len={len(chunk)} ack=OK "
                    f"transfer_len={transfer_len} progress={bytes_sent}/{total_size} "
                    f"avg_rate={rate_kib:.2f} KiB/s"
                )
                break

            print(
                f"seq={seq} payload_len={len(chunk)} ack_status={status} "
                f"transfer_len={transfer_len} retry={attempts}"
            )
            time.sleep(0.05)

    elapsed = max(time.time() - start_time, 1e-6)
    rate_kib = (bytes_sent / 1024.0) / elapsed
    print(f"done bytes={bytes_sent} elapsed={elapsed:.3f}s avg_rate={rate_kib:.2f} KiB/s")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
