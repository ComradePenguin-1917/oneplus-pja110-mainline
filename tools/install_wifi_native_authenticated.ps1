$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$sshArgs = @('-F', 'none', '-tt', '-i', "$taskRoot/out/usb-ncm-20261013/ssh/client_key_host",
    '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
    '-o', "UserKnownHostsFile=$taskRoot/out/native-install-20261017/known_hosts",
    '-o', 'HostKeyAlias=172.16.42.1', '-o', 'ConnectTimeout=6', 'penguin@10.4.183.195')
& 'C:/Windows/System32/OpenSSH/ssh.exe' @sshArgs 'sudo /bin/sh -c ''/bin/sh /home/penguin/wifi-bringup/native-test/install.sh > /home/penguin/wifi-bringup/native-test/install.log 2>&1; status=$?; cat /home/penguin/wifi-bringup/native-test/install.log; exit $status'''
$installExit = $LASTEXITCODE
if ($installExit -notin @(0,255)) { throw "Native Wi-Fi installation exited $installExit; inspect install.log" }
