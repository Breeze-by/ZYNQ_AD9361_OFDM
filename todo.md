# TODO: Realtime Video Transport Mode

This file captures the next protocol milestone for a future agent. It is a task plan, not the main project documentation. Keep the complete project documentation in `README.md` after implementation.

## Status

Stage 1 is implemented in the PC tools:

- Added `video_protocol.py` with AIRV v1 64-byte fixed header and H.264 Annex-B frame fragmentation.
- Added `video_receiver_core.py` with realtime frame assembly metrics.
- Added sender `transfer_protocol` support and sender GUI `Transfer Mode`.
- Added receiver auto-detection for AIR0 vs AIRV and `VIDEO` / `DONE VIDEO` logs.
- Added Python unit tests for AIRV header, fragmentation, bad CRC behavior, bad header CRC rejection, and AIR0/AIRV magic separation.
- Added automatic AIRV MP4 preparation: reuse same-name `.h264/.264` when present, otherwise generate and save same-name `.h264` via `ffmpeg`.

Stage 1 does not yet include actual decoded video preview. It validates the AIRV transport and realtime frame assembly through the existing PS/PL loopback path. Keep PS/PL payload-agnostic.

## Goal

Add a separate realtime video transport mode in addition to the existing file/test-data AIR0 mode.

Current AIR0 mode is a file recovery protocol: it restores the exact original byte stream and saves it only when complete. The new mode should behave like a realtime video stream:

- Sender GUI can choose the transfer mode.
- Receiver GUI/CLI auto-detects the payload mode and dispatches to the correct handler.
- Realtime video is displayed while it is being received.
- If packets/fragments are lost, skip the affected frame and continue with the next valid frame.
- If video frame payload bytes are corrupted but the frame header is still usable, do not drop the frame just because payload CRC fails. Try to decode/display it so visual corruption can be demonstrated.
- If the frame header is corrupted, the fragment cannot be assigned to a frame, or required fragments are missing past the realtime deadline, drop that frame and resynchronize at the next valid frame/keyframe.
- No audio is needed.
- Do not add receiver-side ACK/retransmission or FEC in this milestone.
- Keep PS/PL payload-agnostic. PS and PL must continue treating the PC->PS payload after `net_data_header_t` as ordinary wire payload.

## Terminology

- `AIR0`: current PC-only file/test-data payload header. It is for complete file recovery and CRC-verified save.
- `AIRV`: proposed PC-only realtime video payload header. It is for frame-fragment streaming and live playback.
- `wire payload`: bytes after `net_data_header_t`; PS/PL forward this without parsing.
- `video frame`: one encoded access unit intended for decode/display.
- `fragment`: one piece of a video frame small enough to fit inside one PC->PS wire payload.

## Mode Selection

Sender side:

- Add a transfer mode selector separate from existing `File` / `Test Data` source selection.
- Suggested modes:
  - `AIR0 File/Test` for current exact recovery behavior.
  - `AIRV Realtime Video` for live video playback.
- In AIRV mode, source should be a video file path for now. Live camera capture can be a later milestone.
- Keep `Payload CRC32` enabled by default for PC->PS transport integrity.
- AIRV mode should still use `Chunk Bytes=1440` by default.

Receiver side:

- Auto-detect mode from the returned wire payload stream:
  - AIR0 magic `0x30524941` at expected header positions means current file recovery path.
  - AIRV magic should dispatch to realtime video path.
  - Raw fallback remains as existing raw assembler behavior.
- The receiver UI should not require the user to preselect AIR0 vs AIRV.

## Proposed AIRV Header

Add `AD9361_test2/tools/pc_sender/video_protocol.py`.

Use a fixed-size little-endian header, designed for one fragment per PC->PS packet:

```text
magic               4 bytes  "AIRV" little-endian constant, e.g. 0x56524941
version             1 byte
header_len          1 byte
flags               2 bytes
session_id          4 bytes
stream_id           4 bytes
frame_seq           4 bytes
frag_index          2 bytes
frag_count          2 bytes
frame_type          1 byte   unknown / keyframe / delta
reserved0           1 byte
header_crc32        4 bytes
frame_size          4 bytes
fragment_offset     4 bytes
fragment_len        2 bytes
chunk_bytes         2 bytes
frame_crc32         4 bytes  diagnostic only; do not require it for display
fragment_crc32      4 bytes  diagnostic only; do not require it for display
pts_us              8 bytes
tx_timestamp_us     8 bytes
```

This layout is 64 bytes if packed carefully. Keep it at 64 bytes if possible so `Chunk Bytes=1440` leaves `1376` bytes for video fragment data, matching AIR0.

Suggested flags:

```text
DATA          0x0001
KEYFRAME      0x0002
LAST_FRAGMENT 0x0004
CONFIG        0x0008   optional codec extradata / SPS/PPS packet
```

Header validation should be strict:

- magic/version/header_len/header_crc32 must be valid.
- `frag_index < frag_count`.
- `fragment_len <= chunk_bytes - header_len`.
- `fragment_offset + fragment_len <= frame_size`.
- `LAST_FRAGMENT` should only appear on `frag_index == frag_count - 1`.

Payload CRC policy:

- Record `bad_fragment_crc` and `bad_frame_crc` counters.
- Do not automatically drop a frame only because fragment/frame CRC fails.
- If the header is valid and enough fragments arrived, assemble and feed the decoder anyway. This intentionally allows visible corruption for demonstrations.

## Sender Implementation Plan

Start in PC tools only:

- Update `sender_core.py` with an explicit transfer protocol enum or config field:
  - `air0_file`
  - `airv_video`
  - raw legacy fallback if still needed
- Keep current AIR0 behavior unchanged.
- Add AIRV packet builder in `video_protocol.py`.
- Add GUI controls in `sender_gui.py`:
  - Transfer Mode: `File/Test AIR0` and `Realtime Video AIRV`.
  - For AIRV, source path should be a video file.
  - Keep current network controls.

Video extraction/transcoding:

- Prefer PyAV if available. If not, use `ffmpeg` CLI as a subprocess fallback.
- First milestone may require users to provide H.264 elementary stream or MP4 with H.264 video.
- Recommended encoding profile for testing:
  - H.264
  - no audio
  - no B-frames
  - short GOP, e.g. keyframe every 15 to 30 frames
  - baseline or main profile
- Sender should extract encoded video frames/access units and fragment each encoded frame across AIRV packets.
- Send SPS/PPS / codec extradata before keyframes or periodically if needed.

Do not try to stream arbitrary MP4 file bytes directly for realtime playback. MP4 is a container and does not provide simple packet loss recovery or frame boundary semantics by itself.

## Receiver Implementation Plan

Add a realtime video path alongside existing AIR0 file recovery:

- Add `video_receiver_core.py` or keep a clearly separated class in `receiver_core.py`.
- On AIRV detection, create a `VideoStreamAssembler`.
- Track frames by `frame_seq`.
- For each frame:
  - Collect fragments by `frag_index`.
  - Allow corrupt fragment payload if header is valid.
  - If all required fragments arrive before the frame deadline, assemble the frame and send it to decoder.
  - If fragments are missing after deadline, drop the frame and count `drop_missing`.
  - If header/meta is invalid and frame cannot be reconstructed, count `bad_header` / `bad_meta` and resync at next valid header/frame.
- Use a small jitter buffer:
  - Start with 100 to 300 ms.
  - GUI should expose this later if needed.
- Maintain realtime order:
  - Display frames in increasing `frame_seq`.
  - If a frame is missing past deadline, skip it and continue.

Decoder/playback:

- First implementation target can use PyAV to decode H.264 packets and convert to frames.
- Display frames in a Tkinter canvas or separate OpenCV window.
- If decoder errors after a corrupt frame, keep the pipeline alive and resume at the next decodable frame.
- If a reference frame is missing and the decoder becomes unstable, wait until the next keyframe before displaying again.

Important behavior decision from user:

- Do not drop frames just because payload CRC is bad. Try to display corrupted frames if the frame can be assembled and the decoder accepts it.
- Drop/skip only when packets/fragments are missing, frame headers are unusable, or the decoder cannot recover.

## Receiver Metrics

Add separate AIRV metrics so AIR0 file metrics remain clear:

```text
airv=1
frame_rx=...
frame_show=...
frame_drop=...
frag_rx=...
frag_missing=...
bad_hdr=...
bad_meta=...
bad_frag_crc=...
bad_frame_crc=...
keyframe_rx=...
waiting_keyframe=...
latency_ms=...
fps=...
```

For logs:

- `PROGRESS` should use streaming terms, not AIR0 file terms.
- Example:

```text
VIDEO frame_rx=1200 frame_show=1187 frame_drop=13 frag_rx=9000 frag_missing=27 bad_frag_crc=5 waiting_keyframe=0 fps=24.8 latency_ms=180
```

## Testing Plan

Local Python-only tests:

- AIRV header build/parse roundtrip.
- Fragment a fake frame and reassemble exactly.
- Drop one fragment and verify frame is skipped after deadline.
- Corrupt fragment payload with valid header and verify frame is still assembled and marked `bad_frag_crc`.
- Corrupt header CRC and verify fragment is rejected/resync works.
- Mix AIR0 and AIRV samples and verify receiver mode auto-detection dispatches correctly.
- Regression: current AIR0 file save still passes.

Board tests:

1. Keep current small AIR0 test to verify existing file path still works.
2. AIRV low-rate test:
   - small H.264 test clip
   - `Chunk Bytes=1440`
   - `Window Size=1`
   - `Rate Limit KiB/s=400`
3. AIRV moderate-rate test:
   - `Window Size=4`
   - `Rate Limit KiB/s=550` or near observed stable throughput
4. Confirm:
   - video displays while receiving
   - no full-file wait before display
   - missing fragments increment drop counters
   - corrupt payload can produce visible artifacts rather than automatic file-level rejection

## Documentation Updates After Implementation

Update root `README.md` with:

- AIR0 vs AIRV mode descriptions.
- Sender GUI field descriptions.
- Receiver auto-detection behavior.
- AIRV metrics.
- Recommended H.264 encoding settings.
- Clear note: PS/PL still do not parse AIR0/AIRV payloads.

Update root `AGENTS.md` with:

- New GUI test settings for AIRV.
- New log lines users should copy.
- Reminder that AIRV is realtime and not expected to save an exact file.

## Non-goals For This Milestone

- No FEC.
- No receiver-side ACK or retransmission.
- No audio.
- No PS/PL parsing of video headers.
- No guaranteed exact file recovery in AIRV mode. AIR0 remains the exact recovery mode.
