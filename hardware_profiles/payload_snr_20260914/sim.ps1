param([Parameter(Mandatory=$true)][string]$Out)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Out){throw 'Preserve existing simulation'}
New-Item -ItemType Directory -Path $Out | Out-Null
Push-Location -LiteralPath $Out
try {
    $bin=if(Test-Path -LiteralPath 'D:\Xilinx\Vivado\2018.3\bin'){'D:\Xilinx\Vivado\2018.3\bin'}else{'D:\vivado2018\Vivado\2018.3\bin'}
    & "$bin\xvlog.bat" (Join-Path $PSScriptRoot 'payload_snr_monitor.v') (Join-Path $PSScriptRoot 'monitor_tb.v')
    if($LASTEXITCODE){throw 'xvlog failed'}
    & "$bin\xelab.bat" monitor_tb -s snr_unit
    if($LASTEXITCODE){throw 'xelab failed'}
    & "$bin\xsim.bat" snr_unit -runall -log snr_sim.log
    if($LASTEXITCODE){throw 'xsim failed'}
    if(!(Select-String -LiteralPath snr_sim.log -Pattern '^SNR_MONITOR_SIM_COMPLETE' -Quiet)){throw 'No simulation completion proof'}
} finally {Pop-Location}
