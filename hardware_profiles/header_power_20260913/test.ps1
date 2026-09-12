param([ValidateSet(1,4,8,16,32)][int]$MiB=8,[Parameter(Mandatory=$true)][string]$Tag,[switch]$Capture,[ValidateSet('baseline','candidate')][string]$Image='baseline')
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$profile=Join-Path $diag 'stage20-tools'
$bytes=$MiB*1048576
$seconds=65+[int]($MiB*3)
$delay=5
if($Capture){$delay=30}
if($env:USERNAME -ieq 'WithBreeze'){$role='receiver';$py='C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe'}else{$role='sender';$py='D:\PYTHON\python.exe'}
if($Tag -notmatch '^stage20-[a-z0-9-]+$'){throw 'Invalid test tag'}
if(Test-Path -LiteralPath "$diag\$Tag"){throw 'Preserve prior capture'}
$ila=$null
if($Capture -and $role -eq 'receiver'){
    $ila=Start-Process -FilePath 'D:\Xilinx\Vivado\2018.3\bin\vivado.bat' -ArgumentList @('-mode','batch','-notrace','-nojournal','-log',"$diag\$Tag-ila.log",'-source',"$profile\capture.tcl",'-tclargs',$Tag,$Image) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$diag\$Tag-ila.stdout" -RedirectStandardError "$diag\$Tag-ila.stderr"
}
$process=Start-Process -FilePath $py -ArgumentList @('-u',"$diag\stage17-tools\test_channel.py",$role,'--tag',$Tag,'--bytes',$bytes,'--random','--delay',$delay,'--seconds',$seconds) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$diag\$Tag-$role.stdout" -RedirectStandardError "$diag\$Tag-$role.stderr"
if($process.ExitCode){throw "RF test failed: $($process.ExitCode)"}
if(!(Select-String -LiteralPath "$diag\$Tag\serial.log" -Pattern 'SERIAL_OPEN' -Quiet)){throw 'Missing serial capture proof'}
& $py "$diag\stage19-tools\summarize.py" "$diag\$Tag-$role.stdout"
if($null -ne $ila){
    if(!$ila.WaitForExit(10000)){throw 'Own ILA process still running; inspect before continuing'}
    if($ila.ExitCode){throw 'ILA capture failed; retain RF results separately'}
    if(!(Select-String -LiteralPath "$diag\$Tag-ila.log" -Pattern 'STAGE20_CAPTURE_COMPLETE' -Quiet)){throw 'Missing ILA completion marker'}
}
"STAGE20_TEST_COMPLETED role=$role tag=$Tag"
