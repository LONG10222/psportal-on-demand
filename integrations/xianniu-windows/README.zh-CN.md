# 星渡 · 鲜牛 Windows 游戏共享预览 0.1.0

这是单独安装的原生 provider 预览，保留星渡既有模式、订阅和日常鲜牛客户端。不是鲜牛官方发行版，未签名。整包解压，双击 `InstallPreview.cmd` 安装到当前用户的 `%LOCALAPPDATA%\Programs\StarPassXianniuPreview\0.1.0`，也可直接运行 `StartPreview.cmd`。不需要另装 Python，不要求管理员权限。

1. 打开开始菜单中的 StarPass Xianniu Preview。官方会话和配置使用 CurrentUser DPAPI 保存在 `%LOCALAPPDATA%\StarPassXianniuPreview`，不会写入程序目录。
2. 使用鲜牛官方微信二维码登录，由用户自行扫码授权。界面显示官方剩余秒数和试用秒数，分别展示，每 60 秒刷新。未获取时显示未知。
3. 读取邻居缓存或填写设备 IPv4，勾选允许共享的设备。缓存中的地址不等于设备已在线，也不会自动授权。
4. 模糊搜索游戏，选择区服，获取官方线路。高级设置填写电脑实际 LAN IPv4，HTTP 默认 18082，SOCKS5 默认 18092；默认只监听本机。
5. Windows 独立管理会话前，需先停止同账号的其他入口，并在高级设置明确确认独占。点击启动后按官方规则恢复计时、start 和每 120 秒 token 续期。端口冲突会在 start 前报错。没有多游戏并发支持。
6. 支持 HTTP 代理的设备填写电脑实际 LAN IP 和 HTTP 端口。PC 的支持 SOCKS5 UDP 的客户端可使用 SOCKS5 入口。Steam 商店明确域名默认直连；其余公开 IPv4 目标经 provider，失败不会切换直连。
7. 点击“停止本预览共享”关闭自己的监听和连接。独立模式只停止本预览本次成功 start 的官方会话；复用模式从不调用官方 start/stop、暂停或恢复。停止不自动暂停账号会员计时，需在官方客户端核对。

本预览独占会话运行时，也可点击“停止并暂停计时”，先确认自己的官方 stop 成功，再调用官方暂停并刷新状态；复用模式拒绝此操作。下一次独立启动会按官方规则恢复计时。

若电脑本机可通而外部设备超时，先检查网络和入站规则。可阅读 `AllowLan.ps1` 后手动运行 `AllowLan.cmd`，自行确认 Windows 提权。助手只创建两个固定名称的预览规则，限定本程序、当前 LAN IP、已选设备及 Private 网络；TCP 只开放两个代理端口，UDP 动态端口仍限定本程序与已选来源。不会关闭防火墙或改动已有其他规则。改端口/设备后，先以管理员运行 `AllowLan.ps1 -Remove` 删除这两条，再重新授权。普通权限安装本身不自动授权入站。

HTTP/CONNECT 不包含 UDP。PS5/Switch 的手动 HTTP 代理不能证明联机游戏、语音或 NAT 已经经过电脑。当前不修改默认网关、DNS、DHCP、路由、ARP、热点、ICS、防火墙或 Windows 系统代理。完整主机 UDP 入口的决定见 DESIGN.zh-CN.md；现场结果与未验收项目见 VALIDATION.md。

复用现有会话只允许沿用其原游戏、区服和线路。CLI 可用 `--import-private 私有文件 --borrowed-owner 来源名称` 导入用户合法会话，文件不随软件分发；import 不调用官方接口。官方 token 拒绝后暂停新连接，连续三次续期失败停止入口，不自动重登录或切换 provider。

崩溃后 Windows 会回收本进程套接字；未确认完成的独立 start/stop 留下 ownership.json，下一次启动不会自动停止未知会话或继续 start。请先在官方客户端核对，由开发验证流程处理。令牌过期自动恢复、应用驱动捕获、长时间稳定性、正式签名/升级/卸载器尚未验收。停止后可删除独立程序目录与开始菜单快捷方式；私有账号目录需自行决定是否保留。

源码运行：`python run.py`。先将 `src` 和相邻 `../xianniu-router/src` 加入 PYTHONPATH 再运行 `python -m unittest discover -s tests -v`。构建环境使用 Python 3.12、PyInstaller 6.16.0，运行 `python build.py`。程序未包含官方 EXE/驱动，也不包含实际账号资料。
