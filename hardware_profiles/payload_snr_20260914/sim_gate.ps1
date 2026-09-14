param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Out,
      [switch]$ExpectOldFailure)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Out){throw 'Preserve existing gate simulation'}
$sourceText=Get-Content -LiteralPath $Source -Raw -Encoding UTF8
$a=$sourceText.IndexOf('wire snr_raw_strobe;')
$b=$sourceText.IndexOf('sync_long sync_long_inst (',$a)
if($a -lt 0 -or $b -le $a){throw 'Missing real dot11 SNR block'}
$wrapper=@'
`timescale 1ns/1ps
module snr_gate_under_test(input clock, reset, sync_long_reset,
    long_preamble_detected, sync_long_enable, fcs_out_strobe,
    pkt_header_valid, pkt_header_valid_strobe, pkt_ht,
    input [7:0] pkt_rate, input phy_len_valid, input [14:0] n_ofdm_sym,
    input raw_valid, input [15:0] raw_symbol,
    input [31:0] payload_power_config, output snr_payload_strobe);
'@
$wrapper+="`n"+$sourceText.Substring($a,$b-$a)
$wrapper+="`nassign snr_raw_strobe=raw_valid;`nassign snr_raw_symbol=raw_symbol;`nendmodule`n"
New-Item -ItemType Directory -Path $Out | Out-Null
[IO.File]::WriteAllText((Join-Path $Out 'actual_gate.v'),$wrapper,[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath $Source -Destination (Join-Path $Out 'tested_dot11.v')
$bin=if(Test-Path 'D:\Xilinx\Vivado\2018.3\bin'){'D:\Xilinx\Vivado\2018.3\bin'}else{'D:\vivado2018\Vivado\2018.3\bin'}
Push-Location -LiteralPath $Out
try {
    & "$bin\xvlog.bat" actual_gate.v (Join-Path $PSScriptRoot 'payload_snr_monitor.v') (Join-Path $PSScriptRoot 'gate_tb.v')
    if($LASTEXITCODE){throw 'Gate xvlog failed'}
    & "$bin\xelab.bat" gate_tb -s snr_gate
    if($LASTEXITCODE){throw 'Gate xelab failed'}
    & "$bin\xsim.bat" snr_gate -runall -log gate.log
    $pass=Select-String -LiteralPath gate.log -Pattern '^SNR_GATE_SIM_COMPLETE' -Quiet
    $oldFail=Select-String -LiteralPath gate.log -Pattern 'HEADER_PULSE_REGRESSION' -Quiet
    if($ExpectOldFailure){
        if($pass -or !$oldFail){throw 'Old gate did not reproduce the specific regression'}
        'SNR_OLD_GATE_FAILURE_REPRODUCED'
    } elseif(!$pass -or $oldFail -or $LASTEXITCODE){throw 'Fixed gate regression failed'}
} finally {Pop-Location}
