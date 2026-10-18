# 本机验证记录

日期：桌面整合回归 2026-10-19；既有 iOS/native 构建记录 2026-10-18。环境：Apple Silicon Mac、macOS 27.0.1、Xcode 27.0、iOS 27.0 Simulator。GitHub 分支 `feat/clash-style-lan-sharing`、草稿 PR #4，本地后续分支 `local/lan-runtime`，基于云端 `872f61b3`，整合 `feat/cross-platform-ui-parity` 的 `0980a75`。

| 检查 | 结果 | 证据 |
|---|---|---|
| portable 全量回归，启用 Tk、真实 Mihomo 与原 native 可执行文件 | 247 项：238 通过、9 跳过 | `evidence/desktop-tests.log` |
| 当前 native Go engine/mobile 源码 | engine 测试通过；mobile 包无独立测试 | `evidence/native-tests.log` |
| iPhone 17 / iOS 27.0 Simulator XCTest | 19 项：18 通过、1 跳过 | `evidence/ios-tests.log` |
| 最终 iOS 界面构建 | BUILD SUCCEEDED | `evidence/ios-build.log` |
| iOS 编译产物资源/隐私声明有限检查 | 通过 | `evidence/ios-resource-audit.json` |
| iOS 源码结构检查 | 7 通过、1 跳过 | `evidence/ios-source-check.log` |
| macOS 开发启动器 | 已编译、ad-hoc 签名校验通过、实际打开窗口 | `local-launcher.c`、本机窗口观察 |

## 实际验证的行为

- Tk 真实窗口：监听运行期间切换中英文和深浅主题，不更换后端进程、不丢失输入、页面、日志或未保存状态。
- 一键流程：受控下载 fixture 返回 YAML 和真实格式的套餐字段；自动填地址和端口，保存、启动监听后展示 Wi-Fi 接入说明；未知流量字段保持未知，超额时余额归零；过大/异常日期不会使窗口崩溃。
- 端口：未占用时保持原值；被实际 socket 占用时选择可绑定的备用端口。网络解析只选择物理私网接口，排除 VPN/回环与过大自动接入范围。
- 完整 profile：真实 Mihomo 1.19.32 受控 HTTP 转发；保留原策略组、规则及源文件，运行副本关闭 TUN 和额外 DNS 服务监听；连接释放后回收自己拥有的核心。
- 现有代理联动：受控 HTTP 上游的 HTTP 与 CONNECT 转发通过；停止本程序后，上游服务仍保持可用。该测试没有操作正在使用的 Clash。
- 设备状态：真实本机三条 CONNECT 连接按同一 IP 去重为一台活跃设备，拒绝来源不计入设备；关闭后连接数下降，最近记录保留。另以数据层测试五分钟过期；没有改变系统接口来模拟多台真实手机。
- 节点控制：真实 Mihomo 与两个可控延迟的本机 HTTP 上游，验证组名/节点名中的斜杠及国旗字符、手动切换、最低延迟选择、周期重测、手动退出自动、全部测速失败保留原选择、核心回收后恢复手动选择，以及后台任务不唤醒已休眠核心。修复生成 JSON 中 emoji 代理组正则被 YAML 解析器拒绝的问题。
- 窗口与 IPC：真实 Tk → 独立子进程 → 真实 Mihomo → 受控本机上游，通过界面加载并切换节点；实际建立 CONNECT 后设备数与首页状态改变，语言热切换不改 PID，关闭连接后回到等待状态，偏好设置落盘。联动模式的节点按钮禁用，命令层也拒绝控制现有 Clash。
- GitHub 整合：纳入 Windows/Linux 只读接口识别、系统代理识别与精确 PyYAML/LibYAML 来源和许可证校验。修复 sysfs 比较中未规范化的路径，新增符号链接根路径回归；没有放开虚拟接口限制。JSON 订阅先严格解析再转为 Unicode 运行副本，支持标准代理对形式的国旗字符，原文件不变。native 许可证范围脚本的 9 项单元测试通过。
- HTTPS 运行环境：本机搬迁的 Python 默认 CA 数量为 0；仅在 macOS、无自定义证书路径且无已加载根证书时补载系统 `/etc/ssl/cert.pem`，保持 `CERT_REQUIRED` 和域名校验。三项证书回归通过，另用公开 PyPI 元数据实际完成 66,402 字节的 TLS 校验下载；没有使用用户订阅。精确 PyYAML wheel 审查及两份源归档 SHA 校验也在本机通过。
- Windows 云端测试修复：模拟 Linux 的大小写敏感环境使用普通映射，避免 Windows `os.environ` 本身合并大小写；原始许可证通过 Git 属性保留 LF 字节，未放宽字节相等或完整性校验。
- Clash 缓存：按官方 v2.5.8 文件格式只读提取当前订阅名称及套餐统计，真实本机界面已显示；单元测试验证不输出 URL/令牌，原文件字节不变。标记“缓存、只读、非实时”。
- iOS 真实 XCFramework：实际 socket 的 HTTP、CONNECT、访问来源拒绝、Stop 关闭连接及重启测试通过。这里只证明受控私网直连传输，不等于真实外网加密节点验收。
- iOS 网络逻辑：Wi-Fi/有线/蜂窝分类；蜂窝不会单独证明热点开启；必须有真实私网 bridge 且用户确认；按实际掩码生成名单。语言/主题热切换不重启引擎、不丢失设置。
- 最终手机界面已在 Xcode Device Hub 的独立模拟器中人工检查：中文首页、订阅输入、网络类型、停止状态及设备 Wi-Fi 说明均正常显示，未启动实际订阅或局域网服务。截图见 `evidence/ios-simple-home-zh.png`。

## 跳过与验收边界

portable 的 9 项跳过分别涉及冻结应用、打包启动/转发、X11、其他平台证明。当前运行入口是本机开发启动器，不能据此声称新的独立发行包、Windows/Linux 或公共分发许可审查全部通过。

iOS 唯一 XCTest 跳过项是“真实硬件的数据保护”，模拟器无法建立该证明。另一个源码结构检查跳过项只检查特定 `dist/bindings` 生成头路径；本轮实际 XCFramework 的真实生成头、ABI 和桥接已由构建及传输测试验证。

模拟器无法证明 iPhone 蜂窝、个人热点接口可见性、后台服务、真实游戏机和实际订阅连通。iOS 使用原来的前台生命周期，不增加后台模式。没有填写或测试用户真实订阅，没有切换原 Clash 的节点或设置。

用户本轮反馈其手机已接入且可以使用，已记录为用户反馈，不作为开发侧独立实测。新增设备统计与实时节点功能目前限定 Mac 外部核心／联动路径；移动端及 embedded 不包含这些新面板。统计只表示客户端与本程序的连接，不表示远端目的站成功，也不能枚举整个 Wi-Fi。

Clash 的流量“缓存统计”和本程序直接导入订阅的响应头统计均是快照；流量单位采用 1024 进位的 KiB/MiB/GiB，避免同一原始字节数因进位口径产生不同数字。缺失总流量不推断为无限额度。

## 复现

桌面：在 `portable` 目录，使用本机隔离 Python，设置 `PSPORTAL_TK_TEST=1`、`MIHOMO_BINARY` 与 `PSPORTAL_NATIVE_BINARY` 后运行：

```sh
python -m unittest discover -s tests -v
```

原 native 可执行文件与完整 Mihomo 副本位于本工作区 `work/desktop-cores`，只用于当前本机验证。当前 Go 源码的新增接口由独立源码测试和本轮 iOS XCFramework 构建验证。

iOS：先按 `native/ios/scripts/build-engine.sh` 构建真实框架，再生成 Xcode 工程；本轮使用独立设备 `OnDemand Development`，UUID `E5A8F631-B016-488A-8409-E1A25D457C02`，避免与另一个验证对话共用模拟器。

```sh
xcodebuild test -project native/ios/PSPortalHost.xcodeproj \
  -scheme PSPortalHost \
  -destination 'platform=iOS Simulator,id=E5A8F631-B016-488A-8409-E1A25D457C02' \
  CODE_SIGNING_ALLOWED=NO -parallel-testing-enabled NO
```

完整源码构建仍需固定的 Go/mobile 依赖、XcodeGen 与 Xcode。旧构建曾提示 `github.com/RyuaNerin/testingutil` 无许可文本；新整合的收集器按全部生产目标的真实依赖图审查，不再凭模块名推断测试用途，生产依赖缺失许可仍会失败。旧 iOS 构建不会因脚本更新自动变为重新审计过的产物；本轮没有做公开发行验收。云端结果与原始日志链接见 `GITHUB-STATUS.md`，参考记录见 `SOURCE-REFERENCE.md`。
