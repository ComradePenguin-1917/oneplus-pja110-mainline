$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$sshArgs = @('-F', 'none', '-tt', '-i', "$taskRoot/out/usb-ncm-20261013/ssh/client_key_host",
    '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
    '-o', "UserKnownHostsFile=$taskRoot/out/native-install-20261017/known_hosts",
    '-o', 'HostKeyAlias=172.16.42.1', '-o', 'ConnectTimeout=6', 'penguin@10.4.183.195')
& 'C:/Windows/System32/OpenSSH/ssh.exe' @sshArgs 'sudo /bin/sh /home/penguin/single-battery/install.sh'
$singleBatteryExit = $LASTEXITCODE
if ($singleBatteryExit -notin @(0,255)) { throw "Single battery update exited $singleBatteryExit" }
