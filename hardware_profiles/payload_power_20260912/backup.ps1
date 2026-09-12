$ErrorActionPreference='Stop'
$project='E:\by2025\AD9361_test_board\AD9361_test2'
$repo=Join-Path $project 'AD9361_test2.sdk'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$backup=Join-Path $diag 'stage17-before-power'
if(Test-Path -LiteralPath $backup){throw 'Stage 17 backup already exists'}
New-Item -ItemType Directory -Path $backup | Out-Null
foreach($name in @('AD9361_test2.xpr','AD9361_test2.srcs','ip_repo')){
    Copy-Item -LiteralPath (Join-Path $project $name) -Destination (Join-Path $backup $name) -Recurse
}
foreach($name in @('README.md','AGENTS.md')){Copy-Item -LiteralPath "$repo\$name" -Destination "$backup\$name"}
Copy-Item -LiteralPath "$repo\AD9361_test2\src" -Destination "$backup\src" -Recurse
Copy-Item -LiteralPath "$repo\AD9361_test2\Debug\AD9361_test2.elf" -Destination "$backup\AD9361_test2.elf"
Copy-Item -LiteralPath "$project\AD9361_test2.runs\impl_1\System_wrapper.bit" -Destination "$backup\System_wrapper.bit"
Copy-Item -LiteralPath "$repo\System_wrapper_hw_platform_0\system.hdf" -Destination "$backup\system.hdf"
Copy-Item -LiteralPath "$repo\System_wrapper_hw_platform_0\ps7_init.tcl" -Destination "$backup\ps7_init.tcl"
$protected=@("$project\AD9361_test2.xpr","$project\AD9361_test2.srcs\sources_1\bd\System\System.bd","$repo\AD9361_test2\Debug\AD9361_test2.elf","$repo\System_wrapper_hw_platform_0\system.hdf","$repo\System_wrapper_hw_platform_0\ps7_init.tcl","$project\AD9361_test2.runs\impl_1\System_wrapper.bit")
$protected+=@(Get-ChildItem -LiteralPath "$project\ip_repo","$repo\AD9361_test2\src" -Recurse -File | ForEach-Object FullName)
$protected | ForEach-Object {Get-FileHash -LiteralPath $_ -Algorithm SHA256} | Select-Object Path,Hash | ConvertTo-Json -Depth 3 | Out-File -LiteralPath "$backup\protected-hashes.json" -Encoding utf8
if($env:USERNAME -ieq 'WithBreeze'){$g='D:\Program Files\Git\cmd\git.exe'}else{$g='D:\Git\cmd\git.exe'}
& $g -C $repo status --short | Out-File -LiteralPath "$backup\git-status.txt" -Encoding utf8
& $g -C $repo rev-parse HEAD | Out-File -LiteralPath "$backup\git-head.txt" -Encoding ascii
"STAGE17_BACKUP_COMPLETE $backup"
