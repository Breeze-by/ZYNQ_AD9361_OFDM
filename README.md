# AD9361_test2 SDK Project

这是一个基于 Xilinx SDK 2018.3 的 Zynq-7000 裸机工程，用于在 `ps7_cortexa9_0` 上初始化 AD9361，并通过 AXI DMA 进行 PL/PS 间的数据收发测试。工程当前包含应用工程、BSP 工程和 Vivado 导出的硬件平台文件，适合直接作为 SDK workspace 打开和继续迭代。

## 工程组成

```text
AD9361_test2.sdk/
├── AD9361_test2/                    # SDK 应用工程
│   ├── src/                         # 用户主程序、链接脚本、通用中断入口
│   └── ZYNQ7010_Lib/                # 自定义外设和 AD9361 支持库
├── AD9361_test2_bsp/                # SDK BSP 工程，目标处理器 ps7_cortexa9_0
├── System_wrapper_hw_platform_0/    # Vivado 导出的硬件平台、bitstream、PS 初始化文件
└── System_wrapper.hdf               # 根目录保留的硬件导出文件
```

本仓库刻意保留硬件平台和 BSP 文件，因为这些文件会随 Vivado block design、地址分配、中断号、外设实例和 BSP 配置变化而变化。克隆后可重新构建生成 `Debug/`、`libxil.a`、`.o`、`.d`、`.elf` 等产物。

## 软件功能

应用入口为 `AD9361_test2/src/main.c`，当前流程如下：

1. 关闭 I-Cache 和 D-Cache。
2. 初始化 PS GPIO，并配置 AD9361 相关控制引脚。
3. 初始化 SPI0，调用 AD9361 no-OS 风格驱动完成芯片初始化。
4. 设置 AD9361 TX/RX FIR、采样率、LO、带宽、增益、发射衰减和射频端口。
5. 初始化 PS UART0，波特率为 `115200`。
6. 初始化 SCU GIC 和 AXI DMA 中断。
7. 在 DDR 指定地址生成 64-bit 打包的 12-bit 正弦测试数据。
8. 循环启动 AXI DMA MM2S/S2MM 传输，并等待 TX/RX 中断完成。

当前主要参数：

```text
TX buffer base : 0x01200000
RX buffer base : 0x01400000
TX samples     : 2000 x 64-bit
RX samples     : 400 x 64-bit
AD9361 sample  : 40 MHz
TX LO          : 200 MHz
RX LO          : 200 MHz
RF bandwidth   : 20 MHz
RX gain        : 10 dB
TX attenuation : 70000 mdB
```

AD9361 射频参数主要在 `AD9361_test2/ZYNQ7010_Lib/AD9361/radio_set.h` 和 `AD9361_test2/ZYNQ7010_Lib/AD9361/ad9361_config.h` 中维护。

## 关键目录说明

`AD9361_test2/src/`

- `main.c`：主流程，完成 AD9361 初始化、DMA buffer 填充和循环传输。
- `COMMON.h/.c`：公共头文件和基础宏。
- `ISR.h/.c`：用户中断处理入口，目前保留 SCU timer handler。
- `lscript.ld`：应用链接脚本。
- `Xilinx.spec`：SDK 链接用 specs 文件。

`AD9361_test2/ZYNQ7010_Lib/`

- `AD9361/`：AD9361 驱动、SPI/GPIO 平台适配、参数配置和射频端口选择。
- `AXI_DMA/`：AXI DMA 初始化、TX/RX 中断注册和中断处理。
- `SCU/`：SCU GIC 和私有定时器封装。
- `PS_UART/`：PS UART0 初始化、字符串/格式化/字节发送和非阻塞接收。

`AD9361_test2_bsp/`

- `system.mss`：BSP 配置，当前 OS 为 `standalone 6.8`，处理器为 `ps7_cortexa9_0`。
- `ps7_cortexa9_0/include/`：BSP 导出的头文件，包括 `xparameters.h`。
- `ps7_cortexa9_0/libsrc/`：BSP 驱动源码，如 `axidma 9.8`、`gpiops 3.4`、`spips 3.1`、`uartps 3.7`、`scugic 3.10` 等。
- `ps7_cortexa9_0/lib/libxil.a` 是构建产物，已通过 `.gitignore` 忽略。

`System_wrapper_hw_platform_0/`

- `System_wrapper.bit`：PL bitstream。
- `system.hdf`：SDK 使用的硬件描述文件。
- `ps7_init.*`：PS7 初始化源码、头文件和 TCL 脚本。
- `.project`：SDK 硬件平台工程描述。

## 硬件和 BSP 摘要

从当前 BSP 和 `xparameters.h` 可见，工程依赖以下主要硬件资源：

```text
CPU          : ps7_cortexa9_0, 666.666687 MHz
AXI DMA      : axi_dma_0, base 0x40400000, 64-bit MM2S/S2MM, simple mode
PS GPIO      : ps7_gpio_0
PS SPI       : ps7_spi_0 for AD9361 control
PS UART      : ps7_uart_0
Interrupts   : AXI DMA MM2S/S2MM fabric interrupts through SCU GIC
```

如果 Vivado 中修改了 block design、AXI 地址、中断连接或 bitstream，需要重新导出硬件到 SDK，并同步更新 `System_wrapper_hw_platform_0/`、`System_wrapper.hdf` 和 `AD9361_test2_bsp/`。

## 构建和运行

推荐使用 Xilinx SDK 2018.3 打开本目录作为 workspace。

1. 启动 Xilinx SDK 2018.3。
2. Workspace 选择本目录：`AD9361_test2.sdk`。
3. 如果工程未自动出现，使用 `File -> Import -> Existing Projects into Workspace`，选择本目录导入：
   - `System_wrapper_hw_platform_0`
   - `AD9361_test2_bsp`
   - `AD9361_test2`
4. 先构建 `AD9361_test2_bsp`，再构建 `AD9361_test2`。
5. 连接 JTAG，Program FPGA 后下载 `AD9361_test2.elf` 到 `ARM Cortex-A9 #0` 运行。

注意：`.sdk/launch_scripts` 已忽略，因为当前脚本中含有旧机器上的绝对路径，例如 `E:/by2025/...`。换机器或换工作区后应在 SDK 里重新生成/配置 Launch Configuration。

## 版本控制策略

应跟踪：

- 应用源码：`AD9361_test2/src/`
- 自定义库和 AD9361 移植代码：`AD9361_test2/ZYNQ7010_Lib/`
- SDK 工程配置：`.project`、`.cproject`、`.sdkproject`
- BSP 配置和 BSP 源码：`AD9361_test2_bsp/system.mss`、`include/`、`libsrc/`
- 硬件平台：`System_wrapper_hw_platform_0/`、`System_wrapper.hdf`

不跟踪：

- SDK/Eclipse workspace runtime：`.metadata/`
- 本机调试启动脚本：`.sdk/`
- 远程系统临时工程：`RemoteSystemsTempFiles/`
- WebTalk 和 Xilinx 日志：`webtalk/`、`*.jou`、`*.log`
- 构建产物：`Debug/`、`Release/`、`*.o`、`*.d`、`*.elf`、`*.a`
- 软件自动备份和临时文件：`*.bak`、`*.backup.*`、`*.tmp`、`*~`

## 注意事项

- 当前代码关闭了 I-Cache/D-Cache，但仍调用了 `Xil_DCacheFlushRange()`；如果后续打开 D-Cache，需要重新审视 DMA buffer 的 cache coherency。
- `TX_BUFFER_BASE` 和 `RX_BUFFER_BASE` 是硬编码 DDR 地址，修改链接脚本或 DDR 分区时需要确认不会与 `.text`、堆、栈或其他 buffer 冲突。
- `main.c` 中 DMA 循环会一直等待 `TxDone` 和 `RxDone`，如果硬件中断未连接或 DMA 发生错误，程序会卡在等待循环。调试时建议临时打开错误检查和超时保护。
- AD9361 控制 GPIO 编号依赖当前硬件设计和 `parameters.h`，硬件平台变化后需要重新核对。
