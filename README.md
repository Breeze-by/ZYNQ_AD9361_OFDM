# ZYNQ_AD9361_OFDM

这是一个基于 `Xilinx SDK 2018.3` 的 `Zynq-7000 + AD9361` 裸机工程。当前主链路是 PC 通过 UDP 向 Zynq PS 发送应用层数据包，PS 使用 lwIP RAW UDP 接收、校验和排序，把数据写入 DDR 中的发送缓冲，再通过 AXI DMA MM2S 推给 PL 侧 `tx_intf/openofdm_tx`，最终进入 AD9361 发射路径。

```text
PC UDP sender
-> Zynq PS lwIP RAW UDP
-> net_data_header_t/session/seq/CRC check
-> PS DDR aggregation blocks
-> AXI DMA MM2S
-> PL tx_intf/openofdm_tx
-> AD9361 TX
```

当前仓库只保留这一份 README。以后更新项目说明、协议、构建步骤、PC 工具用法或调参结论，都直接更新根目录 `README.md`，不要在子目录新增 README。

## 目录结构

```text
ZYNQ_AD9361_OFDM/
|-- README.md                         # 唯一项目说明
|-- AGENT.md                          # 后续 agent 上手指南
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
|   `-- tools/pc_sender/              # Python CLI/Tkinter GUI 发送工具
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
    MM2S DMA 启动和完成回收。

AD9361_test2/src/drivers/net/net_stats.c
    周期性串口统计输出。

AD9361_test2/tools/pc_sender/sender_core.py
    Python 发送核心；滑动窗口、reset/session、重传、OFDM legacy 封装、
    PL verify pattern、CLI 参数。

AD9361_test2/tools/pc_sender/send_data.py
    命令行入口。

AD9361_test2/tools/pc_sender/sender_gui.py
    Tkinter GUI 入口。
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
UDP RX ready, agg_blocks=699 block_bytes=3000 total_bytes=2097152 max_payload=3000 rec_window<=64 ack=on_accept
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
bit13      OFDM_LEGACY flag
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
DATA header      16 bytes
ACK packet       16 bytes
RESET flag       0x8000
NO_CRC flag      0x4000
OFDM_LEGACY flag 0x2000
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

`NO_CRC` 由 PC 工具的 Payload CRC32 开关决定。默认关闭 payload CRC，因此 reset 包携带 `NO_CRC`，普通包的 `payload_crc32=0`；开启 `--payload-crc` 或 GUI 对应选项后，PC 对 wire payload 计算 CRC32，PS 接收后校验。

`OFDM_LEGACY` 只标记本次传输模式并写入板端 reset 日志。PS 不解析 OFDM `addr0/addr1`，它只把应用层包头后的 wire payload 原样写入 DMA buffer。

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
NET_AGG_BLOCK_BYTES            3000
NET_AGG_BLOCK_COUNT            699
NET_DMA_QUEUE_CAPACITY         699
NET_AGG_MIN_FLUSH_BYTES        1500
NET_AGG_FLUSH_TIMEOUT_US       15000
NET_AGG_IDLE_FLUSH_TIMEOUT_US  100000
NET_MAX_PAYLOAD_BYTES          3000
```

DDR 中实际参与聚合队列管理的容量是 `699 * 3000 = 2097000` 字节，略小于 `2 MiB` TX buffer，余下尾部不用作聚合块。

聚合块提交条件：

- 下一个 payload 放不进当前 `3000` 字节块时，先提交当前块；
- 当前块已达到 `3000` 字节；
- 当前块至少达到 `1500` 字节，且填充耗时达到 `15000 us`；
- 当前块空闲达到 `100000 us`。

提交时 `transfer_len = align8(payload_len)`，不足 8 字节补 0。DMA 启动前，`net_rx.c` 会：

1. 校验 `payload_len <= NET_OFDM_MAX_PSDU_BYTES`。
2. 校验 `transfer_len == align8(payload_len)`。
3. 根据本次块的真实 `payload_len` 更新 `tx_intf` 帧长、DMA word 数和 auto-start threshold。
4. 调用 `OpenWifi_Tx_Rearm(payload_len)`。
5. 对 DMA buffer 执行 `Xil_DCacheFlushRange()`。
6. 调用 `XAxiDma_SimpleTransfer(..., XAXIDMA_DMA_TO_DEVICE)`。

默认 `Chunk Bytes=1440` 时：

```text
raw payload:
  每包 wire payload = 1440 bytes
  典型每个 DMA block = 2 * 1440 = 2880 bytes

OFDM Legacy Wrap:
  MPDU payload = 1440 bytes
  Legacy frame = addr0 8 bytes + addr1 8 bytes + align8(MPDU)
  每包 wire payload = 16 + 1440 = 1456 bytes
  典型每个 DMA block = 2 * 1456 = 2912 bytes
```

如果修改 PC chunk 大小，需要满足 PS 侧 `payload_len <= 3000`。raw 模式下 chunk 最大为 `3000`；Legacy 模式下 wire payload 为 `16 + align8(chunk)`，因此 chunk 最大建议不超过 `2984`。为避免普通 1500 MTU 下 IP 分片，推荐继续使用默认 `1440`。

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
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1440 --window-size 64 --throughput-mode
```

发送文件：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --file data.bin --chunk-size 1440 --window-size 64 --throughput-mode
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
--chunk-size            每个 MPDU/raw chunk 的原始 payload 字节数，默认 1440
--window-size           滑动窗口，默认 64
--throughput-mode       轻量吞吐输出
--target-rate-kib-s     主机侧限速，0 表示不限速
--ofdm-legacy           启用 Legacy OFDM 输入帧封装
--raw-payload           发送原始 payload，不添加 OFDM addr0/addr1
--ofdm-rate-mbps        Legacy RATE 字段，可选 6/9/12/18/24/36/48/54
--payload-crc           启用应用层 payload CRC32
--no-payload-crc        关闭应用层 payload CRC32，默认
--pl-verify-pattern     用 PL 可见测试头和可预测 pattern 替换 payload
```

推荐 GUI/CLI 吞吐配置：

```text
模式                    Test Data
Throughput Mode         开启
OFDM Legacy Wrap        按 PL 当前期望选择；不需要 OFDM 头时关闭
OFDM Rate               6 Mbps 起步
Payload CRC32           关闭，除非正在排查数据损坏
Verbose Packet Events   关闭
Chunk Bytes             1440
Window Size             64
Progress ms             1000
Test Bytes              64 MiB 或 256 MiB
```

GUI 运行中切换 OFDM Rate 只影响之后新生成的包。已经发出的包和缓存中的重传包保持首次生成时的 rate、payload 和 CRC。

## Raw 与 OFDM Legacy payload

raw 模式下，PC->PS 应用层包头后直接是原始 payload：

```text
net_data_header_t + raw payload
```

Legacy 模式下，PC 将每个 chunk 当作一个 MPDU，封装为一个 Legacy OFDM 输入帧：

```text
net_data_header_t
+ addr0: Legacy L-SIG 控制 word，64 bit little-endian
+ addr1: 0，64 bit
+ MPDU payload
+ 8-byte padding if needed
```

`L-SIG LENGTH = MPDU_LEN + 4`，默认 `RATE=6 Mbps`。PS 侧仍只处理 `net_data_header_t`，协议头后的所有字节都作为 DMA data 原样交给 PL。

## PL Verify Pattern

开启 `--pl-verify-pattern` 或 GUI 的 `PL Verify Pattern` 后，PC 不再发送原始文件/测试数据内容，而是在每个 MPDU/raw chunk 内生成固定测试内容。每个 chunk 长度仍由 `Chunk Bytes` 决定，且最后一个 chunk 必须至少能容纳 32 字节测试头。

每个 chunk 前 32 字节为 little-endian 测试头：

```text
offset  size  field
0       4     magic = 0x30544C50，即 ASCII "PLT0"
4       2     header_bytes = 32
6       2     flags_version，低 8 bit 为 version=1，bit8=OFDM legacy，bit9=last chunk
8       4     seq，从 0 递增
12      4     total_chunks
16      4     chunk_len
20      4     byte_offset = seq * Chunk Bytes
24      4     total_size
28      4     pattern_seed = 0x13579BDF
```

从 offset 32 开始：

```text
payload_byte[i] = (0xDF + seq + (i - 32)) & 0xff
```

PL 侧用 ILA 抓 64-bit little-endian 数据时，测试头前 4 个 word 是：

```text
word0 = flags_version << 48 | 32 << 32 | 0x30544C50
word1 = total_chunks << 32 | seq
word2 = byte_offset << 32 | chunk_len
word3 = 0x13579BDF << 32 | total_size
```

Legacy 模式下，DMA 中每个 MPDU 的结构是：

```text
addr0 Legacy L-SIG word
addr1 0
PLT0 test header, 32 bytes
test pattern bytes
8-byte padding if needed
```

raw 模式下：

```text
PLT0 test header, 32 bytes
test pattern bytes
```

建议 PL 端先检查 `magic` 是否按 MPDU/chunk 边界周期出现，再检查 `seq` 连续性、`chunk_len`、最后一包标记和 pattern 字节公式。

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
app_deliv   原始业务 payload 被 ACK 的速率；raw/Legacy 下都按用户输入数据计数。
wire_acc    PS 已接受的 wire payload 速率；对应板端 `acc`，Legacy 模式会包含 16 字节 OFDM 头和 padding。
udp_tx      主机实际送入 UDP socket 的应用层字节速率；包含 16 字节 PC->PS 包头和重传。
```

判断真实端到端吞吐时：

- 看业务数据吞吐，用 PC `app_deliv`。
- 看 PS 实际接受了多少准备送 PL 的数据，用 PC `wire_acc` 对齐板端 `acc`。
- 看 PL 实际收到多少 DMA 数据，用板端 `dma`。
- 看主机实际发包压力，用 PC `udp_tx`，它会随重传和 ACK/BUSY/PENDING 变化。

`rx` 是板端输入尝试流量，主机发太快或重传多时可能高于 `acc`。Legacy 模式下 `app_deliv` 与 `wire_acc/acc/dma` 本来就不应完全相等，因为 wire payload 额外包含 OFDM `addr0/addr1` 和 8 字节对齐 padding。

## PL->PS S2MM 回环调试

当前代码已开启第一阶段 PL 回环接收调试：

```text
NET_LOOPBACK_S2MM_DEBUG_ENABLE 1
RX_BUFFER_BASE                 0x01400000
RX_TRANSFER_LENGTH_BYTES       8192
```

每次 PS 准备通过 MM2S 把一个聚合块送入 PL 前，会先 arm 同长度的 S2MM 接收。S2MM 完成后，PS 会 invalidate RX buffer，计算 RX CRC，并与当前 TX buffer 做字节比较。当前阶段只打印和比较，不把回环数据 UDP 发回 PC。

关键日志：

```text
S2MM loopback debug ready, rx_base=0x01400000 rx_bytes=8192 ...
S2MM start id=1 block=0 expect=2880 tx_payload=2880
S2MM wait id=1 expect=2880 waited_ms=1000 txdone=... rxdone=... tx_irq=... rx_irq=... rx_sr=...
S2MM done id=1 len=2880 irq=0x... sr=0x... rx_crc=0x... tx_crc=0x... cmp=OK done=1
S2MM done id=1 len=2880 irq=0x... sr=0x... rx_crc=0x... tx_crc=0x... cmp=DIFF first_diff=...
S2MM rx_head ...
S2MM tx_head ...
S2MM error id=1 irq=0x... sr=0x... cr=0x... buflen=... err_int=... err_slv=... err_dec=... errors=1
```

反馈板级测试结果时，优先提供：

- 启动后的 `S2MM loopback debug ready` 行。
- 发送 16 KiB 或更小测试数据后的所有 `S2MM start/wait/done/error` 行。
- 同一轮的 `STAT rate` / `STAT state` 行。
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
- 改 `NET_AGG_BLOCK_BYTES` 时，必须同时检查 `NET_MAX_PAYLOAD_BYTES`、`NET_OFDM_MAX_PSDU_BYTES`、8 字节对齐、AXI DMA simple transfer 长度限制，以及 `tx_intf` auto-start 阈值。
- 改 PC `chunk_size` 默认值时，确认 raw/Legacy 两种 wire payload 都不超过 PS 侧最大 payload，并考虑 1500 MTU 分片。
- 改 cache 开关或新增 S2MM 路径时，先把 flush/invalidate 点设计清楚。
- BSP 和硬件导出目录尽量由 Xilinx 工具再生成，不做零散手改。
- 仓库只保留根目录 `README.md`；不要在子目录重新添加 README。
