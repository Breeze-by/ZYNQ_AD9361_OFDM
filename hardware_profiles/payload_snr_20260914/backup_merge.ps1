param([Parameter(Mandatory=$true)][string]$Out,
      [string]$Project='E:\by2025\AD9361_test_board\AD9361_test2')
$ErrorActionPreference='Stop'
$Project=[IO.Path]::GetFullPath($Project).TrimEnd('\')
$Out=[IO.Path]::GetFullPath($Out).TrimEnd('\')
if(Test-Path -LiteralPath $Out){throw 'Preserve existing backup'}
if($Out.StartsWith($Project+'\',[StringComparison]::OrdinalIgnoreCase) -or $Out -ieq $Project){throw 'Backup must be outside original project'}
$repo=Join-Path $Project 'AD9361_test2.sdk'
if($env:USERNAME -ieq 'WithBreeze'){$git='D:\Program Files\Git\cmd\git.exe'}else{$git='D:\Git\cmd\git.exe'}
New-Item -ItemType Directory -Path $Out | Out-Null
foreach($name in @('AD9361_test2.xpr','AD9361_test2.srcs','ip_repo')){
    Copy-Item -LiteralPath (Join-Path $Project $name) -Destination (Join-Path $Out $name) -Recurse
}
$sdkBackup=Join-Path $Out 'sdk'
foreach($name in @('AD9361_test2/src','AD9361_test2/Debug','AD9361_test2/tools/pc_sender','AD9361_test2_bsp','System_wrapper_hw_platform_0','System_wrapper.hdf','README.md','AGENTS.md')){
    $destination=Join-Path $sdkBackup $name
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo $name) -Destination $destination -Recurse
}
Copy-Item -LiteralPath (Join-Path $Project 'AD9361_test2.runs/impl_1/System_wrapper.bit') -Destination (Join-Path $Out 'original_impl.bit')
$files=@((Join-Path $Project 'AD9361_test2.xpr'),(Join-Path $Project 'AD9361_test2.srcs/sources_1/bd/System/System.bd'),(Join-Path $repo 'System_wrapper.hdf'))
$roots=@((Join-Path $Project 'ip_repo'),(Join-Path $repo 'AD9361_test2/src'),(Join-Path $repo 'AD9361_test2/Debug'),(Join-Path $repo 'AD9361_test2_bsp'),(Join-Path $repo 'System_wrapper_hw_platform_0'))
$files+=@(Get-ChildItem -LiteralPath $roots -Recurse -File | ForEach-Object FullName)
$files | ForEach-Object {Get-FileHash -LiteralPath $_ -Algorithm SHA256} | Select-Object Path,Hash | ConvertTo-Json -Depth 3 | Out-File -LiteralPath (Join-Path $Out 'hashes.json') -Encoding utf8
& $git -C $repo status --short | Out-File -LiteralPath (Join-Path $Out 'git-status.txt') -Encoding utf8
& $git -C $repo rev-parse HEAD | Out-File -LiteralPath (Join-Path $Out 'git-head.txt') -Encoding ascii
$diffPath=Join-Path $Out 'user-worktree.patch'
& $git -C $repo diff --binary "--output=$diffPath"
if($LASTEXITCODE){throw 'Failed to preserve worktree diff'}
"SNR_MERGE_BACKUP_COMPLETE $Out"
