$ErrorActionPreference='Stop'
$project='E:\by2025\AD9361_test_board\AD9361_test2'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$profile=Join-Path $project 'AD9361_test2.sdk\hardware_profiles\payload_power_20260912'
$backup=Join-Path $diag 'stage18-before-defaults'
$reports=Join-Path $diag 'stage18-original-build'
if(Get-Process -Name vivado,eclipse -ErrorAction SilentlyContinue){throw 'Save and close Vivado/SDK before merging'}
$records=Get-Content -LiteralPath "$backup\hashes.json" -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($record in $records){
    if((Get-FileHash -LiteralPath $record.Path -Algorithm SHA256).Hash -ne $record.Hash){throw "Changed since backup: $($record.Path)"}
}
if($env:USERNAME -ieq 'WithBreeze'){$vivado='D:\Xilinx\Vivado\2018.3';$git='D:/Program Files/Git/cmd/git.exe'}else{$vivado='D:\vivado2018\Vivado\2018.3';$git='D:/Git/cmd/git.exe'}
Set-Location -LiteralPath $diag
'STAGE18_BUILD_START'
# Kept inside a live SSH session; no orphan background process or visible window.
$process=Start-Process -FilePath "$vivado\bin\vivado.bat" -ArgumentList @('-mode','batch','-notrace','-nojournal','-log',"`"$diag\stage18-build.log`"",'-source',"`"$profile\merge_defaults.tcl`"",'-tclargs',"`"$project`"","`"$backup`"","`"$reports`"","`"$git`"") -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$diag\stage18-build.stdout" -RedirectStandardError "$diag\stage18-build.stderr"
if($process.ExitCode){throw "Vivado failed: $($process.ExitCode)"}
if(!(Select-String -LiteralPath "$diag\stage18-build.log" -Pattern '^STAGE18_BUILD_COMPLETE ' -Quiet)){throw 'Missing positive build marker; inspect log'}
Get-FileHash -LiteralPath "$reports\System_wrapper.bit","$reports\System_wrapper.hdf","$reports\ps7_init.tcl" | ForEach-Object {[pscustomobject]@{Path=$_.Path;Hash=$_.Hash} | ConvertTo-Json -Compress}
'STAGE18_BUILD_VERIFIED'
