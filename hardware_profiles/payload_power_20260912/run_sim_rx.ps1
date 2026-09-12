$ErrorActionPreference='Stop'
$d=Join-Path $env:TEMP 'ad9361-diag-20260906'
Set-Location -LiteralPath "$d\stage17-tools"
& 'D:\Xilinx\Vivado\2018.3\bin\vivado.bat' -mode batch -notrace -nojournal -log "$d\stage17-sim-rx.log" -source sim_rx.tcl
exit $LASTEXITCODE
