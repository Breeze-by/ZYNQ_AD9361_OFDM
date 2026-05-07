# ZYNQ_AD9361_OFDM

这是一个基于 `Xilinx SDK 2018.3` 的 `Zynq-7000 + AD9361` 裸机工程仓库。仓库包含板端应用、SDK BSP、Vivado 硬件导出和上位机 UDP 发送工具。

本文档作为仓库根目录总说明维护，重点回答：

1. 当前工程由哪些部分组成
2. 当前板端和上位机数据链路如何工作
3. 如何构建、下载、联调和继续维护

## 项目结构

```text
ZYNQ_AD9361_OFDM/
|-- AD9361_test2/
|   |-- .cproject
|   |-- .project
|   |-- README.md
|   |-- src/
|   |   |-- app/
|   |   |   |-- main.c
|   |   |   `-- app_config.h
|   |   |-- drivers/
|   |   |   |-- ad9361/
|   |   |   |-- dma/
|   |   |   |-- interrupt/
|   |   |   |-- net/
|   |   |   |-- timer/
|   |   |   `-- uart/
|   |   |-- utils/
|   |   |-- lscript.ld
|   |   `-- Xilinx.spec
|   `-- tools/
|       `-- pc_sender/
|           |-- send_data.py
|           |-- sender_core.py
|           `-- sender_gui.py
|-- AD9361_test2_bsp/
|   |-- system.mss
|   `-- ps7_cortexa9_0/
|       |-- include/
|       |-- lib/
|       `-- libsrc/
|-- System_wrapper_hw_platform_0/
|   |-- System_wrapper.bit
|   |-- system.hdf
|   `-- ps7_init.*
|-- System_wrapper.hdf
`-- README.md
```

## 目录职责

`AD9361_test2` 是当前主要维护的应用工程。`src/app/main.c` 负责启动顺序和主循环，`src/drivers/net/` 负责 lwIP、UDP 接收、ACK 协议和 DMA TX 调度，`src/drivers/ad9361/`、`dma/`、`interrupt/`、`timer/`、`uart/` 分别封装对应底层驱动。

`AD9361_test2/tools/pc_sender` 是上位机发送端工具。`send_data.py` 是命令行入口，`sender_core.py` 是滑动窗口发送核心，`sender_gui.py` 是 Tkinter 图形界面。

`AD9361_test2_bsp` 是 SDK BSP 工程，包含 Xilinx standalone、AXI DMA、EMACPS、lwIP 等 BSP 头文件、源码和库文件。当前 `ps7_cortexa9_0/lib/` 下已有 `libxil.a` 和 `liblwip4.a`。

`System_wrapper_hw_platform_0` 和 `System_wrapper.hdf` 来自 Vivado 硬件导出，软件侧通常只引用，不建议手工修改。

## 当前运行链路

板端 `main.c` 当前流程：

1. 按 `app_config.h` 中的 cache 策略启用 I-cache、关闭 D-cache
2. 初始化 AD9361 GPIO、SPI 和 AD9361 参数
3. 初始化 UART、SCU GIC、AXI DMA 和 DMA 中断
4. 初始化 lwIP/GEM0，配置静态 IP
5. 绑定 UDP 端口 `5001`
6. 主循环执行 `Net_Poll()` 和 `Net_RxPoll()`

数据路径：

1. PC 将文件或测试数据切成连续序号的 UDP chunk
2. 每个 UDP 包格式为 `net_data_header_t + payload`
3. 板端 lwIP RAW API 收包
4. `net_udp_receive_callback()` 校验 magic、长度和 CRC32
5. 校验通过后将 payload 追加到当前 PS 侧 DMA aggregation block
6. aggregation block 满或超过刷新超时后进入 READY 状态
7. `Net_RxPoll()` 在 DMA 空闲时启动一次较长的 MM2S 传输
8. DMA TX 中断置位完成标志并释放 DMA block
9. 板端在 payload 安全写入 PS buffer 后立即返回 ACK
10. 上位机根据 ACK 更新窗口并继续发送

旧的“本地正弦波生成 + 48-bit/双路组帧 + DMA 循环发送”测试逻辑已经被网络接收路径替换。当前 TX buffer 数据来源是 UDP payload。

## 网络配置

板端默认网络参数来自 `AD9361_test2/src/app/app_config.h`：

- MAC：`02:00:00:00:00:01`
- IP：`192.168.1.50`
- Netmask：`255.255.255.0`
- Gateway：`192.168.1.1`
- UDP 端口：`5001`

上位机需要与板端在同一网段。直连调试时，PC 网卡可配置为 `192.168.1.x/24`，例如 `192.168.1.10`。

## 应用协议

协议定义在 `AD9361_test2/src/drivers/net/net_protocol.h` 和 `net_config.h`。Python 上位机使用 little-endian 打包，格式与 Zynq A9 裸机端结构体布局一致。

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

当前常量：

- 数据包 magic：`0x4E455430`
- ACK magic：`0x41434B30`
- 数据头长度：`16` bytes
- ACK 长度：`16` bytes

ACK 状态码：

- `0` / `OK`：payload 已通过校验并写入 PS aggregation buffer，ACK 可覆盖当前 outstanding 中 `seq <= ack.seq` 的 chunk
- `1` / `BAD_MAGIC`：magic 错误
- `2` / `BAD_LENGTH`：长度错误或 payload 超过 `NET_MAX_PAYLOAD_BYTES`
- `3` / `BAD_CHECKSUM`：CRC32 校验失败
- `4` / `BUSY`：板端 aggregation buffer 暂无可写空间，本次 chunk 未接收
- `5` / `DMA_ERROR`：DMA 启动或传输错误
- `6` / `PENDING`：ACK v1 保留状态；当前 aggregation 路径收到已接收过的重复 chunk 会直接重发 `OK`

当前 ACK v1 格式保持不变，但语义已经从“DMA 完成后 ACK”改为“payload 通过校验并写入 PS 侧 aggregation block 后 ACK”。这会把 PC 发送窗口从 DMA 完成节奏中解耦出来。上位机仍把 `OK seq=N` 当作累计确认处理。

## DMA Buffer 规则

关键参数来自 `app_config.h` 和 `net_config.h`：

- `TX_BUFFER_BASE = 0x01200000`
- `TX_BUFFER_WORD_COUNT = 16384`
- TX buffer 总容量：`16384 * 8 = 131072` bytes
- `NET_AGG_ENABLE = 1`
- `NET_AGG_BLOCK_COUNT = 8`
- `NET_AGG_BLOCK_BYTES = 16 * 1024 = 16384` bytes
- aggregation 总容量：`8 * 16384 = 131072` bytes
- `NET_AGG_MIN_FLUSH_BYTES = 8192`
- `NET_AGG_FLUSH_TIMEOUT_US = 1000`
- `NET_AGG_IDLE_FLUSH_TIMEOUT_US = 100000`
- 最大 payload：`4096` bytes
- DMA 发送长度按 `8` bytes 对齐
- payload 不再拆成两路，也不再使用旧 48-bit 打包格式
- 多个 UDP payload 会按接收顺序连续追加到 aggregation block
- 每个 block 最后一组不足 `8` bytes 时补 `0x00`

推荐默认 chunk 是 `1456` bytes。原因是 `16-byte` 应用头加 `1456-byte` payload 后，UDP payload 总长为 `1472` bytes，可避开常见 `1500 MTU` 下的 IP 分片。

## 上位机命令行

发送测试数据：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 4096
```

发送文件：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --file data.bin
```

常用参数：

- `--ip`：板端 IP，必填
- `--port`：板端 UDP 端口，默认 `5001`
- `--chunk-size`：每个 chunk 的 payload 字节数，默认 `1456`
- `--window-size`：最大在途 chunk 数，默认 `16`
- `--timeout`：ACK 超时时间，默认 `1.0` 秒
- `--retries`：单个 chunk 最大重试次数，默认 `10`
- `--target-rate-kib-s`：发送限速，`0` 表示不限速
- `--socket-buffer-bytes`：主机 UDP socket 收发缓冲，默认 `4194304`
- `--progress-interval-ms`：进度输出间隔，默认 `100`
- `--verbose-events`：打开逐包事件输出，测速时建议关闭
- `--throughput-mode`：吞吐测试模式，关闭逐包事件并把进度输出间隔提高到至少 `1000 ms`
- `--test-size`：生成指定字节数的测试 payload
- `--file`：读取文件原始字节作为 payload

吞吐测试示例：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 64 --throughput-mode
```

## 上位机 GUI

启动：

```bash
python AD9361_test2/tools/pc_sender/sender_gui.py
```

GUI 支持：

- 文件发送和测试数据发送
- IP、端口、chunk、窗口、超时、重试、限速配置
- socket buffer 和进度刷新间隔配置
- 吞吐模式开关，默认开启
- `64 MiB` / `256 MiB` 测试数据预设按钮
- 一键开始/停止
- ACK、RTT、发送速率、delivered 速率、估计 PS 侧速率显示
- 发送速率、估计 PS 侧速率、RTT 曲线
- 可选逐包 verbose 事件日志

吞吐测试时直接在 GUI 中选择 `Test Data`，保持 `Throughput Mode` 开启，使用 `64 MiB` 或 `256 MiB` 预设，然后点击 `Start`。该模式会自动关闭 `Verbose Packet Events`，并把进度刷新限制到至少 `1000 ms`，避免 UI 刷新主导测试结果。

## 推荐调参顺序

初始稳定配置：

```text
chunk_size = 1456
window_size = 64
target_rate_kib_s = 0
throughput_mode = true
verbose_events = false
```

如果链路稳定：

1. 保持 `window_size = 64` 作为当前推荐上限
2. 如果要超过 `64`，先确认 `busy=0` 且 aggregation buffer 没有长期满载
3. 仅在重新核算 MTU 后再考虑增大 `chunk_size`

判断方向：

- `busy` 高：板端队列被打满，降低窗口或限速
- `pending` 高：ACK 延迟或丢失较多，但去重逻辑仍在工作
- `timeout` 高：检查网线、PC 防火墙、IP 配置、BSP pbuf/lwIP 配置和串口日志开销
- `qmax` 长期接近 `1`：通常说明 PC 到 PS 侧喂数不够快，DMA 不是瓶颈

## 板端统计输出

`AD9361_test2/src/drivers/net/net_stats.c` 负责轻量统计。吞吐模式下不做逐包 UART 打印，默认约每 `1` 秒输出一行 `STAT`。

典型字段：

- `rx` / `dma`：最近一个统计周期的板端接收 payload 速率和 DMA 完成速率，单位 `KiB/s`
- `avg_rx` / `avg_dma`：从统计启动以来的平均速率
- `rx_pkt` / `dma_done`：最近周期内收到的 UDP 包数和完成的 DMA 次数
- `q` / `qmax`：当前非空 aggregation block 占用和历史最大占用
- `ack` / `nack`：已发送 ACK 和非 OK ACK 数
- `crc` / `badlen` / `badmagic` / `drop`：协议错误和丢弃计数
- `busy` / `pend` / `dup`：流控、重复包和 pending 计数
- `dma_err`：DMA 错误计数
- `agg` / `agg_full` / `agg_to`：已提交 aggregation block 数、容量触发刷新数、超时触发刷新数
- `agg_avg` / `agg_min` / `agg_max`：aggregation block 的平均、最小、最大 payload 字节数

刷新策略：

- block 满 `16384` bytes 时立即刷新
- block 达到 `NET_AGG_MIN_FLUSH_BYTES` 后，超过 `NET_AGG_FLUSH_TIMEOUT_US` 可刷新
- block 未达到最小刷新量时，只在 idle 超过 `NET_AGG_IDLE_FLUSH_TIMEOUT_US` 后作为尾包刷新

如果看到 `agg_avg=1456` 且 `agg_full=0`、`agg_to` 持续增长，说明每个 UDP chunk 仍被单独刷新，需要优先检查 flush timeout 或 PC 发送节奏。

示例：

```text
STAT rx=820.12 dma=815.43 avg_rx=790.08 avg_dma=786.31 rx_pkt=590 dma_done=64 q=2/8 qmax=5 ack=590 nack=0 crc=0 badlen=0 badmagic=0 busy=0 pend=0 dup=0 drop=0 dma_err=0 agg=64 agg_full=60 agg_to=4 agg_avg=14920 agg_min=1456 agg_max=16384
```

## Cache 策略

Cache 策略由 `AD9361_test2/src/app/app_config.h` 控制：

```c
#define APP_ENABLE_ICACHE 1
#define APP_ENABLE_DCACHE 0
```

当前按 `AGENT.md` 的 Phase 2 要求只启用 I-cache，以降低 lwIP、CRC、memcpy 和协议解析的指令执行开销。D-cache 仍保持关闭，避免引入 DMA coherency 风险。后续如果启用 D-cache，必须重新核查 DMA buffer flush/invalidate 和地址对齐策略。

## BSP lwIP 配置

当前 BSP 关键配置来自 `AD9361_test2_bsp/ps7_cortexa9_0/include/lwipopts.h` 和 `xlwipconfig.h`：

- `NO_SYS = 1`
- `LWIP_SOCKET = 0`
- `LWIP_NETCONN = 0`
- `LWIP_UDP = 1`
- `LWIP_DHCP = 0`
- `MEM_SIZE = 262144`
- `MEMP_NUM_PBUF = 32`
- `MEMP_NUM_UDP_PCB = 4`
- `PBUF_POOL_SIZE = 256`
- `PBUF_POOL_BUFSIZE = 1700`
- `IP_REASSEMBLY = 1`
- `IP_FRAG = 1`
- `IP_FRAG_MAX_MTU = 1500`
- `LWIP_FULL_CSUM_OFFLOAD_RX = 1`
- `LWIP_FULL_CSUM_OFFLOAD_TX = 1`
- `XLWIP_CONFIG_N_TX_DESC = 64`
- `XLWIP_CONFIG_N_RX_DESC = 64`

如果怀疑校验和卸载与硬件导出不匹配，可临时关闭 `LWIP_FULL_CSUM_OFFLOAD_RX/TX` 后对比测试。

## 构建和下载

推荐环境：`Xilinx SDK 2018.3`。

导入工程：

1. 打开 `Xilinx SDK 2018.3`
2. 使用仓库根目录作为 workspace
3. 如未自动识别，手动导入 `System_wrapper_hw_platform_0`、`AD9361_test2_bsp`、`AD9361_test2`

构建顺序：

1. Build `AD9361_test2_bsp`
2. 确认生成或存在 `libxil.a`、`liblwip4.a`
3. Build `AD9361_test2`

下载运行：

1. JTAG 连接板卡
2. Program FPGA，使用 `System_wrapper_hw_platform_0/System_wrapper.bit`
3. 下载并运行 `AD9361_test2.elf`
4. 打开串口，波特率 `115200`
5. PC 先 `ping 192.168.1.50`
6. 再使用命令行或 GUI 发送测试数据

正常串口输出应包含类似信息：

```text
Ethernet ready
MAC : 02:00:00:00:00:01
IP  : 192.168.1.50
UDP : listen on port 5001
UDP RX ready, agg_blocks=8 block_bytes=16384 total_bytes=131072 max_payload=4096 rec_window<=64 ack=on_accept
STAT rx=... dma=... q=... qmax=... agg_avg=...
```

## 建议测试顺序

1. 板端启动后先确认串口打印 `Ethernet ready`
2. PC 执行 `ping 192.168.1.50`
3. 用 `--test-size 64 --chunk-size 32 --window-size 1` 做最小闭环
4. 用默认参数发送 `4096` 或 `65536` bytes 测试
5. 发送实际文件
6. 再逐步提高 `window-size`
7. 最后才调整 BSP、MTU 或 chunk 大小

## 已知限制和注意事项

- 当前网络路径只使用 AXI DMA 的 `MM2S` 方向，也就是 `PS memory -> PL`。
- 当前默认启用 I-cache、关闭 D-cache；DMA 启动前仍保留 `Xil_DCacheFlushRange()` 调用，方便后续受控开启 D-cache。
- 当前 ACK v1 仍适合直连或普通局域网中基本按序到达的 UDP 流。若要支持强乱序网络，应继续实现 `AGENT.md` 中的 ACK v2：连续序号 + bitmap + flow-control。
- `AD9361_test2_bsp` 和 `System_wrapper_hw_platform_0` 是生成/导出产物，除 BSP 参数联调外不建议手动修改。
- 测吞吐时不要打开逐包串口日志或 GUI verbose 事件。

## 文档维护约定

后续如果改动以下内容，应同步更新根目录 `README.md`：

- 网络协议字段、magic、ACK 状态码
- UDP 端口、静态 IP、MAC
- DMA buffer 地址、大小、slot 和对齐规则
- 默认 chunk/window/ACK 策略
- BSP lwIP 参数
- 构建、下载、联调步骤
- 工程目录职责
