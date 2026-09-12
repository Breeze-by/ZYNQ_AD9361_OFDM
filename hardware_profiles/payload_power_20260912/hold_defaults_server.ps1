# Starts only our own loopback JTAG server; never kills a user-owned server.
# Signal completion by creating stage18-release-server in the diagnostics dir.
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$release=Join-Path $diag 'stage18-release-server'
if(Test-Path -LiteralPath $release){throw 'Release marker already exists'}
if(Get-NetTCPConnection -State Listen -LocalPort 3121 -ErrorAction SilentlyContinue){throw '3121 already occupied; inspect owner'}
if($env:USERNAME -ieq 'WithBreeze'){$sdk='D:\Xilinx\SDK\2018.3'}else{$sdk='D:\vivado2018\SDK\2018.3'}
$tag='stage18-server-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$proc=Start-Process -FilePath "$sdk\bin\unwrapped\win64.o\hw_server.exe" -ArgumentList @('-s','tcp:127.0.0.1:3121') -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\$tag.stdout" -RedirectStandardError "$diag\$tag.stderr"
try {
    "STAGE18_OWN_SERVER_PID=$($proc.Id)"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$proc.HasExited -and $timer.Elapsed.TotalSeconds -lt 1200 -and !(Test-Path -LiteralPath $release)){
        Start-Sleep -Seconds 1
        $proc.Refresh()
    }
} finally {
    $proc.Refresh()
    if(!$proc.HasExited){$proc.Kill();$proc.WaitForExit()}
    'STAGE18_OWN_SERVER_CLOSED'
}
