#!/usr/bin/env python3
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from video_protocol import (
    AIRV_FLAG_KEYFRAME,
    AIRV_FRAME_KEY,
    AirvHeader,
    crc32 as airv_crc32,
)


@dataclass
class VideoFrame:
    frame_seq: int
    frame_type: int
    pts_us: int
    payload: bytes
    bad_fragment_crc: bool
    bad_frame_crc: bool
    latency_ms: float


@dataclass
class VideoFrameState:
    frame_seq: int
    frame_type: int
    frame_size: int
    frag_count: int
    frame_crc32: int
    pts_us: int
    first_seen_at: float
    fragments: Dict[int, bytes] = field(default_factory=dict)
    offsets: Dict[int, int] = field(default_factory=dict)
    bad_fragment_crc: bool = False


class VideoStreamAssembler:
    def __init__(self, max_incomplete_frames: int = 8):
        self.max_incomplete_frames = max_incomplete_frames
        self.frames: Dict[int, VideoFrameState] = {}
        self.stream_meta = None
        self.frame_rx = 0
        self.frame_show = 0
        self.frame_drop = 0
        self.frag_rx = 0
        self.frag_missing = 0
        self.bad_meta = 0
        self.bad_frag_crc = 0
        self.bad_frame_crc = 0
        self.keyframe_rx = 0
        self.waiting_keyframe = False
        self.last_latency_ms = 0.0
        self.last_report_latency_ms = 0.0
        self.latency_sum_ms = 0.0
        self.latency_count = 0
        self.latency_max_ms = 0.0
        self.started_at = time.time()
        self.last_pts_us = None
        self.fps = 0.0
        self.latest_frame_seq = -1

    def _meta_tuple(self, header: AirvHeader):
        return (
            header.session_id,
            header.stream_id,
            header.chunk_bytes,
        )

    def _validate_meta(self, header: AirvHeader, payload: bytes) -> bool:
        if len(payload) != header.fragment_len:
            self.bad_meta += 1
            return False
        if self.stream_meta is None:
            self.stream_meta = self._meta_tuple(header)
        elif self.stream_meta != self._meta_tuple(header):
            self.bad_meta += 1
            return False
        if header.frag_index >= header.frag_count:
            self.bad_meta += 1
            return False
        return True

    def _drop_stale_frames(self, newest_frame_seq: int):
        stale_limit = newest_frame_seq - self.max_incomplete_frames
        stale = [seq for seq in self.frames if seq < stale_limit]
        for seq in stale:
            state = self.frames.pop(seq)
            missing = max(state.frag_count - len(state.fragments), 0)
            self.frag_missing += missing
            self.frame_drop += 1
            self.waiting_keyframe = True

    def _complete_frame(self, state: VideoFrameState) -> Optional[VideoFrame]:
        if len(state.fragments) != state.frag_count:
            return None

        ordered = []
        expected_offset = 0
        for frag_index in range(state.frag_count):
            fragment = state.fragments.get(frag_index)
            offset = state.offsets.get(frag_index)
            if fragment is None or offset != expected_offset:
                self.bad_meta += 1
                self.frame_drop += 1
                return None
            ordered.append(fragment)
            expected_offset += len(fragment)

        payload = b"".join(ordered)
        if len(payload) != state.frame_size:
            self.bad_meta += 1
            self.frame_drop += 1
            return None

        bad_frame_crc = airv_crc32(payload) != state.frame_crc32
        if bad_frame_crc:
            self.bad_frame_crc += 1

        now = time.time()
        latency_ms = (now - state.first_seen_at) * 1000.0
        self.last_latency_ms = latency_ms
        if latency_ms >= 0.05:
            self.last_report_latency_ms = latency_ms
        self.latency_sum_ms += latency_ms
        self.latency_count += 1
        self.latency_max_ms = max(self.latency_max_ms, latency_ms)
        if self.last_pts_us is not None and state.pts_us > self.last_pts_us:
            interval = max((state.pts_us - self.last_pts_us) / 1000000.0, 1e-6)
            instant_fps = 1.0 / interval
            self.fps = instant_fps if self.fps <= 0.0 else (self.fps * 0.8 + instant_fps * 0.2)
        self.last_pts_us = state.pts_us
        self.frame_rx += 1
        self.frame_show += 1
        if state.frame_type == AIRV_FRAME_KEY:
            self.keyframe_rx += 1
            self.waiting_keyframe = False

        return VideoFrame(
            frame_seq=state.frame_seq,
            frame_type=state.frame_type,
            pts_us=state.pts_us,
            payload=payload,
            bad_fragment_crc=state.bad_fragment_crc,
            bad_frame_crc=bad_frame_crc,
            latency_ms=latency_ms,
        )

    def process_fragment(
        self,
        header: AirvHeader,
        payload: bytes,
        fragment_crc_ok: bool,
    ) -> List[VideoFrame]:
        if not self._validate_meta(header, payload):
            return []

        self.frag_rx += 1
        if header.frame_seq > self.latest_frame_seq:
            self.latest_frame_seq = header.frame_seq
            self._drop_stale_frames(header.frame_seq)

        if not fragment_crc_ok:
            self.bad_frag_crc += 1

        state = self.frames.get(header.frame_seq)
        if state is None:
            state = VideoFrameState(
                frame_seq=header.frame_seq,
                frame_type=header.frame_type,
                frame_size=header.frame_size,
                frag_count=header.frag_count,
                frame_crc32=header.frame_crc32,
                pts_us=header.pts_us,
                first_seen_at=time.time(),
            )
            self.frames[header.frame_seq] = state
        else:
            if (
                state.frame_size != header.frame_size or
                state.frag_count != header.frag_count or
                state.frame_crc32 != header.frame_crc32
            ):
                self.bad_meta += 1
                return []

        if header.frag_index in state.fragments:
            return []

        state.fragments[header.frag_index] = payload
        state.offsets[header.frag_index] = header.fragment_offset
        if not fragment_crc_ok:
            state.bad_fragment_crc = True

        frame = self._complete_frame(state)
        if frame is None:
            return []
        self.frames.pop(header.frame_seq, None)
        return [frame]

    def flush_missing(self):
        for state in list(self.frames.values()):
            missing = max(state.frag_count - len(state.fragments), 0)
            self.frag_missing += missing
            self.frame_drop += 1
            self.waiting_keyframe = True
        self.frames.clear()

    def metrics(self) -> dict:
        return {
            "frame_rx": self.frame_rx,
            "frame_show": self.frame_show,
            "frame_drop": self.frame_drop,
            "frag_rx": self.frag_rx,
            "frag_missing": self.frag_missing,
            "bad_meta": self.bad_meta,
            "bad_frag_crc": self.bad_frag_crc,
            "bad_frame_crc": self.bad_frame_crc,
            "keyframe_rx": self.keyframe_rx,
            "waiting_keyframe": int(self.waiting_keyframe),
            "latency_ms": self.last_report_latency_ms,
            "latency_avg_ms": (
                self.latency_sum_ms / self.latency_count
                if self.latency_count > 0 else 0.0
            ),
            "latency_max_ms": self.latency_max_ms,
            "fps": self.fps,
        }
