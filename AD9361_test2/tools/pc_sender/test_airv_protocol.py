#!/usr/bin/env python3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from air_protocol import AIR_MAGIC
import sender_core
from sender_core import (
    SenderConfig,
    UdpSender,
    _parse_frame_rate,
    _run_ffmpeg,
    ensure_airv_h264_source,
    find_existing_airv_h264,
)
from video_protocol import (
    AIRV_FRAME_KEY,
    AIRV_HEADER_BYTES,
    AIRV_MAGIC,
    build_airv_packet,
    build_airv_stream,
    crc32,
    iter_h264_annexb_frames,
    parse_airv_header,
)
from video_receiver_core import VideoStreamAssembler


class AirvProtocolTests(unittest.TestCase):
    def test_header_roundtrip(self):
        packet = build_airv_packet(
            b"abc",
            session_id=7,
            stream_id=11,
            frame_seq=3,
            frag_index=0,
            frag_count=1,
            frame_type=AIRV_FRAME_KEY,
            frame_size=3,
            fragment_offset=0,
            chunk_bytes=1440,
            frame_crc32=crc32(b"abc"),
            pts_us=123,
        )
        header = parse_airv_header(packet[:AIRV_HEADER_BYTES])
        self.assertEqual(header.magic, AIRV_MAGIC)
        self.assertEqual(header.header_len, AIRV_HEADER_BYTES)
        self.assertEqual(header.fragment_len, 3)
        self.assertEqual(packet[AIRV_HEADER_BYTES:AIRV_HEADER_BYTES + 3], b"abc")

    def test_fragment_reassembly(self):
        frame = bytes(range(251))
        packets = []
        chunk_bytes = 80
        payload_bytes = chunk_bytes - AIRV_HEADER_BYTES
        frag_count = (len(frame) + payload_bytes - 1) // payload_bytes
        for frag_index in range(frag_count):
            offset = frag_index * payload_bytes
            fragment = frame[offset:offset + payload_bytes]
            packets.append(build_airv_packet(
                fragment,
                session_id=1,
                stream_id=2,
                frame_seq=0,
                frag_index=frag_index,
                frag_count=frag_count,
                frame_type=AIRV_FRAME_KEY,
                frame_size=len(frame),
                fragment_offset=offset,
                chunk_bytes=chunk_bytes,
                frame_crc32=crc32(frame),
                pts_us=0,
            ))

        assembler = VideoStreamAssembler()
        completed = []
        for packet in packets:
            header = parse_airv_header(packet[:AIRV_HEADER_BYTES])
            payload = packet[AIRV_HEADER_BYTES:AIRV_HEADER_BYTES + header.fragment_len]
            completed.extend(assembler.process_fragment(header, payload, True))

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].payload, frame)
        self.assertEqual(assembler.frame_show, 1)

    def test_bad_fragment_crc_still_assembles(self):
        packet = build_airv_packet(
            b"abc",
            session_id=1,
            stream_id=2,
            frame_seq=0,
            frag_index=0,
            frag_count=1,
            frame_type=AIRV_FRAME_KEY,
            frame_size=3,
            fragment_offset=0,
            chunk_bytes=1440,
            frame_crc32=crc32(b"abc"),
            pts_us=0,
        )
        header = parse_airv_header(packet[:AIRV_HEADER_BYTES])
        payload = b"axc"
        assembler = VideoStreamAssembler()
        completed = assembler.process_fragment(header, payload, False)
        self.assertEqual(len(completed), 1)
        self.assertTrue(completed[0].bad_fragment_crc)
        self.assertTrue(completed[0].bad_frame_crc)
        self.assertEqual(assembler.bad_frag_crc, 1)
        self.assertEqual(assembler.bad_frame_crc, 1)

    def test_bad_header_crc_rejected(self):
        packet = bytearray(build_airv_packet(
            b"abc",
            session_id=1,
            stream_id=2,
            frame_seq=0,
            frag_index=0,
            frag_count=1,
            frame_type=AIRV_FRAME_KEY,
            frame_size=3,
            fragment_offset=0,
            chunk_bytes=1440,
            frame_crc32=crc32(b"abc"),
            pts_us=0,
        ))
        packet[30] ^= 0x01
        with self.assertRaises(ValueError):
            parse_airv_header(bytes(packet[:AIRV_HEADER_BYTES]))

    def test_air0_and_airv_magic_are_distinct(self):
        self.assertNotEqual(AIR_MAGIC, AIRV_MAGIC)

    def test_airv_stream_uses_fixed_wire_chunks(self):
        h264_idr = b"\x00\x00\x00\x01\x65" + bytes(range(100))
        stream = build_airv_stream(
            h264_idr,
            chunk_bytes=1440,
            session_id=1,
            stream_id=2,
        )
        self.assertEqual(len(stream) % 1440, 0)
        header = parse_airv_header(stream[:AIRV_HEADER_BYTES])
        self.assertEqual(header.frame_seq, 0)

    def test_h264_multislice_frame_is_not_overcounted(self):
        start = b"\x00\x00\x00\x01"
        frame0_slice0 = start + b"\x41\x80"
        frame0_slice1 = start + b"\x41\x40"
        frame1_slice0 = start + b"\x41\x80"
        frames = list(iter_h264_annexb_frames(frame0_slice0 + frame0_slice1 + frame1_slice0))
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0], frame0_slice0 + frame0_slice1)

    def test_h264_aud_boundaries_are_used(self):
        start = b"\x00\x00\x00\x01"
        aud = start + b"\x09\xf0"
        frame0 = aud + start + b"\x41\x80"
        frame1 = aud + start + b"\x41\x80"
        frames = list(iter_h264_annexb_frames(frame0 + frame1))
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0].startswith(aud))

    def test_airv_h264_sidecar_is_reused_for_mp4(self):
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            mp4_path = directory / "clip.mp4"
            h264_path = directory / "clip.h264"
            mp4_path.write_bytes(b"not a real mp4")
            h264_path.write_bytes(b"\x00\x00\x00\x01\x65")
            self.assertEqual(find_existing_airv_h264(mp4_path), h264_path)
            self.assertEqual(ensure_airv_h264_source(str(mp4_path)), h264_path)

    def test_airv_sidecar_reuse_skips_ffprobe(self):
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            mp4_path = directory / "clip.mp4"
            h264_path = directory / "clip.h264"
            mp4_path.write_bytes(b"not a real mp4")
            h264_path.write_bytes(b"\x00\x00\x00\x01\x65")
            with mock.patch("sender_core.probe_video_fps", side_effect=AssertionError("unexpected ffprobe")):
                source = sender_core.prepare_airv_source(str(mp4_path))
            self.assertEqual(source.path, h264_path)
            self.assertEqual(source.fps_source, "sidecar_fallback")

    def test_airv_h264_input_is_used_directly(self):
        with TemporaryDirectory() as temp_dir:
            h264_path = Path(temp_dir) / "clip.264"
            h264_path.write_bytes(b"\x00\x00\x00\x01\x65")
            self.assertEqual(ensure_airv_h264_source(str(h264_path)), h264_path)

    def test_ffmpeg_runner_handles_missing_stderr_text(self):
        completed = SimpleNamespace(returncode=1, stdout=None, stderr=None)
        with mock.patch("sender_core.subprocess.run", return_value=completed):
            return_code, message = _run_ffmpeg(["ffmpeg"])
        self.assertEqual(return_code, 1)
        self.assertEqual(message, "")

    def test_frame_rate_parser_accepts_rational_values(self):
        self.assertAlmostEqual(_parse_frame_rate("30000/1001"), 29.970, delta=0.001)
        self.assertEqual(_parse_frame_rate("30/0"), None)
        self.assertEqual(_parse_frame_rate("0/0"), None)

    def test_airv_prepare_transfer_uses_configured_frame_interval(self):
        h264_frames = (
            b"\x00\x00\x00\x01\x09\xf0\x00\x00\x00\x01\x65\x80" +
            b"\x00\x00\x00\x01\x09\xf0\x00\x00\x00\x01\x41\x80"
        )
        sender = UdpSender(SenderConfig(
            ip="127.0.0.1",
            transfer_protocol="airv_video",
            airv_frame_interval_us=40000,
        ))
        sender._session_id = 1
        prepared = sender._prepare_transfer(h264_frames)
        first = parse_airv_header(prepared[:AIRV_HEADER_BYTES])
        second = parse_airv_header(prepared[1440:1440 + AIRV_HEADER_BYTES])
        self.assertEqual(first.pts_us, 0)
        self.assertEqual(second.pts_us, 40000)

    def test_video_fps_uses_pts_not_processing_burst(self):
        frame0 = b"abc"
        frame1 = b"def"
        assembler = VideoStreamAssembler()
        completed = []
        for seq, frame in enumerate((frame0, frame1)):
            packet = build_airv_packet(
                frame,
                session_id=1,
                stream_id=2,
                frame_seq=seq,
                frag_index=0,
                frag_count=1,
                frame_type=AIRV_FRAME_KEY,
                frame_size=len(frame),
                fragment_offset=0,
                chunk_bytes=1440,
                frame_crc32=crc32(frame),
                pts_us=seq * 33333,
            )
            header = parse_airv_header(packet[:AIRV_HEADER_BYTES])
            payload = packet[AIRV_HEADER_BYTES:AIRV_HEADER_BYTES + header.fragment_len]
            completed.extend(assembler.process_fragment(header, payload, True))
        self.assertEqual(len(completed), 2)
        self.assertAlmostEqual(assembler.metrics()["fps"], 30.0, delta=0.1)

    def test_video_latency_tracks_average_and_max(self):
        assembler = VideoStreamAssembler()
        packets = []
        for seq, frame in enumerate((b"abc", b"def")):
            packets.append(build_airv_packet(
                frame,
                session_id=1,
                stream_id=2,
                frame_seq=seq,
                frag_index=0,
                frag_count=1,
                frame_type=AIRV_FRAME_KEY,
                frame_size=len(frame),
                fragment_offset=0,
                chunk_bytes=1440,
                frame_crc32=crc32(frame),
                pts_us=seq * 33333,
            ))
        times = iter([10.0, 10.010, 20.0, 20.030])

        def fake_time():
            try:
                return next(times)
            except StopIteration:
                return 20.030

        with mock.patch("video_receiver_core.time.time", side_effect=fake_time):
            for packet in packets:
                header = parse_airv_header(packet[:AIRV_HEADER_BYTES])
                payload = packet[AIRV_HEADER_BYTES:AIRV_HEADER_BYTES + header.fragment_len]
                assembler.process_fragment(header, payload, True)
        metrics = assembler.metrics()
        self.assertAlmostEqual(metrics["latency_ms"], 30.0, delta=0.1)
        self.assertAlmostEqual(metrics["latency_avg_ms"], 20.0, delta=0.1)
        self.assertAlmostEqual(metrics["latency_max_ms"], 30.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
