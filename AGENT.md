# AGENT.md

本文件给后续 agent 快速接手本仓库使用。项目完整说明只维护根目录 `README.md`，不要在子目录新增 README。

## 基本规则

- 本项目已安装 RTK。执行 shell 命令时优先使用 `rtk` 前缀，例如 `rtk git status`、`rtk git diff`、`rtk read <file>`、`rtk grep <pattern> <path>`。
- 修改前先看 `rtk git status --short`，不要覆盖用户未提交改动。
- 阅读文件优先用 `rtk read`，搜索优先用 `rtk grep` 或 `rtk rg --files`，避免普通命令输出过大。
- 只保留根目录 `README.md` 作为项目说明。协议、构建、调参、PC 工具说明都写进根 README。
- `AD9361_test2_bsp/` 和 `System_wrapper_hw_platform_0/` 是 Xilinx 生成产物；除非任务明确要求，不要手动改 BSP、lwIP 源码或硬件平台文件。
- 之后让你做了什么额外的事情，比如需要注意什么，你需要往这个AGENT.md里写入，以便后续的agent都直到这个事项

## 当前工程定位

- 主工程：`AD9361_test2`
- 开发环境：`Xilinx SDK 2018.3`
- 目标平台：`Zynq-7000 + AD9361`
- 主链路：PC UDP -> PS lwIP RAW UDP -> DDR 聚合块 -> AXI DMA MM2S -> PL `tx_intf/openofdm_tx` -> AD9361 TX
- 默认网络：`192.168.1.50:5001`
- 串口：`115200`

## 常看文件

```text
README.md
    唯一完整项目说明。

AD9361_test2/src/app/main.c
    板端启动、AD9361/openofdm 寄存器初始化、主循环。

AD9361_test2/src/app/app_config.h
    cache、DMA buffer、IP 地址。

AD9361_test2/src/drivers/net/net_config.h
    UDP 端口、协议 flag、ACK 状态、聚合块大小和队列参数。

AD9361_test2/src/drivers/net/net_rx.c
    UDP 接收、session reset、顺序控制、ACK、聚合、DMA 调度。

AD9361_test2/src/drivers/net/net_protocol.h/.c
    应用协议结构和 CRC32。

AD9361_test2/tools/pc_sender/sender_core.py
    PC 发送协议、滑动窗口、重传、OFDM legacy 封装、PL verify pattern。

AD9361_test2/tools/pc_sender/send_data.py
    CLI 入口。

AD9361_test2/tools/pc_sender/sender_gui.py
    Tkinter GUI。
```

## 调参边界

- 当前 `NET_AGG_BLOCK_BYTES = 3000`，不是旧文档里的 64 KiB。
- 默认 `Chunk Bytes = 1440`。raw 模式每包 wire payload 为 `1440`；Legacy 模式为 `16 + align8(1440) = 1456`。
- PS 侧 `NET_MAX_PAYLOAD_BYTES = 3000`。Legacy 模式下 chunk 最大建议不超过 `2984`，因为 wire payload 还要加 16 字节 OFDM 头。
- 当前默认启用 I-cache 和 D-cache。MM2S 发送前必须 flush DMA buffer；新增 S2MM 时必须在 DMA 完成后 invalidate。
- OK ACK 默认合并：8 包或 1000 us；非 OK ACK 立即发送。
- 当前已开启第一阶段 PL->PS S2MM 回环调试：每次 MM2S 前 arm 同长度 S2MM，完成后打印 `S2MM done/wait/error`、CRC、首部 word 和 TX/RX 比较结果；尚未实现回环数据 UDP 发回 PC。

## 常用验证命令

```bash
rtk git status --short
rtk git diff -- README.md AGENT.md
rtk rg --files -g "*README*" -g "*readme*"
rtk grep "NET_AGG_BLOCK_BYTES|NET_MAX_PAYLOAD_BYTES|DATA_FLAG|PL_VERIFY" AD9361_test2/src AD9361_test2/tools/pc_sender
```

本环境通常没有 Xilinx SDK 命令行工具，因此无法在普通 shell 中完整构建 SDK 工程。若任务涉及 C 代码行为，至少做静态核对；真正构建和板级验证需要在 Xilinx SDK 2018.3 与目标板上完成。
