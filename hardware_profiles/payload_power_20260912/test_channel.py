"""Real-RF test capture; no payload mutation, RF retry, or artificial noise.

Uses the original PC sender/receiver cores. AIR0 parsing may stop at a stream
hole; WIRE_CHECK independently checks every returned block against its source.
The first 30 application bytes fit in the 32-symbol protected DATA region.
"""
import argparse
import base64
import binascii
from collections import Counter
from dataclasses import asdict
import json
import hashlib
import struct
from pathlib import Path
import queue
import random
import math
import subprocess
import sys
import threading
import time

PROJECT = Path(r'E:\by2025\AD9361_test_board\AD9361_test2')
sys.path.insert(0, str(PROJECT / 'AD9361_test2.sdk' / 'AD9361_test2' / 'tools' / 'pc_sender'))
from sender_core import SenderConfig, UdpSender, load_payload
from receiver_core import LoopbackReceiver, ReceiverConfig
from video_playback import VideoPreviewDecoder
from air_protocol import parse_air_header


def emit(event, **values):
    print(json.dumps({'time': time.time(), 'event': event, **values}, ensure_ascii=True), flush=True)


def capture_serial(port, directory, seconds):
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        f"$s=New-Object System.IO.Ports.SerialPort('{port}',115200); "
        "$s.DtrEnable=$false; $s.RtsEnable=$false; "
        "try {$s.Open(); [Console]::WriteLine('SERIAL_OPEN'); "
        "$timer=[Diagnostics.Stopwatch]::StartNew(); "
        f"while($timer.Elapsed.TotalSeconds -lt {int(seconds)}){{ "
        "$text=$s.ReadExisting(); if($text){[Console]::Write($text)}; "
        "Start-Sleep -Milliseconds 25}} "
        "catch {[Console]::Error.WriteLine($_.Exception.Message)} "
        "finally {if($s.IsOpen){$s.Close()}; $s.Dispose()}"
    )
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    log = (directory / 'serial.log').open('wb')
    error = (directory / 'serial.stderr').open('wb')
    proc = subprocess.Popen(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                             '-EncodedCommand', encoded], stdout=log, stderr=error,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return proc, log, error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['sender', 'receiver'])
    parser.add_argument('--tag', required=True)
    parser.add_argument('--kind', choices=['air0', 'video'], default='air0')
    parser.add_argument('--file')
    parser.add_argument('--bytes', type=int, default=65536)
    parser.add_argument('--rate', type=float, default=400)
    parser.add_argument('--delay', type=float, default=3)
    parser.add_argument('--gap-ms', type=float, default=0)
    parser.add_argument('--chunk', type=int, default=1024)
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--seconds', type=float, default=55)
    args = parser.parse_args()
    def test_source():
        return random.Random(9361320).randbytes(args.bytes) if args.random else load_payload(test_size=args.bytes)
    directory = Path(__file__).resolve().parent.parent / args.tag
    directory.mkdir(exist_ok=False)
    serial, serial_log, serial_error = capture_serial('COM4' if args.role == 'sender' else 'COM3', directory, args.seconds + 30)
    try:
        if args.role == 'sender':
            time.sleep(args.delay)
            config = SenderConfig(ip='192.168.2.50', bind_ip='192.168.2.101', configure_board_ip=True,
                                  chunk_size=args.chunk, window_size=1, timeout=2.0, retries=5,
                                  target_rate_kib_s=args.rate, throughput_mode=True,
                                  validate_payload_crc=True, rf_retry=False,
                                  air_protocol=args.kind == 'air0',
                                  transfer_protocol='air0_file' if args.kind == 'air0' else 'airv_video',
                                  progress_interval_s=1.0)
            payload = test_source() if args.kind == 'air0' else Path(args.file).read_bytes()
            emit('config', role=args.role, config=asdict(config), source_bytes=len(payload))
            def sender_callback(event, data):
                if event in ('progress', 'done', 'timeout', 'retry', 'reset', 'ip_configured', 'ip_config_unconfirmed'):
                    emit(event, **{k: asdict(v) if k == 'stats' else v for k, v in data.items()})
            gaps = []
            class TimedSender(UdpSender):
                last_send_ready = None
                def _apply_rate_limit(self, expected_bytes, start_time):
                    super()._apply_rate_limit(expected_bytes, start_time)
                    now = time.perf_counter()
                    if self.last_send_ready is not None:
                        remaining = args.gap_ms/1000 - (now-self.last_send_ready)
                        if remaining > 0:
                            time.sleep(remaining)
                        now = time.perf_counter()
                        gaps.append((now-self.last_send_ready)*1000)
                    self.last_send_ready = now
            stats = TimedSender(config).send(payload, sender_callback)
            if gaps:
                emit('SEND_GAP_TRACE', gaps_ms=gaps)
                emit('SEND_GAPS', count=len(gaps), minimum_ms=min(gaps), maximum_ms=max(gaps),
                     mean_ms=sum(gaps)/len(gaps), below_2ms=sum(g<2 for g in gaps),
                     below_2p5ms=sum(g<2.5 for g in gaps))
            emit('RESULT', role=args.role, stats=asdict(stats))
        else:
            config = ReceiverConfig(bind_ip='192.168.1.100', bind_port=15003,
                                    board_ip='192.168.1.50', configure_board_ip=False,
                                    output_dir=str(directory), idle_finish_s=10.0, progress_interval_s=1.0)
            wire_blocks = {}
            wire_meta = {}
            class ObservedReceiver(LoopbackReceiver):
                def _process_loopback(self, packet, stats, callback):
                    if args.kind == 'air0':
                        wire_meta[packet['stream_offset']] = {'time': time.time(), 'meta0': packet['meta0'], 'meta1': packet['meta1'], 'block_id': packet['block_id']}
                        block = wire_blocks.setdefault(packet['stream_offset'], {})
                        block[packet['chunk_offset']] = packet['payload']
                    super()._process_loopback(packet, stats, callback)
            receiver = ObservedReceiver(config)
            decoder = VideoPreviewDecoder()
            frames = queue.Queue(maxsize=240)
            decode_state = {'input': 0, 'queue_drops': 0, 'decoded': 0, 'errors': 0, 'waiting_key': True}
            def playback():
                while True:
                    frame = frames.get()
                    if frame is None:
                        break
                    result = decoder.decode(frame['payload'], frame_type=frame['frame_type'],
                                            bad_fragment_crc=frame['bad_fragment_crc'],
                                            bad_frame_crc=frame['bad_frame_crc'])
                    decode_state.update(decoded=decoder.decoded_frames, errors=decoder.decoder_errors,
                                        waiting_key=decoder.waiting_keyframe)
                    if result.images and not (directory / 'first_frame.png').exists():
                        result.images[0].save(directory / 'first_frame.png')
            worker = threading.Thread(target=playback, daemon=True)
            worker.start()
            def callback(event, data):
                if event == 'video_frame':
                    decode_state['input'] += 1
                    try:
                        frames.put_nowait(data)
                    except queue.Full:
                        decode_state['queue_drops'] += 1
                elif event in ('registered', 'start', 'progress', 'video_done', 'done', 'incomplete', 'saved'):
                    emit(event, **{k: asdict(v) if k == 'stats' else v for k, v in data.items()})
            limit = threading.Timer(args.seconds, receiver.stop)
            limit.start()
            try:
                stats = receiver.run(callback)
            finally:
                limit.cancel()
                frames.put(None)
                worker.join(timeout=10)
            emit('RESULT', role=args.role, stats=asdict(stats), preview=decode_state)
            if args.kind == 'air0':
                source = test_source()
                source_crc = binascii.crc32(source) & 0xffffffff
                bit_errors = 0
                checked_bytes = 0
                region_bytes = [0, 0]
                region_errors = [0, 0]
                # Binary records: little-endian u64 stream offset, u32 length, then raw bytes.
                with (directory / 'received_wire.bin').open('wb') as capture:
                    for offset, chunks in sorted(wire_blocks.items()):
                        raw = b''.join(v for k, v in sorted(chunks.items()))
                        capture.write(struct.pack('<QI', offset, len(raw)) + raw)
                received_seqs = set()
                good, bad, malformed = [], [], []
                for offset, chunks in sorted(wire_blocks.items()):
                    raw = b''.join(v for k,v in sorted(chunks.items()))
                    try:
                        header = parse_air_header(raw)
                        if (header.chunk_bytes != args.chunk or header.file_size != len(source) or
                            header.file_offset != header.packet_seq * (args.chunk - 64) or
                            header.payload_len != min(args.chunk - 64, len(source) - header.file_offset) or
                            len(raw) != 64 + header.payload_len or offset != header.packet_seq * args.chunk or
                            header.file_crc32 != source_crc):
                            raise ValueError('Source metadata mismatch')
                        actual = raw[64:64+header.payload_len]
                        expected = source[header.file_offset:header.file_offset+header.payload_len]
                        positions = [i for i,(a,b) in enumerate(zip(actual, expected)) if a != b]
                        bit_errors += sum((a ^ b).bit_count() for a, b in zip(actual, expected))
                        for region, pair in enumerate(((actual[:30], expected[:30]), (actual[30:], expected[30:]))):
                            region_bytes[region] += len(pair[0])
                            region_errors[region] += sum((a ^ b).bit_count() for a, b in zip(*pair))
                        checked_bytes += min(len(actual), len(expected))
                        received_seqs.add(header.packet_seq)
                        if binascii.crc32(actual) & 0xFFFFFFFF == header.payload_crc32:
                            good.append(header.packet_seq)
                        else:
                            bad.append({'seq':header.packet_seq,'bytes':len(actual),
                                        'metadata':wire_meta[offset],
                                        'diff_count':len(positions),'first':positions[:5],'last':positions[-5:],
                                        'actual_start':actual[positions[0]:positions[0]+24].hex() if positions else '',
                                        'expected_start':expected[positions[0]:positions[0]+24].hex() if positions else '',
                                        'byte_delta':Counter((actual[i]-expected[i])%256 for i in positions).most_common(4)})
                    except Exception as exc:
                        malformed.append({'offset':offset,'error':str(exc)})
                total_packets = math.ceil(args.bytes / (args.chunk - 64))
                missing = sorted(set(range(total_packets)) - received_seqs)
                emit('RF_META_TRACE', packets=wire_meta)
                emit('RF_PHASE_HIST', counts=Counter(((v['meta1'] >> 24) ^ 128) - 128 for v in wire_meta.values()))
                emit('SOURCE_CHECK', sha256=hashlib.sha256(source).hexdigest(),
                     protected_payload_bytes=region_bytes[0], protected_payload_bit_errors=region_errors[0],
                     weak_payload_bytes=region_bytes[1], weak_payload_bit_errors=region_errors[1],
                     weak_payload_ber=region_errors[1]/(8*region_bytes[1]) if region_bytes[1] else None)
                emit('WIRE_CHECK', blocks=len(wire_blocks), good=len(good), bad_count=len(bad), bad=bad[:20],
                     malformed=malformed[:8], expected_packets=total_packets, missing_count=len(missing),
                     missing=missing[:100], checked_bytes=checked_bytes, bit_errors=bit_errors,
                     received_payload_ber=bit_errors / (checked_bytes * 8) if checked_bytes else None,
                     exact_match=(not missing and not malformed and bit_errors == 0 and checked_bytes == len(source)))
        time.sleep(1)
    finally:
        if serial.poll() is None:
            serial.terminate()
        serial.wait(timeout=5)
        serial_log.close()
        serial_error.close()
        emit('SERIAL_LOG', text=(directory / 'serial.log').read_text(encoding='utf-8', errors='replace'),
             errors=(directory / 'serial.stderr').read_text(encoding='utf-8', errors='replace'))


if __name__ == '__main__':
    main()
