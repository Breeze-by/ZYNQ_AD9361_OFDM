$ErrorActionPreference='Stop'
$project='E:\by2025\AD9361_test_board\AD9361_test2'
$repo=Join-Path $project 'AD9361_test2.sdk'
$backup=Join-Path $env:TEMP 'ad9361-diag-20260906\stage18-before-defaults'
if(Test-Path -LiteralPath $backup){throw 'Do not overwrite an existing Stage 18 backup'}
New-Item -ItemType Directory -Path $backup | Out-Null
foreach($name in @('AD9361_test2.xpr','AD9361_test2.srcs','ip_repo')){
    Copy-Item -LiteralPath "$project\$name" -Destination "$backup\$name" -Recurse
}
New-Item -ItemType Directory -Path "$backup\sdk" | Out-Null
foreach($name in @('AD9361_test2\src','AD9361_test2\Debug','AD9361_test2_bsp','System_wrapper_hw_platform_0','System_wrapper.hdf','README.md','AGENTS.md')){
    $dst=Join-Path "$backup\sdk" $name
    New-Item -ItemType Directory -Path (Split-Path $dst) -Force | Out-Null
    Copy-Item -LiteralPath "$repo\$name" -Destination $dst -Recurse
}
Copy-Item -LiteralPath "$project\AD9361_test2.runs\impl_1\System_wrapper.bit" -Destination "$backup\System_wrapper.bit"
$files=@("$project\AD9361_test2.xpr","$project\AD9361_test2.srcs\sources_1\bd\System\System.bd","$project\AD9361_test2.runs\impl_1\System_wrapper.bit","$repo\System_wrapper.hdf")
$files+=@(Get-ChildItem -LiteralPath "$project\ip_repo","$repo\AD9361_test2\src","$repo\AD9361_test2\Debug","$repo\AD9361_test2_bsp","$repo\System_wrapper_hw_platform_0" -Recurse -File | ForEach-Object FullName)
$files | ForEach-Object {Get-FileHash -LiteralPath $_ -Algorithm SHA256} | Select-Object Path,Hash | ConvertTo-Json -Depth 3 | Out-File -LiteralPath "$backup\hashes.json" -Encoding utf8
if($env:USERNAME -ieq 'WithBreeze'){$g='D:\Program Files\Git\cmd\git.exe'}else{$g='D:\Git\cmd\git.exe'}
& $g -C $repo status --short | Out-File -LiteralPath "$backup\git-status.txt" -Encoding utf8
& $g -C $repo rev-parse HEAD | Out-File -LiteralPath "$backup\git-head.txt" -Encoding ascii
& $g -C $repo diff --binary --output="$backup\user-worktree.patch"
if($LASTEXITCODE){throw 'Failed to save user diff'}
"STAGE18_BACKUP_COMPLETE $backup"
