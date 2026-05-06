我现在要在现有 Xilinx SDK 裸机工程中增加 lwIP 网口接收功能。硬件是 Zynq + AD9361，当前工程可以正常运行，所以必须低风险修改。

本次任务目标：

1. 在应用工程 AD9361_test2 里建立网口模块，例如：
   src/drivers/net/
     net_config.h
     net_init.c/h
     net_rx.c/h
     net_protocol.c/h

2. 如果 main.c 里已有 lwIP / 网口相关代码，请迁移到 drivers/net/ 中。
   要求只封装和移动，不改变原有初始化顺序和业务逻辑。

3. 实现功能：
   上位机通过网口发送数据给 Zynq；
   Zynq 用 lwIP 接收数据；
   Zynq 将收到的数据写入 DMA TX buffer；
   然后启动 DMA，把数据发送到 PL。

4. DMA buffer 组帧规则需要修改：
   - 不再分两路；
   - 不再使用原来的 48 bit 数据格式；
   - 上位机发来的 payload 按顺序连续写入 DMA TX buffer；
   - DMA 按 64 bit 为单位发送；
   - 每 8 字节作为一个 64 bit word；
   - 最后一组不足 8 字节时补 0；
   - DMA 发送长度必须是 8 字节对齐后的长度。

5. 必须处理网口接收和 DMA 发送之间的时序问题。
   推荐采用 UDP + 应用层 ACK 的停止等待机制：

   上位机发送一个 chunk；
   Zynq 收到 chunk；
   Zynq 校验并写入 DMA TX buffer；
   Zynq 启动 DMA；
   DMA 完成中断触发；
   Zynq 回复 ACK；
   上位机收到 ACK 后再发下一个 chunk。

   这样避免上位机发送太快导致 Zynq 端 lwIP buffer 爆满或 DMA 来不及处理。

6. 应用层协议建议：
   每个 UDP 包包含：
   - magic
   - seq
   - payload_len
   - checksum 或 crc32
   - payload

   Zynq 只在校验通过后启动 DMA。
   DMA 完成后回复 ACK(seq)。
   Python 上位机超时未收到 ACK 就重发。
   Zynq 要能识别重复 seq，避免重复 DMA 发送。

7. 在仓库下新增 Python 上位机发送工具：
   tools/pc_sender/send_data.py

   功能：
   - 指定 Zynq IP 和端口；
   - 支持发送测试数据；
   - 支持从文件发送；
   - 支持设置 chunk size；
   - 每个 chunk 等 ACK；
   - 超时重发；
   - 打印 seq、payload_len、ACK、发送进度和平均速率。

   示例命令：
   python send_data.py --ip 192.168.1.10 --port 5001 --test-size 4096 --chunk-size 1024
   python send_data.py --ip 192.168.1.10 --port 5001 --file data.bin --chunk-size 1024

非常重要的限制：

1. 只允许修改 AD9361_test2 应用工程。
2. 不要修改 AD9361_test2_bsp 和 System_wrapper_hw_platform_0。
3. 不要手动修改 BSP 生成出来的 lwIP 源码。
4. 如果需要调整 lwIP BSP Settings，只能列出需要我手动修改的参数和值，不要你直接改。
5. 不要破坏 AD9361 初始化、SPI、DMA 初始化、DMA 中断、UART、定时器等现有功能。
6. 不要大规模重写 main.c。
7. 修改前先扫描工程，找出：
   - DMA TX buffer 在哪里；
   - DMA 启动函数在哪里；
   - DMA 完成中断在哪里；
   - 当前 48 bit / 分路组帧逻辑在哪里；
   - lwIP 初始化和轮询在哪里。
8. 先给修改计划，确认后再改代码。

请重点检查并告诉我是否需要手动修改以下 BSP Settings 里的 lwIP 参数：

必须确认：
- api_mode = RAW_API
- lwip_udp = true
- lwip_dhcp = false，除非当前工程确实要用 DHCP
- pbuf_pool_bufsize >= 1700
- pbuf_pool_size 是否足够，默认 256，不够可建议 512
- mem_size 是否足够，默认 131072，不够可建议 262144 或更高
- memp_n_pbuf 是否足够，默认 16，不够可建议 32 或 64
- memp_n_udp_pcb 是否足够，默认 4，一般够用，不够可建议 8
- n_rx_descriptors 是否足够，默认 64，不够可建议 128
- n_tx_descriptors 是否足够，默认 64，不够可建议 128

建议保持：
- ip_frag = 1
- ip_reassembly = 1
- ip_frag_max_mtu = 1500
- pbuf_pool_bufsize = 1700
- tcp_ip_rx_checksum_offload = false，除非确认硬件支持
- tcp_ip_tx_checksum_offload = false，除非确认硬件支持
- lwip_debug = false
- udp_debug = false
- lwip_stats = false，调试 buffer 问题时可以建议改成 true

Python 端 chunk size 建议先不要超过 1024 或 1400 字节，避免 IP 分片。优先保证功能稳定，再考虑提高吞吐量。

最终请输出：
1. 修改了哪些文件；
2. 新增了哪些文件；
3. 网口接收流程；
4. DMA 发送流程；
5. 64 bit buffer 填充规则；
6. Python 工具使用方法；
7. 需要我手动改的 BSP lwIP 参数清单。
