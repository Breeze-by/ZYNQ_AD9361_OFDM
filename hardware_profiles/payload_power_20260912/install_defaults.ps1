# Install reviewed, staged C sources and build each board's own application.
# Staging inputs must be uploaded as stage18-{main.c,app_config.h,COMMON.c,rf_board_local.h.example}.
$ErrorActionPreference='Stop'
$project='E:\by2025\AD9361_test_board\AD9361_test2'
$repo=Join-Path $project 'AD9361_test2.sdk'
$app=Join-Path $repo 'AD9361_test2'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$backup=Join-Path $diag 'stage18-before-defaults'
if(Get-Process -Name vivado,eclipse -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -eq 'eclipse'}){throw 'Close SDK before installing sources'}
$changes=@{'app\main.c'='main.c';'app\app_config.h'='app_config.h';'utils\COMMON.c'='COMMON.c';'utils\rf_board_local.h.example'='rf_board_local.h.example'}
foreach($rel in $changes.Keys){
    if((Get-FileHash -LiteralPath "$app\src\$rel").Hash -ne (Get-FileHash -LiteralPath "$backup\sdk\AD9361_test2\src\$rel").Hash){throw "Preserve user change: $rel"}
    if(!(Test-Path -LiteralPath "$diag\stage18-$($changes[$rel])")){throw "Missing staged source: $rel"}
}
foreach($rel in $changes.Keys){Copy-Item -LiteralPath "$diag\stage18-$($changes[$rel])" -Destination "$app\src\$rel"}
if($env:USERNAME -ieq 'WithBreeze'){
    $sdk='D:\Xilinx\SDK\2018.3';$expectedAtt=25000;$expectedGain=66
    if((Get-FileHash -LiteralPath "$app\src\utils\rf_board_local.h").Hash -ne (Get-FileHash -LiteralPath "$backup\sdk\AD9361_test2\src\utils\rf_board_local.h").Hash){throw 'Receiver role changed'}
}else{
    $sdk='D:\vivado2018\SDK\2018.3';$expectedAtt=16000;$expectedGain=36
    if(Test-Path -LiteralPath "$app\src\utils\rf_board_local.h"){throw 'Unexpected sender local override'}
}
$bin="$sdk\gnu\aarch32\nt\gcc-arm-none-eabi\bin"
$env:PATH="$bin;$sdk\gnuwin\bin;$env:PATH"
Set-Location -LiteralPath "$app\Debug"
$inc=@('-I../../AD9361_test2_bsp/ps7_cortexa9_0/include','-I../src','-I../src/app','-I../src/drivers/ad9361','-I../src/drivers/uart','-I../src/drivers/dma','-I../src/drivers/interrupt','-I../src/drivers/net','-I../src/drivers/timer','-I../src/utils')
$macros=@(& "$bin\arm-none-eabi-gcc.exe" -E -dM @inc ../src/utils/COMMON.c)
if($LASTEXITCODE){throw 'Preprocessor failed'}
if($macros -notcontains "#define OPENWIFI_TX_ATT_MDB ${expectedAtt}U"){throw 'Wrong attenuation macro'}
if($macros -notcontains "#define OPENWIFI_RX_GAIN_DB $expectedGain"){throw 'Wrong gain macro'}
$p=Start-Process -FilePath "$sdk\gnuwin\bin\make.exe" -ArgumentList @('-j2','main-build') -WorkingDirectory "$app\Debug" -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$diag\stage18-app-build.stdout" -RedirectStandardError "$diag\stage18-app-build.stderr"
if($p.ExitCode){throw "Application build failed: $($p.ExitCode)"}
& "$sdk\gnuwin\bin\make.exe" -q main-build
if($LASTEXITCODE){throw 'Application build not up-to-date'}
Get-FileHash -LiteralPath "$app\Debug\AD9361_test2.elf" | ForEach-Object {[pscustomobject]@{Path=$_.Path;Hash=$_.Hash} | ConvertTo-Json -Compress}
& "$bin\arm-none-eabi-nm.exe" -n "$app\Debug\AD9361_test2.elf" | Select-String ' gain$| txatt$| sample_rate$| loopback_return_port$| loopback_return_addr$'
'STAGE18_APPLICATION_BUILD_VERIFIED'
