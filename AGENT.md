# AGENT.md

本文件给后续 agent 快速接手本仓库使用。项目完整说明只维护根目录 `README.md`，不要在子目录新增 README。

## 基本规则

- 本项目已安装 RTK。执行 shell 命令时优先使用 `rtk` 前缀，例如 `rtk git status`、`rtk git diff`、`rtk read <file>`、`rtk grep <pattern> <path>`。
- 修改前先看 `rtk git status --short`，不要覆盖用户未提交改动。
- 阅读文件优先用 `rtk read`，搜索优先用 `rtk grep` 或 `rtk rg --files`，避免普通命令输出过大。
- 只保留根目录 `README.md` 作为项目说明。协议、构建、调参、PC 工具说明都写进根 README。
- `AD9361_test2_bsp/` 和 `System_wrapper_hw_platform_0/` 是 Xilinx 生成产物；除非任务明确要求，不要手动改 BSP、lwIP 源码或硬件平台文件。
- 之后用户提出了额外协作要求或项目注意事项，需要同步写入本 `AGENT.md`，让后续 agent 知道。

## 用户协作约定

- 每次完成代码或文档修改后，必须 `git commit` 并 `git push` 到远程；不要让用户自己 push。提交前后都要用 `rtk git status --short` 确认工作区状态。
- 用户主要使用 GUI 发送程序 `AD9361_test2/tools/pc_sender/sender_gui.py`，不要用 CLI 命令作为测试指令。需要用户跑测试时，直接给 GUI 中的字段设置，例如 `Mode`、`Test Bytes`、`Chunk Bytes`、`Window Size`、`Throughput Mode`、`OFDM Legacy Wrap`、`PL Verify Pattern` 等。
- 用户当前要发送纯 payload，不要默认要求勾选 `OFDM Legacy Wrap`，也不要默认给 `--ofdm-legacy` 之类的命令行参数。若确实需要 Legacy 模式，必须先说明原因并明确让用户在 GUI 勾选 `OFDM Legacy Wrap`。
- 调试 PL 回环要分阶段做。由于本地无法板级验证，不要一次性写完大功能；先加可观察日志，让用户上板跑并回传串口输出，再根据日志继续改。
- 需要用户反馈时，明确列出要复制的串口日志行，例如 `S2MM start/wait/done/error`、`S2MM rx_head`、`S2MM tx_head`、`S2MM rx_hdr`、`LB UDP sent`、`STAT rate/state`、`MM2S error`；如果涉及 PC 端回传验证，还要让用户复制 GUI 日志里的 `PROGRESS ... lb=... lb_crc=... lb_diff=... lb_range=...` 和 `DONE ...` 行。
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
    PC 发送协议、滑动窗口、重传、OFDM legacy 封装、PL verify pattern。

AD9361_test2/tools/pc_sender/send_data.py
    CLI 入口。

AD9361_test2/tools/pc_sender/sender_gui.py
    Tkinter GUI。
```

## 调参边界

- 当前 `NET_AGG_BLOCK_BYTES = 3000`，不是旧文档里的 64 KiB。DDR 中每个聚合 slot 的有效 payload 是 3000 字节，但 `NET_AGG_BLOCK_STRIDE_BYTES = 3008`，队列深度为 697；stride 必须保持 cache-line 对齐，避免相邻 DMA slot 共享 cache line。
- 默认 `Chunk Bytes = 1440`。raw 模式每包 wire payload 为 `1440`；Legacy 模式为 `16 + align8(1440) = 1456`。
- PS 侧 `NET_MAX_PAYLOAD_BYTES = 3000`。Legacy 模式下 chunk 最大建议不超过 `2984`，因为 wire payload 还要加 16 字节 OFDM 头。
- 当前默认启用 I-cache 和 D-cache。MM2S 发送前必须 flush DMA buffer；S2MM 完成后必须 invalidate。不要把 DMA buffer slot 设成非 cache-line 对齐，64 MiB/window 16 压测曾暴露出相邻 3000 字节 slot 共享 cache line 后的偶发 `lb_diff`。
- GUI 默认应开启 `Payload CRC32`。64 MiB/window 16 压测曾观察到少量 PC->PS `bad_crc`，开启后坏包会被 PS 拒收并由发送端重传；不开 CRC 时坏包可能进入 PL 并表现为 GUI `lb_diff`。
- OK ACK 默认合并：8 包或 1000 us；非 OK ACK 立即发送。
- 当前已开启 PL->PS S2MM 回环调试和 UDP 回传：每次 MM2S 前 arm `8192` 字节 S2MM 捕获窗口，完成后跳过 RX 前 16 字节前缀，按 `tx_transfer` 长度比较 RX payload 和 TX buffer，并打印 `S2MM done/wait/error`、CRC、首部 word、`S2MM rx_hdr` 头字段推测和 TX/RX 比较结果；如果比较结果为 `cmp=DIFF`，现在会强制打印，不受 128 块间隔限制。随后 PS 用 magic `0x304B424C` 的 loopback UDP 包把 payload 分片发回 GUI。GUI 侧在等待 ACK 的同时处理 loopback 包，raw payload 模式下按 `stream_offset + chunk_offset` 对原始测试数据做 CRC/范围/逐字节校验。PL 设计者称 16 字节头为前 8 字节时间戳、后 8 字节速率和 payload 长度；当前日志显示 `meta1` 低 16 bit 的 `len_field - 4` 与 `tx_transfer` 匹配，字段编码仍需继续用日志确认。

## 当前推荐 GUI 测试设置

```text
Mode                    Test Data
Test Bytes              16384
Chunk Bytes             1440
Window Size             4
Throughput Mode         checked
OFDM Legacy Wrap        unchecked
Payload CRC32           checked
PL Verify Pattern       unchecked
Verbose Packet Events   unchecked
Progress ms             1000
```

这一组用于小数据量回环确认。预期板端串口出现 `Loopback UDP return ready`、`S2MM done ... cmp=OK`、`LB UDP sent ...`，GUI `DONE` 行中 `lb=16384/16384` 且 `lb_crc=0 lb_diff=0 lb_range=0`。

## 常用验证命令

```bash
rtk git status --short
rtk git diff -- README.md AGENT.md
rtk rg --files -g "*README*" -g "*readme*"
rtk grep "NET_AGG_BLOCK_BYTES|NET_MAX_PAYLOAD_BYTES|DATA_FLAG|PL_VERIFY" AD9361_test2/src AD9361_test2/tools/pc_sender
```

本环境通常没有 Xilinx SDK 命令行工具，因此无法在普通 shell 中完整构建 SDK 工程。若任务涉及 C 代码行为，至少做静态核对；真正构建和板级验证需要在 Xilinx SDK 2018.3 与目标板上完成。
