"""Read-only Windows hotspot detection and explicit sharing targets."""
import ipaddress,json,os,subprocess,sys
from .setup import _bounded_json,_lan_result,_rows,discover_lan

QUERY=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding $false
$state='unknown'
try {
 $profile=[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
 if ($null -ne $profile) {
  $manager=[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
  $state=[string]$manager.TetheringOperationalState
 }
} catch {}
$adapters=@(Get-NetAdapter -IncludeHidden | ForEach-Object { @{index=[int]$_.ifIndex;name=[string]$_.Name;up=([int]$_.InterfaceOperationalStatus -eq 1);virtual=[bool]$_.Virtual;description=[string]$_.InterfaceDescription} })
$addresses=@(Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { @{index=[int]$_.InterfaceIndex;address=[string]$_.IPAddress;prefix=[int]$_.PrefixLength;preferred=([int]$_.AddressState -eq 4)} })
@{state=$state;adapters=$adapters;addresses=$addresses} | ConvertTo-Json -Depth 4 -Compress
'''


def parse_hotspot(output):
    data=_bounded_json(output)
    if not isinstance(data,dict):raise ValueError('无法读取热点状态')
    result={'state':str(data.get('state','unknown')),'network':None}
    if result['state'].lower()!='on':return result
    candidates=[]
    for adapter in _rows(data.get('adapters'),256):
        description=str(adapter.get('description','')).lower()
        if adapter.get('up') is not True or adapter.get('virtual') is not True or 'wi-fi direct' not in description:continue
        for row in _rows(data.get('addresses')):
            if row.get('index')!=adapter.get('index') or row.get('preferred') is not True:continue
            try:candidates.append(_lan_result(adapter['name'],row['address'],row['prefix']))
            except (ValueError,KeyError):continue
    if len(candidates)!=1:
        result['state']='ambiguous';return result
    result['network']=candidates[0]
    return result


def inspect():
    result={'lan':None,'hotspot':{'state':'unsupported','network':None}}
    try:result['lan']=discover_lan()
    except ValueError:pass
    if sys.platform=='win32':
        try:
            response=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',QUERY],capture_output=True,
                text=True,encoding='utf-8-sig',errors='replace',timeout=18,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if response.returncode==0:result['hotspot']=parse_hotspot(response.stdout)
        except (OSError,ValueError,subprocess.SubprocessError):pass
    return result


def selected_network(inventory,target):
    network=inventory.get('lan') if target=='lan' else inventory.get('hotspot',{}).get('network') if target=='hotspot' else None
    if not network:raise ValueError('请先连接局域网，或开启 Windows 热点后重新检测')
    checked=_lan_result(network['interface'],network['host'],ipaddress.ip_network(network['subnet']).prefixlen)
    if checked['subnet']!=network['subnet']:raise ValueError('接入网络地址不一致，请重新检测')
    return checked


def open_hotspot_settings():
    if sys.platform!='win32':raise ValueError('移动热点入口仅适用于 Windows')
    os.startfile('ms-settings:network-mobilehotspot')
