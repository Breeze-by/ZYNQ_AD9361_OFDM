# AGENTS.md

本文件给后续 agent 快速接手本仓库使用。项目完整说明只维护根目录 `README.md`，不要在子目录新增 README。

## 基本规则

- 本项目已安装 RTK。执行 shell 命令时优先使用 `rtk` 前缀，例如 `rtk git status`、`rtk git diff`、`rtk read <file>`、`rtk grep <pattern> <path>`。
- 修改前先看 `rtk git status --short`，不要覆盖用户未提交改动。
- 阅读文件优先用 `rtk read`，搜索优先用 `rtk grep` 或 `rtk rg --files`，避免普通命令输出过大。
- 只保留根目录 `README.md` 作为项目说明。协议、构建、调参、PC 工具说明都写进根 README。
- 当前根目录没有 `TODO.md`；如后续重新创建，只用于记录未实现任务路线图，不替代 README，任务完成后要把正式说明同步回根 README。
- `AD9361_test2_bsp/` 和 `System_wrapper_hw_platform_0/` 是 Xilinx 生成产物；除非任务明确要求，不要手动改 BSP、lwIP 源码或硬件平台文件。
- 之后用户提出了额外协作要求或项目注意事项，需要同步写入根目录 agent 文件，让后续 agent 知道。
- 如果仓库根目录有 `AGENT.md`、`Agent.md` 或 `AGENTS.md`，必须优先使用根目录文件作为本项目说明，不要改用 `C:\Users\29143\.codex\` 下的用户级说明。若多个同时存在，优先按用户最近明确指定的根目录文件执行。

## 用户协作约定

- 每次完成代码或文档修改后，必须 `git commit` 并 `git push` 到远程；不要让用户自己 push。提交前后都要用 `rtk git status --short` 确认工作区状态。
- 用户主要使用 GUI 发送程序 `AD9361_test2/tools/pc_sender/sender_gui.py`，不要用 CLI 命令作为测试指令。需要用户跑测试时，直接给 GUI 中的字段设置，例如 `Mode`、`Test Bytes`、`Chunk Bytes`、`Window Size`、`Throughput Mode`、`Payload CRC32`、`RF Strict Match + Retry (max 3)`、`AIR0 Packet Header` 等。
- 旧版额外封装和测试 pattern 选项已从 PC/PS/文档移除，以后不要再建议用户使用相关 GUI 字段或 CLI 参数。PC->PS 应用层包头后始终是普通 wire payload；PL 不解析内容，PS 仅在 S2MM 回传时读取捕获块起始的 AIR0/AIRV v2 头以恢复全局 `stream_offset`，不做文件恢复、视频组帧或解码。
- 当前 AIRV 实时视频模式已支持接收 GUI 独立 `AIRV Preview` 窗口、后台 PyAV 解码和预览队列。AIR0 仍是精确文件/测试数据恢复模式；AIRV 是实时视频组帧/预览/统计模式，不保存精确文件，不做接收端 ACK、重传、FEC 或音频。PL 不解析 AIR0/AIRV；PS 不组帧，但会读取 AIR0/AIRV v2 的全局包序号以恢复 S2MM 回传偏移。
- AIRV 接收器允许开头 S2MM block 丢失后从第一个完整 AIRV chunk 中途接入，日志打印 `VIDEO_DIAG late_attach initial_missing=...`；随后等待 H.264 keyframe 恢复预览。AIR0 仍要求 offset 0 起始连续，不能用该行为掩盖精确文件缺失。
- AIRV 流中间出现完整 chunk 级缺口时，接收器会在下一段通过 chunk 对齐和 AIRV magic 校验后打印 `VIDEO_DIAG gap_skip ...`，只丢弃跨缺口未完成帧并继续按序交付后续完整帧；连续 3 次解码失败才等待 keyframe。`VIDEO stream_gap=...` 累计跳过字节。AIR0 不跳过流中缺口。
- AIRV 接收 GUI 每两秒最多输出 `VIDEO_PREVIEW input/backlog/drops/decoded/rendered/decoder_errors/waiting_key/images/skipped/error`，结束时输出 `VIDEO_PREVIEW_DONE`；逐分片、逐坏帧日志已关闭，用周期 `VIDEO` 和最终汇总看 CRC/丢帧，避免日志影响处理性能。
- 接收 GUI 主窗口已改为紧凑双列布局：Network/Output 参数和 Metrics 都按两列排列；Charts 与 Event Log 位于可上下拖动的纵向分隔区，避免顶部字段把日志挤出窗口。AIRV Preview 仍是独立窗口。
- 接收 GUI 的 `RX Rate (1s)`、RX KiB/s 图和 Packets/s 图使用最近 1 秒滑动窗口，按窗口内累计字节/包数差值计算；不得再改回从点击 Start 起算的累计平均值。第一批数据前不出速率点，停止收包约 1 秒后应回落到 0。
- 发送 GUI 也支持在传输前独立广播 `IPCFG`，不会发送 `RXCFG`、不会注册或覆盖回传目标。只运行发送 GUI 的电脑切换板端网段时，应填写直连网卡的 `PC Bind IP`、目标 `Target IP`、掩码/网关并勾选 `Configure Board IP by broadcast`；不应借用接收 GUI 改址，因为接收 GUI 默认还会发送 RXCFG。
- 发送 GUI 也已改为紧凑布局：Source/Network/Metrics 尽量按双列排列，Charts 与 Event Log 位于可上下拖动的纵向分隔区；默认窗口和最大化窗口都应保留两者的可见空间。
- 当前 SDK 默认 `APP_RX_SOURCE=APP_RX_SOURCE_AD9361`，走真实 AD9361 TX -> SMA -> AD9361 RX 链路；PL 数字回环保留为 `APP_RX_SOURCE_DIGITAL_LOOPBACK` 诊断选项。启动日志必须打印当前 RX source。板级调试继续分阶段做；先加可观察日志，让用户上板跑并回传串口输出，再根据日志继续改。
- PS DMA 已改为单/双板通用的独立调度：显式 RXCFG 注册后持续 arm/re-arm S2MM，接收不依赖本机 TX block；MM2S 完成后独立释放 TX block，不等待本地 S2MM。没有 RXCFG 的纯发射板不 arm S2MM；只有 RXCFG、没有本机发送数据的纯接收板也能回传合法 AIR0/AIRV 帧。同一份 ELF 支持单板同时收发和两板分别收发。
- 板端每次上电仍以 `192.168.1.50/24` 启动；接收和发送 GUI 都能通过全局广播发送 `IPCFG`，把各自直连板卡的 IP/掩码/网关临时切换到另一网段，配置不写 flash，重启恢复 `192.168.1.50`。双网卡电脑做 IPCFG 时必须把 GUI 的 Bind IP 明确填成直连 Zynq 的 PC 网卡地址，不能用 `0.0.0.0`。新电脑接收 GUI 使用 `Bind IP=192.168.2.101`、`Board IP=192.168.2.50` 并勾选 IPCFG 和 RXCFG；只运行发送 GUI 时使用 `PC Bind IP=192.168.2.101`、`Target IP=192.168.2.50`、`Board Netmask=255.255.255.0`、`Board Gateway=0.0.0.0` 并勾选 `Configure Board IP by broadcast`。旧电脑仍可使用 `192.168.1.101 -> 192.168.1.50`，无需改板端默认代码。
- 当前默认走真实 `NET_LOOPBACK_RETURN_SOURCE_S2MM` RF/S2MM 回传路径，不再是 `TX_BUFFER` 诊断模式。需要用户反馈时，优先要接收板的 `RXCFG loopback peer`、`S2MM valid`、`S2MM RX stat`、`S2MM error`，发送板的 `UDP RX reset`、`STAT rate/state`、`DMA stall timeout/recovery`、`MM2S error`。如果涉及 PC 端回传验证，还要让用户复制接收 GUI 日志里的 `RX target registered ...`、AIR0 的 `PROGRESS rx=... crc=... len=... gaps=... air=... air_rx=... pending_air=... bad_hdr=... bad_payload=... bad_meta=... dup=... got_last=...`、`INCOMPLETE ... missing_seq=... bad_payload_seq=... bad_meta_seq=...`、`DONE ... gaps=... air=... air_rx=... miss=... file_crc=... file_id=... file_size=... total_packets=... got_last=... saved=... missing_seq=... bad_payload_seq=...`，以及 AIRV 的周期 `VIDEO ...`、`VIDEO_PREVIEW ...`、最终 `VIDEO_DONE`、`VIDEO_PREVIEW_DONE`、`DONE VIDEO ...` 行。
- 回答用户测试步骤时，用中文、直接、具体；避免给一长串命令让用户自行转换。

## 当前工程定位

- 主工程：`AD9361_test2`
- 开发环境：`Xilinx SDK 2018.3`
- 目标平台：`Zynq-7000 + AD9361`
- 主链路：PC UDP -> PS lwIP RAW UDP -> DDR 聚合块 -> AXI DMA MM2S -> PL `tx_intf/openofdm_tx` -> AD9361 TX -> SMA 线直连 -> AD9361 RX -> PL OFDM RX -> AXI DMA S2MM -> PS UDP 回传
- 上电默认网络：`192.168.1.50:5001`；可由接收 GUI IPCFG 临时切换到与直连 PC 网卡相同的 `/24` 网段
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
    PC 发送协议、滑动窗口、重传、Payload CRC32、AIR0 payload header。

AD9361_test2/tools/pc_sender/send_data.py
    CLI 入口。

AD9361_test2/tools/pc_sender/sender_gui.py
    Tkinter GUI。

AD9361_test2/tools/pc_sender/receiver_core.py
    PC 接收核心；IPCFG 运行时板端改址、RXCFG 注册回传目标、loopback 分片接收、CRC 检查、文件恢复。

AD9361_test2/tools/pc_sender/recv_data.py
    接收 CLI 入口。

AD9361_test2/tools/pc_sender/receiver_gui.py
    接收 Tkinter GUI；AIRV 预览窗口默认 1280x720，主窗口保留日志和预览指标。

AD9361_test2/tools/pc_sender/video_protocol.py
    PC-only AIRV 64 字节头、H.264 Annex-B 粗分帧和实时视频分片封装。

AD9361_test2/tools/pc_sender/video_receiver_core.py
    AIRV 实时组帧、坏 CRC 计数、缺片 drop、VIDEO 指标和 assembled frame 事件。

AD9361_test2/tools/pc_sender/video_playback.py
    AIRV 预览解码器；PyAV/Pillow 可选依赖、H.264 解码、Tk 可显示图像转换。
```

## Project agent instruction source

- If the repository root contains `AGENT.md`, `Agent.md`, or `AGENTS.md`, use that root file as the project agent instructions. Prefer the repository root agent file over user-level files under `C:\Users\29143\.codex\` for project-specific behavior.

## 调参边界

- 2026-09-16 最新新批次：源改为发送机USRP_UDP下indices.bin与h265_payload.h265，目标1e-3/1e-4/1e-5各5份，共30份，全部新RF采集。
  用户重新确认0.5～2倍、停发/关闭IDE/释放COM/20cm固定；旧H低边界批准不适用。整轮全业务BER、零缺包，不修补/拼包/人工翻转/开RF重传。
  已30/30完成：indices 517980B/540包，H265 180422B/188包；错误bit数和逐样本BER详见根README和results30.json。
  50轮19256发/18905收/缺351，16轮缺包、4轮全收但BER越界、30轮入选；PC重传全0，原始50对独立审计通过。
  每源/配置至多10轮、按时间取最早5份；H低30bit=2.078460498e-5明确越界不选，不套用旧批准。
  首次RX未初始化，加载现有原bit/ELF后前6轮缺337/2536；再加载相同RX版本后44轮缺14/16720，具体启动状态根因未闭环。
  第一阶段PS reject86=len2+no_magic84；第二阶段采样结束capture16709/valid16706/reject3/UDP16706，DMA/stall0。
  恢复TX时RX no_magic另增82，非业务包一一映射；初期一轮保护业务前30B有5bit错误，入选30份该区域均0，不泛化到未收到帧。
  入选RX66/DC44/63，高shift3/TX17、中shift3/TX14.5、低shift2/TX19；双板匹配，2.2GHz/40MSPS/guard32/chunk1024/w1/400KiB保持。
  临时sender-only ELF56B16EE8…通过ADI API有界调衰减；正式C/ELF/bit/HDF不改，原TX9AC341A5…已恢复。
  已恢复TX16/RX66、shift4、DC48/63、原时钟、TX IP2.50及RX GUI1.100:15002 ACK/JTAG；串口释放、两板ping通。
  本轮确实下载RX原bit/ELF两次及TX候选/正式ELF；未重新生成bit、未写Flash/SD，不要说全程未下载。
  两机工程根BER_results_20260916_batch30及本地有30份、manifest(DBB677CC…)、全50对raw_evidence.zip(181C31C3…)；数据不进SDK Git。
  旧六份和18份及manifest保持，原GUI严格CRC行为与已取消批量功能均不改；配置不是BER标定表，筛选样本非无偏可靠性统计。
  新collect30.py/test_collect30.py/campaign30.json/results30.json与根文档记录本批；本地37项profile测试过。
  本轮备份TX TEMP/ad9361-ber30-8b31acdd8a1246c8b2fbcad12e036a70，RX TEMP/ad9361-ber30-441a22eaf85e47ee943aca43fe8db2af。
  原BSP/IDE无关dirty94/15须保留；绝对SNR、模型效果、全局时序仍未验收。后续发射/改配置按用户新任务执行。
- 2026-09-16 用户回复“我同意”，仅批准H265低档全1443376bit、3错误bit、188/188包的边界样本；没有普遍放宽BER范围。
  离线重审已有79轮，按时间选r-h265-s2-a16-07和r-h265-s2-a16p75-02，session2247/271、采集时间及双哈希不同。
  原16业务文件不变，新增H低sample02/03；当前18份=原范围16+获批边界2，每源/BER各3份，H低错误2/3/3。
  后两份实际BER2.078460498165412e-6，较原上限高3.923%，必须明确标注，不能向下取整或放宽其他组。
  两机工程根BER_results_20260916_repeats及本地均18份逐bit复核通过；新manifest AE2AADD7…，旧manifest备份635A573D…。
  raw_new_evidence.zip仍F543026D…，原六份及79轮证据不改。boundary_acceptance.json/boundary_results.json记录本次批准与完整哈希。
  replicates.py默认仍严格，显式--acceptance才允许此特例；本地28项单测通过，历史repeat_results.json保留审批前16份快照。
  本次没有新增RF发射、改板卡运行态/C/ELF/bit/HDF、修补/拼包/人工翻转或RF重传；不恢复已取消的批量功能。
  数据在SDK Git外，仅同步离线校验代码和根文档；所选样本不是无偏可靠性统计，SNR/模型/全局时序仍未验收。
- 2026-09-16 AIR0重复样本（以下为批准前历史）：目标每源/BER至少3份，保留原六份sample01，本轮79次新RF新增10份，严格合格16/18，未完成。
  H265低档只有原2bit一份，其余五组已各3份；H中19/10/11、高157/239/284，V低19/13/10、中105/157/94、高1602/2262/2444。
  仍整轮全业务BER、目标0.5～2倍、单轮零缺包，不修补/拼包/人工翻转/开RF重传。原GUI、C/ELF/bit/HDF不改，取消的批量功能不恢复。
  79轮61042发/60996收/缺46，21轮缺包、23轮全收零误码，原始抓包独立audit全过，PC重传0、保护前30B错误0。
  H265三轮16-07、16p75-02/06全收3bit=2.078460498e-6，超上限3.923%，用户是否允许尚待回复；不得擅自四舍五入/放宽条件计数。
  每源/配置最多10轮；VQPK14dB预排两轮的第二轮是额外完整记录，非入选。H15-02终端换行判定失败但采集正常，已恢复审计，不是无效RF轮。
  新profile文件replicates.py/test_replicates.py/repeat_campaign.json/repeat_results.json；发布默认要求18，显式--partial才允许complete=false和真实分组数量。
  新结果工程根目录BER_results_20260916_repeats，16业务文件+manifest+raw_new_evidence.zip(全79对)；manifest635A573D…/zipF543026D…。
  原BER_results_20260915六份及其25次证据不覆盖，旧manifestCA81D6F4…不变；业务文件始终SDK Git外。详见根README。
  临时TX ELF8431801A…已恢复原9AC341A5…，RX78C7914C…不重载；TX16/RX66、shift4、DC48/63、IPCFG和GUI15002 ACK/JTAG恢复。
  RX有效/UDP增60996等于PC；reject增143=len2+no_magic141，跨静默/初始化，不能都归入46业务缺包；DMA/stall不增。
  本轮TEMP TX/ad9361-ber-repeat-18ec04f674e64abebe76cfbc8a8d3c48、RX/ad9361-ber-repeat-d5e9407799c14cbbad3a64bf8ded43b4，before备份原件，source-before备份文档。
  无bit重编/FPGA下载/Flash SD写入；21项profile单测本地通过。没有验收绝对SNR、模型效果或全局时序。继续测试或接纳边界样本以用户下一次指令为准。
- 2026-09-15 实际AIR0文件六样本已取得：用户接受1e-6/1e-5/1e-4各0.5～2倍，按整轮全部业务payload解码后BER，不是弱区/1s。
  H.265 180422B/188包，三个错误bit数2/19/157；VQPK 1610048B/1678包，19/105/1602。六轮均单轮全收，源与结果不进Git。
  共25次采集、24次有效RF试验17916/17922；VQPK缺1/2/1后第四轮成功，另H.265缺2。h265-s2-02采集先结束、发送后开始，不能算188个RF丢包。
  仍是独立profile采集，不改原AIR0 GUI CRC拒收，不恢复用户已取消的文件夹批量功能；保留真实错误、不跨轮拼包、不从源修补、不开RF重传。
  临时RX DC44；TX/RX成对shift2/3。为细调在独立目录编译/下载sender-only ELF，原main加ADI API衰减邮箱，14～20dB/0.25dB有界、两路读回。
  候选F51C23FE…，原源码/ELF/bit/HDF不覆盖；前后用现ELF新符号和8机器字前缀核对。RX不重载，无bit重编或Flash/SD写入。
  已恢复原TX ELF 9AC341A5…、TX16/RX66、双板shift4、DC48/63、原四时钟，IPCFG恢复TX192.168.2.50，GUI15002 ACK/JTAG通过。
  RX有效/UDP增18104=17916有效采集+188过期采集时回传；no_magic增195跨越静默/重初始化，其他拒绝/DMA/stall不增，不把195全算业务丢包。
  全25原始采集独立audit，六个输出在本地和两机全文核验；新13单测通过。条件file_campaign.json、结果file_results.json，旧随机结果results.json保留。
  两机工程根目录BER_results_20260915包含六业务文件、manifest和raw_evidence.zip（全25对采集，SHA0256DBB4…）；业务数据放SDK Git之外。
  仅为选定零缺包误码样本，最多10轮/文件/配置，自适应筛选非无偏可靠性估计；BER有轮间波动，配置不是BER标定表。未验收模型/SNR/全局时序。
  本轮原件备份/候选在TX TEMP/ad9361-file-ber-eccf95119e794080a23f491bef6c5b26，RX TEMP/ad9361-file-ber-292471dc50d24d8998047d07b8ba99a6；source-before备份文档/profile。
- 2026-09-15 AIR0误码/零丢包摸底：用户实际文件后续提供，已确认停发/关闭IDE/释放COM3 COM4，天线约20cm。
  新独立profile ber_trials_20260915，1MiB固定随机源/1093包，保留每轮原始UDP和实际误码字节；原AIR0 GUI CRC拒收/精确恢复行为不改。
  用户之前取消的文件夹批量发送任务不得恢复。当前仅实验采集，不是重新实现批量或放宽主GUI校验。
  DC48/shift4首有效轮0丢包、业务BER3.989840%；DC48/shift3四轮缺1/1/2/1，BER约0.035～0.042%。
  临时DC44/shift4、3、2各首轮1093/1093，业务BER分别3.456891%、0.045466%、0.00022650%；弱BER见results.json。
  八轮8MiB/8744包缺5，RX有效/UDP/PC增量8739，无新增结构拒绝/DMA/stall，PC重传0、保护业务前30B错误0。
  全轮独立struct/zlib逐字节复核通过；10项新单测两机及本地通过，旧PC本地86中76过10缺Tk跳过。
  最多10轮/配置的有界搜索，取得首成功样本即停，DC48/shift3四轮后转44；不能说可靠性已量化、44唯一最优或大文件保证成功。
  初次后台启动导致SSH/子进程退出、未产生源/结果/捕获目录，不计RF轮次；后续直接前台Python/XSCT，不复用不可靠后台启动方式。
  收尾两板功率shift4、RX DC48、63、TX16/RX66恢复，GUI15002已ACK/JTAG读回，COM3/4释放、自有hw_server退出；未重载/重编译/改ELF bit HDF。
  原始记录两机TEMP/ad9361-ber-trials-925d1d90e0434b8e94c67ac95f3d9d7d（RX）和6d61efc52c6e44f790efbaeb1581bc33（TX）。
  误码文件与精确文件分开；缺包填零只作占位并列出序号，不从源修补，不跨轮合并，不增加RF重传或人工翻转。实际文件需另测，SNR/语义模型/全局时序未验收。
- 2026-09-15 用户要求修复SNR，并确认停止Sender/关闭两机Vivado SDK/释放COM3 COM4；允许本轮备份、重建、下载和有界RF验证，不写Flash/SD。
  已定位dot11门控误用pkt_header_valid脉冲，S_DECODE_DATA清零后弱区样本一直0；不是噪声校准或门槛问题。
  新snr_packet_valid锁存合法BPSK1/2头，FCS结束/复位/新LTF/停长同步清除，原弱符号范围和4096样本门槛不变；IP122→123。
  两机原工程已合入并完成构建/配套导出；RX已上板。C/ELF/RF/时钟/CRC/重传均不改；只重载RX，不动TX运行态。
  真实门控旧版首弱符号失败，新版190检查、真实monitor计数64/power1600通过；两机gate/monitor/AXI仿真及各86 PC测试通过。
  不是完整RX PHY仿真；全局时序遗留问题仍须报告。build.tcl旧118候选配方已加同一修复，两配方等价验证通过。
  新备份RX TEMP/ad9361-snr-gate-fix-3ed3da5706444d12afc8d17965110d53，TX TEMP/ad9361-snr-gate-fix-026932ad76784c87b66d64f83a60b0a9。
  before核验1293/1292文件差异0，不能拿上轮merge的before旧Stage18当本轮恢复版本。
  本轮原板读回DC48/63/guard32/shift4，TX16/RX66、40MSPS和四时钟正确；SNR函数8条机器码与现ELF吻合后才读RAM（非全RAM镜像一致证明）。
  read_state.tcl已处理XSCT Tcl32位scan符号扩展；最初同机器码报不一致是工具比较错误，不是板内版本变化。
  RX bit BF40B3EC…/HDF57B822EC…，ELF仍78C7914C…；PS初始化/BSP不变。100MHz+0.535/+0.053，monitor from/to+4.790/+1.603，hold+0.157；全局-7.291/-1.721仍不签核。
  TX bit D954E8FD…/HDF5C867861…，ELF仍9AC341A5…；独立检查同样时序数值，磁盘更新但不重载TX。最后RX96/TX95个应用源码/Debug文件与备份一致。
  旧1MiB1088/1093且SNR样本0；新1MiB1086/1093、21,680,320样本、14点；新8MiB8711/8739、中途遥测48点，隐藏实际GUI曲线可用、停发约1s后N/A。
  三轮独立捕获复核一致，弱BER0.233796/0.034121/0.072520%，保护前30B错误0/PC重传0；两新轮PS有效/UDP/PC均9797，拒7（len2/no_magic5），DMA/stall0。不能当丢包改善因果。
  绝对SNR未验收：当前宽带估计约-13.6~-9.1dB，Pn约7.09e6。三短窗静默IQ约93.5~95.6%能量来自均值、均值方向变化，支持强慢变/近直流背景，未证明具体器件或TX泄漏根因。
  200MHz旧ILA有违例，三1024行/102样本/strobe后两行稳定/10拍间隔通过仅为诊断；不将短窗去均值功率替代Pn，也不由BER反推SNR。
  PC只补充wideband/quiet background/DC tones提示，原算法/窗口/门槛不改，各86测试再次通过；用户原GUI不重启，需用户自己停后重开。
  下一阶段有效payload子载波SNR需另行设计并验证去直流/窄带背景测量，不能把本轮曲线恢复当准确SNR完成。
  功能提交cb7707f已两机同步，TX仅stash本轮11自有文件12bf1084…后FF，无关dirty94/15保留。push本轮Connection aborted，尚未成功。
  本地已同步源IP、脚本和发送角色SDK新bit/HDF，HDF内bit/6个PS初始化核验，ELF不变；TEMP/ad9361-snr-gate-local-2e2d51bd1f054608a8fe9a92a154ab01/sdk-before保留旧产物。
  本地XPR/BD/runs未原生刷新，重建须刷新IP/升级RX123/重生成BD，远端两机原生完成。接收GUI目标JTAG读回192.168.1.100:15002，两板ping正常、COM3/4释放、自有hw_server关闭。
- 2026-09-14 用户授权SNR更新原工程/固化；本轮不写Flash/SD、不改变RF默认值、不增加重传。
  两机原RX IP已合并候选同一补丁并升级revision122，原工程已全量构建和安装硬件导出；原net_rx.c加3个接入点和payload_snr_service.h。
  原SDK make已完成：RX ELF78C7914C…、TX ELF9AC341A5…，与上一轮候选457C74F7…不同。
  两机PC源码同步到3003287基线并各86项全过；功能f9dd4be已两机同步，本地RX IP/PS源码及发送角色SDK产物同步。
  本地无Xilinx构建环境、XPR/BD缓存未原生刷新，本地重建须先刷新IP/升级RX122/重新生成BD输出；远端均已做完。
  main/COMMON/app_config/role未改，DC44仍是历史运行时覆盖，重新初始化本轮ELF仍回48；不声称固化了44。
  备份/构建根：RX TEMP/ad9361-snr-merge-eaa583bf63024bc6aaf01c1f711b7386，TX TEMP/ad9361-snr-merge-f31710dd97674268a699d5ae974b0dd0。
  before含XPR/srcs/IP/sdk源码Debug/PC/BSP/平台，复核1291/1290文件；首次diff参数错误已补存并全部重新核对。
  尚未下载/操作JTAG/串口/进行RF或SNR实测；用户尚未回复本轮停发及释放工具确认，本轮未核验当前板内版本。
  磁盘ELF已更新；读RAM先确认运行版本。若仍为轮初版须用before旧ELF解析符号；用户若自行下载则重新定基线，不能用新ELF地址读旧运行态。
  新RX bit CA0EF531…/HDF5BB28181…，TX bit80343EF2…/HDF74428866…；各机HDF内bit/实现bit/SDK bit一致，6个PS初始化及BSP不变。
  两机实际原AXI联合仿真均2790ns SNR_AXI_SIM_COMPLETE；不是完整RX PHY仿真。两机100MHz +0.518/+0.052ns，monitor from/to setup +4.396/+1.625，hold +0.055。
  全局WNS/WHS -7.177/-1.721ns、200MHz setup -1.715，仍未签核；不能将老候选8AFBCCB1…或旧时序数值当新原工程结果。
  新helper下载脚本已准备但未执行；两机代码功能提交f9dd4be，sender仅stash本轮11自有文件0949f211…后安全FF，无关dirty仍94/15。
  本轮push默认Connection aborted/进程内直连Connection reset，均128，未改凭据/代理；未push成功，历史认证失败不作为本轮唯一原因。
- 2026-09-14 SNR新增候选实现payload_snr_20260914，尚未上板/固化，不把完成构建说成曲线已实测可用。
  原XPR/BD/IP和C/正式bit/ELF/HDF保持；build.tcl只改独立副本，build_elf.ps1只生成候选net_rx对象/ELF。
  GUI用snr_telemetry独立控制socket，4Hz查询原始I/Q矩，约1秒样本加权；BER/缺包曲线不覆盖SNR。
  噪声明确要求Sender静默校准10+200ms，手动固定增益；DC去均值后线性扣噪，Pr<=Pn无效，不从BER/RSSI推导。
  弱DATA从sync_long原RAM输出、FFT/×16恢复前取样，跳guard32和额外1个过渡符号，含导频，只统计有效BPSK1/2 PHY头，不要求FCS正确。
  校准期间合法PHY头/测点削顶/增益模式BW采样率LO配置变化/30分钟过期无效；无包不是无信号，16位检查不排除模拟或早级ADC饱和。
  RX新reg6控制/22快照序号/28数据/29能力A7220001，reg31仍A7170002、reg19不变；绝不可对原bit套新寄存器解释。
  SNRQ请求20B/SNR1回复260B，独立CRC/requestID，不改RXCFG peer或视频40B头；校准poll在S2MM重装后，开销仍待RF验证。
  接收PC阶段86项含10Tk全过，本地76过10缺Tcl跳；计数器sim-b和实际候选AXI联合仿真通过，非完整RX仿真。
  独立硬件E:/by2025/AD9361_test_board/ad9361_snr_20260914_a：bit8AFBCCB1…，HDF2D44FE24…；候选ELF457C74F7…。
  新计数器from/to setup+3.404/+2.085ns、hold+0.070，旧200MHz仍-1.772ns，不是全局时序签核。
  原备份/日志/elf-a/pc-stage在接收TEMP/ad9361-snr-20260914-b3832309dbb14084b1890fd131fc652a。
  没有新板级SNR/RF结果、JTAG重载或Flash/SD写入；板级验证仍需用户确认停发、工具释放及天线配置，保留原Stage18基线。
  本地/接收原SDK已更新4个PC源码测试文件，安装目录86项再次全过；运行GUI不重启，旧bit/ELF仍无SNR。无关dirty接收15/发送94保留。
- 2026-09-14 用户要求丢包率也使用最近1秒窗口：当前 loss_pct 已改为序号范围发现时间 `(t-1s,t]` 的暂定缺失率，
  loss_total_pct 和原累计 missing/expected/received 保留；GUI 标题 last 1s、下方同时列窗口和累计值。
  缺包按推进最高序号时的新范围归属，不知道真实发送时间；活跃范围迟到修正，过期范围迟到仅修正累计，重复不刷新窗口。
  无新范围约1秒后 N/A，不是0/100%；尾部未知/全丢窗口需后续序号才能发现，不能称纯RF或严格发送秒丢包率。
  仍将坏payload视为收到，不改变BER窗口或原视频组帧/解码；只改PC端，板卡/GUI运行进程不动。
  静默/弱区功率法SNR仅说明：同测点同增益带宽的 mean(I²+Q²)，线性扣噪后取10log10；无包不等于无信号。
  强保护区和弱payload分开；缩放/DC/干扰/削顶需处理，PL/PS测量遥测尚未实现，SNR仍N/A。
  共66项测试在接收电脑独立目录及安装目录全部通过，本地61通过/5缺Tcl跳过；接收机及本地已更新，发送机未改。
  接收机六文件备份ad9361-loss-window-e0264d13eaa04e51b7e065726172a2ee/before，无关15项dirty保留。
- 2026-09-14 接收 GUI 增加 Link quality 页：包序号累计暂定缺失率、参考源逐 bit 比对的最近1秒业务 BER，保留 Throughput 页。
  源文件通过 BER Reference 对话框选择：AIRV 为 Sender 真正使用的 H.264 Annex-B（不是 MP4），AIR0 为相同原文件/随机源。
  源/帧和分片 CRC/长度先核对；无参考/不匹配/无新样本必须 N/A，不把 CRC 失败率当 BER。
  skip=0 比较全部业务；skip=30 只对应当前 BPSK1/2、guard32 弱区，不能随 PHY 变化仍固定称为弱区。
  缺失率按0到最高序号、唯一收包统计，可被迟到包修正；坏payload算收到、重复不重复计数，末尾未知。不等于纯空口丢包率或视频丢帧率。
  SNR 仅明确不可用的面板，尚无真实测量/回传，不要称三条实测曲线均完成；需后续扩展 PL/PS 并验证。
  本次只改PC端，不改RTL/C/ELF/bit或RF参数，不读取/重载板卡，不启用RF重传；原GUI进程保留，由用户停止后重开。
  接收电脑独立目录57项测试全通过（含5项Tk和localhost UDP）；本地52通过、5项缺Tcl跳过。没有新的RF性能结果。
  正式说明仅在根README。接收机备份ad9361-quality-gui-20260914-03c7ec8c290c4966885c425794f8e62b/before。
  接收机原SDK已安装新版并再次57项测试/文件哈希验证通过，本地同步相同修改，发送机未改；原15项无关dirty保留，提交/push状态以实际结果为准。
- 2026-09-13第二十一轮测试结束：用户要求继续降低整包缺失、保留payload误码，已确认停止发送、天线0.2m位置不变。
  初始两机HEAD f17b1da、原Stage18 ELF/bit/HDF哈希未变；板内TX16/RX66、DC44/63/guard32/shift4正确，PS累计36042/36040/2，与上轮结束相同。
  备份各机stage21-before-trace；不合并原工程、不写Flash/SD、不增加RF重传或射频功率。实验脚本loss_trace_20260913。
  第一轮32MiB缺4986/22533/30776，共3/34953，弱BER7.5734%，保护业务前30字节错误0，独立复核一致；PS有效/UDP/PC增量34950，无新增拒绝/DMA错误。
  原ILA badheader等待脚本误把timeout单位当秒，实际是分钟，进程后续超时退出；未获得有效失败波形，不能据此声称头无错误。脚本已改timeout3分钟。
  正向goodheader的1MiB全1093包，弱BER7.9494%，独立捕获分析一致；1024行触发valid/strobe=1、rate11、len1028、样本间隔10个200MHz拍，离线验真通过。
  原ILA200MHz自身存在setup违例，不把未触发当排除证据。基线结束PS72085/72083/2、UDP72083，未新增拒绝。
  从原综合网表只读导出stage21-observe-a；2018.3不允许移除HDL实例化ILA，故保留原ILA并增19端口4096深度100MHz观察器，hub亦100MHz，未改RF/PHY功能RTL。
  首次生成bit被RTSTAT-5单网partial antenna拦住；独立checkpoint只重布该DMA网后DRC零错误，bit9E770191…、LTXEAAEA38B…。
  修复后100MHz setup/hold +0.003/+0.017ns，新ILA +0.003/+0.043ns；余量极窄，全局约-6.506/-1.722ns仍不签核。
  接收板observe已上板，发射板未动；正常4096行验证valid/rate11/len1028、state顺序正确，819点I/Q间隔全5拍。
  observer首1MiB缺7～10、len拒2、弱BER5.156%；随后dc32m全34953、ltf32m缺3798/21993/28061、header32m缺10043/14207，弱BER7.3446/7.3181/7.9546%，独立分析一致。
  3种失败触发均未取得有效波形；2018.3超时可正常返回空数据，dc/ltf旧wrapper报Missing ILA completion，RF结果仍有效，最终脚本标记NO_VALID_CAPTURE并保留.invalid文件。
  3轮稳态96MiB缺5/104859，PS有效/UDP/PC增量104854；observer最终PS105945/105943/2，未新增reject，watchdog0/1/DC=0/1/110552；没有证明具体PHY根因。
  临时quiet ELF仅把复制的net_config.h首2条有效包日志改为0，原源码/对象/ELF不动；AB3F6B72…的首1MiB仍缺7～10、len拒2，弱BER7.7246%，不保留；未排除所有UART/PS原因。
  quiet链接符号已变，read_state需显式receiver quiet才读候选统计，不得对已恢复原版使用quiet地址。
  接收板已恢复stage21-before-trace本机原bit/ELF，再写DC44；发送板未重载。接收共3次初始化，BER不可直接跨启动比较。
  恢复首1MiB仍缺7～10、弱BER8.4046%；随后32MiB缺22428/27244/33674、弱BER7.8872%，全9轮164MiB/179137包缺23，独立捕获复核一致，PC重传0，保护业务前30字节错误0。
  最终PS36041/36039/2、长度拒2其余0、UDP36039、DMA错误/stall0，watchdog0/1/DC=0/1/37753；原版稳定缺包未改善，具体PHY根因仍未闭环。
  两机原源码/ELF/bit/LTX/HDF哈希与备份一致，GUI15002已恢复且JTAG读回，COM3/4释放、两板ping正常，自有hw_server19760关闭，最终无Vivado/SDK/XSCT/hw_server遗留。
  sender首次hold_server被执行策略拦住，后续只读XSCT自动启动临时server并退出，未重置下载器；不得把该设置失败当射频缺包。
  PC36+捕获4+波形8测试通过，两机无关dirty仍94/15，RAR保留。测试记录4f58797在接收机已提交，后续状态提交及两机bundle同步以HEAD为准。
  本轮接收机push原代理无法连接，进程内直连Connection was reset，均exit128；未改用户代理/凭据，不要沿用上轮wincredman失败作为本轮唯一原因，也不声称GitHub已更新。
  sender仅暂存本轮自建profile以安全同步，stash eb17d28459f81ed3d3179064ddd8c132aeddcf1a保留；不要pop覆盖最终记录，历史stash和用户BSP改动均不动。
- 2026-09-13第二十轮已结束：用户授权小幅增强保护区，同时维持弱payload功率；不是固化授权。没有可靠收益，候选不保留。
  两板已恢复各机stage20-before-header-power自己的Stage18 bit/正式ELF，基础签名A7170002，候选能力TX reg31/RX reg29读回0。
  code4仍1/16；新增code5=3/64（不是1/32），RX逆幅度64/3近似和LLR权重9/4096匹配。TX16/code4与TX13.5/code5名义弱区功率近似相同。
  独立候选bit FA384968…/sender临时mailbox ELF5AC9879B…仅留作实验记录，不用于正式下载；A/B间通过ADI API改衰减并读回，未重初始化。
  原源码/bit/ELF/BSP/平台没有合并或覆盖，无Flash/SD、无RF重传或人工翻转。当前TX16/RX66、guard32/shift4、RX DC44，DC44仍是临时寄存器，原ELF重新初始化会回48。
  profile header_power_20260913下load/run_load支持candidate/restore；control只接受候选能力标识，receiver保持DC44/63/RX66，400KiB/s/chunk1024/window1不变。
  初版A负数舍入仿真失败，构建已仅停止自己的进程，未上板。B全signed16舍入、6档27919点TX、3780拍LLR、786444项RX恢复及40项PC测试通过；不是完整RX仿真。
  B100MHz setup/hold+0.016/+0.052ns，200MHz-1.771ns，全局-6.280/-1.721ns；余量很窄且全局仍未收敛，不能说量产签核。
  同一候选/初始化A-B-A-B各两轮32MiB：A缺7+5=12/69906，B缺8+3=11/69906，弱BER3.5329%/3.9590%，相差一包不能证明有效改善。
  ILA强前导数字功率+2.538dB、DATA含噪-0.139dB，支持分区功率生效，不是校准SNR。返回业务前30字节错误bit均0，不涵盖未回传的头。
  原版开始32MiB缺4/34953、弱BER5.226%；候选初始化短测缺seq7/8、长度拒收1；不能把跨初始化BER变化归因于功率。
  恢复后1MiB缺seq7～10、长度拒收2；随后32MiB缺seq238/33260、弱BER3.694%，最终PS captures/valid/reject=36042/36040/2，DMA错误/超时0。
  共9轮有效195MiB/212997包，原始捕获独立复核均一致，PC重传0；完整逐轮统计、哈希和限制见results.json/根README，原始记录stage20前缀。
  接收GUI15002已RXCFG与JTAG读回恢复，COM3/4已释放，两板ping正常，自己的hw_server已关闭；不要重新加载本轮候选或回退旧SMA参数。
  实验记录6d9349434cb9fdb44e74fd4b175913c40fc11e6b已两机同步；sender只暂存本轮自有文件以安全FF，stash 0baed4eb8a27d72a8a079ea815950352ffb21db8保留，不要pop覆盖记录。
  两机无关dirty仍94/15（接收机RAR保留）。最新push两机均到达认证但wincredman无法持久化/读取GitHub用户名，exit128；不是已push，也不再仅是第十九轮网络超时，不改用户凭据。
- 2026-09-13第十九轮：用户要求继续降低丢包，同时保持高payload误码目标。本轮只做RX寄存器对比，未重新初始化两板。
  当前接收板保留DC44，即RX reg2=0x002C0000；发送板自身RX reg2仍0x00300000。plateau63、TX16/RX66、guard32/shift4、2.2GHz/40MSPS和时钟全部保留。
  原C/ELF/bit/HDF/PS初始化未改，无RF重传、无人工翻转、无Flash/SD。源码main的POWER_THRES_RF仍48<<16，重新初始化原ELF会回48；不要说已固化44。
  44是同步阶段64点I/Q符号和的DC异常检测门限，不是dB、不是plateau63，也不是FFT配置中的48；降低门限使异常复位更早触发。
  基线DC48的8MiB缺66，回切48的8MiB缺57；DC40的4MiB全4370包、8MiB缺2、32MiB缺7。plateau59/55和DC64均恶化，未保留。
  DC36的8MiB缺2；DC44的8MiB缺1，两轮32MiB分别缺3和2。44共72MiB/78645包缺6（0.00763%），后段BER5.8725%，保护业务前30字节检出0bit。
  36/40/44短测差一两包不能证明唯一最优；当前44为本轮实测较好选择，不是长期零丢包或重启后性能保证。
  44末轮新增PS no_magic拒绝1；最终累计captures/valid/reject=186013/181683/4330，len3/no_magic4326/shift1/header0，DMA error/stall0。
  累计含坏候选和以前运行，不能将4330当44的缺包数，或将PS拒绝与缺失源包逐一对应；DC是重要影响因素，具体单帧波形根因未闭环。
  本轮12个有效随机数据测试共152MiB，PC重传0，目标400KiB/s不变，实际平均约312～389。baseline8m-a发送未启动（执行策略）无效，不计RF丢包。
  独立捕获逐bit复核12轮一致，记录在loss_tuning_20260913/results.json；接收GUI15002已恢复/JTAG读回，COM3/4释放。原文件备份stage19-before-tuning。
  第十八轮defaults_status是启动默认/历史验收快照；当前临时DC覆盖以第十九轮为准。完整RX仿真、全局时序、校准SNR及语义模型仍未验收。
  本轮没有执行准备过的RF重新初始化/增益脚本。保持当前运行态；后续固化44需改正确的DC宏并重编译/重启复测，不改其他48。
- 第十八轮（2026-09-12）用户明确要求“帮我固化进去”，并已确认关闭两台 Vivado/SDK。
  该授权覆盖第十七轮“不合并/不固化”的历史限制；仍不刷 Flash/SD、不改变启动介质。
  目标是 D PHY + TX16/RX66 + 前32 DATA符号保护 + 后段1/16匹配幅度/LLR，不是恢复零误码目标。
  两机已完成 stage18-before-defaults 备份、源码合并与各自ELF构建；RX新bit E3733085…、TX新bit8FF06CFE…均已下载并验证启动默认参数，无RAM补丁。
  TX首次Vivado实现因EXCEPTION_ACCESS_VIOLATION崩溃，原设置重试成功。首1MiB缺12/1093、弱区BER3.997%；首8MiB缺53/8739、弱区BER3.963%，保护业务前30字节错误0。
  第二轮8MiB同样缺53/8739、弱区BER3.883%，两次缺失序号不同，独立原始捕获分析一致。共17MiB缺118/18571，RF无重传、PC重传0。
  RX最终captures/valid/reject=18512/18453/59，len2/no_magic56/shift1，不能将全部缺包认定为空口同步漏检；未测语义模型/校准SNR。
  GUI192.168.1.100:15002已恢复且JTAG读回、COM3/4释放、双板ping正常，临时自己启动的hw_server已关闭。
  当前保留新版，不恢复stage17旧bit/ELF；完整哈希见README/defaults_status.json，三轮统计在defaults_rf_results.json。
  功能30a9b52已在两机同步，sender为安全FF将本轮自己的临时源码/脚本存入stash 37b2167b77e504010a32f164f16fefa31e8a602d；保留备份，不要pop覆盖最终配置。
  两机剩余dirty94/15（原93/14加本轮LTX），BSP原始改动保留。push均因wincredman/无法取得密码失败，GitHub连接器权限push=false，不得声称push成功或修改用户凭据。
  本地SDK配套产物已同步发送机新版，旧本地ps7_init缺FCLK3配置，已从新HDF一起更新；本地无Vivado原生刷新验证、无Git提交能力。
  RX新100MHz setup/hold +0.207/+0.052ns，200MHz -1.803ns，全局 -6.280/-1.721ns仍未签核。BSP和PS初始化/7个地址范围保持。
  COMMON共享TX16000/RX36，接收ignored本机头仍TX25000/RX66。app_config启用不等功率，数字回环旁路；
  main检查TX/RX A7170002签名，默认TXreg2=A704205D/RXreg5=A7048304并读回。旧bit搭配新启用ELF会FATAL。
  保留原时钟/63/RF门限/网络协议，无RF重传；完整RX仿真/全局时序限制不得隐藏。
  新脚本 backup_defaults/merge_defaults/run_merge_defaults/install_defaults 位于原payload_power profile，README是正式说明。
  本地尚无Vivado/git/rtk；远端Git可用。每次ELF重建必须重新解析符号，不沿用stage17固定地址。
- 第十七轮最新进展（17:13）：用户确认两机JTAG恢复并自行烧录，磁盘bit/平台bit/ELF及板内时钟、RF、63已核对一致。
  新原版基线stage17-userbaseline1m-1636收到937/1093、缺156、899520业务字节bit错误0，不得沿用此前2.5%作为当前唯一基线。
  D候选56B0FEEC…在双板完成关闭/1/2/1/4/1/8/1/16实际RF对照，原ELF不变，匹配LLR/签名验证通过，无RF重传或人工翻转payload。
  TX22/RX66时1/4已见弱区BER0.01494%，1/8的8MiB收到7980/8739、缺759、弱区BER2.826%；1/16弱区46.808%且前30字节也有2bit错误。
  额外RAM TX衰减16dB配DATA1/16，较22dB+1/8使前导/受保护区约强6dB、后段绝对功率近似不变。
  较强头1MiB缺6/1093、8MiB缺36/8739，弱区BER3.667/3.668%，前30业务字节错误0。该8MiB有6838坏payload、2374937错误bit，全部payload BER3.55357%。
  回TX22+1/8缺94/1093、弱区BER3.075%，支持增强保护区有帮助；TX重初始化仍是混杂因素，不可声称唯一因果或全部缺包是RF同步漏检。
  17:09两板已恢复各机stage17-before-power原bit/ELF（与用户此次烧录一致），D签名消失、TX22/RX66/63/原时钟通过；最终1MiB缺120/1093，收到内容bit错误0。
  收尾GUI192.168.1.100:15002已RXCFG且JTAG读回，双板ping正常、COM4/3可打开且释放；原文件424/425项差异0，无关dirty仍93/14。
  候选只保留独立实验配方，不固化TX16、不合并原工程、不刷Flash/SD；完整RX仿真/全局时序仍未通过。
  rf_results.json保存实测轮次，README是正式说明。后文“没有候选上板”仅为此前USB故障期间的历史；当前是候选已测但已恢复原版。
  不得将本轮说成已测语义模型、校准SNR或长期零丢包；后续传统/语义比较必须同PHY/保护/资源预算，BER与缺包分开。
  17:24最终记录commit后push直连已到认证阶段，但SSH会话wincredman无法持久化且无法读取GitHub用户名，未push；当前需解决GitHub认证，不能只沿用早期网络超时说明，不改用户凭据配置。
- 2026-09-12 第十七轮（实验进行中）：用户要求物理层/包头保护对照，目标是尽量少丢整包、同时收到的业务 payload 有可测误码，服务于后续语义通信比较；不是继续把全部数据调到零误码。
  用户已确认天线约0.2m无遮挡、2.2GHz获准使用、两板JTAG在线；已停止发送并释放COM4/COM3。
  仅在独立 `hardware_profiles/payload_power_20260912` 配方及远端 sibling 工程制作候选，不合并原XPR/BD/IP，不刷Flash/SD，不修改原ELF/平台/BSP。
  前导码/SIGNAL/前32个BPSK1/2 DATA符号保持原幅度，其后DATA可降幅1/2～1/16；RX做匹配幅度恢复，不能把实现失配伪装成真实RF误码。
  第一版B已生成但新增TX幅度路径setup=-1.498ns，不得用于误码结论；C改写等价舍入及前导旁路，100MHz setup已+0.233ns；全设计旧时序违例仍存在。
  D增加匹配LLR权重a²及随样本的功率标签，3780拍解调单元验证通过，硬件已构建，100MHz setup/hold+0.250/+0.057ns；全局旧时序违例仍在。
  D bit56B0FEEC…/HDF86FCB933…，完整哈希见README；D签名A7170002，不能用B/C签名1作为合格候选。
  独立DFT确认C发送SIGNAL的48个编码bit正确，不等于RX整链通过。尚无候选上板，正式版本仍第十六轮。
  发送波形数值检查通过不等于完整PHY仿真通过；首两轮RX仿真失败（测试台原先还把SIGNAL字节计入payload），必须保留失败记录，不能仅凭Vivado退出0判成功，须检查STAGE17_RX_SIM_COMPLETE。
  默认TX22/RX66、400KiB/s、chunk1024/window1、PC->PS CRC/ACK、无RF重传不变。基线1MiB两轮分别1064/1093、1066/1093，收到payload逐位无误码。
  第二轮最后短包曾被分析器误记为malformed；原始received_wire.bin独立复核确认缺27包、1022656字节/bit错误0，以离线复核为准。
  双机原工程完整备份在各机 `%TEMP%/ad9361-diag-20260906/stage17-before-power`，恢复必须用本机备份bit/ELF，不混用角色或旧SMA profile。
  15:06两机JTAG不再返回APU，重试失败；15:15 Vivado报44-494/jsn1可能被别的hw_server锁定。USB和板卡ping正常，不要认定断电或硬件坏。
  用户已关闭Vivado/SDK，进程退出后JTAG仍空；未强杀用户进程。仅对已确认Xilinx USB Cable执行一次pnputil重启设备，随后Present枚举暂未见下载器。
  agent未重启电脑/板卡、未动串口/网卡。尚无候选上板；后续只读发现接收板bit未加载，不能继续认为无需恢复原版。
  用户已完成USB拔插，15:45两机原下载器端口均报USB Device Descriptor Request Failed；scan-devices未恢复。
  用户已完成下载器USB/JTAG完全断开及换口，随后接回JTAG并确认电源灯。RX枚举OK/Code0且能读APU/ARM/FPGA，TX仍USB Cable Error/Code10/ProblemStatus C0000001、没有APU。
  RX只读提示Bitstream is not programmed，两板ping不通；尚无候选下载，不得归因候选。各机原版备份哈希匹配，开始仅恢复RX原版，首次等待超时未获成功标记，需检查落盘阶段日志，不能直接宣称恢复成功。
  不得反复软件重启或贸然重装驱动/重启电脑。原文件424/425项再次复核差异0。
  16:13恢复日志stage17-rx-restore-1613.log明确APU目标为空，未执行reset_system/FPGA加载；RX尚未确认恢复。首次未落盘尝试状态不能由退出码推定。
  16:19发现两机Vivado/SDK/交互式调试重新启动；暂停板卡动作，询问用户是否正在下载以及是否关闭，不能强杀其hw_server/IDE。
  新hold_hw_server.ps1因3121已有监听主动退出，未启动新服务；download.tcl新增阶段日志。没有候选五档RF结果。
  15:17曾将自动测试15003恢复GUI192.168.1.100:15002且有RXCFG确认，但板内配置缺失后须重新注册/读回，不沿用旧确认；COM3/4须保持释放。原文件及无关dirty不得覆盖。
  实验脚本/记录已在两机以68f0804提交同步（非原RTL合并、非上板）；GitHub push受网络阻碍，默认127.0.0.1:7890代理不可达，单命令直连覆盖也超时。不得声称已push，不改用户代理设置。
- 2026-09-09第十六轮用户明确要求固化天线TX22/RX66。当前默认按第十六轮执行，不再把第十五轮未固化当现状。
  共享COMMON默认TX22000/RX36；接收电脑src/utils/rf_board_local.h本机覆盖为TX25000/RX66，发送电脑无覆盖。
  本机头文件被Git忽略以保护收发角色，接收模板rf_board_local.h.example已跟踪；新克隆接收工程必须先复制模板再编译。
  只改源码配置/重编译应用/下载ELF，不改RTL、bit、平台、BSP、时钟、LO、40MSPS、63、RF门限或协议，无RF重传。
  新TX ELF D23854BF…、RX ELF5C228243…，完整哈希见根README。下载无RAM补丁，编译初值和启动实际读回已验证。
  这次“固化”不是Flash/SD刷写或上电自启动改造；不要让用户以为仅断电重启即可加载本轮ELF，仍按原流程下载新版。
  回SMA先改回TX25000/RX36并编译下载；保留候选不等于消除第十五轮波动或证明无损。两机用户无关BSP/HDF/IDE改动须保留。
  备份stage16-antenna-defaults-before，日志stage16前缀；收尾仍须恢复GUI15002并释放COM3/4，不能混用两机ELF。
  固化后8MiB收到8567/8739，缺172、收到内容bit错误0，DMA error/stall0；这是参数保留验证，不是无损或性能修复验收。
- 2026-09-09第十五轮用户已进一步确认全频段天线和2.2GHz获准使用，覆盖第十四轮许可待确认状态。
  允许在现有0.2m天线链路上有界功率/增益对照，不代表已测天线驻波/增益或辐射功率。
  本轮只重载各机原ELF并在启动前临时改RAM txatt/gain；未改原COMMON/ELF/bit/HDF/时钟/采样/LO/63/门限，无RF重传。
  同参数25/71仅TX重载就使1MiB缺95→25，须记录初始化混杂；不得仅按一次最小丢包认定唯一根因或最优值。
  22/66首1MiB缺seq7/8及长度拒绝1，随后8MiB缺11/8739；19/66的16MiB缺35/17477，回22/66缺59/17477，内容bit错误均0。
  第十四轮结束RX71是历史运行状态，本轮最终状态和完整证据以根README第十五轮为准；不应盲目恢复旧SMA profile。
  ILA采样须跳过第0行未知strobe前态，并用已观察上升沿+1与+2一致核验；只对真实短前导估CFO，不能对噪声/随机payload算CFO。
  最终仍须恢复GUI192.168.1.100:15002并释放COM3/4；备份stage15-baseline-20260909，原文件指纹与第十四轮一致。
  16/60的16MiB缺157/17477，虽短窗SNR粗估约28dB仍恶化，候选不保留；回TX22/RX66做最终回归。
  回22/66两板重载后8MiB缺178，仅RX同参数重载仍缺167/8739，收到内容bit错误0；最好11包结果未稳定复现，不可声称恢复验收无损。
  已保留22/66临时RAM而非固化，磁盘原ELF仍TX25/RX36；重新下载会丢失临时参数，切回SMA须先恢复原参数。
  最终隐藏GUI视频3858/3930分片，246交付/58丢帧，34解码/16绘制，CRC和解码异常0；早期等待关键帧，不能说流畅或完整。
  实际缺RF分片72，不是GUI frag_missing839。记录本轮退化，不把“已恢复原文件哈希”混同“性能恢复到最好”。
- 2026-09-09第十四轮已切换天线，用户称全频段、间距0.2m无遮挡、原TX/RX接口；具体型号、2.2GHz匹配和极化未核实。
  当前原bit已含第十一轮修复并由用户重建，不再恢复旧sma profile。最新RX ELF为48B10D25…，用户已将自身TX衰减改为25dB，
  不得回退旧456100D6…/30dB ELF。当前TX bit B748A4DD…、RX bit18964C4B…、TX ELF4DA504F3…，完整指纹在README。
  本轮仅临时RAM测试RX增益24/36/48/60/71及DC门限127；源/ELF/bit/采样/搬运时钟/频率/TX衰减均未改，无RF重传。
  71两次1MiB缺172和82/1093，最后4MiB缺349/4370；收到内容bit错误0，不能称无损或最优配置已完成。
  已保留RX临时MGC71dB，原COMMON/ELF默认36不变；原ELF重下会回36。DC127仅收到1/1093，已恢复48，不能保留该候选。
  plateau仍63、符号派生15，最终须恢复原GUI192.168.1.100:15002并释放COM3/4。回SMA先恢复RX36，不沿用天线高增益值。
  ILA原1024深度探针的strobe跳变行数据未稳定，需取后一行并核对再后一行一致/strobe有效；本轮初算0.999相关性及CFO推导作废。
  稳定短窗重复质量约17～22dB不是校准SNR；不得套用旧SMA38dB或据三段未满量程排除模拟压缩。
  天线/频段许可或屏蔽条件未核实前，不提高空口发射功率或改频；当前仅保持原2.2GHz/TX25短测。
  备份stage14-baseline-20260909，临时脚本/日志stage14前缀；完整结论只维护根README。尚缺天线型号/近照，不能认定只需微调。
- 第十一轮（2026-09-07）用户已关闭两台原Vivado并明确授权合并。两机原工程已包含第十轮prefill2功能RTL，
  `openofdm_rx`原打包修订2→3，升级IP、重新生成BD输出、实际引用源码比对及check_syntax通过。
  生成共享目录TX=9d9f、RX=16f6，目录名不同不代表逻辑不同；没有合入stage5诊断接口/计数器。
  短同步器、63、RF、采样率、TX41.667/RX40时钟和SDK C/ELF都未改。第十轮“原工程尚未合并”现为历史状态。
- 第十一轮只合并/刷新验证，没有重生成bit、导出SDK平台、编译ELF或下载板卡。synth_1/impl_1均NEEDS_REFRESH=1，
  当前板上仍是第十轮恢复的用户新bit，不能告诉用户本轮补丁已经上板生效；需Generate Bitstream→匹配硬件导出→构建/下载再回归。
  本地仅同步ip_repo源与修订号，旧生成目录未用Vivado刷新；本地构建前也须运行合并脚本。不要手动伪造生成产物或时序验收。
- 新可复现脚本`hardware_profiles/sync_late_20260907/merge_into_project.tcl`会备份源文件并支持修订3刷新，
  自动识别RX IP目录后缀、归一化补丁换行。成功日志stage11-merge-b.log；初次两机预检查失败发生在远端源码修改前。
  原源文件备份stage11-original-merge-b/backup，软件/平台/文档备份pre-stage11-merge，均在两机ad9361-diag-20260906临时目录。
  两机用户已有BSP/HDF/COMMON/IDE改动必须保留，提交只含本轮脚本/文档；36项PC单元测试通过。
  全新Vivado进程重新打开复核通过：RX未锁定、XCI修订3、实际生成源一致、BD/语法校验通过。
  BD差异仅4条net的端口排列顺序，连接集合和其他字段不变；main/COMMON/net_rx、ELF/bit/HDF/ps7_init与备份哈希一致。
- 第十轮（2026-09-07）已用原RTL+原Xilinx IP行为模型回放三段失败/三段正常I/Q，
  在捕获short脉冲的边界驱动下复现LTF状态、检测周期和错误帧头。`sync_long.v`候选prefill2
  同时预填充32点相关历史、把跳过尾部写入环形RAM224～255；三例错误头均恢复11/1028，
  正常三例不变，FFT历史监视无旧数据读出。只预填充相关器的第一版漏修最晚一例，不能采用。
  未强制short的clean-reset正常对照缺捕获前历史，原版和候选均失败；不能声称完整板级模型或12例全通过。
- 第十轮候选仅临时加载RX，TX保持用户新bit；63、RF、时钟、SDK C/ELF、400KiB/s、chunk1024/w1、RF无重传均不变。
  初次8MiB物理层8739全正确，但捕获/PS缺seq7～11；后续32MiB34953全收且文件CRC/逐字节通过。
  再128MiB139811包全到、头错误0，seq68755有3字节/5bit差异及1次PHY FCS失败，不是整包丢失，也不是无损。
  此前168MiB共183503个合法PHY头、头失败0，不等于所有链路缺陷已消失；ADC速率差/初始化/时序问题分别追踪。
  再次加载候选32MiB仍PHY34953全正确、PC缺seq7～10（捕获少2+长度拒绝2）。两次初始化累计200MiB/218456包，头失败0。
- 第十轮功能补丁在`hardware_profiles/sync_late_20260907/sync_long.patch`，独立副本git apply检查及源码等价通过。
  独立诊断bit F5A14FC7…包含第五轮仪表；全设计时序未收敛，100MHz核内setup=-0.182ns，post-route优化未改善、未上板。
  原Vivado窗口未确认关闭前不覆盖原XPR/BD/IP，不将诊断接口合入生产源，不覆盖用户SDK平台/BSP/ELF。
  正式合并须备份、更新打包IP修订/BD输出再重新构建验证；不能把保存补丁说成已合并/用户重建会自动包含。
  备份为各机pre-stage10-userbuild，实验日志/仿真/回放输入在远端ad9361-diag-20260906的stage10前缀；完整结果仅维护README。
  自动测试临时注册UDP15003；结束须恢复原GUI目标192.168.1.100:15002并读回确认，释放COM3/COM4。
- 第十轮结束已恢复用户新RX bit/ELF，TX始终未加载；原RTL/IP/XPR/BD没有合并同步补丁，候选不作为当前运行版。
  恢复8MiB缺seq7/8、长度拒绝1；随后的32MiB缺3且seq6729有3字节/5bit差异，PS reject/error/stall无新增。
  不得隐藏非无损结果或凭恢复哈希声称性能全部验收；原版也有包内误码，但不能由两次短测推定误码率等价。
- 第九轮（2026-09-07）用户确认合并后已经自行重建并下载，恢复必须用各机`pre-stage9-userbuild`的新bit/ELF，
  不再默认恢复旧`sma_20260906`。TX新bit FBC26AE1…、ELF4DA504F3…；RX新bit6ED9305C…、ELF456100D6…，
  完整哈希见README。用户新增BSP/HDF/平台导出文件均保留，不得顺手提交或覆盖。
- 第九轮用户新bit32MiB缺2/34953，收到内容bit错误0，RX S2MM/valid/UDP/PC增量一致，无新增PS拒帧。
  临时stage6-hw-c诊断bit首次32MiB混合启动结构异常、帧头错误、接收搬运差异，不可只归因RF。
  不重启后的两轮32MiB分别缺3和2，LTF计数与TX PHY一致；缺口全部对应帧头拒绝，FCS/S2MM/PC一致。
  随后8MiB全文件一致。TX软件统计在session reset清零，不可直接跨会话作差；TX PHY16位计数按回绕算。
- 第九轮取得3段独立4096点失败帧头波形及同一63配置的3段正常对照。失败STF检测比正常晚约34～46点，
  LTF相对真实波形统一晚34点（20MSPS下1.7us），头rate/length错误；三段ADC丢弃不变、strobe全5拍、无do_mult重入。
  重点嫌疑是短前导晚检与sync_long固定32+22跳过及首次搜索窗口的衔接；未探测addr1/FFT读地址/short内部计数，
  不得说FFT窗口错位或短前导晚检的成因已经唯一闭环。下一步应加内部观测/回放验证，不再仅凭GUI盲调增益/CFO。
- 第九轮静默176017532输入/1007真实ADC丢弃（5.721ppm），板内速率差约5.718ppm；这不是双板SFO。
  ADC问题仍存在，但不是上述3段失败的直接丢样本证据；整体时序仍不收敛也不是单帧因果证明。
- 2018.3 ILA缓存STATUS可能滞后；需完整4096行、实际触发信号及非重复数据联合校验。
  stage9-headerwave的badheader_2是_1的重复超时旧数据，不计样本；有效为stage9-badheader-existing与headerwave_0/1。
  enum必须按LTX逐字段解码：mult的iSTATE=0/iSTATE0=1…，strobe的iSTATE=1/iSTATE0=0，不可统一替换。
  本轮临时工具/日志在远端stage9前缀，正式源码及63/RF参数未改；完整结果只维护README。
- 第九轮恢复新bit时另见初始化状态敏感性：双板重载后16MiB缺926/17477、RX无magic拒绝340；
  TX不动，仅RX重载同一bit/ELF后8MiB只缺开头seq7～10、无magic拒绝0。不得隐去该退化或仅凭读回相同判定恢复验收成功；
  也不得未经波形确认就指定ADC校准/时钟相位/FIFO复位为唯一原因。保持第二次RX初始化状态最终32MiB全收34953包，
  CRC/逐字节比较通过、S2MM/valid/UDP/PC一致，无新增reject/error/stall。保留此用户新版本运行状态，不再重载旧profile。
- 2026-09-07第八轮用户明确要求把TX独立时钟合并回原工程。当前原 `.xpr/.bd` 已包含
  FCLK3约41.667 MHz、TX DAC/FIFO3写时钟和新 `rst_tx_transport`；RX仍FCLK2=40 MHz。
  第二轮“原工程未改”已成为历史说明，不要再告诉用户原工程没有这项改动。
  仅合并连接和修正ROM路径，不加入第五/六轮仪表，不改SDK C/BSP/ELF或RF参数，不烧录板卡。
  原profile bit/HDF/PS初始化继续保留；从原工程新生成的bit须与新导出HDF/PS初始化匹配并重新回归。
- 原硬件文件位于SDK Git仓库之外；仓库内 `hardware_profiles/sma_20260906/merge_into_project.tcl`
  保存可复现合并步骤，执行前关闭对应Vivado工程，脚本要求全新报告目录并备份源文件。
  三个ROM的源XCI采用 `../name.coe`，XPR中旧AD9361_test2_ofdm重复引用已移除；
  要 `reset_target all` 后重新生成BD，单改源XCI而不刷新生成副本会继续使用旧路径。
  本轮远程有一次SSH返回中断，之后已取回两机完整生成完成日志，不能将首次失败日志作为最终结果。
  本地未安装Vivado，仅做源设计语义对照和36项PC测试；原工程的原生验证在两台2018.3电脑进行。
  两机重新打开验证成功（TX日志stage8-reopen-b，RX日志stage8-reopen），综合/实现NEEDS_REFRESH=1；
  本地/两机BD与第二轮已实测BD语义一致。硬件合并不是重新调参，不保证新布局布线零丢包或时序收敛。
- 2026-09-07 用户明确要求固化63及关联计数门槛。当前默认以本条和第七轮为准：
  `main.c::OPENOFDM_RX_MIN_PLATEAU_RF=63U`，PL原 `min_plateau>>2` 自动派生15，原比较 `>15` 保留，
  不要再恢复64，也不要将15硬编码到RTL；数字回环100/25不变。启动读回失败会报FATAL，
  日志 `sign_min_derived=15` 是软件从reg3计算的值，不是内部计数器实测。只改源码/ELF，不刷Flash/SD。
- 2026-09-06 YunSDR 320 双板 SMA 直连（无外串固定衰减器）实测配置：LO 2.2 GHz、RX MGC 36 dB；发射板 TX 衰减 25 dB，接收板自身 TX 衰减 30 dB 保留。RF 模式的 OFDM reg1=0x101（short-sync 0.75）、reg2=0x00300000（DC 48/RSSI 0）、reg3=64，数字回环保留原检测值。1024 字节短帧显著降低视频 payload CRC 错误并成功解码；重编译下载后 GUI 流程实测 decoded=275、rendered=85、decoder_errors=0，但仍丢失 16/3930 个分片并有 4 次 fragment/frame CRC 错误，不能宣称无损或长帧根因完全修复。768 字节对照没有总体改善，不作为默认。不要再盲目降低衰减；没有实测依据不要改采样率、PL 时序或时钟延迟。
- 用户已授权远程编译、JTAG 下载和链路测试，两台电脑使用 Vivado/SDK 2018.3；变更前备份各自源码和 ELF，保留各自 TX 衰减及无关未提交改动。不要把远程登录凭据写入仓库。新版默认分包改为 1024 后，应重启发送 GUI 或明确修改旧窗口的 Chunk Bytes；Rate Limit 保持用户要求的 400。
- 当前 `NET_AGG_BLOCK_BYTES = 1024`，使默认一个 AIR0/AIRV wire chunk 对应一个 OFDM PSDU，避免 2880 字节长帧一次损坏两个 AIR 包。DDR 中每个 slot 的有效 payload 是 1024 字节，`NET_AGG_BLOCK_STRIDE_BYTES = 1024`，队列深度为 2048；stride 必须保持 cache-line 对齐，避免相邻 DMA slot 共享 cache line。
- 默认 `Chunk Bytes = 1024` 且发送 GUI 默认开启 `AIR0 Packet Header`。开启 AIR0 时，每包 wire payload 仍为 `1024`，其中 `64` 字节是 PC-only AIR0 头，最多 `960` 字节是原始文件/测试 payload。PS/PL 不解析 AIR0。关闭 AIR0 后每包 wire payload 为原始文件/测试 payload。
- AIRV 模式也保持 `Chunk Bytes = 1024`，每包 wire payload 为 `64` 字节 AIRV v2 头、最多 `960` 字节 encoded video fragment 和零填充。v2 在偏移 58 增加全局 `packet_seq`，PS 校验头 CRC 后用 `packet_seq * chunk_bytes` 恢复延迟 RF 帧的 UDP `stream_offset`；必须同时使用新版 ELF 和新版 PC 工具。发送端选择 MP4 时会自动在同目录查找同名 `.h264/.264`；已有 sidecar 时直接复用，不再对 MP4 做耗时 `ffprobe`，日志显示 `fps_source=sidecar_fallback` 并按 30fps 写入 PTS；找不到 sidecar时用最多 2 秒的 `ffprobe` 探测帧率并调用 `ffmpeg` 生成同名 `.h264`。新生成文件固定约每秒一个 IDR、无 B 帧、带 AUD、重复 SPS/PPS；旧 sidecar 的 GOP 不受保证，需要统一恢复上限时删除后重新生成。不要再要求用户手工准备 H.264 裸流。
- AIRV 接收组帧器按递增 `frame_seq` 输出，保留最多 3 帧乱序深度；缺片只丢所属帧并继续释放后续完整帧，坏 fragment/frame CRC 的完整帧仍交给 PyAV，允许局部马赛克。预览解码连续 1～2 次 P 帧异常继续尝试，连续 3 次才重置等待 IDR。不要把单帧缺失改回立即等待 keyframe。
- AIRV 接收日志里的 `fps` 是按 AIRV `pts_us` 估算的源帧率，不是 Python 处理瞬时速度；`latency_ms` 是接收端本帧首片到组齐的最近一次可报告耗时，最终日志会保留上一条非零值以避免 idle finish 后显示 `0.0` 误导，`latency_avg_ms` / `latency_max_ms` 是组帧平均/最大耗时，不是严格端到端空口时延。
- AIRV 预览依赖可选 `av` 和 `Pillow`。接收 GUI 会打开独立 `AIRV Preview` 窗口，默认 `1280x720`；后台线程解码，Tk 主线程约 30fps 刷新。预览输入队列最多缓存 240 个 assembled encoded frame，按 H.264 顺序送入解码器；队列满时才丢弃预览队列并等待下一帧 keyframe。`Preview Input`、`Preview Backlog`、`Preview Drops`、`Decoded`、`Displayed`、`Decoder Errors`、`Waiting Key` 是预览指标，其中 `Displayed` 表示实际渲染到 Tk 预览窗口的帧数；预览丢帧不代表 AIRV 传输丢包。
- PS 侧 `NET_MAX_PAYLOAD_BYTES = 1024`。开启 AIR0 时 `Chunk Bytes` 必须大于 64，且 wire payload 不能超过 1024。
- 当前默认启用 I-cache 和 D-cache。MM2S 发送前必须 flush DMA buffer；S2MM 完成后必须 invalidate。不要把 DMA buffer slot 设成非 cache-line 对齐；旧 3000 字节 slot 的压测曾暴露相邻 slot 共享 cache line 后的偶发回传差异。
- 当前 AD9361/PL 速率契约是 2R2T LVDS `40 MSPS`、DATA_CLK 约 `160 MHz`；当前源码设置 `tx_fb_clock_delay=7`，启动时强制校验寄存器读回 `0x70`。不要只在 SDK 改采样率或 delay 而不同时检查 PL bridge、XDC 和板上读回日志。
- GUI 默认应开启 `Payload CRC32`。64 MiB/window 16 压测曾观察到少量 PC->PS `bad_crc`，开启后坏包会被 PS 拒收并由发送端重传；不开 CRC 时坏包可能进入 PL 并表现为接收端 CRC/内容错误。
- 发送 GUI 的 `RF Strict Match + Retry (max 3)` 仍保留但默认关闭。独立 TX/RX 调度无法在两块板之间把接收帧对应到发射板当前 TX block，也没有反向 RF ACK，因此双板和通用模式测试必须保持该项关闭；合法 AIR0/AIRV 帧按自身头部序号回传，错误由 PC 接收端统计。后续若要恢复跨板 RF 重传，需要另行设计接收板到发射板的反馈协议，不能复用旧的本地 block compare。
- 发送 GUI 的 `Busy Retries`、`Pending Retries`、`Recoverable Errors` 是可恢复重传统计，不是最终文件错误。判断文件是否完整，以发送端 `app_ack == total_size` 和接收端 `rx/high == file_size`、`gaps=0`、`crc=0`、`len=0` 为准。
- OK ACK 默认合并：8 包或 1000 us；非 OK ACK 立即发送。
- 当前已开启 PL->PS S2MM 调试和 UDP 回传，默认 `NET_LOOPBACK_RETURN_SOURCE=NET_LOOPBACK_RETURN_SOURCE_S2MM`：RXCFG 后独立 arm `8192` 字节 S2MM 捕获窗口，完成后扫描前 `2048` 字节 AIR0/AIRV magic，跳过 RX 前缀，并用 AIR0/AIRV v2 全局包序号恢复 `stream_offset` 后回传。RF 静默时 S2MM 可以无限等待，不再使用 50 ms TX watchdog误判；`NET_DMA_STALL_TIMEOUT_US = 50000` 只监控 MM2S。单板存在当前 TX block 时保留 compare 诊断，但 frame validity 不依赖 TX block。
- `S2MM valid` 的 `wait_us` 表示 arm S2MM 到主循环观察到 `RxDone` 的时间，其中包含主循环调度延迟；独立 RX 空口静默不受 MM2S 的 50 ms watchdog 约束。
- 上一轮 `NET_LOOPBACK_RETURN_SOURCE_TX_BUFFER` 诊断已证明 PC 发送、PS 接收/聚合、PS UDP 回传和 PC 接收恢复正常；该模式仅作为以后排查 PC/PS 侧时的临时开关，平时不要保持启用。
- S2MM 收到的帧不一定对应本机当前 MM2S 聚合块；纯接收板没有 TX block 是正常情况。AIR0 和 AIRV v2 都用各自的全局 `packet_seq * chunk_bytes` 推导 UDP 回传 `stream_offset`；紧凑 `S2MM valid` 会报告类型、序号、偏移和长度，无效结构仅进入低频累计 `S2MM RX stat`。
- 为降低 115200 UART 对 PS/lwIP/DMA 主循环的影响，当前默认不再打印前若干任意 S2MM 捕获的详细 dump，也不逐帧打印结构 reject。首 2 个真正通过 AIR0/AIRV 头 CRC 校验的捕获在下一次 S2MM 已 arm 后打印紧凑 `S2MM valid`；无效捕获每 10 秒最多汇总一行 `S2MM RX stat captures/valid/reject/len/no_magic/shift/header/last_seq/seq_gap/seq_back`。无效路径不计算仅供详细诊断使用的近似 magic、payload CRC 和 watchdog dump。DMA/RF 错误与周期 STAT 仍保留，周期 STAT 也必须放在 S2MM 重装之后打印。
- MM2S 启动前必须先 `OpenWifi_Tx_Rearm(payload_len)`，再调用 `net_configure_tx_frame()` 写最终 `tx_intf` 帧长、DMA word 数和 auto-start threshold。不要把 re-arm 放在配置之后；否则某些短帧长度会覆盖并清掉 auto-start enable，表现为 `S2MM wait ... txdone=0 rxdone=0`。

## 2026-09-06 第二轮实验硬件配置

- 当前两台在线板的实验配置来自 `hardware_profiles/sma_20260906/`：独立 FCLK3=41.667 MHz
  驱动 TX DAC 搬运/FIFO3 写端及相应复位，RX FCLK2 保持 40 MHz，AD9361 仍是 40 MSPS / 160 MHz LVDS。
  不要把这解释为修改 AD9361 采样率；不要把 RX FCLK2 也提高，该对照未正常收包。
- 新 bitstream 已用 Vivado 2018.3 全量构建，SHA256 为
  `B6BB2F00CAE94A3C9DC7B11777E5D751C68BF6BA8C3C8A6D4D927003069FCA71`。
  原默认硬件平台和主工程保留，实验配置独立存放；用配套 `download.tcl` 下载本机原 ELF，
  不要混用默认旧 bit / PS 初始化。没有写 flash/SD，也没有改 COMMON.c 或启用 RF 重传。
- 两端新硬件 16+32 MiB 随机源共 52430 包、缺 224（约0.427%）；收到的 50,116,608 字节逐字节正确。
  原时钟 8 MiB 有 6 个坏 payload / 15507 个 bit 错误；新配置缓解了包内错误，但不能宣称
  整包丢失率显著改善、全文件无损或任意时长零误码。核心视频复测 3909/3930 分片、283 组帧、166 解码，CRC/解码异常 0。
  最终配套下载脚本在双板重载后的隐藏 GUI 流程为 3905/3930 分片、284 组帧、212 解码、79 绘制，CRC/解码异常 0；不是原用户窗口的截图。
- 短 I/Q 窗口粗估 SNR 38.02～38.66 dB，不是校准仪表、EVM/SINR 或真实 RSSI；RSSI 输入仍为 0。
  全设计时序仍未收敛，LVDS 约束延时模型、内部 Fc=2400 与实际 LO=2200 的遗留差异仍待处理。
  新时钟内部路径有余量不等于整个设计已通过时序签核。完整记录只维护根 README。
- 额外包间隔、RX 增益30、DC watchdog关闭、重装前后100us等待均未显示改善，不保留。
  `stage2-fastpl-p68-random8m` 的参数写入被脚本拒绝，实际仍为64，不能把该日志当68测试。

## 2026-09-06 第三轮对照与保留基线

- 用户要求继续尝试无损；若没有可靠改善，保留第二轮已认可的 `sma_20260906` 配置。
- 本轮仅做运行时接收 plateau 对照和临时目录的接收软件候选，不改原 COMMON.c、ELF、bit，
  不加 RF 重传、不改变 400 KiB/s、1024 字节、window 1。基线 ELF/源码/文档另存远端
  `%TEMP%/ad9361-diag-20260906/pre-stage3-backup/`。
- 基线 8 MiB 为 8705/8739，TX accepted/DMA done=8739；RX 有效捕获/UDP成功发送/PC收包=8705。
  该次未发现 RX 板成功回传之后再丢包，不能据此断言全部剩余缺包都在 RF 空口。
- plateau=48 严重变差（158/8739）；60、68、72 未显示明确改善。全部候选未采纳，保留64。
  关闭 S2MM 首帧/拒绝汇总日志的 8 MiB 仍缺40包，另将 net_rx.c 以 O2 编译的 16 MiB 仍缺74包；
  收到数据均逐字节正确，但不能当成无损或认定日志/CPU性能是唯一根因。原软件日志及编译方式保留。
- 候选文件、测试日志均为远端临时目录 `stage3-` 前缀，不能用其中 candidate.elf 作为正式下载文件。
  当前正式下载方式仍是 `hardware_profiles/sma_20260906/download.tcl`；完整记录仅在根 README。
- 结束时两端均重新执行正式下载脚本恢复基线，ELF、COMMON.c、net_rx.c、net_config.h 与本轮开始备份一致。
  隐藏 GUI 视频回归 3915/3930 分片、294 组帧、10 缺片丢帧、223 解码、72 绘制，CRC/解码异常0。
  本轮没有正式代码或硬件变更，仅更新测试记录；不要把实验候选留作用户继续测试的运行版本。

## 2026-09-06 第四轮：晶振频偏优先排查

- 用户要求继续定位根因，优先查晶振频偏。本轮完成载波频偏测量/LO 对照，唯一根因尚未闭环；
  不要把“有频偏”说成“频偏就是丢包根因”，也不要把丢包描述成 SMA 双板必然现象。
- 基线 8 段短前导相关估计 CFO 均值约 +1025 Hz（短窗口离散约 778 Hz），仅相当于约0.47 ppm
  的相对载波误差，不是校准晶振测量。RX LO +1 kHz 后估计约 -58 Hz，却缺281/8739包；
  基线两轮分别缺40、42包。改变 LO 没有改变采样频率，尚未直接测量/排除 SFO。
- 关闭 I/Q 正交跟踪的临时候选严重恶化，不保留，不能据此认定跟踪为原丢包原因。
  只提高 RX 搬运时钟虽使该次短 ILA 窗口 ready 恒高，仍缺134/2185包，不保留。
  FIFO ready 为低不等于真正丢 ADC 样本，必须计数 `adc_valid && m_axis_tvalid && !m_axis_tready`。
- reg18=0x1FFFF，不支持“CFO 超 watchdog 门限拒包”；整数相位补偿每步约6.217 kHz，
  读回0不等于真实零频偏。Fc=2400/实际LO2200不一致仍待核验，未证实为剩余缺包根因。
- 本轮没有重新生成 bitstream 或保留任何软件/寄存器候选。接收板已重新执行正式下载脚本恢复
  原 ELF、LO 和 RX FCLK2=40 MHz；发送板保持原稳定配置。最终隐藏 GUI 回归3912/3930分片、
  291组帧、231解码、79绘制，CRC/解码错误0；原视频仍不完整。
- 第四轮完整数据仅维护根 README；临时记录在远端 `%TEMP%/ad9361-diag-20260906/`。
  下一层需要 TX 实际发帧、RX STF/LTF/SIGNAL/FCS 和 ADC 真溢出计数才能进一步划分损失环节；
  本轮没有添加这些计数器，不能称已定位到某个确定 RTL 模块或某块晶振。

## 2026-09-06 第五轮：物理层计数与 ADC 速率差

- 用户要求继续定位根因。本轮已构建并临时上板分级计数硬件，证实原 RX 40 MHz 时
  `adc_valid && m_axis_tvalid && !m_axis_tready` 持续发生；不是只凭 ready 低判断溢出。
  接收板 AD9361 相对本板 PS 搬运时钟快约5.966 ppm，静默窗口输入193201717样本、丢1153，
  与速率差吻合。这是板内相对差，不是两块 AD9361 的 SFO，也不是校准晶振测量。
- 临时硬件原时钟8 MiB：TX PHY started/done=8739，RX LTF/合法头/FCS成功/PC收包=8690，
  缺49；此次主要缺口在成功LTF之前。TX done不等于已测量RF波形完整性；STF可重复触发。
  首轮2 MiB有FCS成功2178而PC2176，不能说所有轮次下游都绝不丢帧。
- RX搬运41.667和100 MHz均使运行窗口ADC丢弃归零，但前者缺135/2185、SIGNAL/FCS错误增加；
  100 MHz仍缺13/2185、40/8739，不保留。ADC溢出是已证实缺陷，不是已闭环的全部丢包唯一根因。
- `sync_long.v::do_mult`存在多周期计算与过早新strobe重入的源码风险，尚未建立失败帧对应关系。
  下一步需失败前导I/Q、STF/LTF超时与相关器重入证据；不要把风险直接当成已定位根因。
- 临时TX 2000us启动间隔保护8 MiB缺42包，对照缺45，实测原最短间隔1863us，无明确改善，已撤回。
- 诊断 bit SHA256 `C83937056497E3D4779AEEAF140CB760A6E5E1FF277B86ED0BB8D9702A425DAF`，
  独立构建在接收电脑 `E:/by2025/AD9361_test_board/ad9361_diag_stage5b_20260906`；
  只读计数器单元仿真通过。原工程/profile没有覆盖，全设计WNS=-6.280/WHS=-1.721ns仍未收敛。
  临时reg17高位快照/银行、reg22～29和TX reg20仅适用于该bit，不能对原bit照搬计数读法。
- 两板已经重新下载原 `sma_20260906` bit和各自原ELF，TX41.667/RX40 MHz，原RF参数保留。
  第五轮只更新README/AGENTS，不推广候选。日志和脚本在远端临时目录stage5前缀，
  原文件备份pre-stage5-backup；完整结果只维护根README。
- 恢复后隐藏GUI回归3908/3930分片、286组帧、190解码、62绘制；CRC/解码错误0，
  最终串口序号缺口22，仍非无损。原ELF、COMMON.c、net_rx.c、推荐bit哈希未改变。

## 2026-09-06 第六轮：短前导符号比例边界

- 用户本轮要求继续排查根因，未要求固化新修复。已抓到三段有效4096点失败前导：STF/LTF波形到达，
  STF相关约0.9998，主状态停在SYNC_SHORT；窗口内ADC丢弃不变、输入间隔全为5个100MHz时钟。
  三段I路正样本比例25%/25%/75%。源码 `sync_short` 的 `pos_count/neg_count > (min_plateau>>2)`
  存在严格四分之一边界，是本轮重点证据；不要再只凭GUI猜增益或直接认定CFO过大。
- 逐字提取原always块的控制单元仿真，以三段实测符号序列和16种起始位置复现边界：64时每种4/16通过，
  63时16/16通过。相关判据固定通过，未回放真实乘法/FIFO/复位历史，不能夸成完整OFDM仿真。
- 仅临时RX reg3切换：诊断ILA bit下64的8MiB缺28，63的8MiB缺0，回64缺25，再63的16MiB缺0。
  两次63共24MiB/26216包，TX PHY、RX LTF/header/FCS/PC增量一致，落盘文件SHA256及逐字节比较通过。
  63使符号计数门槛16→15，不是RF功率或CRC门限变化；也不能把以前60/68的结果当成测试过63。
- 恢复原推荐bit/原ELF后，64的8MiB缺45，临时63的16MiB仍缺2/17477，收到内容正确。
  改善明显但剩余少量异常尚未闭环；这两轮累计S2MM完成/valid/UDP成功/PC均26169，reject/error/stall0，
  缺口47，不能将剩余2包归因于已观察到的PS长度拒绝。完整后续复测以根README为准。
- 新仪表bit仅在临时stage6-hw-c：SHA F57F114114333A3BD4FCB83ED756CE8ACC8D5250F01E5AA5F1F22D42D834CDFD。
  原41探针ILA保留，新增13端口89bit、100MHz4096深度；全局WNS=-9.374/WHS=-1.722ns未收敛，
  新探针输入setup/hold+2.473/+0.172ns，调试配置通道仍-1.911ns，不推广该bit。
- 本轮原40MHz再次测得板内AD9361/PS速率差+5.999ppm，994个真实ADC丢弃；63没有修复ADC接口。
  `do_mult`控制仿真也复现4拍重入丢计算，但正常捕获无冲突，不是这三段STF漏检的直接证据。
- `stage6-c-timeout8mb_timeout_*.csv`是空数据，不能引用成失败波形；后续加入FULL/4096行校验，
  count128正向触发通过。真正三段失败文件是`stage6-c-shortwait8m_shortwait_0/1/2.csv`。
- 本轮仅更新README/AGENTS；原COMMON.c/ELF/profile未改，没有写flash/SD或增加RF重传。
  新63是已测试的诊断候选，不应未经说明改写当前推荐64。临时脚本、波形、日志以stage6前缀保存，
  原文件备份pre-stage6-backup；两端原工程无关改动必须继续保留。
- 原bit的63再测8MiB全文件一致，两轮63共24MiB/26216包缺2；63隐藏GUI视频3930/3930分片、
  304组帧/解码、100绘制，CRC/decoder errors/preview drops0。不要把这说成任意时长无损。
- 最后两板已恢复原推荐bit、原ELF、reg3=64，TX41.667/RX40MHz及reg1/2读回通过，COM均释放，
  原GUI/Vivado/SDK保留。最终64隐藏GUI3920/3930、294组帧、282解码、98绘制，CRC/解码异常0。
  本轮没有固化63；后续明确说明后可固化初始化参数，写reg3本身不需要重生成bitstream。

## 2026-09-07 第七轮：已授权固化63

- 用户已明确要求将63及关联计数门槛固化。当前源码 `main.c` 的RF默认值已是63，
  写reg3后校验读回并打印`sign_min_derived=15`；该15由原PL `min_plateau>>2`自动派生，
  原 `>` 比较器未改。数字回环100/25不变；不要把15硬编码进RTL或恢复第六轮结束时的64。
- 两台电脑各自原SDK工程已编译新版ELF并配合原sma_20260906 bit/PS初始化下载。启动与JTAG读回
  均为reg1/2/3=0x101/0x00300000/63，TX41.667/RX40MHz不变。COMMON.c及各自25/30dB衰减保留。
  新TX ELF SHA764CF8860063D96DB607D64F5EF6DFE86F528CA76D79F50340E1F74F2B7F1C46，
  新RX ELF SHA456100D66D21DF2AC3CF6F3A24E57B74379A3D6FE9717E910302EAB89398B633。
- 原36项PC单元回归通过。本轮仅改初始化和日志，不修改CRC、协议、重传、RTL或采样时钟。
  旧profile manifest是第二轮历史快照，不参与初始化；当前参数看main.c和启动读回。
- 固化不等于长期无损。首轮8MiB发送8739，收到8734，缺5、收到内容错误bit0；SSH会话断开后
  已重连取回完整RESULT/WIRE_CHECK，不能报告此轮零丢包。完整后续数据以根README第七轮为准。
- 随后16MiB收到17475/17477，缺2、错误bit0；两轮共24MiB缺7/26216。保留新63配置，
  不要把收到内容正确解释为缺包已全部解决，也不要为此恢复64或开启RF重传。
- 最终隐藏GUI视频3930/3930分片、304完整组帧和解码、104绘制，CRC/decoder errors/preview drops0。
  本地工作区ELF同步为TX25dB构建，远程各机保留各自25/30dB构建，避免跨机混用ELF。
- 回归后再次读回63及原时钟/检测参数通过，新ELF和保留文件哈希核对通过，串口已释放，
  原GUI/Vivado/SDK保留；板卡最终运行的是新63，不是上一轮的64。
- 原文件备份pre-stage7-p63-backup，日志stage7前缀，位置仍为远端ad9361-diag-20260906临时目录。
  ELF地址可能变化，禁止照用按旧ELF固定地址的stage6_ps_counts.tcl。没有刷Flash/SD，断电后
  仍按原流程下载新版ELF；这次程序默认值已经固化，不再是临时调参、也不再恢复64。

## 当前推荐 GUI 测试设置

```text
Mode                    Test Data
Test Bytes              16384
Chunk Bytes             1024
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
RF Strict Match + Retry unchecked
AIR0 Packet Header      checked
Verbose Packet Events   unchecked
Progress ms             1000

Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

这一组用于小数据量回环确认。AIR0 模式下接收端会从 AIR0 头读取 `file_size`、`total_packets` 和 `file_crc32`，`Raw Expected` 保持 `0`，不要再要求用户预填文件大小。先启动接收 GUI并等待 `RX target registered ...`，再启动发送 GUI。预期接收板串口出现 `RXCFG loopback peer` 和 `S2MM valid ... type=AIR0`，接收 GUI `DONE` 行中 `rx=16384` 且 `crc=0 len=0 gaps=0`。

双板独立调度验证使用同样的 `Test Bytes=16384`、`Chunk Bytes=1024`、`Window Size=1`，`Rate Limit KiB/s=400`，且必须关闭 `RF Strict Match + Retry`。发射板只运行发送 GUI，预期 reset 日志 `tx_mode=independent rx_registered=0`，不应因未连接本地 RX 出现逐块 DMA stall/RF drop。接收板先确认 `RXCFG ... rx_mode=independent`，合法帧看 `S2MM valid`，噪声伪帧看低频 `S2MM RX stat`。后续对照实验可临时降速，但不要把降到 50 当作已验证修复。

## 当前推荐 AIRV GUI 测试设置

```text
Sender Transfer Mode    airv_video
Sender Mode             File
Sender file             MP4 video or H.264 Annex-B elementary stream
Chunk Bytes             1024
Window Size             1
ACK Timeout(s)          2.0
Max Retries             200
Rate Limit KiB/s        400
Throughput Mode         checked
Payload CRC32           checked
RF Strict Match + Retry unchecked

Receiver Raw Expected   0
Receiver Idle Finish(s) 10
```

AIRV 用于验证实时组帧、实时预览和统计，不保存精确恢复文件。预期接收 GUI 出现独立 `AIRV Preview` 窗口，`Preview Input`、`Decoded`、`Displayed` 持续增长；日志中 `VIDEO ... frame_drop=0 frag_missing=0 bad_hdr=0 bad_meta=0`，结束时出现 `DONE VIDEO ...`。

## 常用验证命令

```bash
rtk git status --short
rtk git diff -- README.md AGENTS.md
rtk rg --files -g "*README*" -g "*readme*"
rtk grep "NET_AGG_BLOCK_BYTES|NET_MAX_PAYLOAD_BYTES|DATA_FLAG|AIR0" AD9361_test2/src AD9361_test2/tools/pc_sender
```

本环境通常没有 Xilinx SDK 命令行工具，因此无法在普通 shell 中完整构建 SDK 工程。若任务涉及 C 代码行为，至少做静态核对；真正构建和板级验证需要在 Xilinx SDK 2018.3 与目标板上完成。
