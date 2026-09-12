# Incremental, isolated testbench compile; never accesses either board.
$ErrorActionPreference='Stop'
$d=Join-Path $env:TEMP 'ad9361-diag-20260906'
$v='D:\Xilinx\Vivado\2018.3\bin'
$env:PATH="$v;"+$env:PATH
Set-Location 'E:\by2025\AD9361_test_board\stage17-rx-sim\project\stage17_rx.sim\sim_1\behav\xsim'
# Reproduce the unrotated C fixture, not the last channel sweep's temporary input.
$waveSource='E:\by2025\AD9361_test_board\stage17-tx-sim-c\stage17_tx.sim\sim_1\behav\xsim'
foreach($level in 0..4){Copy-Item -LiteralPath "$waveSource\wave$level.mem" -Destination "wave$level.mem" -Force}
& "$v\xvlog.bat" --incr --relax -prj rx_tb_vlog.prj -log xvlog.log
if($LASTEXITCODE -ne 0){throw 'RX Verilog compile failed'}
& '.\elaborate.bat'
if($LASTEXITCODE -ne 0){throw 'RX elaboration failed'}
& "$v\xsim.bat" rx_tb_behav -R -testplusarg '"channel_shift=0"' -testplusarg '"max_level=0"' -log simulate_trace.log
# XSim can return 0 after $fatal: require the positive marker as well.
if($LASTEXITCODE -ne 0 -or !(Select-String -LiteralPath 'simulate_trace.log' -Pattern 'STAGE17_RX_SIM_COMPLETE' -Quiet)){throw 'RX functional check failed; inspect simulate_trace.log'}
