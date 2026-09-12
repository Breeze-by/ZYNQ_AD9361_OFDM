param([Parameter(Mandatory=$true)][ValidateSet('candidate','restore')][string]$Mode,[Parameter(Mandatory=$true)][string]$Tag)
$ErrorActionPreference='Stop'
$repo='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
if($Tag -notmatch '^stage20-[a-z0-9-]+$'){throw 'Invalid tag'}
if(Get-Process -Name eclipse -ErrorAction SilentlyContinue){throw 'User SDK still running'}
if($env:USERNAME -ieq 'WithBreeze'){$role='receiver';$port='COM3';$sdk='D:\Xilinx\SDK\2018.3'}else{$role='sender';$port='COM4';$sdk='D:\vivado2018\SDK\2018.3'}
if(Test-Path -LiteralPath "$diag\$Tag-boot.log"){throw 'Preserve previous boot log'}
$serial=[IO.Ports.SerialPort]::new($port,115200)
$serial.DtrEnable=$false;$serial.RtsEnable=$false
$writer=$null;$process=$null
try {
    $serial.Open()
    $writer=[IO.StreamWriter]::new("$diag\$Tag-boot.log",$false,[Text.Encoding]::UTF8)
    $process=Start-Process -FilePath "$sdk\bin\xsct.bat" -ArgumentList @("$repo\hardware_profiles\header_power_20260913\load.tcl",$role,$Mode) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\$Tag-load.log" -RedirectStandardError "$diag\$Tag-load.stderr"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$process.HasExited -and $timer.Elapsed.TotalSeconds -lt 150){
        $writer.Write($serial.ReadExisting());$writer.Flush()
        Start-Sleep -Milliseconds 50
        $process.Refresh()
    }
    if(!$process.HasExited){throw 'Download timeout; inspect running command and board'}
    $writer.Write($serial.ReadExisting());$writer.Flush()
    if($process.ExitCode){throw "XSCT exited $($process.ExitCode)"}
} finally {
    if($serial.IsOpen){$serial.Close()};$serial.Dispose()
    if($writer){$writer.Dispose()}
}
if(!(Select-String -LiteralPath "$diag\$Tag-load.log" -Pattern '^STAGE20_LOAD_OK ' -Quiet)){throw 'Missing readback marker'}
if(Select-String -LiteralPath "$diag\$Tag-boot.log" -Pattern 'FATAL:' -Quiet){throw 'Boot FATAL'}
if(!(Select-String -LiteralPath "$diag\$Tag-boot.log" -Pattern 'OFDM payload-power enabled=1 guard_data_symbols=32 amplitude_shift=4' -Quiet)){throw 'Missing boot configuration'}
Get-Content -LiteralPath "$diag\$Tag-load.log" | Select-String 'STAGE20_' | ForEach-Object Line
Get-Content -LiteralPath "$diag\$Tag-boot.log" | Select-String 'profile|contract|atten|gain|payload-power|RX source|sample|ERROR|FATAL' | ForEach-Object Line
'STAGE20_LOAD_AND_BOOT_VERIFIED'
