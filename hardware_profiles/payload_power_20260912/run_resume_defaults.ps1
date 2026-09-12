$ErrorActionPreference='Stop'
$p='E:\by2025\AD9361_test_board\AD9361_test2'
$d=Join-Path $env:TEMP 'ad9361-diag-20260906'
if($env:USERNAME -ieq 'WithBreeze'){$v='D:\Xilinx\Vivado\2018.3'}else{$v='D:\vivado2018\Vivado\2018.3'}
if(Get-Process -Name vivado,eclipse -ErrorAction SilentlyContinue){throw 'Do not overlap Vivado/SDK processes'}
Copy-Item -LiteralPath "$d\stage18-build.log" -Destination "$d\stage18-build-first-failed.log"
Set-Location -LiteralPath $d
$process=Start-Process -FilePath "$v\bin\vivado.bat" -ArgumentList @('-mode','batch','-notrace','-nojournal','-log',"`"$d\stage18-build.log`"",'-source',"`"$p\AD9361_test2.sdk\hardware_profiles\payload_power_20260912\resume_defaults.tcl`"",'-tclargs',"`"$p`"","`"$d\stage18-original-build`"") -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$d\stage18-retry.stdout" -RedirectStandardError "$d\stage18-retry.stderr"
if($process.ExitCode){throw "Vivado retry failed: $($process.ExitCode)"}
if(!(Select-String -LiteralPath "$d\stage18-build.log" -Pattern '^STAGE18_BUILD_COMPLETE ' -Quiet)){throw 'Missing build marker'}
'STAGE18_RETRY_BUILD_VERIFIED'
