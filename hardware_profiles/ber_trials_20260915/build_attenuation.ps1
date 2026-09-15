param([Parameter(Mandatory=$true)][string]$Out)
$ErrorActionPreference='Stop'
if($env:USERNAME -ine 'Hardware_simulation'){throw 'Sender only'}
$repo='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk'
$app=Join-Path $repo 'AD9361_test2'
$bsp=Join-Path $repo 'AD9361_test2_bsp\ps7_cortexa9_0'
if(Test-Path -LiteralPath $Out){throw 'Preserve existing candidate'}
New-Item -ItemType Directory -Path $Out | Out-Null
$source=[IO.File]::ReadAllText("$app\src\app\main.c").Replace("`r`n","`n")
$anchor='#define OPENOFDM_TX_BASE  0x40000000U'
if(($source.Split(@($anchor),[StringSplitOptions]::None)).Count -ne 2){throw 'Declaration anchor changed'}
$source=$source.Replace($anchor,"#include `"attenuation_control.h`"`n"+$anchor)
$anchor="        Net_Poll();`n        Net_RxPoll();"
if(($source.Split(@($anchor),[StringSplitOptions]::None)).Count -ne 2){throw 'Poll anchor changed'}
$source=$source.Replace($anchor,$anchor+"`n        file_ber_control_poll(ad9361_phy);")
[IO.File]::WriteAllText("$Out\main.c",$source,[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath "$PSScriptRoot\attenuation_control.h" -Destination $Out
$gcc='D:\vivado2018\SDK\2018.3\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe'
$flags=@('-Wall','-O0','-g3','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard',"-I$bsp\include")
foreach($dir in @('','app','drivers\ad9361','drivers\dma','drivers\interrupt','drivers\net','drivers\timer','drivers\uart','utils')){$flags+="-I$app\src\$dir"}
& $gcc @flags -c -o "$Out\main.o" "$Out\main.c"
if($LASTEXITCODE){throw 'Temporary main compile failed'}
$objects=@()
foreach($include in [IO.File]::ReadAllLines("$app\Debug\makefile")){
    if($include -notmatch '^-include (.*subdir\.mk)$'){continue}
    $part=Join-Path "$app\Debug" $Matches[1]
    if(!(Test-Path -LiteralPath $part)){continue}
    foreach($line in [IO.File]::ReadAllLines($part)){
        if($line -match '^\./(.+\.o)\s*\\?\s*$'){
            $rel=$Matches[1].Replace('/','\')
            if($rel -eq 'src\app\main.o'){$objects+="$Out\main.o"}else{$objects+=(Join-Path "$app\Debug" $rel)}
        }
    }
}
if($objects.Count -ne 16 -or @($objects | Where-Object {$_ -eq "$Out\main.o"}).Count -ne 1){throw 'Unexpected object list'}
foreach($obj in $objects){if(!(Test-Path -LiteralPath $obj)){throw "Missing $obj"}}
$linkFlags=@('-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-Wl,-build-id=none',"-specs=$app\Debug\Xilinx.spec",'-Wl,-T',"-Wl,$app\src\lscript.ld","-L$bsp\lib",'-o',"$Out\candidate.elf")
& $gcc @linkFlags @objects '-lm' '-llwip4' '-Wl,--start-group,-lxil,-lgcc,-lc,--end-group'
if($LASTEXITCODE){throw 'Temporary ELF link failed'}
Get-FileHash -LiteralPath "$Out\candidate.elf","$app\Debug\AD9361_test2.elf" | Format-List Path,Hash
'FILE_BER_ELF_BUILD_COMPLETE'
