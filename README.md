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

当前测试环境下，启用 D-cache 后端到端稳定吞吐约为 `10.8-11.2 MiB/s`。干净传输时典型状态：

```text
PC delivered ~= PS acc ~= PS dma
crc=0
drop=0
dma_err=0
timeouts=0
agg_avg 接近 64 KiB
q 通常只有 1-2/32
```

CRC32 开关对该测试结果影响很小；D-cache 对吞吐影响很大。D-cache 关闭时，PS 侧 `pbuf_copy_partial()`、协议处理和聚合缓冲写入都在无缓存 DDR 上运行，真实 PC->PS->PL 吞吐会退回约 `1.1-1.3 MiB/s`。D-cache 开启后，`rx/acc/dma` 能同时稳定到约 `11 MiB/s`。

当前 `q` 不满不是问题，反而说明 DMA/PL 还没有持续反压；主要限制仍在 PS 侧 lwIP/UDP 回调、pbuf 拷贝、内存访问和裸机轮询路径。如果后续优化后 `q` 长时间接近满、`busy` 增加，再重点看 DMA/PL 消费侧。

## D-cache 和 DMA 维护

项目默认应保持：

```c
#define APP_ENABLE_ICACHE 1
#define APP_ENABLE_DCACHE 1
```

不开 D-cache 只适合定位 cache 一致性问题，不适合作为吞吐测试配置。开启 D-cache 的风险是 CPU cache 与 AXI DMA/PL 访问 DDR 时默认不自动一致，因此必须按方向做维护：

- MM2S，CPU 写 buffer、DMA/PL 读：启动 DMA 前必须 `Xil_DCacheFlushRange()`。
- S2MM，DMA/PL 写 buffer、CPU 读：DMA 完成后、CPU 读之前必须 `Xil_DCacheInvalidateRange()`。
- DMA buffer 起始地址和长度尽量保持 32 字节或更高对齐；不要让 DMA buffer 与普通变量共享同一 cache line。
- 当前 PC->PS->PL 路径是 MM2S，`net_rx.c` 在 `XAxiDma_SimpleTransfer()` 前已经 flush 聚合块，所以可以安全启用 D-cache。

## PC 发送工具

PC 发送端默认会把每个 UDP chunk 作为一个 MPDU，先封装成一个 Legacy OFDM 输入帧：

```text
PC->PS 协议头 + addr0 Legacy L-SIG 控制字 + addr1 0 + MPDU 数据 8 字节对齐补 0
```

板端 PS 仍然只解析 PC->PS 协议头；协议头后的 OFDM 头和 MPDU 数据会被整体当作 DMA data 转发到 PL。默认 Legacy 速率为 6 Mbps，`L-SIG LENGTH = MPDU_LEN + 4`。

GUI 发射过程中可以实时切换 OFDM Rate。切换只影响之后新生成的 MPDU 帧；已经发出的包以及后续重传包会继续使用它们首次发送时的 rate 和 CRC。

如果 GUI 不勾选 `OFDM Legacy Wrap`，PC->PS 协议头后面会直接放原始 data，不会添加 OFDM `addr0/addr1`，OFDM rate 对本次传输无效。GUI Start 日志会显示 `payload_mode=raw`，PS reset 日志会显示 `ofdm=raw`。

PC 每次点击 Start 会先发送一个 reset/session 控制包，板端清空旧序号和聚合状态后再接收新数据。GUI 的 Payload CRC32 开关和 OFDM Legacy Wrap 模式也在这个控制包里生效。Payload CRC32 默认启用；关闭后本次传输 PC 不计算 payload CRC，PS 也不校验 payload CRC。这样多次连续测试时不需要重启板端，也不会把上一次传输的旧序号误判成 duplicate 并产生假吞吐。

命令行吞吐测试：

```bash
python AD9361_test2/tools/pc_sender/send_data.py --ip 192.168.1.50 --test-size 67108864 --chunk-size 1440 --window-size 64 --throughput-mode
```

GUI：

```bash
python AD9361_test2/tools/pc_sender/sender_gui.py
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
