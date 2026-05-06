# AD9361_test2 源码目录说明

这是 `AD9361_test2` 应用工程自己的说明文档，重点关注源码分层。

更完整的项目背景、联调步骤、网络协议、BSP 参数建议和上位机 UI 使用方法，请优先看仓库根目录 [README.md](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/README.md:1)。

## 当前源码结构

```text
src/
|-- app/
|   |-- main.c
|   `-- app_config.h
|-- drivers/
|   |-- ad9361/
|   |-- dma/
|   |-- interrupt/
|   |-- net/
|   |-- timer/
|   `-- uart/
|-- utils/
|-- lscript.ld
`-- Xilinx.spec
```

## 目录职责

- `app/`
  应用主入口和应用常量。

- `drivers/ad9361/`
  AD9361、SPI、GPIO、平台适配相关代码。

- `drivers/dma/`
  AXI DMA 初始化和 DMA 中断处理。

- `drivers/interrupt/`
  SCU GIC 和 ISR。

- `drivers/net/`
  lwIP 网络初始化、UDP 接收、ACK 协议、DMA TX 投递。

- `tools/pc_sender/`
  上位机发送端工具，包含命令行脚本、发送核心模块和图形界面。

- `drivers/timer/`
  SCU 私有定时器封装。

- `drivers/uart/`
  PS UART 打印和字节收发。

- `utils/`
  公共头文件、公共参数和基础工具函数。

## 现在的主循环

当前 `main.c` 已经从“本地生成正弦 + DMA 循环发送”改成：

1. 初始化 AD9361 / SPI / UART / GIC / DMA
2. 初始化 lwIP / UDP 接收
3. 在死循环中执行：
   - `Net_Poll()`
   - `Net_RxPoll()`

当前工程的主数据入口已经变成网口。

## 关键入口文件

- 应用入口：
  [main.c](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/src/app/main.c:1)

- 网络初始化：
  [net_init.c](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/src/drivers/net/net_init.c:1)

- UDP 接收与 DMA 发送调度：
  [net_rx.c](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/src/drivers/net/net_rx.c:1)

- 应用协议：
  [net_protocol.h](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/src/drivers/net/net_protocol.h:1)

- DMA 驱动：
  [AXI_DMA.c](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/src/drivers/dma/AXI_DMA.c:1)

- AD9361 参数和 GPIO 路由：
  [COMMON.c](C:/Users/29143/Desktop/ZYNQ_AD9361_OFDM/AD9361_test2/src/utils/COMMON.c:1)
