param([Parameter(Mandatory=$true)][string]$Candidate,
      [Parameter(Mandatory=$true)][string]$Out)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Out){throw 'Preserve existing simulation'}
$src=Join-Path $Candidate 'ip_repo/openofdm_rx/src'
if(!(Select-String -LiteralPath (Join-Path $src 'openofdm_rx_s_axi.v') -Pattern 'a7220001' -Quiet)){throw 'Not SNR candidate'}
New-Item -ItemType Directory -Path $Out | Out-Null
Push-Location -LiteralPath $Out
try {
    $bin=if(Test-Path -LiteralPath 'D:\Xilinx\Vivado\2018.3\bin'){'D:\Xilinx\Vivado\2018.3\bin'}else{'D:\vivado2018\Vivado\2018.3\bin'}
    & "$bin\xvlog.bat" (Join-Path $src 'openofdm_rx_s_axi.v') (Join-Path $src 'payload_snr_monitor.v') (Join-Path $PSScriptRoot 'axi_tb.v')
    if($LASTEXITCODE){throw 'xvlog failed'}
    & "$bin\xelab.bat" axi_tb -s snr_axi
    if($LASTEXITCODE){throw 'xelab failed'}
    & "$bin\xsim.bat" snr_axi -runall -log snr_axi.log
    if($LASTEXITCODE){throw 'xsim failed'}
    if(!(Select-String -LiteralPath snr_axi.log -Pattern '^SNR_AXI_SIM_COMPLETE' -Quiet)){throw 'No AXI completion proof'}
} finally {Pop-Location}
