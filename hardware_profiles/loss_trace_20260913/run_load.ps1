param([Parameter(Mandatory=$true)][ValidateSet('observe','quiet','restore')][string]$Mode,[Parameter(Mandatory=$true)][string]$Tag)
$ErrorActionPreference='Stop'
if($env:USERNAME -ine 'WithBreeze'){throw 'Receiver only'}
$profile='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk\hardware_profiles\loss_trace_20260913'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
if($Tag -notmatch '^stage21-[a-z0-9-]+$'){throw 'Invalid tag'}
if(Get-Process -Name eclipse -ErrorAction SilentlyContinue){throw 'User SDK still running'}
if(Test-Path -LiteralPath "$diag\$Tag-boot.log"){throw 'Preserve boot log'}
$serial=[IO.Ports.SerialPort]::new('COM3',115200)
$serial.DtrEnable=$false;$serial.RtsEnable=$false
$writer=$null
try {
    $serial.Open()
    $writer=[IO.StreamWriter]::new("$diag\$Tag-boot.log",$false,[Text.Encoding]::UTF8)
    $proc=Start-Process -FilePath 'D:\Xilinx\SDK\2018.3\bin\xsct.bat' -ArgumentList @("$profile\load_observer.tcl",$Mode) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\$Tag-load.log" -RedirectStandardError "$diag\$Tag-load.stderr"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$proc.HasExited -and $timer.Elapsed.TotalSeconds -lt 150){
        $writer.Write($serial.ReadExisting());$writer.Flush()
        Start-Sleep -Milliseconds 50
        $proc.Refresh()
    }
    if(!$proc.HasExited){throw 'Download timeout; inspect own process'}
    $writer.Write($serial.ReadExisting());$writer.Flush()
    if($proc.ExitCode){throw "XSCT exited $($proc.ExitCode)"}
} finally {
    if($serial.IsOpen){$serial.Close()};$serial.Dispose()
    if($writer){$writer.Dispose()}
}
if(!(Select-String -LiteralPath "$diag\$Tag-load.log" -Pattern '^STAGE21_LOAD_OK ' -Quiet)){throw 'No readback proof'}
if(Select-String -LiteralPath "$diag\$Tag-boot.log" -Pattern 'FATAL:' -Quiet){throw 'Boot FATAL'}
if(!(Select-String -LiteralPath "$diag\$Tag-boot.log" -Pattern 'OFDM payload-power enabled=1 guard_data_symbols=32 amplitude_shift=4' -Quiet)){throw 'Missing boot configuration'}
Get-Content -LiteralPath "$diag\$Tag-load.log" | Select-String 'STAGE21_' | ForEach-Object Line
Get-Content -LiteralPath "$diag\$Tag-boot.log" | Select-String 'profile|contract|atten|gain|payload-power|RX source|ERROR|FATAL' | ForEach-Object Line
'STAGE21_LOAD_AND_BOOT_VERIFIED'
