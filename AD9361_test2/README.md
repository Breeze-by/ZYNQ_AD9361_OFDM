# AD9361_test2 当前数据链路说明

`AD9361_test2` 是本仓库的主要 Xilinx SDK 2018.3 裸机应用。它从 PC 接收按序 UDP 负载，完成协议校验后写入 PS 侧聚合缓冲，再通过 AXI DMA MM2S 送入 PL OFDM / AD9361 TX 路径。

```text
PC 发送端
-> UDP 包：net_data_header_t + Legacy OFDM 输入帧
-> Zynq PS lwIP RAW UDP 回调
-> 包头 / 长度 / CRC32 校验
-> 严格按序接收
-> PS 侧聚合块
-> AXI DMA MM2S
-> PL OFDM / AD9361 TX 路径
```

通常只维护 `AD9361_test2/` 下的文件。BSP 和 Vivado 硬件导出目录是生成产物，除非明确调整 BSP 或硬件平台，否则不建议修改。

## 重要文件

```text
src/app/main.c                         板端启动和主循环
src/app/app_config.h                   cache、网络、DMA buffer 参数
src/drivers/net/net_config.h           UDP、ACK、聚合和调参参数
src/drivers/net/net_protocol.h/.c      协议结构体、CRC32、对齐工具
src/drivers/net/net_init.h/.c          lwIP/GEM 初始化和输入轮询
src/drivers/net/net_rx.h/.c            UDP RX、ACK、顺序控制、聚合、DMA 调度
src/drivers/net/net_stats.h/.c         运行统计和串口 STAT 输出
src/drivers/dma/AXI_DMA.*              AXI DMA 初始化和中断封装
src/drivers/uart/PS_UART.*             串口输出封装
tools/pc_sender/send_data.py           命令行入口
tools/pc_sender/sender_core.py         滑动窗口发送核心
tools/pc_sender/sender_gui.py          Tkinter GUI 发送工具
```

## 板端启动流程

`main.c` 的主要流程：

1. 启用 I-cache 和 D-cache。
2. 初始化 GPIO、SPI 和 AD9361 参数。
3. 初始化 UART、GIC、AXI DMA 和 DMA 中断。
4. 初始化 lwIP/GEM，使用静态 IPv4 地址。
5. 绑定 UDP 端口 `5001`。
6. 初始化网络接收和 PS 侧聚合缓冲。
7. 进入主循环：

```c
while (1) {
    Net_Poll();
    Net_RxPoll();
}
```

`Net_Poll()` 每次最多处理 `NET_INPUT_POLL_BUDGET` 个以太网输入包。`Net_RxPoll()` 负责统计输出、ACK 超时 flush、聚合块超时 flush、DMA 启动和 DMA 完成回收。

## 网络默认参数

定义位置：`src/app/app_config.h` 和 `src/drivers/net/net_config.h`。

```text
MAC      02:00:00:00:00:01
IP       192.168.1.50
Netmask  255.255.255.0
Gateway  192.168.1.1
UDP port 5001
```

PC 必须和板端在同一网段，例如 `192.168.1.10/24`。

## UDP 协议

多字节字段均为 little-endian。Python 发送端和 Zynq A9 裸机端使用一致的结构体布局。

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

`net_data_header_t.reserved` 当前用于传输会话控制：

```text
bit15      RESET flag
bit14      NO_CRC flag
bit13      OFDM_LEGACY flag
bit12:0    session id
```

PC 每次点击 Start 会先发送一个 `RESET flag=1, payload_len=0` 的控制包。PS 在 DMA 空闲时清空接收序号、历史记录和聚合队列，并切换到新的 session id。`NO_CRC` 由 GUI 的 Payload CRC32 开关决定，默认关闭 `NO_CRC`，即启用 payload CRC32 校验。`OFDM_LEGACY` 由 GUI 的 OFDM Legacy Wrap 开关决定，只用于标记当前传输模式和串口日志；PS 仍然不会解析 OFDM `addr0/addr1`，协议头后的全部内容都会作为 DMA data 写入聚合缓冲。后续普通数据包都携带同一个 session id 和当前 payload mode 标志。这样可以避免多次测试时 PC 从 `seq=0` 重新开始，而 PS 仍保留上一次 `next_expected_seq` 导致旧序号被当成 duplicate 快速 ACK 的假吞吐现象。

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
数据包头长度     16 bytes
ACK 长度         16 bytes
```

ACK 状态：

```text
0 OK            包已写入 PS 聚合缓冲
1 BAD_MAGIC     magic 错误
2 BAD_LENGTH    包长度或负载长度错误
3 BAD_CHECKSUM  CRC32 校验失败
4 BUSY          板端聚合缓冲满，本包未接收
5 DMA_ERROR     DMA 错误
6 PENDING       本包序号超前，本包未接收
```

## 顺序和可靠性

当前 ACK v1 使用累计确认语义。为了保证累计 ACK 安全，板端强制严格按序接收：

- 板端只接收 `seq == expected_seq` 的包。
- 接收成功后负载写入当前聚合块，然后 `expected_seq++`。
- `seq > expected_seq` 的包返回 `PENDING`，不会写入聚合缓冲。
- 聚合缓冲无可写空间时返回 `BUSY`，不会写入聚合缓冲。
- 已经接收过的重复包返回 `OK`。
- 主机收到 `OK seq=N` 后，可认为当前未确认队列中 `seq <= N` 的包已被板端接收。

DMA 聚合块的顺序也有显式保证。每个 `READY` 聚合块都带有递增的提交序号，`Net_RxPoll()` 总是选择最早提交的 `READY` 聚合块启动 DMA。这样，回收后的低下标聚合块不会插队到旧 `READY` 聚合块前面。

因此，`BUSY`、`PENDING` 和重传只会导致等待或重发，不会造成 PS 到 PL 的数据乱序。

## 聚合和 DMA

当前板端参数：

```text
TX_BUFFER_BASE                 0x01200000
TX_BUFFER_WORD_COUNT           262144
TX 缓冲区大小                  2097152 字节

NET_AGG_BLOCK_BYTES            65536
NET_AGG_BLOCK_COUNT            32
聚合缓冲总容量                 2097152 字节
NET_AGG_MIN_FLUSH_BYTES        32768
NET_AGG_FLUSH_TIMEOUT_US       15000
NET_AGG_IDLE_FLUSH_TIMEOUT_US  100000
```

负载会按接收顺序追加到当前聚合块。聚合块进入 READY 的条件：

- 聚合块已满；
- 聚合块至少达到 `NET_AGG_MIN_FLUSH_BYTES`，且达到 `NET_AGG_FLUSH_TIMEOUT_US`；
- 或聚合块空闲达到 `NET_AGG_IDLE_FLUSH_TIMEOUT_US`。

DMA 传输长度按 8 字节对齐，不足部分补 0。

## Cache 策略

当前 cache 策略：

```c
#define APP_ENABLE_ICACHE 1
#define APP_ENABLE_DCACHE 1
```

I-cache 和 D-cache 均已启用。D-cache 是当前吞吐的关键配置：关闭 D-cache 时，lwIP pbuf 拷贝、payload 写入聚合缓冲和协议处理会大量直接访问无缓存 DDR，实测真实 PC->PS->PL 吞吐只有约 `1.1-1.3 MiB/s`；启用 D-cache 后，`rx/acc/dma` 可以稳定到约 `10.8-11.2 MiB/s`。CRC32 开关前后吞吐接近，说明当前主要收益来自缓存，而不是跳过 CRC。

D-cache 的风险是 CPU cache 与 AXI DMA/PL 访问 DDR 时默认不自动一致。维护规则如下：

```text
MM2S: CPU 写 DDR buffer，DMA/PL 读
      启动 DMA 前必须 Xil_DCacheFlushRange(buffer, len)

S2MM: DMA/PL 写 DDR buffer，CPU 读
      DMA 完成后、CPU 读之前必须 Xil_DCacheInvalidateRange(buffer, len)
```

当前 PC->PS->PL 数据路径只使用 MM2S。`net_rx.c` 在 `XAxiDma_SimpleTransfer()` 前已经对聚合块执行：

```c
Xil_DCacheFlushRange((UINTPTR)block->buffer_ptr, block->transfer_len);
```

因此当前发送路径可以并且应该保持 D-cache 开启。以后如果恢复或新增 PL->PS/S2MM 路径，必须在 DMA 完成后补 `Xil_DCacheInvalidateRange()`，否则 CPU 可能读到 cache 中的旧数据。

维护 DMA buffer 时还要遵守：

- `TX_BUFFER_BASE`、`NET_AGG_BLOCK_BYTES` 和 DMA 传输长度应保持 cache line 友好对齐，推荐至少 32 字节对齐。
- DMA buffer 不要和普通变量、状态结构体共享同一个 cache line。
- `Flush` 必须发生在 CPU 完成写入之后、DMA 启动之前。
- `Invalidate` 必须发生在 DMA 完成之后、CPU 第一次读取之前。
- 临时关闭 D-cache 只用于定位 cache 一致性问题，不应作为性能测试或长期运行配置。

## PC 发送端

PC 发送端默认会把每个 UDP chunk 当作一个 MPDU，封装成一个 Legacy 非聚合 OFDM 输入帧后再发送。PS 侧仍然只解析 `net_data_header_t`；协议头后的 OFDM `addr0/addr1` 和 MPDU 数据会被整体写入聚合缓冲并经 DMA 转发到 PL。

```text
addr0: Legacy L-SIG 控制字，64 bit
addr1: Legacy 未使用，填 0，64 bit
addr2+: MPDU 数据，小端 64 bit word，最后不足 8 字节高位补 0
```

默认 `RATE=6 Mbps`，`L-SIG LENGTH=MPDU_LEN+4`，默认 `chunk-size=1440`，这样加上 16 字节 PC->PS 协议头和 16 字节 OFDM 头后仍能适配普通 1500 MTU。

GUI 发射过程中可以实时切换 OFDM Rate。切换只影响之后新生成的 MPDU 帧；已经发出的包以及后续重传包会继续使用它们首次发送时的 rate 和 CRC。

如果 GUI 不勾选 `OFDM Legacy Wrap`，PC->PS 协议头后面会直接放原始 data，不会添加 OFDM `addr0/addr1`，OFDM rate 对本次传输无效。GUI Start 日志会显示 `payload_mode=raw`，PS reset 日志会显示 `ofdm=raw`。

推荐命令行吞吐测试：

```bash
python tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1440 --window-size 64 --throughput-mode
```

发送文件：

```bash
python tools/pc_sender/send_data.py --ip 192.168.1.50 --file data.bin --chunk-size 1440 --window-size 64 --throughput-mode
```

GUI：

```bash
python tools/pc_sender/sender_gui.py
```

推荐 GUI 配置：

```text
模式：测试数据（GUI 中为 Test Data）
吞吐模式：启用（GUI 中为 Throughput Mode）
OFDM Legacy Wrap：启用
OFDM Rate：6 Mbps
Payload CRC32：启用
逐包日志：关闭（GUI 中为 Verbose Packet Events）
每包 MPDU 字节数：1440（GUI 中为 Chunk Bytes）
窗口大小：64（GUI 中为 Window Size）
进度刷新间隔：1000 ms（GUI 中为 Progress ms）
测试数据大小：64 MiB 或 256 MiB
```

吞吐模式使用非阻塞 ACK 读取、未确认包缓存和自适应有效窗口。`BUSY` 和超时会降低有效窗口；`PENDING` 只做轻微退避，因为它表示顺序压力，而不是数据已丢失。

默认每包 MPDU 大小是 `1440` 字节。Legacy OFDM 封装后为 `1456` 字节，再加上 16 字节 PC->PS 应用层包头后，UDP 负载为 `1472` 字节，可避免普通 1500 MTU 下的 IP 分片。若使用 `--raw-payload` 关闭 OFDM 封装，则可以继续按原始负载模式发送。

## 运行统计

板端只有在当前统计周期内存在接收、已接收或 DMA 活动时才打印统计。每组统计带分隔线：

```text
================ NET STAT ================
STAT rate rx=... acc=... dma=... avg_rx=... avg_acc=... avg_dma=... rx_pkt=... acc_pkt=... dma_done=...
STAT state q=.../... qmax=... ack=... nack=... crc=... badlen=... badmagic=... busy=... pend=... dup=... drop=... dma_err=... agg=... agg_full=... agg_to=... agg_avg=... agg_min=... agg_max=...
==========================================
```

关键字段：

```text
rx / rx_pkt       UDP 回调看到的输入负载速率和包数，包含之后被 BUSY/PENDING 拒收的包
acc / acc_pkt     实际写入 PS 聚合缓冲的负载速率和包数
dma / dma_done    AXI DMA 从聚合块送出的负载速率和 DMA 完成次数
q / qmax          当前和历史最大非空聚合块占用
ack / nack        已发送 ACK 总数和非 OK ACK 总数
busy              因聚合缓冲满而拒收的包数
pend              因序号超前而拒收的包数
dup               重复包数
crc               CRC32 错误数
drop              协议错误或资源不足导致的丢弃数
dma_err           DMA 错误数
agg               已提交聚合块数
agg_full          因聚合块填满而提交的次数
agg_to            因超时而提交的次数
agg_avg/min/max   聚合块负载大小统计
```

判断真实吞吐时，应比较主机 `delivered`、板端 `acc` 和板端 `dma`。`rx` 是输入尝试流量，在主机发送过快时可能高于 `acc`。

## 当前性能

当前测试环境下，启用 D-cache 后干净传输的端到端吞吐约为 `10.8-11.2 MiB/s`：

```text
PC delivered ~= PS acc ~= PS dma
crc=0
drop=0
dma_err=0
timeouts=0
agg_avg 接近 64 KiB
q 通常只有 1-2/32
```

对比测试显示，Payload CRC32 开启和关闭时速率接近；D-cache 开关对速率影响非常大。因此旧的 `1.1-1.3 MiB/s` 不是 DMA 或 PL 的极限，而是 PS 侧无缓存 DDR 访问导致的 CPU/内存路径瓶颈。

`q` 不满不代表需要强行把队列填满。当前 `q=1-2/32` 且 `busy=0`、`pend=0` 时，含义是 DMA/PL 能及时消费 PS 聚合块，系统瓶颈还在前面的 PS 网络接收、pbuf 拷贝、内存写入和轮询调度路径。只有当 `q` 长时间接近满、`busy` 增加，并且 `acc` 明显高于 `dma` 时，才说明 DMA/PL 消费侧成为主要限制。

后续继续提吞吐的优先级：

- 保持 D-cache 开启，并确认 MM2S flush / S2MM invalidate 规则没有被破坏。
- 用 `PC delivered`、PS `acc` 和 PS `dma` 三者对齐判断真实吞吐，不用单看 GUI delivered。
- 若 `rx ~= acc ~= dma` 且 `q` 不满，优先优化 PS 侧 lwIP 输入轮询、pbuf copy 次数、GEM/lwIP BSP 参数和主循环调度。
- 若 `q` 持续满、`busy` 增加，才转向检查 AXI DMA、PL AXI-Stream 反压和 ping-pong/多缓冲消费策略。

## 构建和运行

推荐环境：`Xilinx SDK 2018.3`。

1. 打开 Xilinx SDK 2018.3。
2. 使用仓库根目录作为工作空间。
3. 如需要，导入 `System_wrapper_hw_platform_0`、`AD9361_test2_bsp` 和 `AD9361_test2`。
4. 构建 `AD9361_test2_bsp`。
5. 构建 `AD9361_test2`。
6. 使用 `System_wrapper_hw_platform_0/System_wrapper.bit` 配置 FPGA。
7. 下载并运行 `AD9361_test2.elf`。
8. 打开串口，波特率 `115200`。
9. 确认 Ethernet 启动输出，并 ping `192.168.1.50`。
10. 使用命令行或 GUI 发送数据。

正常启动输出应包含：

```text
Ethernet ready
MAC : 02:00:00:00:00:01
IP  : 192.168.1.50
UDP : listen on port 5001
UDP RX ready, agg_blocks=32 block_bytes=65536 total_bytes=2097152 max_payload=65535 rec_window<=64 ack=on_accept
```

## 注意事项

- 板端在负载写入 PS 聚合缓冲后 ACK，不等待 DMA 完成。
- `BUSY` 和 `PENDING` 都表示对应包未被接收，主机需要重发。
- 一旦检测到 DMA 启动失败或 DMA 中断错误，板端进入失败停止状态，保留现有聚合块，不再继续向 PL 推送后续数据；新来的包会收到 `DMA_ERROR`。
- 默认关闭逐包 UART 日志。
- BSP 和硬件导出目录不应随意修改。
- 如果后续需要继续提高吞吐，建议先测量 DMA 是否持续忙碌，以及 PL 是否对 AXI-Stream 施加反压。
