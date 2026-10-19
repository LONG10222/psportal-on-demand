# 本机验证记录

日期：2026-10-18。环境：Apple Silicon Mac、macOS 27.0.1、Xcode 27.0、iOS 27.0 Simulator。以下为原 `local/clash-style-desktop` 开发阶段的历史记录，随后保存到 PR #4（`49a8467`）；不代表后续跨平台改动已通过这些验证。

| 检查 | 结果 | 证据 |
|---|---|---|
| portable 全量回归，启用 Tk、真实 Mihomo 与原 native 可执行文件 | 202 项：193 通过、9 跳过 | `evidence/desktop-tests.log` |
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
- Clash 缓存：按官方 v2.5.8 文件格式只读提取当前订阅名称及套餐统计，真实本机界面已显示；单元测试验证不输出 URL/令牌，原文件字节不变。标记“缓存、只读、非实时”。
- iOS 真实 XCFramework：实际 socket 的 HTTP、CONNECT、访问来源拒绝、Stop 关闭连接及重启测试通过。这里只证明受控私网直连传输，不等于真实外网加密节点验收。
- iOS 网络逻辑：Wi-Fi/有线/蜂窝分类；蜂窝不会单独证明热点开启；必须有真实私网 bridge 且用户确认；按实际掩码生成名单。语言/主题热切换不重启引擎、不丢失设置。
- 最终手机界面已在 Xcode Device Hub 的独立模拟器中人工检查：中文首页、订阅输入、网络类型、停止状态及设备 Wi-Fi 说明均正常显示，未启动实际订阅或局域网服务。截图见 `evidence/ios-simple-home-zh.png`。

## 跳过与验收边界

portable 的 9 项跳过分别涉及冻结应用、打包启动/转发、X11、其他平台证明。当前运行入口是本机开发启动器，不能据此声称新的独立发行包、Windows/Linux 或公共分发许可审查全部通过。

iOS 唯一 XCTest 跳过项是“真实硬件的数据保护”，模拟器无法建立该证明。另一个源码结构检查跳过项只检查特定 `dist/bindings` 生成头路径；本轮实际 XCFramework 的真实生成头、ABI 和桥接已由构建及传输测试验证。

模拟器无法证明 iPhone 蜂窝、个人热点接口可见性、后台服务、真实游戏机和实际订阅连通。iOS 使用原来的前台生命周期，不增加后台模式。没有填写或测试用户真实订阅，没有切换原 Clash 的节点或设置。

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

完整源码构建仍需固定的 Go/mobile 依赖、XcodeGen 与 Xcode。许可收集器提示一个测试辅助模块 `github.com/RyuaNerin/testingutil` 未携带许可文本；本轮没有做公开发行验收，该问题及精确依赖清单应在分发前处理。参考源码及许可证记录见 `SOURCE-REFERENCE.md`。
