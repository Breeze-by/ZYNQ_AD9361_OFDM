# Keep the SSH channel running this script open; Windows OpenSSH may terminate
# detached children when a short-lived parent channel exits.
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$release=Join-Path $diag 'stage19-release-server'
if(Test-Path -LiteralPath $release){throw 'Existing release marker; preserve this run'}
if(Get-NetTCPConnection -State Listen -LocalPort 3121 -ErrorAction SilentlyContinue){throw 'JTAG port occupied'}
if($env:USERNAME -ieq 'WithBreeze'){$sdk='D:\Xilinx\SDK\2018.3'}else{$sdk='D:\vivado2018\SDK\2018.3'}
$proc=Start-Process -FilePath "$sdk\bin\unwrapped\win64.o\hw_server.exe" -ArgumentList @('-s','tcp:127.0.0.1:3121') -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\stage19-server.stdout" -RedirectStandardError "$diag\stage19-server.stderr"
try {
    "STAGE19_OWN_SERVER_PID=$($proc.Id)"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$proc.HasExited -and $timer.Elapsed.TotalSeconds -lt 7200 -and !(Test-Path -LiteralPath $release)){
        Start-Sleep -Seconds 1
        $proc.Refresh()
    }
}finally{
    $proc.Refresh()
    if(!$proc.HasExited){$proc.Kill();$proc.WaitForExit()}
    'STAGE19_OWN_SERVER_CLOSED'
}
