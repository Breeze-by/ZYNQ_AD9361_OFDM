# Sender-only temporary ELF. Original main/objects/BSP/ELF remain untouched.
# A bounded idle-time MMIO command changes TX attenuation through the ADI API,
# so A/B comparisons need not reset/reinitialize the radio between levels.
$ErrorActionPreference='Stop'
if($env:USERNAME -ine 'Hardware_simulation'){throw 'Sender only'}
$repo='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk'
$app=Join-Path $repo 'AD9361_test2'
$bsp=Join-Path $repo 'AD9361_test2_bsp\ps7_cortexa9_0'
$out=Join-Path $env:TEMP 'ad9361-diag-20260906\stage20-mailbox'
if(Test-Path -LiteralPath "$out\candidate.elf"){throw 'Preserve built candidate'}
if(!(Test-Path -LiteralPath $out)){New-Item -ItemType Directory -Path $out | Out-Null}
$source=[IO.File]::ReadAllText("$app\src\app\main.c").Replace("`r`n","`n")
$declaration=@'
/* Experimental sender-only MMIO control. No RF retransmission. */
volatile uint32_t stage20_result[8] __attribute__((aligned(32))) = {0xA7200001U};
static void stage20_control_poll(struct ad9361_rf_phy *phy)
{
    uint32_t command = Xil_In32(0x40000004U);
    uint32_t requested, actual0 = 0U, actual1 = 0U;
    int32_t status = 0;
    if ((command & 0xFFFF0000U) != 0xA7200000U) return;
    requested = ((command >> 8) & 0xFFU) * 250U;
    /* Preserve the pilot scrambler seed, clear command before calling ADI. */
    Xil_Out32(0x40000004U, command & 0x7FU);
    if (requested != 13500U && requested != 16000U) status = -100;
    else {
        status = ad9361_set_tx_attenuation(phy, 0, requested);
        if (!status) status = ad9361_set_tx_attenuation(phy, 1, requested);
        if (!status) status = ad9361_get_tx_attenuation(phy, 0, &actual0);
        if (!status) status = ad9361_get_tx_attenuation(phy, 1, &actual1);
        if (!status && (actual0 != requested || actual1 != requested)) status = -101;
        if (!status) txatt = requested;
    }
    stage20_result[1]++;
    stage20_result[2] = requested;
    stage20_result[3] = (uint32_t)status;
    stage20_result[4] = actual0;
    stage20_result[5] = actual1;
    Xil_DCacheFlushRange((INTPTR)stage20_result, sizeof(stage20_result));
    UART_Printf("STAGE20_ATT requested=%lu actual=%lu/%lu status=%ld\r\n",
                (unsigned long)requested, (unsigned long)actual0,
                (unsigned long)actual1, (long)status);
}

'@
$anchor='#define OPENOFDM_TX_BASE  0x40000000U'
if(($source.Split(@($anchor),[StringSplitOptions]::None)).Count -ne 2){throw 'main declaration anchor changed'}
$source=$source.Replace($anchor,"#include `"xil_cache.h`"`n"+$declaration+$anchor)
$anchor="        Net_Poll();`n        Net_RxPoll();"
if(($source.Split(@($anchor),[StringSplitOptions]::None)).Count -ne 2){throw 'main loop anchor changed'}
$source=$source.Replace($anchor,$anchor+"`n        stage20_control_poll(ad9361_phy);")
[IO.File]::WriteAllText("$out\main.c",$source,[Text.UTF8Encoding]::new($false))
$gcc='D:\vivado2018\SDK\2018.3\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe'
$flags=@('-Wall','-O0','-g3','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard',"-I$bsp\include")
foreach($dir in @('','app','drivers\ad9361','drivers\dma','drivers\interrupt','drivers\net','drivers\timer','drivers\uart','utils')){$flags+="-I$app\src\$dir"}
& $gcc @flags -c -o "$out\main.o" "$out\main.c"
if($LASTEXITCODE){throw 'Temporary main compile failed'}
$objects=@()
foreach($include in [IO.File]::ReadAllLines("$app\Debug\makefile")){
    if($include -notmatch '^-include (.*subdir\.mk)$'){continue}
    $makePart=Join-Path "$app\Debug" $Matches[1]
    if(!(Test-Path -LiteralPath $makePart)){continue} # make's -include is optional
    foreach($line in [IO.File]::ReadAllLines($makePart)){
        if($line -match '^\./(.+\.o)\s*\\?\s*$'){
            $rel=$Matches[1].Replace('/','\')
            if($rel -eq 'src\app\main.o'){$objects+="$out\main.o"}else{$objects+=(Join-Path "$app\Debug" $rel)}
        }
    }
}
if($objects.Count -ne 16 -or @($objects | Where-Object {$_ -eq "$out\main.o"}).Count -ne 1){throw 'Object list differs from verified 16-object application'}
foreach($obj in $objects){if(!(Test-Path -LiteralPath $obj)){throw "Missing $obj"}}
$linkFlags=@('-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-Wl,-build-id=none',"-specs=$app\Debug\Xilinx.spec",'-Wl,-T',"-Wl,$app\src\lscript.ld","-L$bsp\lib",'-o',"$out\candidate.elf")
& $gcc @linkFlags @objects '-lm' '-llwip4' '-Wl,--start-group,-lxil,-lgcc,-lc,--end-group'
if($LASTEXITCODE){throw 'Temporary ELF link failed'}
& ($gcc.Replace('gcc.exe','nm.exe')) -n "$out\candidate.elf" | Select-String ' stage20_result$| txatt$| gain$| sample_rate$'
Get-FileHash -Algorithm SHA256 -LiteralPath "$out\candidate.elf","$app\Debug\AD9361_test2.elf" | Format-List
'STAGE20_MAILBOX_BUILD_COMPLETE'
