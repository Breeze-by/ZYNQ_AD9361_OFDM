param([Parameter(Mandatory=$true)][string]$Out)
$ErrorActionPreference='Stop'
$repo='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk'
$app=Join-Path $repo 'AD9361_test2'
$bsp=Join-Path $repo 'AD9361_test2_bsp\ps7_cortexa9_0'
if(Test-Path -LiteralPath $Out){throw 'Preserve existing candidate ELF'}
New-Item -ItemType Directory -Path $Out | Out-Null
$code=Get-Content -LiteralPath "$app\src\drivers\net\net_rx.c" -Encoding UTF8 -Raw
if($code.Contains('#include "payload_snr_service.h"')){throw 'SNR is already merged; use the normal SDK application build'}
function Replace-Once([string]$s,[string]$a,[string]$b){
    $n=$s.IndexOf($a)
    if($n -lt 0 -or $s.IndexOf($a,$n+$a.Length) -ge 0){throw "Expected one anchor: $a"}
    return $s.Remove($n,$a.Length).Insert($n,$b)
}
$code=Replace-Once $code 'static void net_udp_receive_callback(void *arg,' "#include `"payload_snr_service.h`"`n`nstatic void net_udp_receive_callback(void *arg,"
$code=Replace-Once $code '    NetStats_OnRxPacket((uint32_t)p->tot_len,' "    if (net_snr_request(p, addr, port)) return;`n`n    NetStats_OnRxPacket((uint32_t)p->tot_len,"
$code=Replace-Once $code '    net_loopback_print_rx_status();' "    net_snr_poll();`n    net_loopback_print_rx_status();"
[IO.File]::WriteAllText("$Out\net_rx.c",$code,[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath "$app\src\drivers\net\net_config.h","$PSScriptRoot\payload_snr_service.h" -Destination $Out
$gcc='D:\Xilinx\SDK\2018.3\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe'
$flags=@('-Wall','-Wextra','-O0','-g3','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard',"-I$bsp\include")
foreach($dir in @('','app','drivers\ad9361','drivers\dma','drivers\interrupt','drivers\net','drivers\timer','drivers\uart','utils')){$flags+="-I$app\src\$dir"}
& $gcc @flags -c -o "$Out\net_rx.o" "$Out\net_rx.c"
if($LASTEXITCODE){throw 'Temporary net_rx compile failed'}
$objects=@()
foreach($include in [IO.File]::ReadAllLines("$app\Debug\makefile")){
    if($include -notmatch '^-include (.*subdir\.mk)$'){continue}
    $makePart=Join-Path "$app\Debug" $Matches[1]
    if(!(Test-Path -LiteralPath $makePart)){continue}
    foreach($line in [IO.File]::ReadAllLines($makePart)){
        if($line -match '^\./(.+\.o)\s*\\?\s*$'){
            $rel=$Matches[1].Replace('/','\')
            if($rel -eq 'src\drivers\net\net_rx.o'){$objects+="$Out\net_rx.o"}else{$objects+=(Join-Path "$app\Debug" $rel)}
        }
    }
}
if($objects.Count -ne 16){throw 'Unexpected object count'}
$linkFlags=@('-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-Wl,-build-id=none',"-specs=$app\Debug\Xilinx.spec",'-Wl,-T',"-Wl,$app\src\lscript.ld","-L$bsp\lib",'-o',"$Out\candidate.elf")
& $gcc @linkFlags @objects '-lm' '-llwip4' '-Wl,--start-group,-lxil,-lgcc,-lc,--end-group'
if($LASTEXITCODE){throw 'Temporary link failed'}
Get-FileHash -LiteralPath "$Out\candidate.elf" | ForEach-Object Hash
'SNR_ELF_BUILD_COMPLETE'
