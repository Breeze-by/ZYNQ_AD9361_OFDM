param([ValidateSet('1m','8m')][string]$Size='1m',[string]$Tag='stage18-defaults-1m-a')
$ErrorActionPreference='Stop'
$diag=Join-Path $env:TEMP 'ad9361-diag-20260906'
if($Size -eq '8m'){$bytes=8388608;$seconds=80}else{$bytes=1048576;$seconds=55}
if($env:USERNAME -ieq 'WithBreeze'){$role='receiver';$py='C:\Users\WithBreeze\AppData\Local\Programs\Python\Python314\python.exe'}else{$role='sender';$py='D:\PYTHON\python.exe'}
if($Tag -notmatch '^stage18-[a-z0-9-]+$'){throw 'Invalid bounded test tag'}
if(Test-Path -LiteralPath "$diag\$Tag"){throw 'Preserve previous capture; use a new tag'}
$process=Start-Process -FilePath $py -ArgumentList @('-u',"$diag\stage17-tools\test_channel.py",$role,'--tag',$Tag,'--bytes',$bytes,'--random','--delay','20','--seconds',$seconds) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$diag\$Tag-$role.stdout" -RedirectStandardError "$diag\$Tag-$role.stderr"
if($process.ExitCode){throw "RF test failed: $($process.ExitCode)"}
Get-Content -LiteralPath "$diag\$Tag-$role.stdout" | Where-Object {$_ -match 'RESULT|SOURCE_CHECK|WIRE_CHECK|registered'}
"STAGE18_TEST_COMPLETED role=$role tag=$Tag"
