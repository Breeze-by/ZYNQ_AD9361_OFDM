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
- 用户主要使用 GUI 发送程序 `AD9361_test2/tools/pc_sender/sender_gui.py`，不要用 CLI 命令作为测试指令。需要用户跑测试时，直接给 GUI 中的字段设置，例如 `Mode`、`Test Bytes`、`Chunk Bytes`、`Window Size`、`Throughput Mode`、`Payload CRC32`、`RF Strict Match + Retry (max 3)`、`AIR0 Packet Header` 等。
- 旧版额外封装和测试 pattern 选项已从 PC/PS/文档移除，以后不要再建议用户使用相关 GUI 字段或 CLI 参数。PC->PS 应用层包头后始终是普通 wire payload；PL 不解析内容，PS 仅在 S2MM 回传时读取捕获块起始的 AIR0/AIRV v2 头以恢复全局 `stream_offset`，不做文件恢复、视频组帧或解码。
- 当前 AIRV 实时视频模式已支持接收 GUI 独立 `AIRV Preview` 窗口、后台 PyAV 解码和预览队列。AIR0 仍是精确文件/测试数据恢复模式；AIRV 是实时视频组帧/预览/统计模式，不保存精确文件，不做接收端 ACK、重传、FEC 或音频。PL 不解析 AIR0/AIRV；PS 不组帧，但会读取 AIR0/AIRV v2 的全局包序号以恢复 S2MM 回传偏移。
- AIRV 接收器允许开头 S2MM block 丢失后从第一个完整 AIRV chunk 中途接入，日志打印 `VIDEO_DIAG late_attach initial_missing=...`；随后等待 H.264 keyframe 恢复预览。AIR0 仍要求 offset 0 起始连续，不能用该行为掩盖精确文件缺失。
- AIRV 流中间出现完整 chunk 级缺口时，接收器会在下一段通过 chunk 对齐和 AIRV magic 校验后打印 `VIDEO_DIAG gap_skip ...`，只丢弃跨缺口未完成帧并继续按序交付后续完整帧；连续 3 次解码失败才等待 keyframe。`VIDEO stream_gap=...` 累计跳过字节。AIR0 不跳过流中缺口。
- AIRV 接收 GUI 每两秒最多输出 `VIDEO_PREVIEW input/backlog/drops/decoded/rendered/decoder_errors/waiting_key/images/skipped/error`，结束时输出 `VIDEO_PREVIEW_DONE`；逐分片、逐坏帧日志已关闭，用周期 `VIDEO` 和最终汇总看 CRC/丢帧，避免日志影响处理性能。
- 接收 GUI 主窗口已改为紧凑双列布局：Network/Output 参数和 Metrics 都按两列排列；Charts 与 Event Log 位于可上下拖动的纵向分隔区，避免顶部字段把日志挤出窗口。AIRV Preview 仍是独立窗口。
- 接收 GUI 的 `RX Rate (1s)`、RX KiB/s 图和 Packets/s 图使用最近 1 秒滑动窗口，按窗口内累计字节/包数差值计算；不得再改回从点击 Start 起算的累计平均值。第一批数据前不出速率点，停止收包约 1 秒后应回落到 0。
- 发送 GUI 也支持在传输前独立广播 `IPCFG`，不会发送 `RXCFG`、不会注册或覆盖回传目标。只运行发送 GUI 的电脑切换板端网段时，应填写直连网卡的 `PC Bind IP`、目标 `Target IP`、掩码/网关并勾选 `Configure Board IP by broadcast`；不应借用接收 GUI 改址，因为接收 GUI 默认还会发送 RXCFG。
- 发送 GUI 也已改为紧凑布局：Source/Network/Metrics 尽量按双列排列，Charts 与 Event Log 位于可上下拖动的纵向分隔区；默认窗口和最大化窗口都应保留两者的可见空间。
- 当前 SDK 默认 `APP_RX_SOURCE=APP_RX_SOURCE_AD9361`，走真实 AD9361 TX -> SMA -> AD9361 RX 链路；PL 数字回环保留为 `APP_RX_SOURCE_DIGITAL_LOOPBACK` 诊断选项。启动日志必须打印当前 RX source。板级调试继续分阶段做；先加可观察日志，让用户上板跑并回传串口输出，再根据日志继续改。
- PS DMA 已改为单/双板通用的独立调度：显式 RXCFG 注册后持续 arm/re-arm S2MM，接收不依赖本机 TX block；MM2S 完成后独立释放 TX block，不等待本地 S2MM。没有 RXCFG 的纯发射板不 arm S2MM；只有 RXCFG、没有本机发送数据的纯接收板也能回传合法 AIR0/AIRV 帧。同一份 ELF 支持单板同时收发和两板分别收发。
- 板端每次上电仍以 `192.168.1.50/24` 启动；接收和发送 GUI 都能通过全局广播发送 `IPCFG`，把各自直连板卡的 IP/掩码/网关临时切换到另一网段，配置不写 flash，重启恢复 `192.168.1.50`。双网卡电脑做 IPCFG 时必须把 GUI 的 Bind IP 明确填成直连 Zynq 的 PC 网卡地址，不能用 `0.0.0.0`。新电脑接收 GUI 使用 `Bind IP=192.168.2.101`、`Board IP=192.168.2.50` 并勾选 IPCFG 和 RXCFG；只运行发送 GUI 时使用 `PC Bind IP=192.168.2.101`、`Target IP=192.168.2.50`、`Board Netmask=255.255.255.0`、`Board Gateway=0.0.0.0` 并勾选 `Configure Board IP by broadcast`。旧电脑仍可使用 `192.168.1.101 -> 192.168.1.50`，无需改板端默认代码。
- 当前默认走真实 `NET_LOOPBACK_RETURN_SOURCE_S2MM` RF/S2MM 回传路径，不再是 `TX_BUFFER` 诊断模式。需要用户反馈时，优先要接收板的 `RXCFG loopback peer`、`S2MM valid`、`S2MM RX stat`、`S2MM error`，发送板的 `UDP RX reset`、`STAT rate/state`、`DMA stall timeout/recovery`、`MM2S error`。如果涉及 PC 端回传验证，还要让用户复制接收 GUI 日志里的 `RX target registered ...`、AIR0 的 `PROGRESS rx=... crc=... len=... gaps=... air=... air_rx=... pending_air=... bad_hdr=... bad_payload=... bad_meta=... dup=... got_last=...`、`INCOMPLETE ... missing_seq=... bad_payload_seq=... bad_meta_seq=...`、`DONE ... gaps=... air=... air_rx=... miss=... file_crc=... file_id=... file_size=... total_packets=... got_last=... saved=... missing_seq=... bad_payload_seq=...`，以及 AIRV 的周期 `VIDEO ...`、`VIDEO_PREVIEW ...`、最终 `VIDEO_DONE`、`VIDEO_PREVIEW_DONE`、`DONE VIDEO ...` 行。
- 回答用户测试步骤时，用中文、直接、具体；避免给一长串命令让用户自行转换。

## 当前工程定位

- 主工程：`AD9361_test2`
- 开发环境：`Xilinx SDK 2018.3`
- 目标平台：`Zynq-7000 + AD9361`
- 主链路：PC UDP -> PS lwIP RAW UDP -> DDR 聚合块 -> AXI DMA MM2S -> PL `tx_intf/openofdm_tx` -> AD9361 TX -> SMA 线直连 -> AD9361 RX -> PL OFDM RX -> AXI DMA S2MM -> PS UDP 回传
- 上电默认网络：`192.168.1.50:5001`；可由接收 GUI IPCFG 临时切换到与直连 PC 网卡相同的 `/24` 网段
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
    PC 接收核心；IPCFG 运行时板端改址、RXCFG 注册回传目标、loopback 分片接收、CRC 检查、文件恢复。

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

- 2026-09-07第八轮用户明确要求把TX独立时钟合并回原工程。当前原 `.xpr/.bd` 已包含
  FCLK3约41.667 MHz、TX DAC/FIFO3写时钟和新 `rst_tx_transport`；RX仍FCLK2=40 MHz。
  第二轮“原工程未改”已成为历史说明，不要再告诉用户原工程没有这项改动。
  仅合并连接和修正ROM路径，不加入第五/六轮仪表，不改SDK C/BSP/ELF或RF参数，不烧录板卡。
  原profile bit/HDF/PS初始化继续保留；从原工程新生成的bit须与新导出HDF/PS初始化匹配并重新回归。
- 原硬件文件位于SDK Git仓库之外；仓库内 `hardware_profiles/sma_20260906/merge_into_project.tcl`
  保存可复现合并步骤，执行前关闭对应Vivado工程，脚本要求全新报告目录并备份源文件。
  三个ROM的源XCI采用 `../name.coe`，XPR中旧AD9361_test2_ofdm重复引用已移除；
  要 `reset_target all` 后重新生成BD，单改源XCI而不刷新生成副本会继续使用旧路径。
  本轮远程有一次SSH返回中断，之后已取回两机完整生成完成日志，不能将首次失败日志作为最终结果。
  本地未安装Vivado，仅做源设计语义对照和36项PC测试；原工程的原生验证在两台2018.3电脑进行。
  两机重新打开验证成功（TX日志stage8-reopen-b，RX日志stage8-reopen），综合/实现NEEDS_REFRESH=1；
  本地/两机BD与第二轮已实测BD语义一致。硬件合并不是重新调参，不保证新布局布线零丢包或时序收敛。
- 2026-09-07 用户明确要求固化63及关联计数门槛。当前默认以本条和第七轮为准：
  `main.c::OPENOFDM_RX_MIN_PLATEAU_RF=63U`，PL原 `min_plateau>>2` 自动派生15，原比较 `>15` 保留，
  不要再恢复64，也不要将15硬编码到RTL；数字回环100/25不变。启动读回失败会报FATAL，
  日志 `sign_min_derived=15` 是软件从reg3计算的值，不是内部计数器实测。只改源码/ELF，不刷Flash/SD。
- 2026-09-06 YunSDR 320 双板 SMA 直连（无外串固定衰减器）实测配置：LO 2.2 GHz、RX MGC 36 dB；发射板 TX 衰减 25 dB，接收板自身 TX 衰减 30 dB 保留。RF 模式的 OFDM reg1=0x101（short-sync 0.75）、reg2=0x00300000（DC 48/RSSI 0）、reg3=64，数字回环保留原检测值。1024 字节短帧显著降低视频 payload CRC 错误并成功解码；重编译下载后 GUI 流程实测 decoded=275、rendered=85、decoder_errors=0，但仍丢失 16/3930 个分片并有 4 次 fragment/frame CRC 错误，不能宣称无损或长帧根因完全修复。768 字节对照没有总体改善，不作为默认。不要再盲目降低衰减；没有实测依据不要改采样率、PL 时序或时钟延迟。
- 用户已授权远程编译、JTAG 下载和链路测试，两台电脑使用 Vivado/SDK 2018.3；变更前备份各自源码和 ELF，保留各自 TX 衰减及无关未提交改动。不要把远程登录凭据写入仓库。新版默认分包改为 1024 后，应重启发送 GUI 或明确修改旧窗口的 Chunk Bytes；Rate Limit 保持用户要求的 400。
- 当前 `NET_AGG_BLOCK_BYTES = 1024`，使默认一个 AIR0/AIRV wire chunk 对应一个 OFDM PSDU，避免 2880 字节长帧一次损坏两个 AIR 包。DDR 中每个 slot 的有效 payload 是 1024 字节，`NET_AGG_BLOCK_STRIDE_BYTES = 1024`，队列深度为 2048；stride 必须保持 cache-line 对齐，避免相邻 DMA slot 共享 cache line。
- 默认 `Chunk Bytes = 1024` 且发送 GUI 默认开启 `AIR0 Packet Header`。开启 AIR0 时，每包 wire payload 仍为 `1024`，其中 `64` 字节是 PC-only AIR0 头，最多 `960` 字节是原始文件/测试 payload。PS/PL 不解析 AIR0。关闭 AIR0 后每包 wire payload 为原始文件/测试 payload。
- AIRV 模式也保持 `Chunk Bytes = 1024`，每包 wire payload 为 `64` 字节 AIRV v2 头、最多 `960` 字节 encoded video fragment 和零填充。v2 在偏移 58 增加全局 `packet_seq`，PS 校验头 CRC 后用 `packet_seq * chunk_bytes` 恢复延迟 RF 帧的 UDP `stream_offset`；必须同时使用新版 ELF 和新版 PC 工具。发送端选择 MP4 时会自动在同目录查找同名 `.h264/.264`；已有 sidecar 时直接复用，不再对 MP4 做耗时 `ffprobe`，日志显示 `fps_source=sidecar_fallback` 并按 30fps 写入 PTS；找不到 sidecar时用最多 2 秒的 `ffprobe` 探测帧率并调用 `ffmpeg` 生成同名 `.h264`。新生成文件固定约每秒一个 IDR、无 B 帧、带 AUD、重复 SPS/PPS；旧 sidecar 的 GOP 不受保证，需要统一恢复上限时删除后重新生成。不要再要求用户手工准备 H.264 裸流。
- AIRV 接收组帧器按递增 `frame_seq` 输出，保留最多 3 帧乱序深度；缺片只丢所属帧并继续释放后续完整帧，坏 fragment/frame CRC 的完整帧仍交给 PyAV，允许局部马赛克。预览解码连续 1～2 次 P 帧异常继续尝试，连续 3 次才重置等待 IDR。不要把单帧缺失改回立即等待 keyframe。
- AIRV 接收日志里的 `fps` 是按 AIRV `pts_us` 估算的源帧率，不是 Python 处理瞬时速度；`latency_ms` 是接收端本帧首片到组齐的最近一次可报告耗时，最终日志会保留上一条非零值以避免 idle finish 后显示 `0.0` 误导，`latency_avg_ms` / `latency_max_ms` 是组帧平均/最大耗时，不是严格端到端空口时延。
- AIRV 预览依赖可选 `av` 和 `Pillow`。接收 GUI 会打开独立 `AIRV Preview` 窗口，默认 `1280x720`；后台线程解码，Tk 主线程约 30fps 刷新。预览输入队列最多缓存 240 个 assembled encoded frame，按 H.264 顺序送入解码器；队列满时才丢弃预览队列并等待下一帧 keyframe。`Preview Input`、`Preview Backlog`、`Preview Drops`、`Decoded`、`Displayed`、`Decoder Errors`、`Waiting Key` 是预览指标，其中 `Displayed` 表示实际渲染到 Tk 预览窗口的帧数；预览丢帧不代表 AIRV 传输丢包。
- PS 侧 `NET_MAX_PAYLOAD_BYTES = 1024`。开启 AIR0 时 `Chunk Bytes` 必须大于 64，且 wire payload 不能超过 1024。
- 当前默认启用 I-cache 和 D-cache。MM2S 发送前必须 flush DMA buffer；S2MM 完成后必须 invalidate。不要把 DMA buffer slot 设成非 cache-line 对齐；旧 3000 字节 slot 的压测曾暴露相邻 slot 共享 cache line 后的偶发回传差异。
- 当前 AD9361/PL 速率契约是 2R2T LVDS `40 MSPS`、DATA_CLK 约 `160 MHz`；当前源码设置 `tx_fb_clock_delay=7`，启动时强制校验寄存器读回 `0x70`。不要只在 SDK 改采样率或 delay 而不同时检查 PL bridge、XDC 和板上读回日志。
- GUI 默认应开启 `Payload CRC32`。64 MiB/window 16 压测曾观察到少量 PC->PS `bad_crc`，开启后坏包会被 PS 拒收并由发送端重传；不开 CRC 时坏包可能进入 PL 并表现为接收端 CRC/内容错误。
- 发送 GUI 的 `RF Strict Match + Retry (max 3)` 仍保留但默认关闭。独立 TX/RX 调度无法在两块板之间把接收帧对应到发射板当前 TX block，也没有反向 RF ACK，因此双板和通用模式测试必须保持该项关闭；合法 AIR0/AIRV 帧按自身头部序号回传，错误由 PC 接收端统计。后续若要恢复跨板 RF 重传，需要另行设计接收板到发射板的反馈协议，不能复用旧的本地 block compare。
- 发送 GUI 的 `Busy Retries`、`Pending Retries`、`Recoverable Errors` 是可恢复重传统计，不是最终文件错误。判断文件是否完整，以发送端 `app_ack == total_size` 和接收端 `rx/high == file_size`、`gaps=0`、`crc=0`、`len=0` 为准。
- OK ACK 默认合并：8 包或 1000 us；非 OK ACK 立即发送。
- 当前已开启 PL->PS S2MM 调试和 UDP 回传，默认 `NET_LOOPBACK_RETURN_SOURCE=NET_LOOPBACK_RETURN_SOURCE_S2MM`：RXCFG 后独立 arm `8192` 字节 S2MM 捕获窗口，完成后扫描前 `2048` 字节 AIR0/AIRV magic，跳过 RX 前缀，并用 AIR0/AIRV v2 全局包序号恢复 `stream_offset` 后回传。RF 静默时 S2MM 可以无限等待，不再使用 50 ms TX watchdog误判；`NET_DMA_STALL_TIMEOUT_US = 50000` 只监控 MM2S。单板存在当前 TX block 时保留 compare 诊断，但 frame validity 不依赖 TX block。
- `S2MM valid` 的 `wait_us` 表示 arm S2MM 到主循环观察到 `RxDone` 的时间，其中包含主循环调度延迟；独立 RX 空口静默不受 MM2S 的 50 ms watchdog 约束。
- 上一轮 `NET_LOOPBACK_RETURN_SOURCE_TX_BUFFER` 诊断已证明 PC 发送、PS 接收/聚合、PS UDP 回传和 PC 接收恢复正常；该模式仅作为以后排查 PC/PS 侧时的临时开关，平时不要保持启用。
- S2MM 收到的帧不一定对应本机当前 MM2S 聚合块；纯接收板没有 TX block 是正常情况。AIR0 和 AIRV v2 都用各自的全局 `packet_seq * chunk_bytes` 推导 UDP 回传 `stream_offset`；紧凑 `S2MM valid` 会报告类型、序号、偏移和长度，无效结构仅进入低频累计 `S2MM RX stat`。
- 为降低 115200 UART 对 PS/lwIP/DMA 主循环的影响，当前默认不再打印前若干任意 S2MM 捕获的详细 dump，也不逐帧打印结构 reject。首 2 个真正通过 AIR0/AIRV 头 CRC 校验的捕获在下一次 S2MM 已 arm 后打印紧凑 `S2MM valid`；无效捕获每 10 秒最多汇总一行 `S2MM RX stat captures/valid/reject/len/no_magic/shift/header/last_seq/seq_gap/seq_back`。无效路径不计算仅供详细诊断使用的近似 magic、payload CRC 和 watchdog dump。DMA/RF 错误与周期 STAT 仍保留，周期 STAT 也必须放在 S2MM 重装之后打印。
- MM2S 启动前必须先 `OpenWifi_Tx_Rearm(payload_len)`，再调用 `net_configure_tx_frame()` 写最终 `tx_intf` 帧长、DMA word 数和 auto-start threshold。不要把 re-arm 放在配置之后；否则某些短帧长度会覆盖并清掉 auto-start enable，表现为 `S2MM wait ... txdone=0 rxdone=0`。

## 2026-09-06 第二轮实验硬件配置

- 当前两台在线板的实验配置来自 `hardware_profiles/sma_20260906/`：独立 FCLK3=41.667 MHz
  驱动 TX DAC 搬运/FIFO3 写端及相应复位，RX FCLK2 保持 40 MHz，AD9361 仍是 40 MSPS / 160 MHz LVDS。
  不要把这解释为修改 AD9361 采样率；不要把 RX FCLK2 也提高，该对照未正常收包。
- 新 bitstream 已用 Vivado 2018.3 全量构建，SHA256 为
  `B6BB2F00CAE94A3C9DC7B11777E5D751C68BF6BA8C3C8A6D4D927003069FCA71`。
  原默认硬件平台和主工程保留，实验配置独立存放；用配套 `download.tcl` 下载本机原 ELF，
  不要混用默认旧 bit / PS 初始化。没有写 flash/SD，也没有改 COMMON.c 或启用 RF 重传。
- 两端新硬件 16+32 MiB 随机源共 52430 包、缺 224（约0.427%）；收到的 50,116,608 字节逐字节正确。
  原时钟 8 MiB 有 6 个坏 payload / 15507 个 bit 错误；新配置缓解了包内错误，但不能宣称
  整包丢失率显著改善、全文件无损或任意时长零误码。核心视频复测 3909/3930 分片、283 组帧、166 解码，CRC/解码异常 0。
  最终配套下载脚本在双板重载后的隐藏 GUI 流程为 3905/3930 分片、284 组帧、212 解码、79 绘制，CRC/解码异常 0；不是原用户窗口的截图。
- 短 I/Q 窗口粗估 SNR 38.02～38.66 dB，不是校准仪表、EVM/SINR 或真实 RSSI；RSSI 输入仍为 0。
  全设计时序仍未收敛，LVDS 约束延时模型、内部 Fc=2400 与实际 LO=2200 的遗留差异仍待处理。
  新时钟内部路径有余量不等于整个设计已通过时序签核。完整记录只维护根 README。
- 额外包间隔、RX 增益30、DC watchdog关闭、重装前后100us等待均未显示改善，不保留。
  `stage2-fastpl-p68-random8m` 的参数写入被脚本拒绝，实际仍为64，不能把该日志当68测试。

## 2026-09-06 第三轮对照与保留基线

- 用户要求继续尝试无损；若没有可靠改善，保留第二轮已认可的 `sma_20260906` 配置。
- 本轮仅做运行时接收 plateau 对照和临时目录的接收软件候选，不改原 COMMON.c、ELF、bit，
  不加 RF 重传、不改变 400 KiB/s、1024 字节、window 1。基线 ELF/源码/文档另存远端
  `%TEMP%/ad9361-diag-20260906/pre-stage3-backup/`。
- 基线 8 MiB 为 8705/8739，TX accepted/DMA done=8739；RX 有效捕获/UDP成功发送/PC收包=8705。
  该次未发现 RX 板成功回传之后再丢包，不能据此断言全部剩余缺包都在 RF 空口。
- plateau=48 严重变差（158/8739）；60、68、72 未显示明确改善。全部候选未采纳，保留64。
  关闭 S2MM 首帧/拒绝汇总日志的 8 MiB 仍缺40包，另将 net_rx.c 以 O2 编译的 16 MiB 仍缺74包；
  收到数据均逐字节正确，但不能当成无损或认定日志/CPU性能是唯一根因。原软件日志及编译方式保留。
- 候选文件、测试日志均为远端临时目录 `stage3-` 前缀，不能用其中 candidate.elf 作为正式下载文件。
  当前正式下载方式仍是 `hardware_profiles/sma_20260906/download.tcl`；完整记录仅在根 README。
- 结束时两端均重新执行正式下载脚本恢复基线，ELF、COMMON.c、net_rx.c、net_config.h 与本轮开始备份一致。
  隐藏 GUI 视频回归 3915/3930 分片、294 组帧、10 缺片丢帧、223 解码、72 绘制，CRC/解码异常0。
  本轮没有正式代码或硬件变更，仅更新测试记录；不要把实验候选留作用户继续测试的运行版本。

## 2026-09-06 第四轮：晶振频偏优先排查

- 用户要求继续定位根因，优先查晶振频偏。本轮完成载波频偏测量/LO 对照，唯一根因尚未闭环；
  不要把“有频偏”说成“频偏就是丢包根因”，也不要把丢包描述成 SMA 双板必然现象。
- 基线 8 段短前导相关估计 CFO 均值约 +1025 Hz（短窗口离散约 778 Hz），仅相当于约0.47 ppm
  的相对载波误差，不是校准晶振测量。RX LO +1 kHz 后估计约 -58 Hz，却缺281/8739包；
  基线两轮分别缺40、42包。改变 LO 没有改变采样频率，尚未直接测量/排除 SFO。
- 关闭 I/Q 正交跟踪的临时候选严重恶化，不保留，不能据此认定跟踪为原丢包原因。
  只提高 RX 搬运时钟虽使该次短 ILA 窗口 ready 恒高，仍缺134/2185包，不保留。
  FIFO ready 为低不等于真正丢 ADC 样本，必须计数 `adc_valid && m_axis_tvalid && !m_axis_tready`。
- reg18=0x1FFFF，不支持“CFO 超 watchdog 门限拒包”；整数相位补偿每步约6.217 kHz，
  读回0不等于真实零频偏。Fc=2400/实际LO2200不一致仍待核验，未证实为剩余缺包根因。
- 本轮没有重新生成 bitstream 或保留任何软件/寄存器候选。接收板已重新执行正式下载脚本恢复
  原 ELF、LO 和 RX FCLK2=40 MHz；发送板保持原稳定配置。最终隐藏 GUI 回归3912/3930分片、
  291组帧、231解码、79绘制，CRC/解码错误0；原视频仍不完整。
- 第四轮完整数据仅维护根 README；临时记录在远端 `%TEMP%/ad9361-diag-20260906/`。
  下一层需要 TX 实际发帧、RX STF/LTF/SIGNAL/FCS 和 ADC 真溢出计数才能进一步划分损失环节；
  本轮没有添加这些计数器，不能称已定位到某个确定 RTL 模块或某块晶振。

## 2026-09-06 第五轮：物理层计数与 ADC 速率差

- 用户要求继续定位根因。本轮已构建并临时上板分级计数硬件，证实原 RX 40 MHz 时
  `adc_valid && m_axis_tvalid && !m_axis_tready` 持续发生；不是只凭 ready 低判断溢出。
  接收板 AD9361 相对本板 PS 搬运时钟快约5.966 ppm，静默窗口输入193201717样本、丢1153，
  与速率差吻合。这是板内相对差，不是两块 AD9361 的 SFO，也不是校准晶振测量。
- 临时硬件原时钟8 MiB：TX PHY started/done=8739，RX LTF/合法头/FCS成功/PC收包=8690，
  缺49；此次主要缺口在成功LTF之前。TX done不等于已测量RF波形完整性；STF可重复触发。
  首轮2 MiB有FCS成功2178而PC2176，不能说所有轮次下游都绝不丢帧。
- RX搬运41.667和100 MHz均使运行窗口ADC丢弃归零，但前者缺135/2185、SIGNAL/FCS错误增加；
  100 MHz仍缺13/2185、40/8739，不保留。ADC溢出是已证实缺陷，不是已闭环的全部丢包唯一根因。
- `sync_long.v::do_mult`存在多周期计算与过早新strobe重入的源码风险，尚未建立失败帧对应关系。
  下一步需失败前导I/Q、STF/LTF超时与相关器重入证据；不要把风险直接当成已定位根因。
- 临时TX 2000us启动间隔保护8 MiB缺42包，对照缺45，实测原最短间隔1863us，无明确改善，已撤回。
- 诊断 bit SHA256 `C83937056497E3D4779AEEAF140CB760A6E5E1FF277B86ED0BB8D9702A425DAF`，
  独立构建在接收电脑 `E:/by2025/AD9361_test_board/ad9361_diag_stage5b_20260906`；
  只读计数器单元仿真通过。原工程/profile没有覆盖，全设计WNS=-6.280/WHS=-1.721ns仍未收敛。
  临时reg17高位快照/银行、reg22～29和TX reg20仅适用于该bit，不能对原bit照搬计数读法。
- 两板已经重新下载原 `sma_20260906` bit和各自原ELF，TX41.667/RX40 MHz，原RF参数保留。
  第五轮只更新README/AGENTS，不推广候选。日志和脚本在远端临时目录stage5前缀，
  原文件备份pre-stage5-backup；完整结果只维护根README。
- 恢复后隐藏GUI回归3908/3930分片、286组帧、190解码、62绘制；CRC/解码错误0，
  最终串口序号缺口22，仍非无损。原ELF、COMMON.c、net_rx.c、推荐bit哈希未改变。

## 2026-09-06 第六轮：短前导符号比例边界

- 用户本轮要求继续排查根因，未要求固化新修复。已抓到三段有效4096点失败前导：STF/LTF波形到达，
  STF相关约0.9998，主状态停在SYNC_SHORT；窗口内ADC丢弃不变、输入间隔全为5个100MHz时钟。
  三段I路正样本比例25%/25%/75%。源码 `sync_short` 的 `pos_count/neg_count > (min_plateau>>2)`
  存在严格四分之一边界，是本轮重点证据；不要再只凭GUI猜增益或直接认定CFO过大。
- 逐字提取原always块的控制单元仿真，以三段实测符号序列和16种起始位置复现边界：64时每种4/16通过，
  63时16/16通过。相关判据固定通过，未回放真实乘法/FIFO/复位历史，不能夸成完整OFDM仿真。
- 仅临时RX reg3切换：诊断ILA bit下64的8MiB缺28，63的8MiB缺0，回64缺25，再63的16MiB缺0。
  两次63共24MiB/26216包，TX PHY、RX LTF/header/FCS/PC增量一致，落盘文件SHA256及逐字节比较通过。
  63使符号计数门槛16→15，不是RF功率或CRC门限变化；也不能把以前60/68的结果当成测试过63。
- 恢复原推荐bit/原ELF后，64的8MiB缺45，临时63的16MiB仍缺2/17477，收到内容正确。
  改善明显但剩余少量异常尚未闭环；这两轮累计S2MM完成/valid/UDP成功/PC均26169，reject/error/stall0，
  缺口47，不能将剩余2包归因于已观察到的PS长度拒绝。完整后续复测以根README为准。
- 新仪表bit仅在临时stage6-hw-c：SHA F57F114114333A3BD4FCB83ED756CE8ACC8D5250F01E5AA5F1F22D42D834CDFD。
  原41探针ILA保留，新增13端口89bit、100MHz4096深度；全局WNS=-9.374/WHS=-1.722ns未收敛，
  新探针输入setup/hold+2.473/+0.172ns，调试配置通道仍-1.911ns，不推广该bit。
- 本轮原40MHz再次测得板内AD9361/PS速率差+5.999ppm，994个真实ADC丢弃；63没有修复ADC接口。
  `do_mult`控制仿真也复现4拍重入丢计算，但正常捕获无冲突，不是这三段STF漏检的直接证据。
- `stage6-c-timeout8mb_timeout_*.csv`是空数据，不能引用成失败波形；后续加入FULL/4096行校验，
  count128正向触发通过。真正三段失败文件是`stage6-c-shortwait8m_shortwait_0/1/2.csv`。
- 本轮仅更新README/AGENTS；原COMMON.c/ELF/profile未改，没有写flash/SD或增加RF重传。
  新63是已测试的诊断候选，不应未经说明改写当前推荐64。临时脚本、波形、日志以stage6前缀保存，
  原文件备份pre-stage6-backup；两端原工程无关改动必须继续保留。
- 原bit的63再测8MiB全文件一致，两轮63共24MiB/26216包缺2；63隐藏GUI视频3930/3930分片、
  304组帧/解码、100绘制，CRC/decoder errors/preview drops0。不要把这说成任意时长无损。
- 最后两板已恢复原推荐bit、原ELF、reg3=64，TX41.667/RX40MHz及reg1/2读回通过，COM均释放，
  原GUI/Vivado/SDK保留。最终64隐藏GUI3920/3930、294组帧、282解码、98绘制，CRC/解码异常0。
  本轮没有固化63；后续明确说明后可固化初始化参数，写reg3本身不需要重生成bitstream。

## 2026-09-07 第七轮：已授权固化63

- 用户已明确要求将63及关联计数门槛固化。当前源码 `main.c` 的RF默认值已是63，
  写reg3后校验读回并打印`sign_min_derived=15`；该15由原PL `min_plateau>>2`自动派生，
  原 `>` 比较器未改。数字回环100/25不变；不要把15硬编码进RTL或恢复第六轮结束时的64。
- 两台电脑各自原SDK工程已编译新版ELF并配合原sma_20260906 bit/PS初始化下载。启动与JTAG读回
  均为reg1/2/3=0x101/0x00300000/63，TX41.667/RX40MHz不变。COMMON.c及各自25/30dB衰减保留。
  新TX ELF SHA764CF8860063D96DB607D64F5EF6DFE86F528CA76D79F50340E1F74F2B7F1C46，
  新RX ELF SHA456100D66D21DF2AC3CF6F3A24E57B74379A3D6FE9717E910302EAB89398B633。
- 原36项PC单元回归通过。本轮仅改初始化和日志，不修改CRC、协议、重传、RTL或采样时钟。
  旧profile manifest是第二轮历史快照，不参与初始化；当前参数看main.c和启动读回。
- 固化不等于长期无损。首轮8MiB发送8739，收到8734，缺5、收到内容错误bit0；SSH会话断开后
  已重连取回完整RESULT/WIRE_CHECK，不能报告此轮零丢包。完整后续数据以根README第七轮为准。
- 随后16MiB收到17475/17477，缺2、错误bit0；两轮共24MiB缺7/26216。保留新63配置，
  不要把收到内容正确解释为缺包已全部解决，也不要为此恢复64或开启RF重传。
- 最终隐藏GUI视频3930/3930分片、304完整组帧和解码、104绘制，CRC/decoder errors/preview drops0。
  本地工作区ELF同步为TX25dB构建，远程各机保留各自25/30dB构建，避免跨机混用ELF。
- 回归后再次读回63及原时钟/检测参数通过，新ELF和保留文件哈希核对通过，串口已释放，
  原GUI/Vivado/SDK保留；板卡最终运行的是新63，不是上一轮的64。
- 原文件备份pre-stage7-p63-backup，日志stage7前缀，位置仍为远端ad9361-diag-20260906临时目录。
  ELF地址可能变化，禁止照用按旧ELF固定地址的stage6_ps_counts.tcl。没有刷Flash/SD，断电后
  仍按原流程下载新版ELF；这次程序默认值已经固化，不再是临时调参、也不再恢复64。

## 当前推荐 GUI 测试设置

```text
Mode                    Test Data
Test Bytes              16384
Chunk Bytes             1024
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
RF Strict Match + Retry unchecked
AIR0 Packet Header      checked
Verbose Packet Events   unchecked
Progress ms             1000

Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

这一组用于小数据量回环确认。AIR0 模式下接收端会从 AIR0 头读取 `file_size`、`total_packets` 和 `file_crc32`，`Raw Expected` 保持 `0`，不要再要求用户预填文件大小。先启动接收 GUI并等待 `RX target registered ...`，再启动发送 GUI。预期接收板串口出现 `RXCFG loopback peer` 和 `S2MM valid ... type=AIR0`，接收 GUI `DONE` 行中 `rx=16384` 且 `crc=0 len=0 gaps=0`。

双板独立调度验证使用同样的 `Test Bytes=16384`、`Chunk Bytes=1024`、`Window Size=1`，`Rate Limit KiB/s=400`，且必须关闭 `RF Strict Match + Retry`。发射板只运行发送 GUI，预期 reset 日志 `tx_mode=independent rx_registered=0`，不应因未连接本地 RX 出现逐块 DMA stall/RF drop。接收板先确认 `RXCFG ... rx_mode=independent`，合法帧看 `S2MM valid`，噪声伪帧看低频 `S2MM RX stat`。后续对照实验可临时降速，但不要把降到 50 当作已验证修复。

## 当前推荐 AIRV GUI 测试设置

```text
Sender Transfer Mode    airv_video
Sender Mode             File
Sender file             MP4 video or H.264 Annex-B elementary stream
Chunk Bytes             1024
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
RF Strict Match + Retry unchecked

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
