# Windows 鲜牛代理与局域网中转

本分支在现有星渡 Windows 工具里增加鲜牛代理检测入口。设备仍然连接星渡的局域网 HTTP 代理，星渡只会在验证成功后将外部 TCP 请求转交给鲜牛的回环代理。

```text
配置了 HTTP 代理的局域网设备
            ↓ HTTP / CONNECT（TCP）
       Windows 星渡中转
            ↓ 已验证的 127.0.0.1 代理
          鲜牛客户端
```

## 使用

1. 在鲜牛官方客户端中登录，选择目标游戏或主机并开启加速。
2. 在星渡 Windows 首页点击“检测并共享鲜牛代理”。检测在后台进行。
3. 检测器只检查鲜牛主进程和能够归属于鲜牛安装目录的辅助进程，仅探测这些进程持有的 IPv4 回环监听端口。
4. 候选端口必须接受 HTTP CONNECT，并在隧道内完成对 `example.com:443` 的 TLS 握手与证书校验。仅端口开放、返回 HTTP 200 或名称包含 socks，都不构成通过。
5. 检测通过后，沿用现有游戏模式的 LAN 地址规划、设备访问控制与启动失败回滚。按“局域网共享”页面显示的地址为目标设备配置 HTTP 代理。
6. 鲜牛的游戏选择、登录、节点和加速状态继续在鲜牛客户端管理。重新启动共享时会重新检测，不直接复用上次保存的端口。

命令行和打包程序的后端同样会在创建 LAN 监听之前重验鲜牛端口；与配置不匹配时要求重新联动。高级启动保留手动指定的网卡与设备名单。取消检测或在后端预检期间停止，不会在检查结束后自动开启共享。

如果提示没有找到通过验证的 HTTP CONNECT 代理，当前版本不会启动鲜牛共享，也不会把控制端口当成代理。可以保持原来的独立核心或系统代理配置继续使用。

诊断命令（在 `portable` 目录下）：

```powershell
python -m portalproxy.windows_accelerator
python -m portalproxy.windows_accelerator --probe
```

第一条只读取安装、进程和监听状态；第二条另做有限候选的协议检查，会尝试经候选代理连接上述测试站点。通过测试站点只证明该端口能中转经过证书校验的 TCP 隧道，**不证明目标游戏已命中鲜牛规则或获得延迟改善**。

## 游戏加速的边界

- 当前星渡中转支持 HTTP / CONNECT TCP，没有 UDP、SOCKS 转 HTTP、Windows 透明网关、驱动转发或 ICS/NAT 共享实现。
- PS Portal 串流、主机游戏联机以及不使用手动 HTTP 代理的游戏，可能有独立 UDP 流量。设置了 HTTP 代理不代表这些流量也经过星渡或鲜牛。
- 鲜牛可能只捕获特定游戏进程、目的地址或驱动流量。即使代理协议验证通过，也仍需用真实目标设备测试流量路径、延迟与丢包，才能判断加速效果。
- IPv6 和 `0.0.0.0` 等通配监听目前仅作为诊断信息，不自动共享。
- 检测失败、TLS 证书不受信任或候选不可达时，不静默回退到另一种协议。

如果本机鲜牛只有驱动模式，没有可复用的 HTTP CONNECT 入口，下一步应单独评估其官方主机/网关共享功能，以及 Windows 转发流量能否命中加速规则。在完成这些实测前，不将本分支描述为 UDP 游戏加速器。

## 本地分析依据

本次检查的客户端版本为 5.3.1.8。REA 的静态检查确认 `gatewayapiv2.dll` 是 x86 PE，未包含 .NET CLI 元数据，其 SHA-256 为：

```text
3fb046d85f8c62442350643fcb666d8a0f333ed2c2b0a3dd8bc7111eef9e9e14
```

对应 REA 元数据记录：`ev_ec3087480d7e0507b704eca7f57cc920832ef1faddef4f3c1cbc1a416b050fc2`；PE 资源记录：`ev_f5d1bc76cc20ff7551f5d2b714402da895b3ac20a10b614f87ee49d54d1d1a09`。

安装目录包含网关、SOCKS 和网络驱动组件；静态导出名称及字符串是分析线索，没有建立私有 API 的调用约定、代理协议或运行行为。当前环境没有配置原生反编译引擎，因此本次不宣称完成原生代码反编译。

在“已登录、尚未确认开启目标加速”的本机状态下，检测到主进程的一个回环 TCP 监听，实际 HTTP CONNECT 被拒绝，结果为 `probe_failed` / `connect_rejected`。此状态不能启用鲜牛共享；开启具体游戏或主机加速后的结果与真实设备加速效果仍待验证。

客户端以管理员权限运行时，普通进程查询可能读不到 `ExecutablePath`，因此主进程的准确名称可以用于发现；辅助进程必须有可归属的安装路径，不能仅凭通用进程名认定。诊断不读取鲜牛账号、Cookie、会话配置或日志，也不调用其私有控制接口。

## 开发与验收

分支：`feat/windows-xianniu-lan-relay`。基于 `836bb9b` 的桌面功能分支；`main` 当前仅含路由器版，不能直接从它开发 Windows 界面。

```powershell
cd portable
python -m unittest discover -s tests -p test_windows_accelerator.py -v
python -m unittest discover -s tests -p test_xianniu_desktop.py -v
python -m unittest discover -s tests -p test_xianniu_backend.py -v
python -m unittest discover -s tests -p test_existing_proxy.py -v
python -m portalproxy.desktop
```

自动化测试覆盖错误协议拒绝、限时检测、旧结果丢弃、配置不变、重新验证和原有 LAN 中转。模拟测试与本机检测均不能代替真实设备游戏验收。

2026-10-23 本地验收：执行 521 项 Python 测试，结果通过，其中 83 项因对应平台、原生核心或显式 GUI 条件未满足而跳过；新增检测、桌面事务和后端检查测试均执行通过。另做 Windows Tk 检查，确认中文按钮、能力说明、忙碌状态和取消恢复。实测已登录鲜牛的候选端口被检测器与后端共同拒绝。本次未产出新的 Windows 发布安装包，未完成真实设备游戏或 UDP 验收。
