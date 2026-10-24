param([switch]$Persistent)
$ErrorActionPreference='Stop'
$target=Join-Path $PSScriptRoot '../out/usb-ncm-20261013'
[IO.Directory]::CreateDirectory($target)|Out-Null
$adapters=@(Get-NetAdapter | Where-Object MacAddress -eq '02-1A-11-00-00-02')
if($adapters.Count -ne 1){throw 'Expected exactly one phone NCM adapter'}
$adapter=$adapters[0]
if($adapter.InterfaceDescription -notmatch '^UsbNcm Host Device(?: #\d+)?$'){throw 'Unexpected adapter driver'}
$device=Get-CimInstance Win32_NetworkAdapter | Where-Object InterfaceIndex -eq $adapter.ifIndex
if($device.PNPDeviceID -notmatch '^USB\\VID_1D6B&PID_010A&MI_0[02]\\'){throw 'Adapter is not the expected PJA110 NCM function'}
$existing=@(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue)
$existing | Select-Object IPAddress,PrefixLength,PrefixOrigin | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $target 'windows-ip-before.json')
$conflict=@(Get-NetRoute -AddressFamily IPv4 | Where-Object { $_.DestinationPrefix -eq '172.16.42.0/24' -and $_.InterfaceIndex -ne $adapter.ifIndex })
if($conflict.Count){throw 'Phone test subnet conflicts with another interface'}
$addressStore = if ($Persistent) { 'PersistentStore' } else { 'ActiveStore' }
$configured=@(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -PolicyStore $addressStore -ErrorAction SilentlyContinue)
if(-not ($configured | Where-Object IPAddress -eq '172.16.42.2')){
    if ($Persistent) {
        # This Windows provider rejects New-NetIPAddress -PolicyStore PersistentStore.
        # netsh explicitly supports persisting this one adapter's static address.
        & netsh.exe interface ipv4 set address "name=$($adapter.ifIndex)" source=static address=172.16.42.2 mask=255.255.255.0 gateway=none store=persistent
        if ($LASTEXITCODE -ne 0) { throw "netsh failed with exit $LASTEXITCODE" }
    } else {
        New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress 172.16.42.2 -PrefixLength 24 -PolicyStore ActiveStore -ErrorAction Stop | Out-Null
    }
}
if(-not (Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 | Where-Object IPAddress -eq '172.16.42.2')){throw 'Expected NCM address was not installed'}
if($Persistent -and -not (Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -PolicyStore PersistentStore | Where-Object IPAddress -eq '172.16.42.2')){throw 'Persistent NCM address was not installed'}
$state=[ordered]@{
    InterfaceIndex=$adapter.ifIndex
    AdapterName=$adapter.Name
    PnpDeviceId=$device.PNPDeviceID
    Address=@(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength)
    Routes=@(Get-NetRoute -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 | Select-Object DestinationPrefix,NextHop)
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $target 'windows-network.json')
$state | ConvertTo-Json -Depth 5
