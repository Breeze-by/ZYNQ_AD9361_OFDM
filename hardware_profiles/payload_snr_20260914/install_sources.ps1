param([Parameter(Mandatory=$true)][string]$Backup,
      [Parameter(Mandatory=$true)][string]$Out,
      [string]$Project='E:\by2025\AD9361_test_board\AD9361_test2')
$ErrorActionPreference='Stop'
if(Get-Process eclipse,xsdk -ErrorAction SilentlyContinue){throw 'Save and close SDK first'}
if(Test-Path -LiteralPath $Out){throw 'Preserve existing software build records'}
$repo=Join-Path $Project 'AD9361_test2.sdk'
$app=Join-Path $repo 'AD9361_test2'
$net=Join-Path $app 'src/drivers/net'
$source=Join-Path $net 'net_rx.c'
if((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Backup 'sdk/AD9361_test2/src/drivers/net/net_rx.c')).Hash){throw 'Preserve net_rx changes since backup'}
if(Test-Path -LiteralPath (Join-Path $net 'payload_snr_service.h')){throw 'Service already installed'}
New-Item -ItemType Directory -Path $Out | Out-Null
function Replace-Once([string]$s,[string]$a,[string]$b){
    $n=$s.IndexOf($a)
    if($n -lt 0 -or $s.IndexOf($a,$n+$a.Length) -ge 0){throw "Expected one source anchor: $a"}
    return $s.Remove($n,$a.Length).Insert($n,$b)
}
$code=Get-Content -LiteralPath $source -Raw -Encoding UTF8
$code=Replace-Once $code 'static void net_udp_receive_callback(void *arg,' "#include `"payload_snr_service.h`"`n`nstatic void net_udp_receive_callback(void *arg,"
$code=Replace-Once $code '    NetStats_OnRxPacket((uint32_t)p->tot_len,' "    if (net_snr_request(p, addr, port)) return;`n`n    NetStats_OnRxPacket((uint32_t)p->tot_len,"
$code=Replace-Once $code '    net_loopback_print_rx_status();' "    net_snr_poll();`n    net_loopback_print_rx_status();"
[IO.File]::WriteAllText((Join-Path $Out 'net_rx.c'),$code,[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'payload_snr_service.h') -Destination $net
Copy-Item -LiteralPath (Join-Path $Out 'net_rx.c') -Destination $source
if($env:USERNAME -ieq 'WithBreeze'){$sdk='D:\Xilinx\SDK\2018.3';$att=25000;$gain=66}else{$sdk='D:\vivado2018\SDK\2018.3';$att=16000;$gain=36}
$bin=Join-Path $sdk 'gnu/aarch32/nt/gcc-arm-none-eabi/bin'
$env:PATH="$bin;$sdk\gnuwin\bin;$env:PATH"
Push-Location -LiteralPath (Join-Path $app 'Debug')
try {
    $inc=@('-I../../AD9361_test2_bsp/ps7_cortexa9_0/include','-I../src','-I../src/app','-I../src/drivers/ad9361','-I../src/drivers/uart','-I../src/drivers/dma','-I../src/drivers/interrupt','-I../src/drivers/net','-I../src/drivers/timer','-I../src/utils')
    $macros=@(& "$bin\arm-none-eabi-gcc.exe" -E -dM @inc ../src/utils/COMMON.c)
    if($LASTEXITCODE -or $macros -notcontains "#define OPENWIFI_TX_ATT_MDB ${att}U" -or $macros -notcontains "#define OPENWIFI_RX_GAIN_DB $gain"){throw 'Wrong RF role macros'}
    & "$sdk\gnuwin\bin\make.exe" -j2 main-build
    if($LASTEXITCODE){throw 'Original SDK ELF build failed'}
    & "$sdk\gnuwin\bin\make.exe" -q main-build
    if($LASTEXITCODE){throw 'SDK ELF not up to date'}
    $symbols=@(& "$bin\arm-none-eabi-nm.exe" -n AD9361_test2.elf)
    if($LASTEXITCODE -or !($symbols -match ' net_snr_request$') -or !($symbols -match ' net_snr_poll$')){throw 'ELF lacks SNR service'}
    Get-FileHash -LiteralPath AD9361_test2.elf | Select-Object Path,Hash | Format-List
    'SNR_ORIGINAL_ELF_BUILD_COMPLETE'
} finally {Pop-Location}
