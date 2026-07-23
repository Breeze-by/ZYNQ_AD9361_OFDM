# ZYNQ_AD9361_OFDM

这是一个基于 `Xilinx SDK 2018.3` 的 `Zynq-7000 + AD9361` 裸机工程。当前主链路是 PC 通过 UDP 向 Zynq PS 发送应用层数据包，PS 使用 lwIP RAW UDP 接收、校验和排序，把数据写入 DDR 中的发送缓冲，再通过 AXI DMA MM2S 推给 PL 侧 `tx_intf/openofdm_tx`。当前板级链路已经从纯 PL 数字回环推进到 AD9361 RF 回环：PL 侧 OFDM 调制后的数据送入 AD9361 TX，经 SMA 线直连到 AD9361 RX，再进入 PL 侧 OFDM 接收/解调；解调后的数据通过 S2MM 回到 PS，PS 再把恢复出的 payload 用 UDP 发回专门的 PC 接收工具做分片 CRC、连续性检查和文件恢复。

SDK 默认 `APP_RX_SOURCE=APP_RX_SOURCE_AD9361`，即 `rx_intf` 使用真实 AD9361
ADC 数据。PL 内部数字回环仍保留为单独的诊断选项；需要隔离 RF 链路时，可把
`AD9361_test2/src/app/app_config.h` 中该宏改为
`APP_RX_SOURCE_DIGITAL_LOOPBACK`。启动日志会明确打印 `AD9361_RF` 或
`DIGITAL_LOOPBACK`，不要再根据函数名或寄存器魔数猜测当前路径。

```text
PC UDP sender
-> Zynq PS lwIP RAW UDP
-> net_data_header_t/session/seq/CRC check
-> PS DDR aggregation blocks
-> AXI DMA MM2S
-> PL tx_intf/openofdm_tx
-> AD9361 TX -> SMA cable -> AD9361 RX
-> PL OFDM RX/decode
-> AXI DMA S2MM
-> PS UDP loopback return
-> PC receiver GUI/CLI restore
```

当前仓库只保留这一份 README。以后更新项目说明、协议、构建步骤、PC 工具用法或调参结论，都直接更新根目录 `README.md`，不要在子目录新增 README。

## 目录结构

```text
ZYNQ_AD9361_OFDM/
|-- README.md                         # 唯一项目说明
|-- AGENTS.md                         # 后续 agent 上手指南
|-- System_wrapper.hdf                # Vivado 硬件导出
|-- System_wrapper_hw_platform_0/     # SDK 硬件平台，含 bit/hdf/ps7_init
|-- AD9361_test2/                     # 主要 Xilinx SDK 应用工程
|   |-- .project/.cproject            # SDK/Eclipse 工程配置
|   |-- src/
|   |   |-- app/                      # main.c、app_config.h
|   |   |-- drivers/ad9361/           # AD9361、SPI、GPIO、平台适配
|   |   |-- drivers/dma/              # AXI DMA 初始化和中断封装
|   |   |-- drivers/interrupt/        # SCU GIC/ISR
|   |   |-- drivers/net/              # lwIP、UDP 协议、ACK、聚合、DMA 调度
|   |   |-- drivers/timer/            # SCU timer 封装
|   |   |-- drivers/uart/             # PS UART 打印
|   |   |-- utils/                    # 公共配置和工具
|   |   |-- lscript.ld
|   |   `-- Xilinx.spec
|   `-- tools/pc_sender/              # Python CLI/Tkinter GUI 发送/接收工具
`-- AD9361_test2_bsp/                 # Xilinx SDK BSP/lwIP/libxil 生成产物
```

通常只维护 `AD9361_test2/src/` 和 `AD9361_test2/tools/pc_sender/`。`AD9361_test2_bsp/` 与 `System_wrapper_hw_platform_0/` 是 Xilinx 生成产物，除非明确要改 BSP、lwIP 选项或硬件平台，否则不要手动改。

## 关键源码

```text
AD9361_test2/src/app/main.c
    板端入口；初始化 cache、AD9361、openofdm/tx_intf/rx_intf 寄存器、
    UART、GIC、AXI DMA、lwIP，然后进入网络轮询主循环。

AD9361_test2/src/app/app_config.h
    RX 数据源、cache 开关、DMA buffer 地址和长度、上电默认 IPv4 配置。

AD9361_test2/src/drivers/net/net_config.h
    UDP 端口、协议 magic/flag、ACK 状态、聚合块、ACK 合并、轮询预算。

AD9361_test2/src/drivers/net/net_protocol.h/.c
    PC<->PS 应用层包头、ACK 包结构、CRC32、8 字节对齐。

AD9361_test2/src/drivers/net/net_init.c
    lwIP/GEM 初始化、上电默认 IP、IPCFG 运行时改址、`xemacif_input()` 输入轮询。

AD9361_test2/src/drivers/net/net_rx.c
    UDP RX 回调、session reset、严格按序接收、ACK、聚合块提交、
    MM2S DMA 启动、S2MM 回环接收、PL 头解析、UDP 回传和完成回收。

AD9361_test2/src/drivers/net/net_stats.c
    周期性串口统计输出。

AD9361_test2/tools/pc_sender/sender_core.py
    Python 发送核心；滑动窗口、reset/session、重传、Payload CRC32、
    AIR0 payload header、CLI 参数。

AD9361_test2/tools/pc_sender/send_data.py
    命令行入口。

AD9361_test2/tools/pc_sender/sender_gui.py
    Tkinter GUI 入口。
AD9361_test2/tools/pc_sender/receiver_core.py
    PC 接收核心；注册 PL loopback 回传目标、接收分片、CRC 检查、
    按 stream_offset 恢复输出文件。
AD9361_test2/tools/pc_sender/recv_data.py
    接收 CLI 入口。
AD9361_test2/tools/pc_sender/receiver_gui.py
    接收 Tkinter GUI 入口；参数和指标使用紧凑双列布局，Charts/Event Log
    使用可拖动的纵向分隔区，AIRV Preview 为独立窗口。
```

## 板端启动流程

`main.c` 当前流程：

1. 根据 `APP_ENABLE_ICACHE` / `APP_ENABLE_DCACHE` 开关启用或关闭 cache。
2. 初始化 UART，波特率 `115200`，确保 AD9361 初始化日志不会走 JTAG DCC。
3. 初始化 GPIO、SPI 和 AD9361；任一步失败都会打印阶段名并停止启动。
4. 将 2R2T LVDS 采样率配置为 `40 MSPS`（DATA_CLK 约 `160 MHz`），当前源码设置
   `tx_fb_clock_delay=7`，并在启动时强制校验 TX clock/data delay 寄存器读回为 `0x70`。
5. 初始化 SCU GIC。
6. 初始化 `openofdm_tx`、`tx_intf` 静态寄存器，并用默认 `3000` 字节 PSDU 先 re-arm 一次。
7. 根据 `APP_RX_SOURCE` 初始化 `openofdm_rx/rx_intf`，并打印实际 RX 数据源。
8. 初始化 AXI DMA 和高电平敏感的 MM2S/S2MM 中断。
9. 初始化 lwIP/GEM，使用上电默认 IPv4，并允许空闲时通过 IPCFG 临时改址。
10. 绑定 UDP `5001`，初始化 DDR 聚合缓冲并进入主循环：

```c
while (1) {
    Net_Poll();
    Net_RxPoll();
}
```

`Net_Poll()` 每轮最多处理 `NET_INPUT_POLL_BUDGET=32` 个以太网输入包。`Net_RxPoll()` 负责统计输出、ACK 合并超时 flush、聚合块超时 flush、DMA 启动、DMA 完成回收和错误停机。

## 网络配置

默认配置位于 `AD9361_test2/src/app/app_config.h` 和 `AD9361_test2/src/drivers/net/net_config.h`。

```text
MAC      02:00:00:00:00:01
IP       192.168.1.50
Netmask  255.255.255.0
Gateway  192.168.1.1
UDP port 5001
```

以上是每次上电后的默认地址。为了兼容不同直连网段，接收 GUI 可以在注册回传目标前发送全局 UDP 广播 `IPCFG`，调用板端 `netif_set_addr()` 临时修改 IP、掩码和网关。该设置只在本次上电有效，不写 flash；板子复位后仍回到 `192.168.1.50/24`，所以原来的电脑和已有 ELF 使用习惯不受影响。

板端只在 DMA、S2MM 和聚合队列均空闲时接受 IPCFG。接收 GUI 必须先绑定到直连 Zynq 的 PC 网卡地址，再向 `255.255.255.255:5001` 发送配置；板端切换地址后从新地址 ACK，然后 GUI 再向新地址发送普通 RXCFG。双网卡电脑不要使用 `Bind IP=0.0.0.0` 做 IPCFG，否则 Windows 可能从连接互联网的另一张网卡发送广播。

两台电脑的推荐配置：

```text
原电脑：PC/Zynq 网卡 192.168.1.101/24 -> Board IP 192.168.1.50
新电脑：PC/Zynq 网卡 192.168.2.101/24 -> Board IP 192.168.2.50
```

新电脑接收 GUI 启动并看到 `IPCFG applied ...`、`RX target registered ...` 后，应能 `ping 192.168.2.50`；随后发送 GUI 的 `Target IP` 也必须使用 `192.168.2.50`。

正常网络启动日志应包含：

```text
Ethernet ready
MAC : 02:00:00:00:00:01
IP  : 192.168.1.50
MASK: 255.255.255.0
GW  : 192.168.1.1
UDP : listen on port 5001
UDP RX ready, agg_blocks=697 block_bytes=3000 stride=3008 total_bytes=2097152 max_payload=3000 rec_window<=64 ack=on_accept
Loopback UDP return ready, magic=0x304B424C chunk_bytes=1200
```

## UDP 应用协议

多字节字段均为 little-endian。PC Python 端和 Zynq Cortex-A9 裸机端使用一致结构。

数据包头：

```c
typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint16_t payload_len;
    uint16_t reserved;
    uint32_t payload_crc32;
} net_data_header_t;
```

`reserved` 当前作为 flag/session 字段：

```text
bit15      RESET flag
bit14      NO_CRC flag
bit13      RF_RETRY flag
bit12:0    session id
```

ACK 包：

```c
typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint16_t status;
    uint16_t reserved;
    uint32_t transfer_len;
} net_ack_packet_t;
```

常量：

```text
DATA magic       0x4E455430
ACK magic        0x41434B30
RXCFG magic      0x52435830
IPCFG magic      0x49504330
DATA header      16 bytes
ACK packet       16 bytes
IPCFG packet     24 bytes
RESET flag       0x8000
NO_CRC flag      0x4000
RF_RETRY flag    0x2000
session mask     0x1FFF
```

ACK 状态：

```text
0 OK            包已写入 PS 聚合缓冲
1 BAD_MAGIC     magic 错误
2 BAD_LENGTH    包长度、payload_len 或 payload 范围错误
3 BAD_CHECKSUM  CRC32 校验失败
4 BUSY          聚合缓冲无可写空间，本包未接收
5 DMA_ERROR     DMA 已进入 fatal error 状态
6 PENDING       session 不匹配或序号超前，本包未接收
```

每次 PC 发送工具开始传输前，都会先发送 `RESET flag=1, payload_len=0, seq=0` 的控制包。板端只有在 DMA 空闲且无 fatal error 时接受 reset，随后清空序号、历史记录、聚合队列和统计，并切换到新的 13-bit session id。普通数据包必须带同一个 session id。

`NO_CRC` 由 PC 工具的 Payload CRC32 开关决定。关闭 payload CRC 时，reset 包携带 `NO_CRC`，普通包的 `payload_crc32=0`；开启 `--payload-crc` 或 GUI 对应选项后，PC 对 wire payload 计算 CRC32，PS 接收后校验。GUI 默认开启 Payload CRC32，高负载测试时曾观察到少量 PC->PS payload CRC 错误，开启后坏包会被 PS 拒收并由发送端重传，最终 loopback 校验才可信。

`RF_RETRY` 只在每次传输开始的 reset 包中选择本 session 的板端 RF 策略。发送 GUI 的 `RF Strict Match + Retry (max 3)` 默认关闭，对应启动日志 `rf_mode=deliver_no_retry`；勾选后 reset 包携带 `RF_RETRY`，对应 `rf_mode=strict_retry`。该 flag 不改变 PC->PS UDP 滑动窗口重传，也不是 AIR0/AIRV 接收端 ACK。

IPCFG 是独立的 24 字节控制包，包含 `magic/seq/ip_addr/netmask/gateway/reserved`。PC 和 PS 都按 4 个原始网络地址字节传输 IPv4 字段，避免主机字节序歧义。板端拒绝非法/广播/网络地址、非连续掩码、跨网段非零网关、请求源不在目标网段以及传输期间的改址请求。直连板卡推荐 `gateway=0.0.0.0`。

## UDP Loopback 回传协议

如果启用了运行时板端改址，接收工具先广播 IPCFG；收到 ACK 或完成有限次数尝试后，再用本机接收 socket 向 GUI 中的 `Board IP:Board Port` 发送一个 16 字节 `RXCFG` 控制包。RXCFG 与普通 `net_data_header_t` 形状相同，只是 `magic=0x52435830`、`payload_len=0`。板端收到后记录该 UDP 包的源 IP/源端口作为 PL loopback 回传目标，返回 `ACK OK`，并打印 `RXCFG loopback peer port=...`。

注册成功后，即使发送端随后发 `RESET`，板端也会继续把 PL loopback 回传发给已注册的接收端；不会被发送端源端口覆盖。这样支持单电脑场景，也支持一台电脑只跑发送 GUI、另一台电脑只跑接收 GUI 的场景。如果接收工具没有注册，板端仍保留兼容行为：把回传发给最近一次发送/RESET 数据包的源 IP/端口。

PL->PS S2MM 完成后，PS 会跳过 PL 返回数据前面的 16 字节头，只把恢复出的 payload 按 1200 字节分片 UDP 发回已注册接收端。DMA 比较仍按 `align8(payload_len)` 检查补零后的传输内容，但 UDP 回传只发送原始聚合块 `payload_len`，不会把末尾 8 字节对齐补零写进恢复文件。发送程序现在只处理发送 ACK；如果意外收到 loopback 包，会按 magic 识别后忽略。

回传包头：

```c
typedef struct {
    uint32_t magic;
    uint32_t block_id;
    uint32_t stream_offset;
    uint16_t block_payload_len;
    uint16_t chunk_offset;
    uint16_t chunk_len;
    uint16_t flags;
    uint32_t payload_crc32;
    uint32_t timestamp_lo;
    uint32_t timestamp_hi;
    uint32_t meta0;
    uint32_t meta1;
} net_loopback_packet_header_t;
```

常量：

```text
Loopback magic      0x304B424C
Loopback header     40 bytes
UDP return payload  1200 bytes per packet
LAST_CHUNK flag     0x0001
```

字段含义：

```text
block_id           板端 S2MM transfer id，从 1 递增
stream_offset      这个聚合块在本次 raw/wire 数据流中的起始字节偏移
block_payload_len  本次回传的块 payload 长度
chunk_offset       当前 UDP 分片在该块内的偏移
chunk_len          当前 UDP 分片 payload 长度
payload_crc32      当前 UDP 分片 payload 的 CRC32
timestamp_lo/hi    PL 16 字节头的前 8 字节，按 little-endian 透传
meta0/meta1        PL 16 字节头的后 8 字节，按 little-endian 透传
```

当前日志观察到 PL 16 字节头形态如下：

```text
S2MM rx_hdr ts=00000000_00000000 meta0=0x01000000 meta1=0x000B0B44 len_field=2884 payload_guess=2880 rate_guess=0x0B tx_transfer=2880 match=yes
S2MM rx_hdr ts=00000000_00000000 meta0=0x01000000 meta1=0x000B07C4 len_field=1988 payload_guess=1984 rate_guess=0x0B tx_transfer=1984 match=yes
```

PL 设计者说明：前 8 字节是时间戳，后 8 字节包含速率和 payload 长度。当前代码只把这 16 字节作为诊断元数据透传和打印，不把它发给 GUI 当 payload 校验。

## 顺序、ACK 和重传

板端严格按序接收：

- 只接受 `seq == next_expected_seq` 的数据包。
- 成功接收后，payload 写入当前聚合块，记录到 duplicate history，然后 `next_expected_seq++`。
- `seq > next_expected_seq` 返回 `PENDING`，payload 不写入聚合块。
- 聚合缓冲无可写块时返回 `BUSY`，payload 不写入聚合块。
- 已接受过的重复包返回 `OK`，不重复写入聚合块。
- DMA fatal error 后返回 `DMA_ERROR`，不再继续向 PL 推送后续数据。

OK ACK 使用累计确认语义。主机收到 `OK seq=N` 后，可认为当前未确认窗口中 `seq <= N` 的包均已被板端接收。为了降低 ACK 负载，板端默认启用 OK ACK 合并：每 `8` 个 OK 包或 `1000 us` flush 一次；非 OK ACK 会立即发送，并会先 flush 已挂起的 OK ACK。

`PENDING` 表示前面还有缺口，发送端会优先重传当前窗口中最老的未确认包。`BUSY` 表示板端暂时没有聚合块空间，发送端会退避后重发。二者只影响速度，不改变 PS 到 PL 的数据顺序。

PC->PS UDP 重传与板端 RF 重发是两层不同机制。GUI 的 `Max Retries` 限制 UDP 包因 timeout/BUSY/PENDING/错误 ACK 触发的主机重传；`RF Strict Match + Retry (max 3)` 则控制一个已经被 PS 接受并形成聚合块的数据是否在 RF/S2MM 失败后由板端重新送入 MM2S，最大值由代码中的 `NET_LOOPBACK_RF_RETRY_MAX=3` 固定。

## 聚合、DMA 和 openofdm 帧长

当前配置与旧版 64 KiB 聚合不同，代码以 openofdm/tx_intf 的单帧长度为中心：

```text
TX_BUFFER_BASE                 0x01200000
TX_BUFFER_WORD_COUNT           262144
TX buffer size                 2097152 bytes

NET_OFDM_TARGET_PSDU_BYTES     3000
NET_OFDM_MAX_DMA_WORDS         1022
NET_OFDM_MAX_PSDU_BYTES        8176 bytes
NET_DMA_CACHE_LINE_BYTES       64
NET_AGG_BLOCK_BYTES            3000
NET_AGG_BLOCK_STRIDE_BYTES     3008
NET_AGG_BLOCK_COUNT            697
NET_DMA_QUEUE_CAPACITY         697
NET_AGG_MIN_FLUSH_BYTES        1500
NET_AGG_FLUSH_TIMEOUT_US       15000
NET_AGG_IDLE_FLUSH_TIMEOUT_US  100000
NET_MAX_PAYLOAD_BYTES          3000
```

每个聚合块的有效 payload 容量仍是 `3000` 字节，但 DDR slot stride 是 `3008` 字节。`3008` 是 64 字节 cache line 对齐后的槽跨度，用来避免相邻 DMA slot 共享同一条 cache line。DDR 中实际参与聚合队列管理的容量是 `697 * 3008 = 2096576` 字节，略小于 `2 MiB` TX buffer，余下尾部不用作聚合块。

聚合块提交条件：

- 下一个 payload 放不进当前 `3000` 字节块时，先提交当前块；
- 当前块已达到 `3000` 字节；
- 当前块至少达到 `1500` 字节，且填充耗时达到 `15000 us`；
- 当前块空闲达到 `100000 us`。

提交时 `transfer_len = align8(payload_len)`，不足 8 字节补 0。DMA 启动前，`net_rx.c` 会：

1. 校验 `payload_len <= NET_OFDM_MAX_PSDU_BYTES`。
2. 校验 `transfer_len == align8(payload_len)`。
3. 调用 `OpenWifi_Tx_Rearm(payload_len)` 重置 TX 状态机。
4. 根据本次块的真实 `payload_len` 更新 `tx_intf` 帧长、DMA word 数和 auto-start threshold。
5. 对 DMA buffer 执行 `Xil_DCacheFlushRange()`。
6. 调用 `XAxiDma_SimpleTransfer(..., XAXIDMA_DMA_TO_DEVICE)`。

默认 `Chunk Bytes=1440` 时：

```text
raw payload:
  每包 wire payload = 1440 bytes
  典型每个 DMA block = 2 * 1440 = 2880 bytes

AIR0 enabled:
  每包 wire payload 仍为 1440 bytes
  其中 64 bytes 是 PC-only AIR0 header
  最多 1376 bytes 是原始文件/测试 payload
```

如果修改 PC chunk 大小，需要满足 PS 侧 `payload_len <= 3000`。开启 AIR0 时，chunk 必须大于 64 字节，实际业务 payload 为 `chunk_size - 64`。为避免普通 1500 MTU 下 IP 分片，推荐继续使用默认 `1440`。

## Cache 和 DMA 一致性

当前默认：

```c
#define APP_ENABLE_ICACHE 1
#define APP_ENABLE_DCACHE 1
```

保持 D-cache 开启。PC->PS->PL 路径是 MM2S：CPU 写 DDR buffer，DMA/PL 读 DDR buffer。因此启动 DMA 前必须 flush 对应 buffer。当前 `net_rx.c` 已在 `XAxiDma_SimpleTransfer()` 前执行：

```c
Xil_DCacheFlushRange((UINTPTR)block->buffer_ptr, block->transfer_len);
```

以后如果恢复或新增 PL->PS/S2MM 路径，DMA/PL 写 DDR 后、CPU 读取前必须执行 `Xil_DCacheInvalidateRange()`。DMA buffer 起始地址、长度和相邻对象要保持 cache line 友好，不要让 DMA buffer 与普通状态变量共享同一 cache line。

关闭 D-cache 只适合定位 cache 一致性问题，不适合作为吞吐测试或长期运行配置。

## PC 发送工具

命令行入口：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1440 --window-size 1 --target-rate-kib-s 400 --throughput-mode
```

发送文件：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --file data.bin --chunk-size 1440 --window-size 1 --target-rate-kib-s 400 --throughput-mode
```

GUI：

```bash
python AD9361_test2/tools/pc_sender/sender_gui.py
```

发送 GUI 的 Source、Network and Sender、Metrics 已使用紧凑双列布局；下方 Charts 与 Event Log 位于可上下拖动的纵向分隔区。普通窗口和最大化窗口都会保留图表、日志的可见空间，需要重点查看其中一项时可拖动分隔条调整高度。

常用参数：

```text
--ip                    Zynq IP，默认工程应使用 192.168.1.50
--port                  UDP 端口，默认 5001
--test-size             生成测试数据字节数
--file                  从文件读取 payload
--chunk-size            每个 UDP wire payload 字节数，默认 1440
--window-size           滑动窗口，默认 1
--throughput-mode       轻量吞吐输出
--target-rate-kib-s     主机侧限速，默认 400 KiB/s，0 表示不限速
--payload-crc           启用应用层 payload CRC32；高负载/完整性测试推荐开启
--no-payload-crc        关闭应用层 payload CRC32
--rf-retry              启用板端 RF 严格匹配并最多重发 3 次；GUI 默认关闭
--no-rf-retry           关闭板端 RF 重发，合法帧即使 payload 不同也回传诊断
--air-protocol          启用 PC-only AIR0 payload header，默认开启
--no-air-protocol       关闭 AIR0，发送旧版原始文件/测试字节流
```

## PC-only AIR0 payload header

AIR0 强协议只在 PC 端生效。发送 PC 默认把每个 `Chunk Bytes=1440` 的 wire payload 封装成：

```text
64-byte AIR0 header + up to 1376-byte original file/test payload
```

PL 不解析 AIR0；PS 不恢复文件，只读取捕获块起始 AIR0 头的 `packet_seq/chunk_bytes` 来恢复延迟 RF 帧的回传偏移，其余内容仍按普通 payload 转发。接收 PC 从 PL loopback 回传的字节流中自动识别 AIR0，按 `packet_seq/file_offset/file_size/payload_crc32/header_crc32/file_crc32` 恢复原始文件，并统计丢包、坏头、坏 payload CRC 和重复包。AIR0 本身不做 FEC、接收端 ACK 或分片级重传，只用于让接收端明确知道是否完整以及缺了哪些包；发送 GUI 可另行开启板端 `RF Strict Match + Retry (max 3)`，让整个 PS 聚合块在 RF/S2MM 失败后重发。

如需回到旧版纯字节流，对发送 GUI 取消勾选 `AIR0 Packet Header`，或 CLI 使用 `--no-air-protocol`。

## PC-only AIRV realtime video payload header

AIRV 是当前 PC 工具侧的实时视频传输/预览模式。PL 不解析 AIRV；PS 也不组帧或解码，只校验捕获块起始的 AIRV v2 头并读取全局 `packet_seq/chunk_bytes`，用于给延迟到达的 RF/S2MM 数据恢复正确的 UDP 回传 `stream_offset`。发送 GUI 提供 `Transfer Mode`：

```text
air0_file   当前默认 File/Test 精确恢复模式
airv_video  实时视频组帧/统计模式
raw         旧版原始字节流
```

AIRV 使用 64 字节固定头，`Chunk Bytes=1440` 时每个 PC->PS wire payload 是：

```text
64-byte AIRV header + up to 1376-byte encoded video frame fragment + optional zero padding
```

AIRV v2 头包含 `session_id/stream_id/packet_seq/frame_seq/frag_index/frag_count/frame_type/frame_size/fragment_offset/fragment_len/chunk_bytes/frame_crc32/fragment_crc32/pts_us` 等字段。每个分片都重复携带完整帧元数据，不要求先收到 `frag_index=0` 才能建立帧状态；全局 `packet_seq` 位于 64 字节头偏移 58，PS 用 `packet_seq * chunk_bytes` 计算绝对回传偏移，避免 TX/RX 解耦时误用当前 TX block 的偏移。发送端会把 H.264 Annex-B elementary stream 按 access unit 粗分帧；如果输入文件没有 Annex-B start code，则先作为单个 encoded frame 分片发送。AIRV v1 与 v2 不混用，升级后必须同时使用新版 ELF 和新版 PC 工具。

AIRV 模式选择视频文件时，发送工具会自动准备 H.264 Annex-B 裸流：

- 如果选择的就是 `.h264` / `.264`，直接发送该文件。
- 如果选择的是 `.mp4` 等容器文件，先在同目录查找同名 `.h264` / `.264`，例如 `clip.mp4` 对应 `clip.h264`。
- 如果同名裸流已存在，发送 GUI 会直接复用这个 sidecar，不再对 MP4 做耗时探测；此时 AIRV FPS 日志显示 `fps_source=sidecar_fallback`，按 30fps 写入 PTS。
- 如果同名裸流不存在，则调用 `ffmpeg` 在同目录生成 `clip.h264` 并保存下来；后续再选同一个 MP4 会直接快速复用这个 `.h264`。
- 新生成的 sidecar 统一转码为 H.264 baseline、无 B 帧、带 AUD，并按源 FPS 设置约每秒一个固定 IDR；关闭 scenecut 漂移且在 IDR 重复 SPS/PPS，使连续错误触发重建后最多约一秒恢复。已有 `.h264/.264` 仍直接复用，其 GOP 和 SPS/PPS 周期由原文件决定；需要统一恢复上限时，删除旧 sidecar 后重新选择 MP4 生成。
- 只有在没有 sidecar、需要从容器准备 AIRV 源时，发送端才会用 `ffprobe` 读取源视频帧率，并把真实帧间隔写入 AIRV `pts_us`；`ffprobe` 最多等待 2 秒，失败则回退到 `30fps`，GUI 日志会显示 `AIRV source file=... fps=... fps_source=...`。

因此可以直接在发送 GUI 里选择 MP4；只有首次为没有 sidecar 的容器视频准备 AIRV 源时，本机必须能在 `PATH` 中找到 `ffmpeg`。

AIRV 接收端自动从回传 payload 起始 magic `0x56524941` 识别实时模式，并走实时组帧统计和可选实时预览路径。头校验严格：magic/version/header_len/header_crc32、分片序号、分片长度和 LAST_FRAGMENT 都必须合法。payload CRC 和 frame CRC 只计数，不作为自动丢帧条件；只要头有效且分片齐全，接收端仍把 encoded H.264 access unit 交给预览解码器，允许错码表现为局部马赛克。组帧器以 `(session_id, stream_id, frame_seq)` 保存分片，按 `frag_index/fragment_offset` 拼接，并只按递增 `frame_seq` 输出；最多保留 3 帧乱序深度，确认某帧无法补齐后只 drop 该帧，再立即释放后续完整帧。单帧缺失不会强制等待 keyframe。AIRV 不保存精确文件，不做接收端 ACK、重传、FEC 或音频。

接收 GUI 现在会打开独立 `AIRV Preview` 窗口，默认大小 `1280x720`，不再挤占主窗口日志区域。AIRV 解码在后台线程执行，Tk 主线程以约 `30fps` 刷新最近一张已解码图片，避免 PyAV 解码或坏码流导致 GUI 未响应。预览输入端会缓存最多 `240` 个 assembled encoded frame，并按 H.264 顺序送给解码器，避免为了追最新画面而跳过 P 帧参考链。只有预览队列真的满了，才清空预览队列并等待下一帧 keyframe 恢复；这只影响预览，不影响 AIRV 统计。主窗口保留 `Preview/Preview Input/Preview Backlog/Preview Drops/Decoded/Displayed/Decoder Errors/Waiting Key` 状态，其中 `Displayed` 是实际渲染到 Tk 预览窗口的帧数。预览依赖可选 Python 包 `av` 和 `Pillow`：

```bash
python -m pip install av pillow
```

如果未安装，AIRV 传输、组帧和统计仍可正常运行，接收 GUI 会在日志和预览窗口中输出 `VIDEO_PREVIEW PyAV is not installed...` 或 Pillow 相关提示，提示里会带当前 GUI 使用的 Python 路径。`Preview Input` 表示接收端已经组出的 AIRV encoded frame 数；`Preview Backlog` 是等待后台解码的帧数；`Preview Drops` 只表示预览端因队列积压主动丢弃的 encoded frame，不代表传输丢包。如果 `Preview Input` 增长但 `Decoded/Displayed` 不增长，重点检查 `av/Pillow` 安装和 H.264 解码错误；如果 `Preview Input` 也不增长，重点检查接收 GUI 是否注册成功、AIRV `VIDEO frame_rx/frame_show` 是否增长、板端是否有 `LB UDP sent`。预览解码器遇到坏 payload/frame CRC 时仍会尝试解码显示；一次或两次连续 P 帧解码异常只显示 `Decode warning` 并继续喂后续帧，连续 3 次失败才重建解码器并等待下一帧 keyframe。

AIRV 接收 GUI 只保留少量关键 `VIDEO_DIAG`：模式识别、中途接入、magic 重同步、坏头和跨缺口恢复。逐分片 `fragment`、正常等待 `wait_chunk`、逐帧 `frame_complete/VIDEO_FRAME` 已关闭，坏分片和坏帧统一查看每两秒一条的 `VIDEO bad_frag_crc/bad_frame_crc` 以及最终 `VIDEO_DONE`，避免日志本身抢占 PC 处理时间。如果组帧计数增长但 `Decoded/Displayed` 不增长，应继续查看 `VIDEO_PREVIEW`，重点检查 PyAV/Pillow 环境或 H.264 解码状态。

AIRV 是实时预览模式，允许在开头若干 S2MM block 丢失时从第一个实际收到的
完整 AIRV chunk 中途接入。此时日志会打印
`VIDEO_DIAG late_attach initial_missing=...`，`VIDEO` 行也会保留
`initial_missing=...`；接收器继续组帧并等待后续 H.264 keyframe。该行为不用于
AIR0，AIR0 精确文件恢复仍要求从 offset 0 连续接收，不能跳过开头缺失。

AIRV 流中间出现至少一个完整 wire chunk 的缺口时，接收器会在下一段起点同时
满足 chunk 对齐和 AIRV magic 校验后跳过缺口，打印
`VIDEO_DIAG gap_skip from=... to=... bytes=...`，只丢弃跨缺口的未完成帧，
后续完整帧继续按序送入解码器；只有连续解码失败才等待 keyframe。`VIDEO` 中的 `stream_gap` 累计这类跳过的字节数。AIR0 不允许
该行为。

预览线程正常运行时，接收 GUI 每两秒最多输出一条 `VIDEO_PREVIEW`，包含
`input/backlog/drops/decoded/rendered/decoder_errors/waiting_key/images/skipped/error`；
AIRV idle finish 时还会输出 `VIDEO_PREVIEW_DONE`。其中 `decoded` 是 PyAV 解码
出的图像累计数，`rendered` 是 Tk 实际显示数，两者可用于区分组帧、解码和 GUI
渲染三个阶段。

AIRV 接收日志示例：

```text
VIDEO frame_rx=120 frame_show=120 frame_drop=0 frag_rx=280 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=4 waiting_keyframe=0 fps=24.8 latency_ms=5.1
VIDEO_DONE frame_rx=120 frame_show=120 frame_drop=0 frag_rx=280 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=4 fps=24.8 latency_ms=5.1 latency_avg_ms=4.2 latency_max_ms=8.7
DONE VIDEO frame_rx=120 frame_show=120 frame_drop=0 frag_rx=280 frag_missing=0 bad_hdr=0 bad_meta=0 bad_frag_crc=0 bad_frame_crc=0 keyframe_rx=4 waiting_keyframe=0 fps=24.8 latency_ms=5.1 latency_avg_ms=4.2 latency_max_ms=8.7
```

AIRV 的 `fps` 当前按 AIRV `pts_us` 帧间隔估算源视频帧率，不再按 Python 瞬时组帧速度统计；发送端优先使用 `ffprobe` 探测源 FPS，失败时回退 30fps。`latency_ms` 是接收端从本帧首个分片到帧组齐的最近一次可报告耗时；如果最后一帧在同一轮解析中近似 0ms 完成，最终 `VIDEO_DONE` / `DONE VIDEO` 会保留上一条非零 latency，避免 idle finish 后显示 `0.0` 误导。`latency_avg_ms` / `latency_max_ms` 是本次 AIRV 流的组帧平均/最大耗时；这些都不是严格端到端空口时延。

推荐 AIRV GUI 测试：

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
RF Strict Match + Retry unchecked

Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

重点看 AIRV 是否能经 PC->PS->PL->PS->PC 回传后连续组帧并实时预览：`bad_hdr=0`、`bad_meta=0`、`frame_drop=0`、`frag_missing=0`，接收 GUI 的 `Preview Input`、`Decoded`、`Displayed` 应持续增长。如果出现 `bad_frag_crc` 或 `bad_frame_crc`，接收端仍会尝试组帧并输出 `VIDEO_FRAME ... bad_frag_crc=1 bad_frame_crc=1`，这符合 AIRV 的实时演示策略。

推荐 GUI/CLI 吞吐配置：

```text
模式                    Test Data
Throughput Mode         开启
Payload CRC32           开启
RF Strict Match + Retry 关闭
AIR0 Packet Header      开启
Verbose Packet Events   关闭
Chunk Bytes             1440
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Progress ms             1000
Test Bytes              64 MiB 或 256 MiB
```

发送 GUI 里的 `Busy Retries`、`Pending Retries`、`Recoverable Errors` 是可恢复重传统计，不是最终文件错误。只要发送端最终 `app_ack` 等于总字节数，接收端最终 `rx/high` 等于原文件大小且 `gaps=0 crc=0 len=0`，说明当前这次恢复文件是连续完整的。`Recoverable Errors` 中常见的是板端 payload CRC 拒收后重传成功；如果该计数持续升高，可以降低 `Window Size` 或设置 `Rate Limit KiB/s` 继续压低主机发包压力。

## PC 接收工具

接收 GUI 主窗口的 Network/Output 参数和 Metrics 使用双列紧凑布局；下方 Charts 与 Event Log 之间的横向分隔条可以上下拖动。需要重点看串口/接收日志时，可向上拖动分隔条扩大 Event Log；AIRV 图像继续显示在独立 `AIRV Preview` 窗口中，不占主窗口日志空间。

接收 GUI 的 `RX Rate (1s)`、`RX KiB/s (last 1s)` 和 `Packets/s (last 1s)` 都使用最近 1 秒滑动窗口，只统计该窗口内新增的 loopback payload 和 UDP 包数。点击 Start 后等待 IPCFG/RXCFG 或等待第一批数据的时间不进入速率分母；停止收包后，指标会在约 1 秒内回落到 `0`。这表示近期接收速率，不是从启动至今的累计平均值。

接收 GUI 入口：

```bash
python AD9361_test2/tools/pc_sender/receiver_gui.py
```

命令行入口：

```bash
python AD9361_test2/tools/pc_sender/recv_data.py --board-ip 192.168.1.50 --bind-port 15002 --output-dir output
```

常用 GUI 字段：

```text
Bind IP             本机监听 IP；双网卡 IPCFG 必须填直连 Zynq 的网卡 IP，不能填 0.0.0.0
Bind Port           本机接收 loopback UDP 端口。默认 15002
Board IP            板端本次运行 IP；上电默认 192.168.1.50
Board Netmask       板端本次运行掩码，默认 255.255.255.0
Board Gateway       直连时填 0.0.0.0
Board Port          板端 UDP 端口。默认 5001
Configure Board IP  勾选后在 RXCFG 前广播 IPCFG；切换网段时使用
Register RX target  勾选后发送 RXCFG，把本机注册为回传目标
Socket Buffer       本机 UDP 接收缓冲，默认 16777216
Output Directory    恢复文件保存目录。默认 output
File Name           可选输出文件名；不填则按时间自动命名并推断扩展名
Raw Expected        仅 raw 模式使用的期望连续字节数；AIR0 模式保持 0
Idle Finish(s)      数据不完整时，收到最后一个回传分片后空闲多久判定结束
```

单电脑测试时，在同一台电脑上先启动 `receiver_gui.py`，确认日志出现 `RX target registered ...`，再启动 `sender_gui.py` 发送文件。两台 PC 分别承担发送和接收时，在接收电脑先完成 IPCFG/RXCFG；发送电脑的 `Target IP` 必须与接收 GUI 的 `Board IP` 一致。

新电脑双网卡直连 Zynq 的完整 GUI 设置：

```text
Receiver Bind IP                     192.168.2.101
Receiver Bind Port                   15002
Receiver Board IP                    192.168.2.50
Receiver Board Netmask               255.255.255.0
Receiver Board Gateway               0.0.0.0
Receiver Configure Board IP          checked
Receiver Register RX target          checked
Receiver Raw Expected                0
Receiver Idle Finish(s)              10

Sender Target IP                     192.168.2.50
Sender Target Port                   5001
```

启动顺序必须是板卡上电并运行新版 ELF，再启动接收 GUI。接收 GUI 预期依次输出 `IPCFG applied board=192.168.2.50 ...` 和 `RX target registered at board 192.168.2.50:5001 ...`；板端串口预期输出 `IPCFG applied IP=192.168.2.50`、`IPCFG ready ...`、`RXCFG loopback peer ...`。确认这些日志后再启动发送 GUI。若 IPCFG 日志没有出现，首先检查 `Bind IP` 是否误填 `0.0.0.0`、网口2是否确实为 `192.168.2.101/24`，以及 Windows 防火墙是否允许该 Python 程序使用专用网络 UDP。

要恢复图片或视频，发送 GUI 使用 `Mode=File`，选择原始图片/视频文件；`Payload CRC32` 开启，`AIR0 Packet Header` 保持默认开启。AIR0 头已携带 `file_size`、`total_packets` 和 `file_crc32`，接收 GUI 的 `Raw Expected` 保持 `0` 即可，不需要预先填写文件大小。无失真且无缺口时，恢复出的文件会出现在 `output` 目录，扩展名会根据文件头自动推断为 `.png`、`.jpg`、`.mp4` 等常见格式。

当前默认开启 `AIR0 Packet Header`。开启 AIR0 后，接收端会优先使用 AIR0 头里的 `file_size` 和 `file_crc32` 判断完整性；`Raw Expected` 只在关闭 AIR0 的 raw 模式下作为保存长度兜底。接收 GUI/CLI 的 `PROGRESS` 会输出 `pending_air=...`，表示当前尚未收到的 AIR0 包数；传输未结束时它会随接收推进逐步下降，不是最终丢包数。最终 `DONE` / `INCOMPLETE` 输出 `miss=... bad_hdr=... bad_payload=... bad_meta=... dup=... file_crc=... got_last=... file_id=... file_size=... total_packets=...`。如果最终存在缺失 AIR0 包，`INCOMPLETE` / `DONE` 还会输出 `missing_seq=...`，用逗号分隔缺失 `packet_seq` 范围，例如 `missing_seq=120-124,301,488`；范围很多时会截断为 `...(+N ranges)`。如果出现 payload CRC 或 AIR0 元数据一致性错误，还会输出 `bad_payload_seq=...` 或 `bad_meta_seq=...`。`Idle Finish(s)` 仍保留，用于缺包或尾包未到达时触发最终 `INCOMPLETE` 判断。

如果接收 GUI 出现 `INCOMPLETE`，或者 `DONE` 中 `gaps` 不为 0、`saved` 为空，说明 PC 接收端没有拿到完整连续 payload；此时工具不会保存带洞文件。大文件测试时优先确认 `rx` 最终等于原文件大小、`high` 等于原文件大小、`gaps=0`、`crc=0`、`len=0`。

## PC->PS payload 格式

PC->PS 应用层包头后始终是普通 wire payload，PS 和 PL 不根据 payload 内容做额外交互：

```text
net_data_header_t + wire payload
```

默认开启 AIR0 时，wire payload 内部为：

```text
64-byte AIR0 header + original file/test payload fragment
```

关闭 AIR0 时，wire payload 就是原始文件/测试数据片段。无论是否开启 AIR0，PS 都只校验 `net_data_header_t` 和可选 payload CRC32，然后把 wire payload 原样写入 DDR 聚合块并通过 DMA 送入 PL。

## 串口统计

板端仅在统计周期内有 RX、accepted 或 DMA 活动时输出统计：

```text
================ NET STAT ================
STAT rate rx=... acc=... dma=... avg_rx=... avg_acc=... avg_dma=... rx_pkt=... acc_pkt=... dma_done=...
STAT state q=.../... qmax=... ack=... nack=... crc=... badlen=... badmagic=... busy=... pend=... dup=... drop=... dma_err=... agg=... agg_full=... agg_to=... agg_avg=... agg_min=... agg_max=...
==========================================
```

字段含义：

```text
rx / rx_pkt       UDP 回调看到的输入 payload 速率和包数，包含之后被拒收的包
acc / acc_pkt     实际写入 PS 聚合缓冲的 payload 速率和包数
dma / dma_done    AXI DMA 已完成发送的字节速率和完成次数
q / qmax          当前和历史最大非 FREE 聚合块数量
ack / nack        ACK 发送总数和非 OK ACK 总数
crc               payload CRC 错误数
badlen/badmagic   协议长度或 magic 错误
busy              聚合缓冲满导致拒收
pend              session 不匹配或序号超前导致拒收
dup               重复包
drop              协议错误或资源不足导致丢弃
dma_err           DMA 错误
agg               已提交聚合块数
agg_full          满块或放不下下一包导致提交
agg_to            超时导致提交
agg_avg/min/max   聚合块 payload_len 统计
```

PC 发送工具现在把速率拆成三个真实口径：

```text
app_deliv   原始业务 payload 被 ACK 的速率；按用户输入数据计数。
wire_acc    PS 已接受的 wire payload 速率；对应板端 `acc`，AIR0 模式会包含 64 字节 AIR0 header。
udp_tx      主机实际送入 UDP socket 的应用层字节速率；包含 16 字节 PC->PS 包头和重传。
```

PC 接收工具负责 PL->PS->UDP 回传指标：

```text
rx          从 offset 0 开始已经连续恢复的 payload 字节数。
high        当前收到过的最高结束偏移。
pkt         收到的 loopback UDP 分片数。
blk         收到完整 LAST_CHUNK 标记的 PL 回传块数。
rate        接收端 loopback payload 平均速率。
crc         loopback UDP 分片 CRC 错误数。
len         loopback 分片实际长度与包头 chunk_len 不一致的错误数。
gaps        当前已收到区间中 offset 0 之后的缺口数量。
saved       已保存的恢复文件路径。
air         是否自动识别到 AIR0 payload header。
air_rx      已通过 AIR0 header/payload CRC 校验的数据包数 / AIR0 总包数。
pending_air PROGRESS 中当前尚未收到的 AIR0 包数量；传输中不代表最终丢包。
miss        DONE/INCOMPLETE 中 AIR0 packet_seq 统计出的最终缺失包数量。
missing_seq 最终缺失 AIR0 packet_seq 范围；仅在 INCOMPLETE/DONE 且 miss>0 时输出。
bad_hdr     AIR0 header magic/version/length/header_crc 校验失败次数。
bad_payload AIR0 payload_crc32 校验失败次数。
bad_payload_seq 最终 AIR0 payload CRC 错误 packet_seq 范围。
bad_meta    AIR0 `session_id/file_id/total_packets/file_size/file_crc32/chunk_bytes` 不一致，或 DATA/LAST flag 不合法的包数量。
bad_meta_seq 最终 AIR0 元数据错误 packet_seq 范围。
dup         AIR0 重复 packet_seq 数量。
file_crc    AIR0 恢复文件 CRC32 是否匹配。
file_size   AIR0 header 声明的原始文件/测试数据总字节数。
total_packets AIR0 header 声明的总包数。
file_id     AIR0 header 中由文件大小、文件 CRC 和 session 生成的文件标识。
got_last    是否收到合法 LAST 包；LAST 必须出现在 `packet_seq == total_packets - 1`。
```

判断真实端到端吞吐时：

- 看业务数据吞吐，用 PC `app_deliv`。
- 看 PS 实际接受了多少准备送 PL 的数据，用 PC `wire_acc` 对齐板端 `acc`。
- 看 PL 实际收到多少 DMA 数据，用板端 `dma`。
- 看主机实际发包压力，用 PC `udp_tx`，它会随重传和 ACK/BUSY/PENDING 变化。

`rx` 是板端输入尝试流量，主机发太快或重传多时可能高于 `acc`。AIR0 模式下 `app_deliv` 与 `wire_acc/acc/dma` 本来就不应完全相等，因为 wire payload 额外包含 64 字节 AIR0 header。

## AD9361 RF 回环与 S2MM 调试

当前 DMA 调试使用 `NET_DMA_STALL_TIMEOUT_US = 20000`。此前 64 KiB AIR0 数字回环
精确恢复测试表明前 8 个块的主循环观察耗时约 `8.1～10.1 ms`，旧 `6000 us`
阈值会误判正常 S2MM 为 stall；改为 `20000 us` 后所有块 `cmp=OK`，文件
`65536/65536` 字节、48/48 AIR0 包和最终 CRC 全部正确。
成功完成的 `S2MM diag` 和 `S2MM done` 会输出 `wait_us`，表示从 arm S2MM
到主循环观察到 `RxDone` 的耗时。该值包含主循环处理 UART、lwIP 和 UDP 回传
造成的观察延迟；只要进入完成分支，就不会再按 watchdog 判为超时。

当前代码已开启 AD9361 RF 回环后的 S2MM 接收调试和 UDP 回传：

```text
NET_LOOPBACK_S2MM_DEBUG_ENABLE 1
NET_LOOPBACK_UDP_RETURN_ENABLE 1
RX_BUFFER_BASE                 0x01400000
RX_TRANSFER_LENGTH_BYTES       8192
NET_DMA_STALL_TIMEOUT_US       20000
NET_LOOPBACK_RX_PREFIX_BYTES   16
NET_LOOPBACK_UDP_PAYLOAD_BYTES 1200
NET_LOOPBACK_S2MM_LOG_FIRST_BLOCKS 2
NET_LOOPBACK_S2MM_LOG_INTERVAL_BLOCKS 0
NET_LOOPBACK_S2MM_LOG_DIFF_ALWAYS 0
NET_LOOPBACK_S2MM_SUMMARY_FIRST_BLOCKS 8
NET_LOOPBACK_S2MM_SUMMARY_INTERVAL_BLOCKS 0
NET_LOOPBACK_S2MM_SUMMARY_DIFF_ALWAYS 0
NET_LOOPBACK_RETURN_SOURCE     NET_LOOPBACK_RETURN_SOURCE_S2MM
```

RX 端可能没有解出合法帧，S2MM 也可能一直等不到 TLAST。当前使用 `NET_DMA_STALL_TIMEOUT_US = 20000` 的 watchdog：如果 MM2S/S2MM 在超时内没有完成，板端会打印 `DMA stall timeout ...`，重置 AXI DMA 和 RX pipeline。若 `TxDone=1`，说明本块已经送入 TX 侧；若 `TxDone=0`，说明 TX stream/tx_intf 侧也没有完成，并会计一次 `dma_err`。随后如何处理当前聚合块由本 session 的 RF 模式决定：默认 `deliver_no_retry` 释放该块并继续调度；`strict_retry` 保留该块并最多重新送入 MM2S 3 次，耗尽后打印 `RF drop` 再释放。两种模式都避免把后续 PC 输入永久卡在 `BUSY`。

当前默认已经切回 `NET_LOOPBACK_RETURN_SOURCE_S2MM`，启动日志应出现 `Loopback return source=S2MM RF path`。上一轮 `NET_LOOPBACK_RETURN_SOURCE_TX_BUFFER` 诊断模式已证明 PC 发送、PS 接收/聚合、PS UDP 回传和 PC 接收恢复正常；如果后续再次怀疑 PC/PS 侧，可临时切回该模式，启动日志会显示 `Loopback return source=TX_BUFFER diagnostic, MM2S/S2MM bypassed`，每块打印 `TXECHO return ... first=0x30524941 ...`。

为避免 UART 打印拖慢 PS/lwIP/DMA 主循环，当前只对前 2 个 S2MM block 打印较完整的 `S2MM done/rx_head/rx_hdr/rx_payload_head/tx_head`，并只对前 8 个 block 打印一行 `S2MM diag ...` 摘要。后续普通 payload mismatch 不再逐块打印 `S2MM diag/S2MM pass corrupt`，其影响由 PC 的周期 `VIDEO` 和最终 `VIDEO_DONE` 汇总；结构无效仍打印 `S2MM reject`，DMA/RF timeout、retry、drop、error 和周期 `STAT` 仍保留。

每次 PS 准备通过 MM2S 把一个聚合块送入 PL 前，会先 arm 一个 `8192` 字节
S2MM 捕获窗口。简单模式 AXI DMA 只保留编程的窗口容量，没有独立的实际接收
字节数；因此 S2MM 完成后，PS 会从 16 字节 PL 头中的 OFDM length 字段推导
真实 payload 长度，并校验它不超过 OFDM/捕获窗口上限。magic 扫描、CRC、比较
和 UDP 回传都被限制在该可信长度内，窗口尾部未写入的旧数据不再参与处理。
若头部长度非法或与当前 TX block 不同，摘要分别显示
`RX_LENGTH_INVALID` / `RX_LENGTH_MISMATCH`，且非法长度的帧不会回传。

当前 TX/RX 已解耦，S2MM 收到的帧可能是 RX 侧 FIFO 中延迟堆积的旧帧，不一定对应当前刚启动的 MM2S 聚合块。为定位这种错配，PS 会在 S2MM buffer 前 `2048` 字节内扫描 AIR0/AIRV magic。AIR0 与 AIRV v2 都会校验必要头字段，并用各自的全局 `packet_seq * chunk_bytes` 推导 UDP 回传 `stream_offset`；详细日志分别打印 `S2MM air0 ... desync=...` 和 `S2MM airv packet=... chunk=... stream_off=... tx_stream_off=... desync=...`。AIRV v2 头 CRC 或关键字段非法时摘要为 `class=AIRV_HEADER_INVALID`；找不到 magic 时为 `class=NO_AIR_MAGIC`，并给出最接近 magic 的 `best_off/best_xor/best_bits`。

S2MM 完成后的校验和动作取决于 RF 模式：

- 默认 `deliver_no_retry`：长度、固定 16 字节前缀和 AIR0/AIRV magic 等帧结构合法时，即使 RX payload 与当前 TX block 存在字节差异，仍打印 `S2MM pass corrupt ... action=deliver_no_retry` 并把实际 RX 字节回传给 PC；AIR0/AIRV 的 CRC 和缺包统计负责暴露损坏。长度非法、magic 缺失、前缀偏移等结构无效帧打印 `S2MM reject ... action=drop_no_retry` 并丢弃当前块。
- `strict_retry`：payload mismatch 也视为无效捕获，不向 PC 回传。若收到的可能是延迟旧帧，板端先只重新 arm S2MM 等待期望帧；等待超时或恢复路径再重置 DMA/RX pipeline，将保留的聚合块重新送入 MM2S。初次发送之外最多重发 3 次，日志打印 `RF retry reason=... attempt=.../3`；耗尽或 DMA reset 失败后打印 `RF drop`。

MM2S 启动前的顺序是先 `OpenWifi_Tx_Rearm(payload_len)`，再由 `net_configure_tx_frame()` 写入最终 `tx_intf` 帧长、DMA word 数和 auto-start threshold。不要把 `OpenWifi_Tx_Rearm()` 放在 `net_configure_tx_frame()` 后面，否则某些短帧长度会覆盖并清掉 auto-start enable，表现为 `S2MM wait ... txdone=0 rxdone=0`。

关键日志：

```text
S2MM loopback debug ready, rx_base=0x01400000 rx_bytes=8192 ...
S2MM start id=1 block=0 capture=8192 tx_transfer=2880 tx_payload=2880
S2MM wait id=1 capture=8192 tx_transfer=2880 waited_ms=1000 txdone=... rxdone=... tx_irq=... rx_irq=... rx_sr=...
S2MM diag id=1 class=NO_AIR_MAGIC cap=8192 tx_payload=1440 tx_transfer=1440 prefix=16 len_guess=... len_valid=1 magic=no off=0 word=0x00000000 best_off=... best_magic=... best_xor=... best_bits=... rx0=... rx_payload0=... tx0=0x30524941 rx_crc=... tx_crc=... cmp=DIFF diff=0 rx_state=... wd=...
S2MM done id=1 capture=8192 tx_transfer=2880 rx_prefix=16 cmp_len=2880 irq=0x... sr=0x... rx_crc=0x... tx_crc=0x... cmp=OK done=1
S2MM done id=1 capture=8192 tx_transfer=2880 rx_prefix=16 cmp_len=2880 irq=0x... sr=0x... rx_crc=0x... tx_crc=0x... cmp=DIFF first_diff=...
S2MM rx_head ...
S2MM rx_hdr ts=... meta0=... meta1=... len_field=... payload_guess=... rate_guess=... tx_payload=... tx_transfer=... match=...
S2MM rx_payload_head ...
S2MM tx_head ...
S2MM payload_magic offset=16 magic=0x30524941 expected_prefix=16
S2MM air0 seq=0 chunk=1440 file_off=0 stream_off=0 tx_stream_off=0 desync=no
S2MM airv packet=0 chunk=1440 stream_off=0 tx_stream_off=0 desync=no
LB UDP sent block=1 stream_off=0 payload=2880 packets=3 total_bytes=2880 peer_port=...
DMA stall timeout id=3 block=0 waited_us=6001 txdone=0 rxdone=0 tx_irq=0x... rx_irq=0x... tx_sr=0x... rx_sr=0x... tx_cr=0x... rx_cr=0x... tx_buflen=... rx_buflen=... rx_state=0x... wd=... count=1
DMA stall recovery reset_done=1
RF retry reason=timeout id=... block=... attempt=1/3 payload=... stream_off=... total=...
RF drop reason=timeout id=... block=... payload=... stream_off=... reset_done=... drops=...
S2MM pass corrupt id=... block=... first_diff=... passes=... action=deliver_no_retry
S2MM reject id=... block=... reason=... rejects=... action=drop_no_retry
S2MM error id=1 irq=0x... sr=0x... cr=0x... buflen=... err_int=... err_slv=... err_dec=... errors=1
```

反馈板级测试结果时，优先提供：

- 启动后的 `S2MM loopback debug ready` 行。
- 发送 16 KiB 或更小测试数据后的所有 `S2MM start/wait/done/error` 行。
- 所有 `S2MM diag`、`S2MM payload_magic`、`S2MM air0` 和 `S2MM airv` 行。
- 所有 `LB UDP sent` 行。
- 同一轮的 `UDP RX reset ... rf_mode=...`、`RF retry`、`RF drop`、`S2MM pass corrupt/reject`、`STAT rate` / `STAT state` 行。
- 接收 GUI 日志中的 `RX target registered ...`、`PROGRESS rx=... crc=... len=... gaps=...`、`INCOMPLETE ... missing_seq=...` 和 `DONE ... saved=... missing_seq=...` 行。
- 如果出现 `cmp=DIFF`，提供紧随其后的 `S2MM rx_head` 和 `S2MM tx_head`。

如果只看到 `S2MM start` 后出现 `DMA stall timeout`，说明真实空口 RX 没有在 watchdog 时间内形成完整 S2MM 包。重点看 `txdone/rxdone`：`txdone=1 rxdone=0` 偏向 RX/解调/TLAST 问题；`txdone=0 rxdone=0` 偏向 TX stream/tx_intf/openofdm_tx 没有消费完本块。再根据 reset 日志中的 `rf_mode` 判断后续：`deliver_no_retry` 会丢弃当前块并继续，`strict_retry` 应继续出现 `RF retry`，最多 3 次后才 `RF drop`。如果出现 `S2MM error`，先根据 `irq` 判断 DMA 错误类型，再检查长度、TLAST 和 AXI-Stream 握手。

## 构建和运行

推荐环境：`Xilinx SDK 2018.3`。

1. 打开 Xilinx SDK 2018.3。
2. 使用仓库根目录作为 workspace。
3. 如未自动识别，导入 `System_wrapper_hw_platform_0`、`AD9361_test2_bsp`、`AD9361_test2`。
4. 在 BSP Settings 中确认 standalone `stdin/stdout` 都是 `ps7_uart_0`，然后
   重新生成并构建 `AD9361_test2_bsp`；不要使用 `ps7_coresight_comp_0`。
5. 构建 `AD9361_test2`。
6. 使用 `System_wrapper_hw_platform_0/System_wrapper.bit` 配置 FPGA。
7. 下载并运行 `AD9361_test2.elf`。
8. 打开串口，波特率 `115200`。
9. 从 PC ping 当前板端地址：默认是 `192.168.1.50`，IPCFG 成功后使用 GUI 中配置的新地址。
10. 使用 CLI 或 GUI 发送数据。

SDK 工程当前 Debug 配置使用 Cortex-A9 hard-float flags：

```text
-mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard
```

链接依赖 BSP 的 `libxil`、`libgcc`、`libc` 和 `lwip4`，链接脚本为 `AD9361_test2/src/lscript.ld`。

## 修改注意事项

- 改协议结构、flag、ACK 语义、CRC 默认值或 PC 发送策略时，同时改 `net_protocol.h`、`net_config.h` 和 `sender_core.py`，并更新本 README。
- 改 `NET_AGG_BLOCK_BYTES` 时，必须同时检查 `NET_AGG_BLOCK_STRIDE_BYTES`、`NET_MAX_PAYLOAD_BYTES`、`NET_OFDM_MAX_PSDU_BYTES`、8 字节对齐、AXI DMA simple transfer 长度限制，以及 `tx_intf` auto-start 阈值。DMA slot stride 必须保持 cache-line 对齐，不能让相邻 slot 共享 cache line。
- 改 PC `chunk_size` 默认值时，确认 raw/AIR0 wire payload 不超过 PS 侧最大 payload，并考虑 1500 MTU 分片。
- 改 cache 开关或新增 S2MM 路径时，先把 flush/invalidate 点设计清楚。
- BSP 和硬件导出目录尽量由 Xilinx 工具再生成，不做零散手改。
- 仓库只保留根目录 `README.md`；不要在子目录重新添加 README。
