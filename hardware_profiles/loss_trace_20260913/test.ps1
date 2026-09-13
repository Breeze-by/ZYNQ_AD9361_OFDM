param([ValidateSet(1,8,32,64)][int]$MiB=32,[Parameter(Mandatory=$true)][string]$Tag,[ValidateSet('none','goodheader','badheader','ltftimeout','dc_ltf','dc_signal')][string]$Capture='none',[switch]$Observer)
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$profile='E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk\hardware_profiles\loss_trace_20260913'
if($Tag -notmatch '^stage21-[a-z0-9-]+$'){throw 'Invalid test tag'}
if(Test-Path -LiteralPath "$diag\$Tag"){throw 'Preserve prior capture'}
$delay=5
if($Capture -ne 'none'){$delay=35}
$seconds=65+$MiB*3
if($env:USERNAME -ieq 'WithBreeze'){$role='receiver';$py='C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe'}else{$role='sender';$py='D:\PYTHON\python.exe'}
$ila=$null
if($Capture -ne 'none' -and $role -eq 'receiver'){
    $captureScript='capture.tcl'
    if($Observer){$captureScript='capture_observer.tcl'}
    if(!$Observer -and $Capture -notin @('goodheader','badheader')){throw 'Failure-state triggers require observer'}
    $ila=Start-Process -FilePath 'D:\Xilinx\Vivado\2018.3\bin\vivado.bat' -ArgumentList @('-mode','batch','-notrace','-nojournal','-log',"$diag\$Tag-ila.log",'-source',"$profile\$captureScript",'-tclargs',$Tag,$Capture) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\$Tag-ila.stdout" -RedirectStandardError "$diag\$Tag-ila.stderr"
}
$proc=Start-Process -FilePath $py -ArgumentList @('-u',"$diag\stage17-tools\test_channel.py",$role,'--tag',$Tag,'--bytes',($MiB*1048576),'--random','--delay',$delay,'--seconds',$seconds) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$diag\$Tag-$role.stdout" -RedirectStandardError "$diag\$Tag-$role.stderr"
if($proc.ExitCode){throw "RF process failed $($proc.ExitCode)"}
if(!(Select-String -LiteralPath "$diag\$Tag\serial.log" -Pattern 'SERIAL_OPEN' -Quiet)){throw 'No serial proof'}
& $py "$diag\stage19-tools\summarize.py" "$diag\$Tag-$role.stdout"
if($null -ne $ila){
    # RF wait plus this bound covers the documented three-minute ILA timeout.
    if(!$ila.WaitForExit(210000)){throw 'Own ILA still running; inspect it'}
    if($ila.ExitCode){throw 'ILA process failed; RF result retained separately'}
    if(!(Select-String -LiteralPath "$diag\$Tag-ila.log" -Pattern 'STAGE21_CAPTURE_FINISHED' -Quiet)){throw 'Missing ILA completion'}
    Get-Content -LiteralPath "$diag\$Tag-ila.log" | Select-String 'STAGE21_' | ForEach-Object Line
}
"STAGE21_TEST_COMPLETE role=$role tag=$Tag"
