param([Parameter(Mandatory=$true)][string]$Out)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Out){throw 'Preserve existing regression results'}
New-Item -ItemType Directory -Path $Out | Out-Null
$project=Split-Path (Split-Path (Split-Path $PSScriptRoot))
& (Join-Path $PSScriptRoot 'sim_gate.ps1') -Source (Join-Path $project 'ip_repo/openofdm_rx/src/dot11.v') -Out (Join-Path $Out 'gate')
& (Join-Path $PSScriptRoot 'sim.ps1') -Out (Join-Path $Out 'monitor')
& (Join-Path $PSScriptRoot 'sim_axi.ps1') -Candidate $project -Out (Join-Path $Out 'axi')
$python=if($env:USERNAME -ieq 'WithBreeze'){'C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe'}else{'D:\PYTHON\python.exe'}
$pc=Join-Path $project 'AD9361_test2.sdk/AD9361_test2/tools/pc_sender'
& $python -m unittest discover -s $pc -p 'test_*.py'
if($LASTEXITCODE){throw 'PC regression failed'}
'SNR_GATE_REGRESSIONS_COMPLETE'
