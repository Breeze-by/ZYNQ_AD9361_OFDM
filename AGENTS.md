# AGENTS.md

本文件给后续 agent 快速接手本仓库使用。项目完整说明只维护根目录 `README.md`，不要在子目录新增 README。

## 基本规则

- 本项目已安装 RTK。执行 shell 命令时优先使用 `rtk` 前缀，例如 `rtk git status`、`rtk git diff`、`rtk read <file>`、`rtk grep <pattern> <path>`。
- 修改前先看 `rtk git status --short`，不要覆盖用户未提交改动。
- 阅读文件优先用 `rtk read`，搜索优先用 `rtk grep` 或 `rtk rg --files`，避免普通命令输出过大。
- 只保留根目录 `README.md` 作为项目说明。协议、构建、调参、PC 工具说明都写进根 README。
- 当前根目录没有 `TODO.md`；如后续重新创建，只用于记录未实现任务路线图，不替代 README，任务完成后要把正式说明同步回根 README。
- `AD9361_test2_bsp/` 和 `System_wrapper_hw_platform_0/` 是 Xilinx 生成产物；除非任务明确要求，不要手动改 BSP、lwIP 源码或硬件平台文件。
- 之后用户提出了额外协作要求或项目注意事项，需要同步写入根目录 agent 文件，让后续 agent 知道。
- 如果仓库根目录有 `AGENT.md`、`Agent.md` 或 `AGENTS.md`，必须优先使用根目录文件作为本项目说明，不要改用 `C:\Users\29143\.codex\` 下的用户级说明。若多个同时存在，优先按用户最近明确指定的根目录文件执行。

## 用户协作约定

- 每次完成代码或文档修改后，必须 `git commit` 并 `git push` 到远程；不要让用户自己 push。提交前后都要用 `rtk git status --short` 确认工作区状态。
- 用户主要使用 GUI 发送程序 `AD9361_test2/tools/pc_sender/sender_gui.py`，不要用 CLI 命令作为测试指令。需要用户跑测试时，直接给 GUI 中的字段设置，例如 `Mode`、`Test Bytes`、`Chunk Bytes`、`Window Size`、`Throughput Mode`、`Payload CRC32`、`AIR0 Packet Header` 等。
- 旧版额外封装和测试 pattern 选项已从 PC/PS/文档移除，以后不要再建议用户使用相关 GUI 字段或 CLI 参数。PC->PS 应用层包头后始终是普通 wire payload；PS/PL 不根据 payload 内容做额外交互。
- 当前 AIRV 实时视频模式已支持接收 GUI 独立 `AIRV Preview` 窗口、后台 PyAV 解码和预览队列。AIR0 仍是精确文件/测试数据恢复模式；AIRV 是实时视频组帧/预览/统计模式，不保存精确文件，不做接收端 ACK、重传、FEC 或音频。PS/PL 仍不解析 AIR0/AIRV。
- AIRV 接收器允许开头 S2MM block 丢失后从第一个完整 AIRV chunk 中途接入，日志打印 `VIDEO_DIAG late_attach initial_missing=...`；随后等待 H.264 keyframe 恢复预览。AIR0 仍要求 offset 0 起始连续，不能用该行为掩盖精确文件缺失。
- AIRV 接收 GUI 每秒输出 `VIDEO_PREVIEW input/backlog/drops/decoded/rendered/decoder_errors/waiting_key/images/skipped/error`，结束时输出 `VIDEO_PREVIEW_DONE`；用它区分组帧成功后是 PyAV 解码未出图，还是 Tk 未渲染。
- 当前为定位 AIRV 问题，Vivado/PL 已临时切回数字回环：PL OFDM 调制输出直接送入解调接收路径，不经过 AD9361 TX、SMA 和 AD9361 RX；RF 回环仍是后续目标链路。板级调试继续分阶段做，不要一次性写完大功能；先加可观察日志，让用户上板跑并回传串口输出，再根据日志继续改。
- 当前默认走真实 `NET_LOOPBACK_RETURN_SOURCE_S2MM` RF/S2MM 回传路径，不再是 `TX_BUFFER` 诊断模式。S2MM 前 8 个 block 会打印较完整 dump，前 16 个 block 和后续异常 block 会打印一行 `S2MM diag ...` 摘要。需要用户反馈时，优先要 `RXCFG loopback peer`、`UDP RX reset`、`S2MM diag`、`STAT rate/state`、`DMA stall timeout/recovery`、`S2MM error`、`MM2S error`；如果前 8 包内还有详细日志，也要复制 `S2MM start/done`、`S2MM rx_head`、`S2MM tx_head`、`S2MM rx_hdr`、`S2MM payload_magic`、`S2MM air0`、`LB UDP sent`。如果涉及 PC 端回传验证，还要让用户复制接收 GUI 日志里的 `RX target registered ...`、AIR0 的 `PROGRESS rx=... crc=... len=... gaps=... air=... air_rx=... pending_air=... bad_hdr=... bad_payload=... bad_meta=... dup=... got_last=...`、`INCOMPLETE ... missing_seq=... bad_payload_seq=... bad_meta_seq=...`、`DONE ... gaps=... air=... air_rx=... miss=... file_crc=... file_id=... file_size=... total_packets=... got_last=... saved=... missing_seq=... bad_payload_seq=...`，以及 AIRV 的 `VIDEO frame_rx=... frame_show=... frame_drop=... frag_rx=... frag_missing=... bad_hdr=... bad_meta=... bad_frag_crc=... bad_frame_crc=... keyframe_rx=... waiting_keyframe=... fps=... latency_ms=...`、`VIDEO_FRAME ...`、`VIDEO_DONE ...`、`DONE VIDEO ...` 行。
- 回答用户测试步骤时，用中文、直接、具体；避免给一长串命令让用户自行转换。

## 当前工程定位

- 主工程：`AD9361_test2`
- 开发环境：`Xilinx SDK 2018.3`
- 目标平台：`Zynq-7000 + AD9361`
- 主链路：PC UDP -> PS lwIP RAW UDP -> DDR 聚合块 -> AXI DMA MM2S -> PL `tx_intf/openofdm_tx` -> AD9361 TX -> SMA 线直连 -> AD9361 RX -> PL OFDM RX -> AXI DMA S2MM -> PS UDP 回传
- 默认网络：`192.168.1.50:5001`
- 串口：`115200`

## 常看文件

```text
README.md
    唯一完整项目说明。

AD9361_test2/src/app/main.c
    板端启动、AD9361/openofdm 寄存器初始化、主循环。

AD9361_test2/src/app/app_config.h
    cache、DMA buffer、IP 地址。

AD9361_test2/src/drivers/net/net_config.h
    UDP 端口、协议 flag、ACK 状态、聚合块大小和队列参数。

AD9361_test2/src/drivers/net/net_rx.c
    UDP 接收、session reset、顺序控制、ACK、聚合、DMA 调度。

AD9361_test2/src/drivers/net/net_protocol.h/.c
    应用协议结构和 CRC32。

AD9361_test2/tools/pc_sender/sender_core.py
    PC 发送协议、滑动窗口、重传、Payload CRC32、AIR0 payload header。

AD9361_test2/tools/pc_sender/send_data.py
    CLI 入口。

AD9361_test2/tools/pc_sender/sender_gui.py
    Tkinter GUI。

AD9361_test2/tools/pc_sender/receiver_core.py
    PC 接收核心；RXCFG 注册回传目标、loopback 分片接收、CRC 检查、文件恢复。

AD9361_test2/tools/pc_sender/recv_data.py
    接收 CLI 入口。

AD9361_test2/tools/pc_sender/receiver_gui.py
    接收 Tkinter GUI；AIRV 预览窗口默认 1280x720，主窗口保留日志和预览指标。

AD9361_test2/tools/pc_sender/video_protocol.py
    PC-only AIRV 64 字节头、H.264 Annex-B 粗分帧和实时视频分片封装。

AD9361_test2/tools/pc_sender/video_receiver_core.py
    AIRV 实时组帧、坏 CRC 计数、缺片 drop、VIDEO 指标和 assembled frame 事件。

AD9361_test2/tools/pc_sender/video_playback.py
    AIRV 预览解码器；PyAV/Pillow 可选依赖、H.264 解码、Tk 可显示图像转换。
```

## Project agent instruction source

- If the repository root contains `AGENT.md`, `Agent.md`, or `AGENTS.md`, use that root file as the project agent instructions. Prefer the repository root agent file over user-level files under `C:\Users\29143\.codex\` for project-specific behavior.

## 调参边界

- 当前 `NET_AGG_BLOCK_BYTES = 3000`，不是旧文档里的 64 KiB。DDR 中每个聚合 slot 的有效 payload 是 3000 字节，但 `NET_AGG_BLOCK_STRIDE_BYTES = 3008`，队列深度为 697；stride 必须保持 cache-line 对齐，避免相邻 DMA slot 共享 cache line。
- 默认 `Chunk Bytes = 1440` 且发送 GUI 默认开启 `AIR0 Packet Header`。开启 AIR0 时，每包 wire payload 仍为 `1440`，其中 `64` 字节是 PC-only AIR0 头，最多 `1376` 字节是原始文件/测试 payload。PS/PL 不解析 AIR0。关闭 AIR0 后每包 wire payload 为原始文件/测试 payload。
- AIRV 模式也保持 `Chunk Bytes = 1440`，每包 wire payload 为 `64` 字节 AIRV 头、最多 `1376` 字节 encoded video fragment 和零填充。发送端选择 MP4 时会自动在同目录查找同名 `.h264/.264`；已有 sidecar 时直接复用，不再对 MP4 做耗时 `ffprobe`，日志显示 `fps_source=sidecar_fallback` 并按 30fps 写入 PTS；找不到 sidecar 时才用最多 2 秒的 `ffprobe` 探测帧率并调用 `ffmpeg` 生成同名 `.h264`。自动生成的 `.h264` 会插入 AUD 分隔符；接收端分帧也会用 slice header 避免多 slice 帧被过度计数。不要再要求用户手工准备 H.264 裸流。
- AIRV 接收日志里的 `fps` 是按 AIRV `pts_us` 估算的源帧率，不是 Python 处理瞬时速度；`latency_ms` 是接收端本帧首片到组齐的最近一次可报告耗时，最终日志会保留上一条非零值以避免 idle finish 后显示 `0.0` 误导，`latency_avg_ms` / `latency_max_ms` 是组帧平均/最大耗时，不是严格端到端空口时延。
- AIRV 预览依赖可选 `av` 和 `Pillow`。接收 GUI 会打开独立 `AIRV Preview` 窗口，默认 `1280x720`；后台线程解码，Tk 主线程约 30fps 刷新。预览输入队列最多缓存 240 个 assembled encoded frame，按 H.264 顺序送入解码器；队列满时才丢弃预览队列并等待下一帧 keyframe。`Preview Input`、`Preview Backlog`、`Preview Drops`、`Decoded`、`Displayed`、`Decoder Errors`、`Waiting Key` 是预览指标，其中 `Displayed` 表示实际渲染到 Tk 预览窗口的帧数；预览丢帧不代表 AIRV 传输丢包。
- PS 侧 `NET_MAX_PAYLOAD_BYTES = 3000`。开启 AIR0 时 `Chunk Bytes` 必须大于 64，且 wire payload 不能超过 3000。
- 当前默认启用 I-cache 和 D-cache。MM2S 发送前必须 flush DMA buffer；S2MM 完成后必须 invalidate。不要把 DMA buffer slot 设成非 cache-line 对齐，64 MiB/window 16 压测曾暴露出相邻 3000 字节 slot 共享 cache line 后的偶发回传差异。
- GUI 默认应开启 `Payload CRC32`。64 MiB/window 16 压测曾观察到少量 PC->PS `bad_crc`，开启后坏包会被 PS 拒收并由发送端重传；不开 CRC 时坏包可能进入 PL 并表现为接收端 CRC/内容错误。
- 发送 GUI 的 `Busy Retries`、`Pending Retries`、`Recoverable Errors` 是可恢复重传统计，不是最终文件错误。判断文件是否完整，以发送端 `app_ack == total_size` 和接收端 `rx/high == file_size`、`gaps=0`、`crc=0`、`len=0` 为准。
- OK ACK 默认合并：8 包或 1000 us；非 OK ACK 立即发送。
- 当前已开启 AD9361 RF 回环后的 PL->PS S2MM 调试和 UDP 回传，默认 `NET_LOOPBACK_RETURN_SOURCE=NET_LOOPBACK_RETURN_SOURCE_S2MM`：每次 MM2S 前 arm `8192` 字节 S2MM 捕获窗口，完成后扫描前 `2048` 字节 AIR0/AIRV magic，跳过 RX 前缀，按聚合块真实 `payload_len` 比较 RX payload 和 TX buffer；`tx_transfer` 只是 8 字节对齐后的 DMA 长度，尾部 padding 不参与 payload 比较。随后 PS 用 magic `0x304B424C` 的 loopback UDP 包把 payload 分片发回已注册的接收 GUI/CLI。当前加了 `NET_DMA_STALL_TIMEOUT_US = 6000` 的发送/RF 回环 watchdog：真实空口 RX 或 S2MM 不完成时会打印 `DMA stall timeout ... rx_state=... wd=...` 和 `DMA stall recovery ...`，重置 AXI DMA、释放当前聚合块并继续下一块，不再让接收端无信号把 PC 发送端拖到 `BUSY` 重试耗尽。
- 上一轮 `NET_LOOPBACK_RETURN_SOURCE_TX_BUFFER` 诊断已证明 PC 发送、PS 接收/聚合、PS UDP 回传和 PC 接收恢复正常；该模式仅作为以后排查 PC/PS 侧时的临时开关，平时不要保持启用。
- 由于当前 TX/RX 已解耦，S2MM 收到的帧不一定对应当前刚送入 MM2S 的聚合块。PS 侧 `S2MM diag` 会输出 `class=OK|NO_AIR_MAGIC|AIR_MAGIC_SHIFT|AIR_MAGIC_PAYLOAD_DIFF`、`best_off/best_xor/best_bits`、`rx0/rx_payload0/tx0`、`rx_crc/tx_crc`、`rx_state` 和 `wd` 计数；若识别到 AIR0，会打印 `S2MM air0 ... desync=...`，并用 AIR0 `packet_seq * chunk_bytes` 推导 UDP 回传 `stream_offset`，避免把延迟堆积的 RX 帧错误标成当前 TX block offset。
- 为兼顾定位和 UART 压力，当前默认 `NET_LOOPBACK_S2MM_LOG_FIRST_BLOCKS=8`、`NET_LOOPBACK_S2MM_LOG_INTERVAL_BLOCKS=0`、`NET_LOOPBACK_S2MM_LOG_DIFF_ALWAYS=0`，同时 `NET_LOOPBACK_S2MM_SUMMARY_FIRST_BLOCKS=16`、`NET_LOOPBACK_S2MM_SUMMARY_DIFF_ALWAYS=1`。也就是说前 8 包有详细 dump，前 16 包和后续异常包有一行摘要。
- MM2S 启动前必须先 `OpenWifi_Tx_Rearm(payload_len)`，再调用 `net_configure_tx_frame()` 写最终 `tx_intf` 帧长、DMA word 数和 auto-start threshold。不要把 re-arm 放在配置之后；否则某些短帧长度会覆盖并清掉 auto-start enable，表现为 `S2MM wait ... txdone=0 rxdone=0`。

## 当前推荐 GUI 测试设置

```text
Mode                    Test Data
Test Bytes              16384
Chunk Bytes             1440
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
AIR0 Packet Header      checked
Verbose Packet Events   unchecked
Progress ms             1000

Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

这一组用于小数据量回环确认。AIR0 模式下接收端会从 AIR0 头读取 `file_size`、`total_packets` 和 `file_crc32`，`Raw Expected` 保持 `0`，不要再要求用户预填文件大小。先启动接收 GUI 并等待 `RX target registered ...`，再启动发送 GUI。预期板端串口出现 `RXCFG loopback peer`、`Loopback UDP return ready`、`S2MM done ... cmp=OK`、`LB UDP sent ...`，接收 GUI `DONE` 行中 `rx=16384` 且 `crc=0 len=0 gaps=0`。

## 当前推荐 AIRV GUI 测试设置

```text
Sender Transfer Mode    airv_video
Sender Mode             File
Sender file             MP4 video or H.264 Annex-B elementary stream
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

AIRV 用于验证实时组帧、实时预览和统计，不保存精确恢复文件。预期接收 GUI 出现独立 `AIRV Preview` 窗口，`Preview Input`、`Decoded`、`Displayed` 持续增长；日志中 `VIDEO ... frame_drop=0 frag_missing=0 bad_hdr=0 bad_meta=0`，结束时出现 `DONE VIDEO ...`。

## 常用验证命令

```bash
rtk git status --short
rtk git diff -- README.md AGENTS.md
rtk rg --files -g "*README*" -g "*readme*"
rtk grep "NET_AGG_BLOCK_BYTES|NET_MAX_PAYLOAD_BYTES|DATA_FLAG|AIR0" AD9361_test2/src AD9361_test2/tools/pc_sender
```

本环境通常没有 Xilinx SDK 命令行工具，因此无法在普通 shell 中完整构建 SDK 工程。若任务涉及 C 代码行为，至少做静态核对；真正构建和板级验证需要在 Xilinx SDK 2018.3 与目标板上完成。
