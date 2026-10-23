# 独立加速器模式（Windows 预览）

加速器模式复用星渡原有的局域网 HTTP/CONNECT 转发核心，和“游戏 / 混合 / Clash”三个模式分别保存来源与网络偏好。切入时保存原模式的私有配置，切回时恢复原订阅、上游和 LAN 地址；不会因为选择模式就自动启动中转。

当前首个服务是 **Steam 商店、社区和支持代理的文字聊天**。本模式尚未实现游戏 UDP、Steam Link 串流或语音中转。

## 加速器怎么接入

| 接入方式 | 适用情况 | 星渡验证什么 |
| --- | --- | --- |
| 电脑网络出口 | 客户端通过驱动、网卡或路由处理 Windows 发出的流量 | 星渡将获准的 Steam TCP 请求从电脑发出；加速器是否接管仍需实测 |
| HTTP 代理入口 | 加速器提供本机标准 HTTP/CONNECT 端口 | 代理 CONNECT、Steam 商店 TLS 域名及系统证书链 |
| SOCKS5 代理入口 | 加速器提供本机无认证 SOCKS5 端口 | SOCKS5 握手与连接、Steam 商店 TLS 域名及系统证书链 |

HTTP/SOCKS5 入口仅接受 `127.0.0.1` 和 1024–65535 的明确端口，当前不支持账号密码。仅端口开放、返回 HTTP 200 或名字里有 socks 都不足以通过验证。每次后端启动时重新检查；失败会停止，不静默切换到其他出口。

这是通用协议接入，不是“所有品牌均已验证兼容”。鲜牛是首个自动检测适配器；其他加速器可填写其明确提供的标准入口。仅提供私有驱动或 SDK 的产品，需确认能接管星渡发出的 Windows 连接。不要从“加速器正在运行”推断“中转流量已经加速”。

## 使用流程

Windows 本地预览包应整包解压，双击 `StartAcceleratorPreview.cmd`。它打开同一个星渡程序，并使用 `%LOCALAPPDATA%\StarPassAcceleratorPreview` 下的独立预览配置；其他模式仍可在同一界面切换。不要仅复制 EXE，旁边的运行文件夹也需要保留。

1. 在电脑的加速器客户端中选择 Steam／商店社区，开启加速并保持运行。
2. 打开本分支的星渡 Windows 版，选择“加速器模式”。此模式无需订阅或 Mihomo 核心。
3. 选择接入方式。标准代理填写客户端给出的本机端口；不提供标准入口时选择“电脑网络出口”。鲜牛可用检测按钮检查其可复用入口。
4. 点击“启动加速器中转”。星渡复用现有 LAN 检测、来源 IP 白名单、连接限制和启动失败回滚。
5. 手机与电脑连接同一可达局域网。在“局域网共享”页查看实际电脑地址与端口，不依赖文档中的示例地址。
6. 安卓当前 Wi-Fi 支持“自动配置代理”时，填写界面显示的 `http://电脑地址:端口/accelerator.pac`。Steam 文档域名走星渡，其他域名直连；Steam 目标不设置直连回退。
7. 如果手机系统没有自动代理选项，可使用“手动代理”，填写电脑地址与端口，不填认证。手动方式下，遵循 Wi-Fi 代理的非 Steam 请求会因服务范围限制而被拒绝；测试后恢复手机代理设置。
8. 先在手机浏览器分别访问 Steam 商店和社区，再验证 Steam / Steam Chat 应用。浏览器成功不代表 App 的全部连接都使用 Wi-Fi 代理，也不代表文字聊天、推送和语音全部成功。

普通来源的订阅导入在加速器模式中禁用。切回游戏、混合或 Clash 后可以继续编辑原来源；加速器模式的端口、设备列表和接入方式留作下次使用。

## 验证边界

后端只允许 Steam 官方网络说明列出的域名及标签边界内的子域名，端口为 TCP 80/443：`steampowered.com`、`steamcommunity.com`、`steamgames.com`、`steamusercontent.com`、`steamcontent.com`、`steamstatic.com`、`akamaihd.net`。最后一项是共享 CDN，不是 Valve 独占空间。所有 DNS 答案都必须是公网地址；电脑出口的连接固定到已检查的数字 IP。不会为了测试而开放私网目的地。

HTTPS 通过 CONNECT 透明转发，由手机自身验证目标站证书；不读取 Steam 登录内容或聊天内容。切换模式所需的原配置快照只保存在本机私有配置文件内，不进入连接指南、PAC 或运行状态输出。

参考：[Steam 官方网络说明](https://help.steampowered.com/en/faqs/view/2EA8-4D75-DA21-31EB)、[Steam 手机应用说明](https://store.steampowered.com/mobile)。

## 已做与尚待完成的实测

本机未开启鲜牛 Steam 加速的基线测试中，新中转核心成功连接 Steam 商店，TLS 验证通过并收到 HTTP 200；Steam 社区连接超时。这说明转发链路已有成功样例，也说明不能据此宣称社区已加速。

当前没有完成安卓手机真实接入、鲜牛开启 Steam 加速后的前后对比或其他品牌现场验收；状态中的 `acceleration_verified` 保持 `false`。这些需要用户有空时用目标客户端和手机继续测试。预览包也不代表正式 Windows 运行时发布审核已经完成。

## 开发验证

```powershell
cd portable
python -m unittest discover -s tests -v
$env:PSPORTAL_TK_TEST = '1'
python -m unittest discover -s tests -p test_accelerator_gui.py -v
python -m portalproxy.desktop
```

核心组件：`steam_host.py`（电脑出口与服务边界）、`accelerator_proxy.py`（通用 HTTP/SOCKS5）、`accelerator_pac.py`（选择性自动代理）、`windows_accelerator.py`（鲜牛适配）、原有 `proxy.py`（共享转发核心）。

本地 Windows 预览沿用现有构建流程：创建 `portable/.venv-build`、安装 `requirements-build.txt`、运行 `scripts/fetch_yaml_sources.py`、运行 `build.py`。为便于打开独立预览配置，将 `launchers/StartAcceleratorPreview.cmd` 和本说明复制到 `dist/PSPortalProxy` 后，重新压缩整个目录即可。基础预览无需附带 Mihomo；公开发布的完整运行时审核另行执行。
