$ErrorActionPreference='Stop'
$d=Join-Path $env:TEMP 'ad9361-diag-20260906'
$p='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk\hardware_profiles\header_power_20260913'
$v='D:\Xilinx\Vivado\2018.3\bin'
$out='E:\by2025\AD9361_test_board\stage20-unit-sim-b'
$s='E:\by2025\AD9361_test_board\ad9361_stage20_header_b_20260913\ip_repo\openofdm_rx\src'
& "$v\vivado.bat" -mode batch -notrace -nojournal -log "$d\stage20-sim-b.log" -source "$p\sim.tcl"
if($LASTEXITCODE -or !(Select-String -LiteralPath "$d\stage20-sim-b.log" -Pattern STAGE20_SIM_FIXTURES_READY -Quiet)){throw 'Simulation fixture/TX run failed'}
if(!(Select-String -LiteralPath "$d\stage20-sim-b.log" -Pattern STAGE20_TX_SIM_COMPLETE -Quiet)){throw 'TX completion missing'}
& 'C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe' "$p\check_tx.py" "$out\tx\stage20_tx.sim\sim_1\behav\xsim"
if($LASTEXITCODE){throw 'Independent TX numeric check failed'}
Set-Location -LiteralPath $out
& "$v\xvlog.bat" --sv --work xil_defaultlib -i $s "$s\demodulate.v" llr_tb.v restore_tb.v
if($LASTEXITCODE){throw 'Unit compile failed'}
foreach($name in @('llr','restore')){
    & "$v\xelab.bat" --relax --mt 2 --debug typical --snapshot "stage20_$name" "xil_defaultlib.${name}_tb"
    if($LASTEXITCODE){throw 'Unit elaborate failed'}
    & "$v\xsim.bat" "stage20_$name" -R -log "$name.log"
    if($LASTEXITCODE -or !(Select-String -LiteralPath "$name.log" -Pattern "STAGE20_$($name.ToUpper())_UNIT_COMPLETE" -Quiet)){throw "Unit failed $name"}
}
'STAGE20_UNITS_COMPLETE'
