# Keep only this experiment's hw_server alive through a held SSH channel.
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$release=Join-Path $diag 'stage21-release-server'
if(Test-Path -LiteralPath $release){throw 'Preserve prior release marker'}
if(Get-NetTCPConnection -State Listen -LocalPort 3121 -ErrorAction SilentlyContinue){throw 'JTAG port already occupied'}
if($env:USERNAME -ieq 'WithBreeze'){$sdk='D:\Xilinx\SDK\2018.3'}else{$sdk='D:\vivado2018\SDK\2018.3'}
$proc=Start-Process -FilePath "$sdk\bin\unwrapped\win64.o\hw_server.exe" -ArgumentList @('-s','tcp:127.0.0.1:3121') -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\stage21-server.stdout" -RedirectStandardError "$diag\stage21-server.stderr"
try {
    "STAGE21_OWN_SERVER_PID=$($proc.Id)"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$proc.HasExited -and $timer.Elapsed.TotalSeconds -lt 7200 -and !(Test-Path -LiteralPath $release)){
        Start-Sleep -Seconds 1
        $proc.Refresh()
    }
}finally{
    $proc.Refresh()
    if(!$proc.HasExited){$proc.Kill();$proc.WaitForExit()}
    'STAGE21_OWN_SERVER_CLOSED'
}
