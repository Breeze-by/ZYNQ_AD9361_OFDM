# ZYNQ_AD9361_OFDM

这是一个基于 `Xilinx SDK 2018.3` 的 `Zynq-7000 + AD9361` 裸机工程仓库。当前仓库同时包含：

- 应用工程：`AD9361_test2`
- BSP 工程：`AD9361_test2_bsp`
- Vivado 导出的硬件平台：`System_wrapper_hw_platform_0`
- 根目录硬件导出文件：`System_wrapper.hdf`

本文档长期维护为中文版总说明，回答三个核心问题：

1. 这个仓库现在是什么结构
2. 目前代码已经改到了什么状态
3. 接下来应该怎么编译、下载、联调和继续改

## 当前项目结构

```text
ZYNQ_AD9361_OFDM/
|-- AD9361_test2/
|   |-- .cproject
|   |-- .project
|   |-- AGENT.md
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
|   |   |-- README.md
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

## 各目录职责

### `AD9361_test2`

这是用户代码主工程，也是当前主要修改区。

- `src/app/`
  - `main.c`：主流程，只负责初始化顺序和主循环调度
  - `app_config.h`：应用常量，例如缓冲区地址、静态 IP、UDP 端口相关设置

- `src/drivers/ad9361/`
  AD9361、SPI、GPIO、平台适配相关代码。

- `src/drivers/dma/`
  AXI DMA 初始化、DMA 中断注册、完成标志和错误恢复。

- `src/drivers/interrupt/`
  SCU GIC 封装和 ISR。

- `src/drivers/timer/`
  SCU 私有定时器封装。

- `src/drivers/uart/`
  PS UART 封装，主要用于串口调试输出。

- `src/drivers/net/`
  新增的 lwIP 网络模块，负责：
  - GEM0 网口初始化
  - UDP RAW API 接收
  - 应用层 ACK
  - DMA TX 数据投递

- `src/utils/`
  公共参数、公共头文件和基础工具函数。

- `tools/pc_sender/send_data.py`
  命令行 UDP 发送脚本。

- `tools/pc_sender/sender_gui.py`
  上位机图形界面，支持文件选择、速率配置、实时状态和可视化。

### `AD9361_test2_bsp`

这是 SDK 自动生成/维护的 BSP 工程。

- `ps7_cortexa9_0/include/`
  BSP 导出的头文件
- `ps7_cortexa9_0/lib/`
  BSP 编译产物，例如 `libxil.a`、`liblwip4.a`
- `ps7_cortexa9_0/libsrc/`
  BSP 驱动和 lwIP 源码

现在 `.gitignore` 已调整为允许跟踪这三个目录及其嵌套内容，后续如果你在 SDK 中重建 BSP，`lib/` 里的产物可以进入版本控制。

### `System_wrapper_hw_platform_0`

这是 Vivado 导出的硬件平台工程，包含 bitstream、硬件描述和 `ps7_init.*`。软件侧通常只引用，不手改。

## 当前软件状态

### 保留不变的部分

以下底层流程没有被故意重写：

- AD9361 初始化流程
- SPI 初始化和 AD9361 寄存器访问
- AXI DMA 初始化
- DMA TX/RX 中断处理逻辑
- UART 初始化和打印
- SCU GIC 初始化
- 定时器驱动

### 当前主功能

当前板端运行模式是：

1. 初始化 AD9361、SPI、UART、GIC、DMA
2. 初始化 lwIP 和 GEM0 网口
3. 在 UDP 端口 `5001` 监听数据
4. 上位机发送带协议头的 UDP 数据块
5. 板端校验后写入 DMA TX buffer
6. 启动 DMA MM2S 把数据发往 PL
7. DMA TX 中断完成后回 ACK
8. 上位机收到 ACK 再发下一块

### 当前已替换的旧逻辑

原来 `main.c` 里的“正弦波生成 + 48-bit / 双路组帧 + DMA 循环发送”测试逻辑，已经被网口接收路径替换。  
当前 TX buffer 的数据来源是 UDP payload。

## 当前网络协议

### 数据包格式

每个 UDP 包为：

```text
net_data_header_t + payload
```

头格式：

```c
uint32_t magic;
uint32_t seq;
uint16_t payload_len;
uint16_t reserved;
uint32_t payload_crc32;
```

当前常量：

- 数据包 `magic`：`0x4E455430`
- ACK 包 `magic`：`0x41434B30`
- UDP 端口：`5001`

### ACK 包格式

```c
uint32_t magic;
uint32_t seq;
uint16_t status;
uint16_t reserved;
uint32_t transfer_len;
```

### ACK 状态码

- `0`：OK
- `1`：magic 错误
- `2`：长度错误
- `3`：CRC 校验错误
- `4`：板端忙
- `5`：DMA 错误

## DMA TX buffer 规则

当前 TX buffer 规则如下：

- 起始地址：`TX_BUFFER_BASE = 0x01200000`
- 缓冲区容量：`2000 x 64-bit = 16000 bytes`
- 上位机 payload 不再分两路
- 不再使用旧的 48-bit 打包格式
- payload 按字节顺序连续写入 TX buffer
- 每 `8` 字节构成一个 `64-bit word`
- 最后一组不足 `8` 字节时补 `0x00`
- 实际 DMA 发送长度必须按 `8` 字节对齐

## 如何在板端运行

推荐使用 `Xilinx SDK 2018.3`。

### 导入工程

1. 打开 `Xilinx SDK 2018.3`
2. 选择本仓库根目录作为 workspace
3. 如未自动出现，手动导入：
   - `System_wrapper_hw_platform_0`
   - `AD9361_test2_bsp`
   - `AD9361_test2`

### 构建顺序

1. 先 Build `AD9361_test2_bsp`
2. 确认 `AD9361_test2_bsp/ps7_cortexa9_0/lib/` 下生成库文件
3. 再 Build `AD9361_test2`

### 下载运行

1. JTAG 连接板卡
2. Program FPGA
3. 下载 `AD9361_test2.elf`
4. 打开串口观察输出

正常情况下应看到类似信息：

- `Ethernet ready`
- MAC 地址
- 静态 IP 地址
- `UDP : listen on port 5001`
- `UDP RX ready, max payload ...`
- 收到数据时打印：`UDP recv seq=... payload=... aligned=...`
- 启动 DMA 时打印：`DMA start seq=... len=...`
- 完成 ACK 时打印：`ACK seq=... len=... total_bytes=... recent=... avg=...`

## 上位机如何发送数据

脚本路径：

[send_data.py](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/tools/pc_sender/send_data.py:1)
[sender_gui.py](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/tools/pc_sender/sender_gui.py:1)

### 发送测试数据

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --port 5001 --test-size 4096 --chunk-size 1024
```

### 发送文件

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --port 5001 --file data.bin --chunk-size 1024
```

### 参数说明

- `--ip`：板端 IP
- `--port`：板端 UDP 端口，默认 `5001`
- `--test-size`：发送指定长度的测试数据
- `--file`：从文件读取原始字节发送
- `--chunk-size`：每个 UDP chunk 的 payload 大小
- `--timeout`：等待 ACK 超时时间
- `--retries`：单个 chunk 最大重发次数
- `--target-rate-kib-s`：可选的发送限速，`0` 表示不主动限速

### 使用建议

- 初始调试建议 `chunk-size = 1024`
- 不要一开始就超过 `1400`
- 如果经常收到 `BUSY`，先减小 chunk 或增加发送间隔

## 上位机图形界面

图形界面入口：

```bash
python AD9361_test2/tools/pc_sender/sender_gui.py
```

### 当前 UI 支持的能力

- 选择常见二进制源文件直接发送
  - `jpg / jpeg / png / bmp / gif`
  - `bin`
  - `mp4 / mov / avi / ts`
  - `txt / csv / json`
  - 以及任意其他原始文件

- 发送测试数据
  - 输入测试字节数
  - 不依赖文件即可做链路压测

- 配置网络参数
  - 目标 IP
  - 目标端口
  - Chunk 大小
  - ACK 超时
  - 最大重试次数
  - 发送限速 `KiB/s`

- 一键发送 / 停止发送

- 实时状态显示
  - 当前状态
  - 最近 ACK 状态
  - 最近 Seq
  - 最近 RTT
  - 当前发送速率
  - 平均发送速率
  - 估计 PS 侧速率
  - ACK OK 数
  - Timeout 数
  - 重试次数
  - BUSY 次数
  - 错误 ACK 次数

- 实时可视化
  - 发送速率曲线
  - 估计 PS 侧速率曲线
  - RTT 曲线

- 事件日志
  - 每个 chunk 的发送
  - ACK OK
  - ACK 非 OK 状态
  - Timeout
  - 停止 / 完成 / 错误

### 关于“估计 PS 侧速率”

上位机拿不到板端 DMA 的绝对真实瞬时速率，只能通过 ACK 返回时间做估算。  
当前 UI 里显示的“估计 PS 侧速率”本质上是：

- `transfer_len / (发送该 chunk 到收到 ACK 的时间)`

它更适合作为联调指标，而不是严格的硬件 DMA 基准值。

## 当前 BSP lwIP 配置状态

根据现有 `AD9361_test2_bsp/ps7_cortexa9_0/include/lwipopts.h` 与 `xlwipconfig.h`：

- `NO_SYS = 1`
- `LWIP_SOCKET = 0`
- `LWIP_NETCONN = 0`
- `LWIP_UDP = 1`
- `LWIP_DHCP = 0`
- `MEM_SIZE = 131072`
- `MEMP_NUM_PBUF = 16`
- `MEMP_NUM_UDP_PCB = 4`
- `PBUF_POOL_SIZE = 256`
- `PBUF_POOL_BUFSIZE = 1700`
- `IP_REASSEMBLY = 1`
- `IP_FRAG = 1`
- `IP_FRAG_MAX_MTU = 1500`
- `XLWIP_CONFIG_N_TX_DESC = 64`
- `XLWIP_CONFIG_N_RX_DESC = 64`

### 当前建议你手动重点检查

- `MEMP_NUM_PBUF`
  当前 `16`，如果后续丢包或 ACK 超时，建议升到 `32`

- `MEM_SIZE`
  当前 `131072`，如网络流量增大可考虑 `262144`

- `LWIP_FULL_CSUM_OFFLOAD_RX`
- `LWIP_FULL_CSUM_OFFLOAD_TX`
  当前 BSP 中是 `1`。如果怀疑校验和卸载与当前硬件配置不匹配，建议手动关掉再测。

## 当前已知限制

- 当前仓库里 `AD9361_test2_bsp/ps7_cortexa9_0/lib/` 还没有现成产物，因此我只能做源码级编译检查，不能完整链接最终 ELF。
- 当前网络路径只用了 DMA 的 `MM2S` 方向，也就是“PS 内存 -> PL”。
- 当前采用停止等待协议，优先保证稳定，不追求最高吞吐。
- 当前只记住“最近一次已成功完成的 seq”，用于处理 ACK 重传场景。

## 建议测试顺序

1. 先 Build BSP，确认 `libxil.a`、`liblwip4.a` 生成
2. Build `AD9361_test2`
3. 板端启动，看串口是否打印网口 ready
4. PC 先 ping 板端 IP
5. 用 `--test-size 64 --chunk-size 32` 做最小闭环
6. 再测 `1024`、`4096`、文件发送
7. 最后再考虑增大 chunk 或调 BSP 参数

## 文档维护约定

从现在开始，这个根目录 `README.md` 作为项目总说明持续维护。  
后续如果再改：

- 协议格式
- 网口端口
- DMA buffer 规则
- 调试步骤
- BSP 参数建议
- 工程结构

都应该同步更新这里。
