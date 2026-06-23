# AGENTS.md

本文件给后续 agent 快速接手本仓库使用。项目完整说明只维护根目录 `README.md`，不要在子目录新增 README。

## 基本规则

- 本项目已安装 RTK。执行 shell 命令时优先使用 `rtk` 前缀，例如 `rtk git status`、`rtk git diff`、`rtk read <file>`、`rtk grep <pattern> <path>`。
- 修改前先看 `rtk git status --short`，不要覆盖用户未提交改动。
- 阅读文件优先用 `rtk read`，搜索优先用 `rtk grep` 或 `rtk rg --files`，避免普通命令输出过大。
- 只保留根目录 `README.md` 作为项目说明。协议、构建、调参、PC 工具说明都写进根 README。
- `AD9361_test2_bsp/` 和 `System_wrapper_hw_platform_0/` 是 Xilinx 生成产物；除非任务明确要求，不要手动改 BSP、lwIP 源码或硬件平台文件。
- 之后用户提出了额外协作要求或项目注意事项，需要同步写入根目录 agent 文件，让后续 agent 知道。
- 如果仓库根目录有 `AGENT.md`、`Agent.md` 或 `AGENTS.md`，必须优先使用根目录文件作为本项目说明，不要改用 `C:\Users\29143\.codex\` 下的用户级说明。若多个同时存在，优先按用户最近明确指定的根目录文件执行。

## 用户协作约定

- 每次完成代码或文档修改后，必须 `git commit` 并 `git push` 到远程；不要让用户自己 push。提交前后都要用 `rtk git status --short` 确认工作区状态。
- 用户主要使用 GUI 发送程序 `AD9361_test2/tools/pc_sender/sender_gui.py`，不要用 CLI 命令作为测试指令。需要用户跑测试时，直接给 GUI 中的字段设置，例如 `Mode`、`Test Bytes`、`Chunk Bytes`、`Window Size`、`Throughput Mode`、`Payload CRC32`、`AIR0 Packet Header` 等。
- 旧版额外封装和测试 pattern 选项已从 PC/PS/文档移除，以后不要再建议用户使用相关 GUI 字段或 CLI 参数。PC->PS 应用层包头后始终是普通 wire payload；PS/PL 不根据 payload 内容做额外交互。
- 调试 PL 回环要分阶段做。由于本地无法板级验证，不要一次性写完大功能；先加可观察日志，让用户上板跑并回传串口输出，再根据日志继续改。
- 需要用户反馈时，明确列出要复制的串口日志行，例如 `RXCFG loopback peer`、`S2MM start/wait/done/error`、`S2MM rx_head`、`S2MM tx_head`、`S2MM rx_hdr`、`LB UDP sent`、`STAT rate/state`、`MM2S error`；如果涉及 PC 端回传验证，还要让用户复制接收 GUI 日志里的 `RX target registered ...`、`PROGRESS rx=... crc=... len=... gaps=... air=... air_rx=... miss=... bad_hdr=... bad_payload=... dup=...`、`INCOMPLETE ...` 和 `DONE ... gaps=... air=... air_rx=... miss=... file_crc=... saved=...` 行。
- 回答用户测试步骤时，用中文、直接、具体；避免给一长串命令让用户自行转换。

## 当前工程定位

- 主工程：`AD9361_test2`
- 开发环境：`Xilinx SDK 2018.3`
- 目标平台：`Zynq-7000 + AD9361`
- 主链路：PC UDP -> PS lwIP RAW UDP -> DDR 聚合块 -> AXI DMA MM2S -> PL `tx_intf/openofdm_tx` -> AD9361 TX
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
    接收 Tkinter GUI。
```

## Project agent instruction source

- If the repository root contains `AGENT.md`, `Agent.md`, or `AGENTS.md`, use that root file as the project agent instructions. Prefer the repository root agent file over user-level files under `C:\Users\29143\.codex\` for project-specific behavior.

## 调参边界

- 当前 `NET_AGG_BLOCK_BYTES = 3000`，不是旧文档里的 64 KiB。DDR 中每个聚合 slot 的有效 payload 是 3000 字节，但 `NET_AGG_BLOCK_STRIDE_BYTES = 3008`，队列深度为 697；stride 必须保持 cache-line 对齐，避免相邻 DMA slot 共享 cache line。
- 默认 `Chunk Bytes = 1440` 且发送 GUI 默认开启 `AIR0 Packet Header`。开启 AIR0 时，每包 wire payload 仍为 `1440`，其中 `64` 字节是 PC-only AIR0 头，最多 `1376` 字节是原始文件/测试 payload。PS/PL 不解析 AIR0。关闭 AIR0 后每包 wire payload 为原始文件/测试 payload。
- PS 侧 `NET_MAX_PAYLOAD_BYTES = 3000`。开启 AIR0 时 `Chunk Bytes` 必须大于 64，且 wire payload 不能超过 3000。
- 当前默认启用 I-cache 和 D-cache。MM2S 发送前必须 flush DMA buffer；S2MM 完成后必须 invalidate。不要把 DMA buffer slot 设成非 cache-line 对齐，64 MiB/window 16 压测曾暴露出相邻 3000 字节 slot 共享 cache line 后的偶发回传差异。
- GUI 默认应开启 `Payload CRC32`。64 MiB/window 16 压测曾观察到少量 PC->PS `bad_crc`，开启后坏包会被 PS 拒收并由发送端重传；不开 CRC 时坏包可能进入 PL 并表现为接收端 CRC/内容错误。
- 发送 GUI 的 `Busy Retries`、`Pending Retries`、`Recoverable Errors` 是可恢复重传统计，不是最终文件错误。判断文件是否完整，以发送端 `app_ack == total_size` 和接收端 `rx/high == file_size`、`gaps=0`、`crc=0`、`len=0` 为准。
- OK ACK 默认合并：8 包或 1000 us；非 OK ACK 立即发送。
- 当前已开启 PL->PS S2MM 回环调试和 UDP 回传：每次 MM2S 前 arm `8192` 字节 S2MM 捕获窗口，完成后跳过 RX 前 16 字节前缀，按聚合块真实 `payload_len` 比较 RX payload 和 TX buffer；`tx_transfer` 只是 8 字节对齐后的 DMA 长度，尾部 padding 不参与 payload 比较。代码会打印 `S2MM done/wait/error`、CRC、首部 word、`S2MM rx_hdr` 头字段推测和 TX/RX 比较结果；如果比较结果为 `cmp=DIFF`，现在会强制打印，不受 128 块间隔限制。随后 PS 用 magic `0x304B424C` 的 loopback UDP 包把 payload 分片发回已注册的接收 GUI/CLI。接收端按 `stream_offset + chunk_offset` 恢复连续 payload，检查分片 CRC、长度和缺口，并把图片/视频等原始文件保存到 `output`；如果存在缺口，接收端应报 `INCOMPLETE` 且不保存带洞文件。
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
```

这一组用于小数据量回环确认。先启动接收 GUI 并等待 `RX target registered ...`，再启动发送 GUI。预期板端串口出现 `RXCFG loopback peer`、`Loopback UDP return ready`、`S2MM done ... cmp=OK`、`LB UDP sent ...`，接收 GUI `DONE` 行中 `rx=16384` 且 `crc=0 len=0 gaps=0`。

## 常用验证命令

```bash
rtk git status --short
rtk git diff -- README.md AGENTS.md
rtk rg --files -g "*README*" -g "*readme*"
rtk grep "NET_AGG_BLOCK_BYTES|NET_MAX_PAYLOAD_BYTES|DATA_FLAG|AIR0" AD9361_test2/src AD9361_test2/tools/pc_sender
```

本环境通常没有 Xilinx SDK 命令行工具，因此无法在普通 shell 中完整构建 SDK 工程。若任务涉及 C 代码行为，至少做静态核对；真正构建和板级验证需要在 Xilinx SDK 2018.3 与目标板上完成。
