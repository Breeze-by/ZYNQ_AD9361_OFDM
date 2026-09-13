# Run only after RF tests have stopped. Never reset boards or write user artifacts.
$ErrorActionPreference='Stop'
$project='E:\by2025\AD9361_test_board\AD9361_test2'
$repo=Join-Path $project 'AD9361_test2.sdk'
$backup=Join-Path $env:TEMP 'ad9361-diag-20260906\stage21-before-trace'
$pairs=@{
    'COMMON.c'="$repo\AD9361_test2\src\utils\COMMON.c"
    'main.c'="$repo\AD9361_test2\src\app\main.c"
    'app_config.h'="$repo\AD9361_test2\src\app\app_config.h"
    'AD9361_test2.elf'="$repo\AD9361_test2\Debug\AD9361_test2.elf"
    'System_wrapper.bit'="$project\AD9361_test2.runs\impl_1\System_wrapper.bit"
    'System_wrapper.ltx'="$project\AD9361_test2.runs\impl_1\System_wrapper.ltx"
    'system.hdf'="$repo\System_wrapper_hw_platform_0\system.hdf"
}
foreach($name in $pairs.Keys){
    $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $pairs[$name]).Hash
    $saved=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backup $name)).Hash
    if($actual -ne $saved){throw "Original artifact differs from backup: $name"}
    "STAGE21_HASH_OK $name $actual"
}
if($env:USERNAME -ieq 'WithBreeze'){$port='COM3';$board='192.168.1.50'}else{$port='COM4';$board='192.168.2.50'}
$serial=[IO.Ports.SerialPort]::new($port,115200)
$serial.DtrEnable=$false;$serial.RtsEnable=$false
try {$serial.Open();"STAGE21_SERIAL_FREE $port"}finally{if($serial.IsOpen){$serial.Close()};$serial.Dispose()}
& ping.exe -n 1 -w 1500 $board
if($LASTEXITCODE){throw "Board ping failed: $board"}
'STAGE21_ORIGINAL_ARTIFACTS_PORT_NETWORK_OK'
