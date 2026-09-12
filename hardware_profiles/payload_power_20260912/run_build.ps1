$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$tools=Join-Path $diag 'stage17-tools'
Set-Location -LiteralPath $tools
& 'D:\Xilinx\Vivado\2018.3\bin\vivado.bat' -mode batch -notrace -nojournal -log "$diag\stage17-build-d.log" -source "$tools\build.tcl" -tclargs 'E:/by2025/AD9361_test_board/AD9361_test2' 'E:/by2025/AD9361_test_board/ad9361_stage17_power_d_20260912' 'D:/Program Files/Git/cmd/git.exe'
exit $LASTEXITCODE
