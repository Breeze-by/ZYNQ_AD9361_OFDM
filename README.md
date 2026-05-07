# ZYNQ_AD9361_OFDM

这是一个基于 `Xilinx SDK 2018.3` 的 `Zynq-7000 + AD9361` 裸机工程。当前主要数据链路是：

```text
PC UDP 发送端
-> Zynq PS lwIP RAW UDP 接收
-> 包头 / 长度 / CRC32 校验
-> 严格按序接收
-> PS 侧 DMA 聚合缓冲
-> AXI DMA MM2S
-> PL OFDM / AD9361 TX 路径
```

仓库包含板端 SDK 应用、BSP、Vivado 硬件导出文件，以及 PC 端 UDP 发送工具。

## 目录结构

```text
ZYNQ_AD9361_OFDM/
|-- AD9361_test2/                  # 主要 SDK 应用工程
|   |-- src/
|   |   |-- app/                   # main.c 和 app_config.h
|   |   |-- drivers/
|   |   |   |-- net/               # UDP RX、ACK、统计、聚合
|   |   |   |-- dma/               # AXI DMA 封装
|   |   |   |-- uart/              # PS UART 封装
|   |   |   |-- interrupt/         # GIC 初始化
|   |   |   `-- ad9361/            # AD9361 支持代码
|   |   `-- utils/
|   `-- tools/pc_sender/           # 命令行和 Tkinter GUI 发送工具
|-- AD9361_test2_bsp/              # Xilinx SDK BSP
|-- System_wrapper_hw_platform_0/  # Vivado 硬件平台导出
|-- System_wrapper.hdf
|-- AGENT.md                       # 开发指导
`-- HANDOFF_NEXT_SESSION.md        # 当前交接记录
```

通常只维护 `AD9361_test2/`。`AD9361_test2_bsp/` 和 `System_wrapper_hw_platform_0/` 是 SDK/Vivado 生成产物，除非明确调整 BSP 或硬件平台，否则不建议手动修改。

## 当前网络配置

默认配置定义在 `AD9361_test2/src/app/app_config.h`。

```text
MAC      02:00:00:00:00:01
IP       192.168.1.50
Netmask  255.255.255.0
Gateway  192.168.1.1
UDP port 5001
```

直连测试时，PC 网卡需要配置在同一网段，例如 `192.168.1.10/24`。

## 数据可靠性

板端严格按序接收负载。只有当 UDP 包的 `seq` 等于板端当前期望序号时，负载才会写入 PS 侧聚合缓冲。

- 高于期望序号的包返回 `PENDING`，不会写入 DMA 数据流。
- 聚合缓冲满时返回 `BUSY`，对应包也不会写入 DMA 数据流。
- 主机收到 `PENDING` 或 `BUSY` 后会重发。
- 已提交的聚合块按提交顺序 FIFO 送入 DMA，不按数组下标抢占。

因此，重传和等待只会影响速度，不会改变 PS 到 PL 的数据顺序。

## 当前吞吐状态

当前测试环境下，端到端稳定吞吐约为 `1.1-1.2 MiB/s`。干净传输时典型状态：

```text
PC delivered ~= PS acc ~= PS dma
crc=0
drop=0
dma_err=0
timeouts=0
agg_avg 接近 16 KiB
```

目前主要持续速率瓶颈不再是 PC 发送、ACK 或 UDP 聚合，而更可能在 AXI DMA / PL 消费侧，或者 PL 侧 AXI-Stream 反压。

## PC 发送工具

命令行吞吐测试：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1456 --window-size 64 --throughput-mode
```

GUI：

```bash
python AD9361_test2/tools/pc_sender/sender_gui.py
```

推荐 GUI 配置：

```text
模式：测试数据（GUI 中为 Test Data）
吞吐模式：启用（GUI 中为 Throughput Mode）
逐包日志：关闭（GUI 中为 Verbose Packet Events）
每包负载字节数：1456（GUI 中为 Chunk Bytes）
窗口大小：64（GUI 中为 Window Size）
进度刷新间隔：1000 ms（GUI 中为 Progress ms）
测试数据大小：64 MiB 或 256 MiB
```

## 构建和运行

推荐环境：`Xilinx SDK 2018.3`。

1. 打开 Xilinx SDK 2018.3。
2. 使用仓库根目录作为工作空间。
3. 如未自动识别，导入 `System_wrapper_hw_platform_0`、`AD9361_test2_bsp` 和 `AD9361_test2`。
4. 构建 `AD9361_test2_bsp`。
5. 构建 `AD9361_test2`。
6. 使用 `System_wrapper_hw_platform_0/System_wrapper.bit` 配置 FPGA。
7. 下载并运行 `AD9361_test2.elf`。
8. 打开串口，波特率 `115200`。
9. PC 执行 `ping 192.168.1.50`。
10. 使用命令行或 GUI 发送数据。

## 详细文档

当前应用的数据链路、协议、统计字段和关键参数详见：

```text
AD9361_test2/README.md
```

如果修改协议字段、ACK 行为、DMA 缓冲大小、网络默认参数、PC 发送工具默认参数或构建运行方式，需要同步更新根目录 README 和 `AD9361_test2/README.md`。
