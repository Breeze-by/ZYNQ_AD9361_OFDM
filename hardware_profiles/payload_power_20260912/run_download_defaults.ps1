$ErrorActionPreference='Stop'
$repo='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
if(Get-Process -Name eclipse -ErrorAction SilentlyContinue){throw 'SDK debugger must be closed'}
if($env:USERNAME -ieq 'WithBreeze'){$role='receiver';$port='COM3';$sdk='D:\Xilinx\SDK\2018.3'}else{$role='sender';$port='COM4';$sdk='D:\vivado2018\SDK\2018.3'}
if(Test-Path -LiteralPath "$diag\stage18-boot-serial.log"){throw 'Preserve previous boot log before retry'}
$serial=New-Object System.IO.Ports.SerialPort($port,115200)
$serial.DtrEnable=$false;$serial.RtsEnable=$false
$writer=$null;$process=$null
try {
    $serial.Open()
    $writer=New-Object System.IO.StreamWriter("$diag\stage18-boot-serial.log",$false,[Text.Encoding]::UTF8)
    $process=Start-Process -FilePath "$sdk\bin\xsct.bat" -ArgumentList @("`"$repo\hardware_profiles\payload_power_20260912\download_defaults.tcl`"",$role) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\stage18-download.log" -RedirectStandardError "$diag\stage18-download.stderr"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$process.HasExited -and $timer.Elapsed.TotalSeconds -lt 150){
        $writer.Write($serial.ReadExisting());$writer.Flush()
        Start-Sleep -Milliseconds 50
        $process.Refresh()
    }
    if(!$process.HasExited){throw 'Download timeout; inspect stage log and board state'}
    $writer.Write($serial.ReadExisting());$writer.Flush()
    if($process.ExitCode){throw "XSCT exited $($process.ExitCode)"}
} finally {
    if($serial.IsOpen){$serial.Close()};$serial.Dispose()
    if($writer){$writer.Dispose()}
}
if(!(Select-String -LiteralPath "$diag\stage18-download.log" -Pattern '^STAGE18_LOADED ' -Quiet)){throw 'Missing successful readback marker'}
if(Select-String -LiteralPath "$diag\stage18-boot-serial.log" -Pattern 'FATAL:' -Quiet){throw 'Boot reported FATAL'}
if(!(Select-String -LiteralPath "$diag\stage18-boot-serial.log" -Pattern 'OFDM payload-power enabled=1 guard_data_symbols=32 amplitude_shift=4' -Quiet)){throw 'Boot configuration log missing'}
Get-Content -LiteralPath "$diag\stage18-download.log" | Select-String 'STAGE18_' | ForEach-Object Line
Get-Content -LiteralPath "$diag\stage18-boot-serial.log" | Select-String 'profile|contract|atten|gain|payload-power|RX source|sample|ERROR|FATAL' | ForEach-Object Line
'STAGE18_DOWNLOAD_AND_BOOT_VERIFIED'
