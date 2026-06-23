# ZYNQ_AD9361_OFDM

这是一个基于 `Xilinx SDK 2018.3` 的 `Zynq-7000 + AD9361` 裸机工程。当前主链路是 PC 通过 UDP 向 Zynq PS 发送应用层数据包，PS 使用 lwIP RAW UDP 接收、校验和排序，把数据写入 DDR 中的发送缓冲，再通过 AXI DMA MM2S 推给 PL 侧 `tx_intf/openofdm_tx`。当前 Vivado 工程是 PL loopback：数据经过 PL 侧 OFDM 调制/解调恢复后，通过 S2MM 回到 PS，PS 再把恢复出的 payload 用 UDP 发回专门的 PC 接收工具做分片 CRC、连续性检查和文件恢复。

```text
PC UDP sender
-> Zynq PS lwIP RAW UDP
-> net_data_header_t/session/seq/CRC check
-> PS DDR aggregation blocks
-> AXI DMA MM2S
-> PL tx_intf/openofdm_tx
-> PL OFDM loopback/decode
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
    cache 开关、DMA buffer 地址和长度、静态 IPv4 配置。

AD9361_test2/src/drivers/net/net_config.h
    UDP 端口、协议 magic/flag、ACK 状态、聚合块、ACK 合并、轮询预算。

AD9361_test2/src/drivers/net/net_protocol.h/.c
    PC<->PS 应用层包头、ACK 包结构、CRC32、8 字节对齐。

AD9361_test2/src/drivers/net/net_init.c
    lwIP/GEM 初始化、静态 IP、`xemacif_input()` 输入轮询。

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
    接收 Tkinter GUI 入口。
```

## 板端启动流程

`main.c` 当前流程：

1. 根据 `APP_ENABLE_ICACHE` / `APP_ENABLE_DCACHE` 开关启用或关闭 cache。
2. 初始化 GPIO、SPI、AD9361，并写入 AD9361 TX clock/data delay。
3. 初始化 UART，波特率 `115200`。
4. 初始化 SCU GIC。
5. 初始化 `openofdm_tx`、`tx_intf` 静态寄存器，并用默认 `3000` 字节 PSDU 先 re-arm 一次。
6. 初始化 `openofdm_rx/rx_intf` 的数字 loopback/debug 相关寄存器，并周期性打印 RX debug 计数。
7. 初始化 AXI DMA 和 MM2S/S2MM 中断。
8. 初始化 lwIP/GEM，使用静态 IPv4。
9. 绑定 UDP `5001`，初始化 DDR 聚合缓冲。
10. 进入主循环：

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

直连测试时，PC 网卡配置到同一网段，例如 `192.168.1.10/24`。板端正常启动后应能从 PC `ping 192.168.1.50`。

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
bit13      reserved，当前置 0
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
DATA header      16 bytes
ACK packet       16 bytes
RESET flag       0x8000
NO_CRC flag      0x4000
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

## UDP Loopback 回传协议

接收工具启动后会先用本机接收 socket 向板端 `192.168.1.50:5001` 发送一个 16 字节 `RXCFG` 控制包。该包与普通 `net_data_header_t` 形状相同，只是 `magic=0x52435830`、`payload_len=0`。板端收到后记录该 UDP 包的源 IP/源端口作为 PL loopback 回传目标，返回 `ACK OK`，并打印 `RXCFG loopback peer port=...`。

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
--air-protocol          启用 PC-only AIR0 payload header，默认开启
--no-air-protocol       关闭 AIR0，发送旧版原始文件/测试字节流
```

## PC-only AIR0 payload header

当前第一阶段强协议只在 PC 端生效。发送 PC 默认把每个 `Chunk Bytes=1440` 的 wire payload 封装成：

```text
64-byte AIR0 header + up to 1376-byte original file/test payload
```

PS 和 PL 不解析 AIR0；对它们来说这 1440 字节仍然只是普通 payload。接收 PC 从 PL loopback 回传的字节流中自动识别 AIR0，按 `packet_seq/file_offset/file_size/payload_crc32/header_crc32/file_crc32` 恢复原始文件，并统计丢包、坏头、坏 payload CRC 和重复包。AIR0 当前不做 FEC、不做接收端 ACK、不做空口重传，只用于让接收端明确知道是否完整以及缺了哪些包。

如需回到旧版纯字节流，对发送 GUI 取消勾选 `AIR0 Packet Header`，或 CLI 使用 `--no-air-protocol`。

推荐 GUI/CLI 吞吐配置：

```text
模式                    Test Data
Throughput Mode         开启
Payload CRC32           开启
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
Bind IP             本机监听 IP。通常填 0.0.0.0
Bind Port           本机接收 loopback UDP 端口。默认 15002
Board IP            板端 IP。默认 192.168.1.50
Board Port          板端 UDP 端口。默认 5001
Register RX target  勾选后发送 RXCFG，把本机注册为回传目标
Socket Buffer       本机 UDP 接收缓冲，默认 16777216
Output Directory    恢复文件保存目录。默认 output
File Name           可选输出文件名；不填则按时间自动命名并推断扩展名
Expected Bytes      期望恢复的连续字节数；知道原文件大小时填文件大小
Idle Finish(s)      Expected Bytes 为 0 时，收到数据后空闲多久自动保存
```

单电脑测试时，在同一台电脑上先启动 `receiver_gui.py`，确认日志出现 `RX target registered ...`，再启动 `sender_gui.py` 发送文件。双电脑测试时，在接收电脑先启动 `receiver_gui.py` 并注册；发送电脑只运行 `sender_gui.py`，目标 IP 仍填板端 `192.168.1.50`。

要恢复图片或视频，发送 GUI 使用 `Mode=File`，选择原始图片/视频文件；`Payload CRC32` 开启，`AIR0 Packet Header` 保持默认开启。接收 GUI 的 `Expected Bytes` 最好填原文件大小；不方便确认时可填 `0`，由空闲超时保存。无失真且无缺口时，恢复出的文件会出现在 `output` 目录，扩展名会根据文件头自动推断为 `.png`、`.jpg`、`.mp4` 等常见格式。

当前默认开启 `AIR0 Packet Header`。开启 AIR0 后，接收端会优先使用 AIR0 头里的 `file_size` 和 `file_crc32` 判断完整性；`Expected Bytes` 仍可填写原文件大小作为人工核对。接收 GUI/CLI 的 `PROGRESS` 和 `DONE` 会额外输出 `air=... air_rx=... miss=... bad_hdr=... bad_payload=... dup=... file_crc=...`。如果最终存在缺失 AIR0 包，`INCOMPLETE` / `DONE` 还会输出 `missing_seq=...`，用逗号分隔缺失 `packet_seq` 范围，例如 `missing_seq=120-124,301,488`；范围很多时会截断为 `...(+N ranges)`。

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
miss        AIR0 packet_seq 统计出的缺失包数量。
missing_seq 最终缺失 AIR0 packet_seq 范围；仅在 INCOMPLETE/DONE 且 miss>0 时输出。
bad_hdr     AIR0 header magic/version/length/header_crc 校验失败次数。
bad_payload AIR0 payload_crc32 校验失败次数。
dup         AIR0 重复 packet_seq 数量。
file_crc    AIR0 恢复文件 CRC32 是否匹配。
```

判断真实端到端吞吐时：

- 看业务数据吞吐，用 PC `app_deliv`。
- 看 PS 实际接受了多少准备送 PL 的数据，用 PC `wire_acc` 对齐板端 `acc`。
- 看 PL 实际收到多少 DMA 数据，用板端 `dma`。
- 看主机实际发包压力，用 PC `udp_tx`，它会随重传和 ACK/BUSY/PENDING 变化。

`rx` 是板端输入尝试流量，主机发太快或重传多时可能高于 `acc`。AIR0 模式下 `app_deliv` 与 `wire_acc/acc/dma` 本来就不应完全相等，因为 wire payload 额外包含 64 字节 AIR0 header。

## PL->PS S2MM 回环调试

当前代码已开启 PL 回环接收和 UDP 回传：

```text
NET_LOOPBACK_S2MM_DEBUG_ENABLE 1
NET_LOOPBACK_UDP_RETURN_ENABLE 1
RX_BUFFER_BASE                 0x01400000
RX_TRANSFER_LENGTH_BYTES       8192
NET_LOOPBACK_RX_PREFIX_BYTES   16
NET_LOOPBACK_UDP_PAYLOAD_BYTES 1200
```

每次 PS 准备通过 MM2S 把一个聚合块送入 PL 前，会先 arm 一个 `8192` 字节 S2MM 捕获窗口。S2MM 完成后，PS 会 invalidate RX buffer，跳过 PL/RX 接口返回数据前面的 16 字节前缀，并按当前聚合块真实 `payload_len` 比较 RX payload 和 TX buffer；`tx_transfer` 只是 8 字节对齐后的 DMA 长度，尾部 padding 不参与 payload 比较。比较完成后，PS 会把跳过 16 字节头后的 payload 按 1200 字节 UDP 分片发回已注册的 PC 接收工具。

MM2S 启动前的顺序是先 `OpenWifi_Tx_Rearm(payload_len)`，再由 `net_configure_tx_frame()` 写入最终 `tx_intf` 帧长、DMA word 数和 auto-start threshold。不要把 `OpenWifi_Tx_Rearm()` 放在 `net_configure_tx_frame()` 后面，否则某些短帧长度会覆盖并清掉 auto-start enable，表现为 `S2MM wait ... txdone=0 rxdone=0`。

关键日志：

```text
S2MM loopback debug ready, rx_base=0x01400000 rx_bytes=8192 ...
S2MM start id=1 block=0 capture=8192 tx_transfer=2880 tx_payload=2880
S2MM wait id=1 capture=8192 tx_transfer=2880 waited_ms=1000 txdone=... rxdone=... tx_irq=... rx_irq=... rx_sr=...
S2MM done id=1 capture=8192 tx_transfer=2880 rx_prefix=16 cmp_len=2880 irq=0x... sr=0x... rx_crc=0x... tx_crc=0x... cmp=OK done=1
S2MM done id=1 capture=8192 tx_transfer=2880 rx_prefix=16 cmp_len=2880 irq=0x... sr=0x... rx_crc=0x... tx_crc=0x... cmp=DIFF first_diff=...
S2MM rx_head ...
S2MM rx_hdr ts=... meta0=... meta1=... len_field=... payload_guess=... rate_guess=... tx_payload=... tx_transfer=... match=...
S2MM rx_payload_head ...
S2MM tx_head ...
LB UDP sent block=1 stream_off=0 payload=2880 packets=3 total_bytes=2880 peer_port=...
S2MM error id=1 irq=0x... sr=0x... cr=0x... buflen=... err_int=... err_slv=... err_dec=... errors=1
```

反馈板级测试结果时，优先提供：

- 启动后的 `S2MM loopback debug ready` 行。
- 发送 16 KiB 或更小测试数据后的所有 `S2MM start/wait/done/error` 行。
- 所有 `LB UDP sent` 行。
- 同一轮的 `STAT rate` / `STAT state` 行。
- 接收 GUI 日志中的 `RX target registered ...`、`PROGRESS rx=... crc=... len=... gaps=...`、`INCOMPLETE ... missing_seq=...` 和 `DONE ... saved=... missing_seq=...` 行。
- 如果出现 `cmp=DIFF`，提供紧随其后的 `S2MM rx_head` 和 `S2MM tx_head`。

如果只看到 `S2MM start` 和周期性 `S2MM wait`，说明 S2MM 没有完成，重点看 PL 是否输出 TLAST、S2MM 中断是否接到 GIC、RX stream 是否有数据。如果出现 `S2MM error`，先根据 `irq` 判断 DMA 错误类型，再检查长度、TLAST 和 AXI-Stream 握手。

## 构建和运行

推荐环境：`Xilinx SDK 2018.3`。

1. 打开 Xilinx SDK 2018.3。
2. 使用仓库根目录作为 workspace。
3. 如未自动识别，导入 `System_wrapper_hw_platform_0`、`AD9361_test2_bsp`、`AD9361_test2`。
4. 构建 `AD9361_test2_bsp`。
5. 构建 `AD9361_test2`。
6. 使用 `System_wrapper_hw_platform_0/System_wrapper.bit` 配置 FPGA。
7. 下载并运行 `AD9361_test2.elf`。
8. 打开串口，波特率 `115200`。
9. 从 PC `ping 192.168.1.50`。
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
