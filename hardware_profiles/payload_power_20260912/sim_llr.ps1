$ErrorActionPreference='Stop'
$d=Join-Path $env:TEMP 'ad9361-diag-20260906'
$s='E:\by2025\AD9361_test_board\ad9361_stage17_power_d_20260912\ip_repo\openofdm_rx\src'
$out=Join-Path $d 'stage17-llr-sim'
if(!(Test-Path -LiteralPath $out)){New-Item -ItemType Directory -Path $out | Out-Null}
Set-Location -LiteralPath $out
$v='D:\Xilinx\Vivado\2018.3\bin'
& "$v\xvlog.bat" --sv --work xil_defaultlib -i $s "$s\demodulate.v" "$d\stage17-tools\llr_tb.v"
if($LASTEXITCODE -ne 0){throw 'LLR compile failed'}
& "$v\xelab.bat" --relax --mt 2 --debug typical --snapshot llr_test xil_defaultlib.llr_tb
if($LASTEXITCODE -ne 0){throw 'LLR elaborate failed'}
& "$v\xsim.bat" llr_test -R -log llr_simulate.log
if($LASTEXITCODE -ne 0 -or !(Select-String -LiteralPath llr_simulate.log -Pattern STAGE17_LLR_UNIT_COMPLETE -Quiet)){throw 'LLR unit simulation failed'}
