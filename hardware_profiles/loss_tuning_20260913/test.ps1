param([ValidateSet(1,4,8,16,32)][int]$MiB=8,[Parameter(Mandatory=$true)][string]$Tag)
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
$bytes=$MiB*1048576
$seconds=55+[int]($MiB*3)
if($env:USERNAME -ieq 'WithBreeze'){$role='receiver';$py='C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe'}else{$role='sender';$py='D:\PYTHON\python.exe'}
if($Tag -notmatch '^stage19-[a-z0-9-]+$'){throw 'Invalid test tag'}
if(Test-Path -LiteralPath "$diag\$Tag"){throw 'Preserve previous capture; use a fresh tag'}
$process=Start-Process -FilePath $py -ArgumentList @('-u',"$diag\stage17-tools\test_channel.py",$role,'--tag',$Tag,'--bytes',$bytes,'--random','--delay','20','--seconds',$seconds) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$diag\$Tag-$role.stdout" -RedirectStandardError "$diag\$Tag-$role.stderr"
if($process.ExitCode){throw "RF test failed: $($process.ExitCode)"}
if(!(Select-String -LiteralPath "$diag\$Tag\serial.log" -Pattern 'SERIAL_OPEN' -Quiet)){throw 'Missing serial capture proof'}
& $py "$diag\stage19-tools\summarize.py" "$diag\$Tag-$role.stdout"
"STAGE19_TEST_COMPLETED role=$role tag=$Tag"
