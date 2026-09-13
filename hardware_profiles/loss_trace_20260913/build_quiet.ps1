# Receiver-only temporary ELF. Only the two initial valid-frame prints are disabled.
$ErrorActionPreference='Stop'
if($env:USERNAME -ine 'WithBreeze'){throw 'Receiver only'}
$repo='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk'
$app=Join-Path $repo 'AD9361_test2'
$bsp=Join-Path $repo 'AD9361_test2_bsp\ps7_cortexa9_0'
$out=Join-Path $env:TEMP 'ad9361-diag-20260906\stage21-quiet'
if(Test-Path -LiteralPath $out){throw 'Preserve prior quiet experiment'}
New-Item -ItemType Directory -Path $out | Out-Null
Copy-Item -LiteralPath "$app\src\drivers\net\net_rx.c","$app\src\drivers\net\net_config.h" -Destination $out
& 'D:\Program Files\Git\cmd\git.exe' -C $out apply --check --unidiff-zero "$repo\hardware_profiles\loss_trace_20260913\quiet.patch"
if($LASTEXITCODE){throw 'Quiet patch check failed'}
& 'D:\Program Files\Git\cmd\git.exe' -C $out apply --unidiff-zero "$repo\hardware_profiles\loss_trace_20260913\quiet.patch"
if($LASTEXITCODE){throw 'Quiet patch failed'}
$gcc='D:\Xilinx\SDK\2018.3\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe'
$flags=@('-Wall','-O0','-g3','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard',"-I$bsp\include")
foreach($dir in @('','app','drivers\ad9361','drivers\dma','drivers\interrupt','drivers\net','drivers\timer','drivers\uart','utils')){$flags+="-I$app\src\$dir"}
& $gcc @flags -c -o "$out\net_rx.o" "$out\net_rx.c"
if($LASTEXITCODE){throw 'Temporary net_rx compile failed'}
$objects=@()
foreach($include in [IO.File]::ReadAllLines("$app\Debug\makefile")){
    if($include -notmatch '^-include (.*subdir\.mk)$'){continue}
    $makePart=Join-Path "$app\Debug" $Matches[1]
    if(!(Test-Path -LiteralPath $makePart)){continue}
    foreach($line in [IO.File]::ReadAllLines($makePart)){
        if($line -match '^\./(.+\.o)\s*\\?\s*$'){
            $rel=$Matches[1].Replace('/','\')
            if($rel -eq 'src\drivers\net\net_rx.o'){$objects+="$out\net_rx.o"}else{$objects+=(Join-Path "$app\Debug" $rel)}
        }
    }
}
if($objects.Count -ne 16 -or @($objects | Where-Object {$_ -eq "$out\net_rx.o"}).Count -ne 1){throw 'Unexpected application object list'}
foreach($obj in $objects){if(!(Test-Path -LiteralPath $obj)){throw "Missing $obj"}}
$linkFlags=@('-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-Wl,-build-id=none',"-specs=$app\Debug\Xilinx.spec",'-Wl,-T',"-Wl,$app\src\lscript.ld","-L$bsp\lib",'-o',"$out\candidate.elf")
& $gcc @linkFlags @objects '-lm' '-llwip4' '-Wl,--start-group,-lxil,-lgcc,-lc,--end-group'
if($LASTEXITCODE){throw 'Temporary link failed'}
& ($gcc.Replace('gcc.exe','nm.exe')) -n "$out\candidate.elf" | Select-String ' txatt$| gain$| sample_rate$'
Get-FileHash -Algorithm SHA256 -LiteralPath "$out\candidate.elf","$app\Debug\AD9361_test2.elf" | Select-Object Path,Hash | ConvertTo-Json -Compress
'STAGE21_QUIET_BUILD_COMPLETE'
