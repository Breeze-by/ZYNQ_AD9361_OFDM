$ErrorActionPreference='Stop'
$d=Join-Path $env:TEMP 'ad9361-diag-20260906'
Set-Location -LiteralPath "$d\stage17-tools"
$vivado='D:\Xilinx\Vivado\2018.3\bin\vivado.bat'
& $vivado -mode batch -notrace -nojournal -log "$d\stage17-sim-tx-c.log" -source sim_tx.tcl
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& 'C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe' check_tx.py 'E:\by2025\AD9361_test_board\stage17-tx-sim-c\stage17_tx.sim\sim_1\behav\xsim'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& $vivado -mode batch -notrace -nojournal -log "$d\stage17-sim-rx-c.log" -source sim_rx.tcl
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
if(!(Select-String -LiteralPath "$d\stage17-sim-rx-c.log" -SimpleMatch STAGE17_RX_SIM_COMPLETE -Quiet)){
    throw 'XSim can return exit 0 after $fatal; positive completion marker is required'
}
'STAGE17_CHAIN_VERIFIED'
