# TODO: AIRV Realtime Video Handoff

This file is the active task handoff for the next agent. It is a roadmap and lab log, not the main project documentation. Keep stable user-facing documentation in root `README.md` after implementation.

## Current State

AIR0 exact file/test-data recovery is working and should be preserved.

AIRV Stage 1 transport is implemented in the PC tools and has passed board loopback validation. PS/PL remain payload-agnostic: after `net_data_header_t`, AIR0/AIRV bytes are still ordinary wire payload forwarded through PS DDR -> AXI DMA MM2S -> PL loopback -> S2MM -> PS UDP return.

Relevant files:

```text
AD9361_test2/tools/pc_sender/video_protocol.py
    AIRV v1 header, H.264 Annex-B parsing, frame fragmentation.

AD9361_test2/tools/pc_sender/video_receiver_core.py
    AIRV realtime frame assembler and metrics.

AD9361_test2/tools/pc_sender/sender_core.py
    transfer_protocol selection, AIRV MP4/.h264 preparation, ffmpeg fallback.

AD9361_test2/tools/pc_sender/sender_gui.py
    Sender GUI Transfer Mode.

AD9361_test2/tools/pc_sender/receiver_core.py
    AIR0/AIRV auto-detection from loopback payload stream.

AD9361_test2/tools/pc_sender/receiver_gui.py
    AIRV metrics display and VIDEO logs.
```

## Latest Verified Board Results

### AIR0 Regression

User tested 64 MiB AIR0 with:

```text
Transfer Mode           air0_file
Mode                    Test Data
Test Bytes              67108864
Chunk Bytes             1440
Window Size             1
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
```

Result was successful:

```text
Sender DONE app_ack=67108864 app_sched=67108864 wire_ack=70230208 udp_tx=71042576 ack_ok=48771 timeouts=0
Receiver DONE rx=67108864 high=67108864 gaps=0 air=1 air_rx=48771/48771 miss=0 bad_hdr=0 bad_payload=0 bad_meta=0 dup=0 file_crc=1 got_last=1 saved=output\test.bin
```

Conclusion: AIR0 exact recovery path is good. Do not regress it.

### AIRV Transport

User tested AIRV with an MP4 source. Sender auto-prepared same-name `.h264` through ffmpeg. Test settings were effectively:

```text
Transfer Mode           airv_video
Mode                    File
Chunk Bytes             1440
Window Size             1
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

Latest receiver result:

```text
VIDEO frame_rx=18825 frame_show=18825 frame_drop=0 frag_rx=112386 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=126 waiting_keyframe=0 fps=30.0 latency_ms=45.3
VIDEO frame_rx=18881 frame_show=18881 frame_drop=0 frag_rx=112682 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=126 waiting_keyframe=0 fps=30.0 latency_ms=30.9
VIDEO frame_rx=18921 frame_show=18921 frame_drop=0 frag_rx=112948 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=127 waiting_keyframe=0 fps=30.0 latency_ms=26.6
VIDEO_DONE frame_rx=18947 frame_show=18947 frame_drop=0 frag_rx=113005 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0
DONE VIDEO frame_rx=18947 frame_show=18947 frame_drop=0 frag_rx=113005 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=127 waiting_keyframe=0 fps=30.0 latency_ms=0.0 reason=AIRV stream idle finish; realtime mode does not save an exact file
```

Latest sender result:

```text
DONE app_ack=162727200 app_sched=162727200 wire_ack=162727200 udp_tx=164612448 app_deliv=400.00KiB/s wire_acc=400.00KiB/s udp_tx_rate=404.63KiB/s ack_ok=113005 timeouts=0
```

Conclusion: AIRV transport integrity is good at 400 KiB/s, window 1. No missing fragments, no bad headers, no bad metadata, no payload/frame CRC errors, no sender timeouts.

## Important Interpretation Notes

- `frame_rx/frame_show` currently means "assembled encoded AIRV frames", not decoded/displayed frames.
- `fps` now comes from AIRV `pts_us`, not Python burst processing speed. It currently defaults to about 30fps because sender writes `frame_interval_us=33333` unless improved.
- `latency_ms` is currently first-fragment-to-frame-complete assembler time. It is not end-to-end RF/video latency.
- Final `DONE VIDEO ... latency_ms=0.0` is not meaningful; it is caused by final idle-finish bookkeeping after no new frame. Do not treat that as measured latency.
- AIRV does not save a recovered file by design. AIR0 remains the exact file recovery mode.

## Completed Implementation

- AIRV v1 fixed 64-byte header.
- Sender GUI `Transfer Mode`: `air0_file`, `airv_video`, `raw`.
- AIRV MP4 preparation:
  - If user selects `.h264` / `.264`, use directly.
  - If user selects MP4, reuse same-name `.h264/.264` if present.
  - Otherwise call `ffmpeg` to create same-name `.h264`.
  - Generated H.264 inserts AUD to help frame boundary detection.
- H.264 Annex-B parser uses AUD and slice header `first_mb_in_slice` to reduce multi-slice frame overcounting.
- Receiver auto-detects AIR0 vs AIRV from loopback payload magic.
- AIRV assembler:
  - strict header validation;
  - collect fragments by `frame_seq/frag_index`;
  - count bad fragment/frame CRC but still assemble if header/meta and fragments are usable;
  - drop incomplete stale frames;
  - emit `VIDEO`, `VIDEO_FRAME`, `VIDEO_DONE`, `DONE VIDEO`.
- Unit tests currently cover AIRV header roundtrip, fragmentation, CRC behavior, bad header rejection, MP4 sidecar reuse, ffmpeg runner edge case, H.264 AUD/slice parsing, and PTS-based FPS.

## Immediate Next Goal

Implement actual realtime video preview on the receiver side.

The user originally wanted realtime video behavior, not just transport statistics:

- Display video while AIRV frames are being received.
- Do not wait for the full file.
- If fragments are missing, skip/drop that frame and continue.
- If header/meta is good but payload/frame CRC is bad, still try to decode/display the frame so visible corruption can be demonstrated.
- If decoder state breaks after corrupt/missing reference frames, wait for the next keyframe and resume.
- No audio.
- No receiver ACK/retransmission/FEC for this milestone.

## Recommended Next Implementation Plan

### Step 1: Add Decode/Preview Path Locally

Prefer PyAV if available because it can decode H.264 packets in-process and return frames suitable for Tkinter display.

Add a separate receiver-side component, for example:

```text
AD9361_test2/tools/pc_sender/video_playback.py
```

Responsibilities:

- Accept assembled AIRV encoded frames from `VideoStreamAssembler`.
- Feed each frame as an H.264 packet into a decoder.
- Convert decoded frames to RGB/PIL/Tk image.
- Keep decoder alive across recoverable decode errors.
- If decode errors persist after missing/corrupt delta frames, set `waiting_keyframe=1` and resume on next keyframe.

If PyAV is not installed, either:

- show a clear GUI error with install guidance, or
- fall back to OpenCV if available, but PyAV is better for packet-level H.264.

Do not make PS/PL parse AIRV. This is PC receiver-only.

### Step 2: Integrate With Receiver GUI

Extend `receiver_gui.py`:

- Add a video preview area or a separate preview window.
- Subscribe to `video_frame` events from `receiver_core.py`.
- Feed frames into the decoder/playback component.
- Display decoded frames as they arrive.
- Add visible status fields:
  - decoded frames
  - displayed frames
  - decoder errors
  - waiting keyframe
  - dropped missing frames

Keep existing AIR0 metrics visible and unchanged.

### Step 3: Improve AIRV Timing Metadata

Current sender uses default `frame_interval_us=33333`. This is fine for initial validation but not robust for arbitrary MP4.

Implement source FPS detection:

- Use `ffprobe` if available, or parse `ffmpeg` metadata output.
- Determine source frame rate from MP4.
- Pass real `frame_interval_us` into `build_airv_stream()`.
- If FPS cannot be detected, fall back to 30fps and log that fallback.

Potential API change:

```python
ensure_airv_h264_source(...) -> AirvSource(path: Path, fps: float)
build_airv_stream(..., frame_interval_us=round(1_000_000 / fps))
```

Update GUI log so the user sees:

```text
AIRV source file=... fps=...
```

### Step 4: Make Final Metrics Less Misleading

Fix final `DONE VIDEO ... latency_ms=0.0` behavior:

- Track `last_nonzero_latency_ms`.
- Add average/max assemble latency:
  - `latency_avg_ms`
  - `latency_max_ms`
- On final idle finish, report last/avg/max rather than resetting to 0.

This is a metrics fix, not a transport fix.

### Step 5: Board Test After Preview Is Added

Ask user to test in GUI only.

Recommended first AIRV preview test:

```text
Sender Transfer Mode    airv_video
Sender Mode             File
Sender file             MP4 video
Chunk Bytes             1440
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked

Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

Ask user to copy:

```text
Receiver:
RX target registered ...
VIDEO ...
VIDEO_FRAME ... only if present
VIDEO_DONE ...
DONE VIDEO ...
Any decoder/playback error lines

Sender:
PROGRESS ...
DONE ...

Board serial:
RXCFG loopback peer
S2MM start/wait/done/error
S2MM rx_hdr
LB UDP sent
STAT rate/state
```

Expected transport result should remain:

```text
frame_drop=0
frag_missing=0
bad_hdr=0
bad_meta=0
bad_frag_crc=0
bad_frame_crc=0
sender timeouts=0
```

Expected preview result:

```text
decoded/displayed frames increase during transfer
no full-file wait before display starts
if corrupt payload is later induced, decoder attempts display and recovers at keyframe
```

## Later Work

- Add jitter buffer controls, initially 100-300 ms.
- Add sender pacing by video PTS for "wall-clock realtime" mode. Current sender is transport-rate limited by KiB/s, not frame-time paced.
- Add optional loss/corruption injection in receiver or sender for visual artifact demos.
- Add live camera capture as a later milestone.
- Consider adaptive rate/window tests after preview works:
  - Window Size 4
  - Rate Limit KiB/s 550 or near observed stable throughput
- Do not add FEC, receiver ACK, retransmission, audio, or PS/PL AIRV parsing in this milestone unless user explicitly changes scope.

## Local Verification Commands

Use RTK prefix:

```bash
rtk python AD9361_test2/tools/pc_sender/test_airv_protocol.py
rtk python -m py_compile AD9361_test2/tools/pc_sender/air_protocol.py AD9361_test2/tools/pc_sender/video_protocol.py AD9361_test2/tools/pc_sender/video_receiver_core.py AD9361_test2/tools/pc_sender/sender_core.py AD9361_test2/tools/pc_sender/sender_gui.py AD9361_test2/tools/pc_sender/receiver_core.py AD9361_test2/tools/pc_sender/receiver_gui.py AD9361_test2/tools/pc_sender/send_data.py AD9361_test2/tools/pc_sender/recv_data.py
rtk git status --short
```

This environment usually cannot build the Xilinx SDK project from shell. For C/board behavior, do static checks locally and rely on user board logs.
