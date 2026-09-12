# Keep the diagnostic server's SSH parent alive; never restart a USB device.
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
if(Get-NetTCPConnection -State Listen -LocalPort 3121 -ErrorAction SilentlyContinue){
    throw 'Port 3121 already has a listener; inspect its owner instead of replacing it'
}
if($env:USERNAME -ieq 'WithBreeze'){
    $server='D:\Xilinx\SDK\2018.3\bin\unwrapped\win64.o\hw_server.exe'
}else{
    $server='D:\vivado2018\SDK\2018.3\bin\unwrapped\win64.o\hw_server.exe'
}
$tag='stage17-hw-server-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$proc=Start-Process -FilePath $server -ArgumentList @('-s','tcp:127.0.0.1:3121') -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\$tag.stdout" -RedirectStandardError "$diag\$tag.stderr"
try {
    "STAGE17_OWN_HW_SERVER_PID=$($proc.Id) LOG=$diag\$tag.stdout MAX_SECONDS=600"
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while(!$proc.HasExited -and $timer.Elapsed.TotalSeconds -lt 600){Start-Sleep -Seconds 1; $proc.Refresh()}
} finally {
    $proc.Refresh()
    if(!$proc.HasExited){$proc.Kill(); $proc.WaitForExit()}
    'STAGE17_OWN_HW_SERVER_CLOSED'
}
