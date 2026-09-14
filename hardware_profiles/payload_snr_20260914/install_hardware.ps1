param([Parameter(Mandatory=$true)][string]$Backup,
      [Parameter(Mandatory=$true)][string]$Reports)
# Install the matching export after a successful original-project build.
# PS configuration and BSP must remain byte-identical: no interfaces changed.
$ErrorActionPreference='Stop'
$project='E:\by2025\AD9361_test_board\AD9361_test2'
$repo=Join-Path $project 'AD9361_test2.sdk'
$platform=Join-Path $repo 'System_wrapper_hw_platform_0'
$extract=Join-Path $reports 'checked_export'
if(Get-Process -Name eclipse -ErrorAction SilentlyContinue){throw 'Close SDK before hardware export update'}
if(!(Select-String -LiteralPath (Join-Path (Split-Path $Reports) 'build.log') -Pattern '^SNR_ORIGINAL_BUILD_COMPLETE ' -Quiet)){throw 'Build not complete'}
if(Test-Path -LiteralPath $extract){throw 'Export directory already exists; inspect before retrying'}
New-Item -ItemType Directory -Path $extract | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=[IO.Compression.ZipFile]::OpenRead("$reports\System_wrapper.hdf")
$initFiles=@('ps7_init.c','ps7_init.h','ps7_init_gpl.c','ps7_init_gpl.h','ps7_init.html','ps7_init.tcl')
try {
    foreach($name in ($initFiles + @('System_wrapper.bit'))){
        $entry=$archive.GetEntry($name)
        if(!$entry){throw "Missing HDF member: $name"}
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,"$extract\$name")
    }
} finally {$archive.Dispose()}
foreach($name in $initFiles){
    $expected=(Get-FileHash -LiteralPath "$backup\sdk\System_wrapper_hw_platform_0\$name").Hash
    if((Get-FileHash -LiteralPath "$platform\$name").Hash -ne $expected){throw "User modified platform: $name"}
    if((Get-FileHash -LiteralPath "$extract\$name").Hash -ne $expected){throw "PS initialization changed: $name"}
}
$hash=(Get-FileHash -LiteralPath "$reports\System_wrapper.bit").Hash
foreach($path in @("$extract\System_wrapper.bit","$project\AD9361_test2.runs\impl_1\System_wrapper.bit")){
    if((Get-FileHash -LiteralPath $path).Hash -ne $hash){throw "Bit/HDF mismatch: $path"}
}
$records=Get-Content -LiteralPath "$backup\hashes.json" -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($record in $records){
    if($record.Path.StartsWith("$repo\AD9361_test2_bsp\",[StringComparison]::OrdinalIgnoreCase)){
        if((Get-FileHash -LiteralPath $record.Path).Hash -ne $record.Hash){throw "BSP changed: $($record.Path)"}
    }
}
foreach($path in @("$platform\System_wrapper.bit","$platform\system.hdf","$repo\System_wrapper.hdf")){
    $entry=@($records | Where-Object {$_.Path -ieq $path})
    if($entry.Count -ne 1 -or (Get-FileHash -LiteralPath $path).Hash -ne $entry[0].Hash){throw "Preserve user export change: $path"}
}
Copy-Item -LiteralPath "$reports\System_wrapper.hdf" -Destination "$platform\system.hdf"
Copy-Item -LiteralPath "$reports\System_wrapper.hdf" -Destination "$repo\System_wrapper.hdf"
Copy-Item -LiteralPath "$reports\System_wrapper.bit" -Destination "$platform\System_wrapper.bit"
if(Test-Path -LiteralPath "$platform\System_wrapper.ltx"){
    Copy-Item -LiteralPath "$platform\System_wrapper.ltx" -Destination "$backup\pre-export-System_wrapper.ltx"
}
Copy-Item -LiteralPath "$reports\System_wrapper.ltx" -Destination "$platform\System_wrapper.ltx"
"SNR_HARDWARE_EXPORT_INSTALLED BIT=$hash PS_INIT_UNCHANGED=1 BSP_UNCHANGED=1"
