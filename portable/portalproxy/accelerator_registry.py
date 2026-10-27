"""Read-only accelerator discovery and explicit provider capability declarations."""
from dataclasses import dataclass
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    title: str
    display_pattern: str
    process_names: tuple
    directories: tuple
    website: str
    built_in: bool = False


PROVIDERS=(
    ProviderSpec('xianniu','鲜牛',r'鲜牛|xianniu',('xianniu.exe',),('xianniu',),'https://www.xianniu.com/',True),
    ProviderSpec('uu','网易 UU',r'网易.*UU|UU.*加速|UU Booster',('uu.exe','uu_launcher.exe'),('Netease/UU','UU'),'https://uu.163.com/'),
    ProviderSpec('leigod','雷神',r'雷神.*加速|leigod',('leigod.exe','leishen.exe'),('leigod','Leigod','雷神加速器'),'https://www.leigod.com/'),
)

INVENTORY=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$installations=@()
foreach($root in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
 Get-ItemProperty $root -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match '鲜牛|xianniu|网易.*UU|UU.*加速|UU Booster|雷神.*加速|leigod'} | ForEach-Object {
  $installations+=@{display_name=[string]$_.DisplayName;location=[string]$_.InstallLocation;icon=[string]$_.DisplayIcon}
 }
}
$processes=@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -match '^(XianNiu|UU|UU_launcher|Leigod|Leishen)$'} | ForEach-Object {
 @{pid=$_.Id;name=$_.ProcessName+'.exe';path=[string]$_.Path}
})
@{installations=$installations;processes=$processes}|ConvertTo-Json -Depth 4 -Compress
'''


def inventory():
    if sys.platform!='win32':return {'installations':[],'processes':[],'error':'unsupported_platform'}
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',INVENTORY],capture_output=True,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:return {'installations':[],'processes':[],'error':'inventory_failed'}
        data=json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(data,dict):raise ValueError()
        return data
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {'installations':[],'processes':[],'error':'inventory_unavailable'}


def absolute_path(value):
    if not isinstance(value,str):return None
    value=os.path.expandvars(value.strip().strip('"'))
    if not ntpath.isabs(value) or value.startswith(('\\\\','//')) or any(c in value for c in '\r\n\0'):return None
    return value


def discover(data=None, *, exists=None):
    data=inventory() if data is None else data
    exists=exists or (lambda p:Path(p).exists())
    output=[]
    for spec in PROVIDERS:
        roots=[];executables=[];pids=[]
        for row in data.get('installations',[])[:96]:
            if not isinstance(row,dict) or not re.search(spec.display_pattern,str(row.get('display_name','')),re.I):continue
            location=absolute_path(row.get('location',''))
            if location and exists(location):roots.append(location)
            icon=str(row.get('icon','')).strip()
            match=re.match(r'^"([^"]+\.exe)"(?:,[-\d]+)?$',icon,re.I) or re.match(r'^(.+\.exe)(?:,[-\d]+)?$',icon,re.I)
            executable=absolute_path(match[1]) if match else None
            if executable and exists(executable):
                roots.append(ntpath.dirname(executable));executables.append(executable)
        for base in (os.environ.get('ProgramFiles(x86)'),os.environ.get('ProgramFiles'),os.environ.get('LOCALAPPDATA')):
            if not base:continue
            for directory in spec.directories:
                location=ntpath.join(base,directory.replace('/','\\'))
                if exists(location):roots.append(location)
        for row in data.get('processes',[])[:96]:
            if not isinstance(row,dict) or str(row.get('name','')).casefold() not in spec.process_names:continue
            executable=absolute_path(row.get('path',''))
            owned=bool(executable and any(ntpath.normcase(executable).startswith(ntpath.normcase(root).rstrip('\\')+'\\') for root in roots))
            if owned or not executable and roots:
                if type(row.get('pid')) is int:pids.append(row['pid'])
            if owned and exists(executable):executables.append(executable)
        for root in list(roots):
            for name in spec.process_names:
                candidate=ntpath.join(root,name)
                if exists(candidate):executables.append(candidate)
        roots=list(dict.fromkeys(roots));executables=list(dict.fromkeys(executables))
        output.append({'key':spec.key,'title':spec.title,'installed':bool(roots or pids),'running':bool(pids),
          'roots':roots,'executables':executables,'process_ids':pids,'website':spec.website,
          'capabilities':{'built_in':spec.built_in,'public_catalog_reader':spec.key=='xianniu',
            'account_provider':spec.key=='xianniu','native_tcp_udp':spec.key=='xianniu',
            'standard_proxy_requires_verification':True,'whole_lan_game_udp_verified':False},
          'inventory_error':data.get('error','')})
    return output


def launch_client(provider):
    candidates=provider.get('executables',[])
    if not candidates:raise ValueError('没有找到已验证的客户端启动文件，请先安装官方客户端')
    executable=absolute_path(candidates[0])
    if not executable or not Path(executable).is_file() or not executable.lower().endswith('.exe'):
        raise ValueError('客户端路径已变化，请重新检测')
    subprocess.Popen([executable],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

