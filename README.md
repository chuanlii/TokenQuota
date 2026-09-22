# Token Quota · AI 订阅额度面板

常驻 Windows 桌面的小面板：贴在屏幕右边缘收起成一条细条，鼠标移上去展开卡片，
一眼看完 **Codex** 和 **OpenCode Go** 两个订阅的剩余额度、距下次重置的时间，
以及额度重置卡的过期时间。额度紧张或者消耗节奏不对时，长条会自己变色提醒。

只读展示，不做任何额度操作，也不会替你花掉任何额度。

---

## 效果

收起状态是屏幕右边缘一条 8px 宽的细条，里面两根竖条分别是两个订阅的额度，
**高度 = 剩余额度，颜色 = 告警色**，不用展开也能看出哪个快见底：

```
屏幕右边缘
    │▌   ← Codex
    │▌   ← OpenCode Go
```

鼠标悬停展开卡片，各字段含义：

| 位置 | 含义 |
| --- | --- |
| 标题行左 | 服务图标 + 名称 |
| 标题行右 `EXP 13d` | **最近一张额度重置卡的过期时间**（只有 Codex 有这种东西） |
| 标题行右 `2` | 可用额度重置次数 |
| 每行左 `33%` | 剩余额度百分比（向下取整，不虚报额度） |
| 每行中 长条 | 剩余额度，颜色随告警档变化 |
| 每行右 `4h23` | 距下次重置（不足 1 小时才带 `m` 单位） |
| 底部 `⚙ 设置` | 打开设置窗口 |

每个订阅显示几行由它自己的额度窗口决定：Codex 是 5H / 1W 两行，OpenCode Go 是 5H / 1W / 1M 三行。

---

## 特性

- **贴边常驻、悬停展开**：默认收起，不占桌面空间；展开动画 260ms。
- **不抢焦点**：窗口带 `WS_EX_NOACTIVATE`，点面板不会把你从编辑器里踢出来。
- **收起时可点击穿透**：细条下方就是正常桌面，点击不受影响。
- **三档颜色提醒**：剩余额度不够、或额度与时间进度明显不匹配时自动变色。
- **可配置**：显示哪些服务、变色阈值、三档用哪种配色、要不要开机自启，都在设置窗口里改。
- **失败不丢数据**：取数失败时保留上一份数据并标记「数据已过期」，而不是清空。
- **托盘常驻**：立即刷新 / 显示隐藏面板 / 面板移到光标所在屏 / 设置 / 开机自启 / 退出。

---

## 环境要求

| 项 | 要求 |
| --- | --- |
| 系统 | **Windows 10 / 11**（用了 `winreg`、`WS_EX_NOACTIVATE`、`WS_EX_TRANSPARENT`，未做跨平台适配） |
| Python | 3.11+（开发环境 3.14） |
| 依赖 | PySide6 ≥ 6.6 |

面板贴**最靠右**那块屏幕的右边缘；多屏环境下可以用托盘菜单临时改到光标所在屏。

---

## 安装

```powershell
git clone <this-repo> token-quota
cd token-quota
pip install -r requirements.txt
```

## 运行

```powershell
python run.pyw      # 前台运行，能看到 traceback，便于排查
pythonw run.pyw     # 后台运行，不弹控制台窗口（日常使用）
```

开机自启：**托盘菜单**和**设置窗口**里都有「开机自启」勾选框，会在
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下写入 `TokenQuota` 项，
命令形如 `"<Python>\pythonw.exe" "<repo>\run.pyw"`；**打包后的 exe 则直接写 exe 自身的路径**
（靠 `sys.frozen` 区分，不会写出指向临时解包目录的无效项）。

两处勾选框都当场读注册表，所以在哪边改都会同步到另一边。默认**不开**：注册表里没有这一项时
勾选框就是空的；取消勾选会把这一项删掉。这一项**不存在 config.json 里**，见下文「配置」。

程序是单实例的（命名互斥体 `Local\TokenQuota.Panel`）。重复启动时第二份会往 stderr
打印 `AI 订阅额度 已经在运行。` 然后立刻退出——托盘里那份才是活的。

---

## 打包成免安装 exe

给不想装 Python 的机器，或者只是想拷给别人用：

```powershell
pip install -r requirements-dev.txt   # 只有 PyInstaller 一个构建依赖
.\build.cmd                           # 双击也行，等价于 build.ps1 -Mode onefile
```

也可以用 `build.ps1` 直接控制：

| 参数 | 作用 |
| --- | --- |
| `-Mode onefile` | 只出单文件 `dist\TokenQuota.exe`（默认，约 44 MB） |
| `-Mode onedir` | 只出目录版 `dist\TokenQuota\`（启动更快，整个目录约 110 MB） |
| `-Mode both` | 两种都出 |
| `-Clean` | 先清掉 `build\`、`dist\` 再打包 |
| `-Console` | 保留控制台窗口，便于看启动报错 |
| `-NoIcon` | 跳过图标生成，用 PyInstaller 默认图标 |

产物就在 `dist\` 下，双击即用，目标机器不需要装 Python、PySide6 或任何运行库。
不需要管理员权限。

几个和打包有关的取舍：

- **两种形态共用一份 spec**（`packaging/TokenQuota.spec`），靠环境变量
  `TOKENQUOTA_ONE_FILE` / `TOKENQUOTA_CONSOLE` 切换，不维护两份会走偏的配置。
- **不用 Pillow 等额外构建依赖**：Qt 自己写不了 ICO，所以打包图标由
  `packaging/make_icon.py` 手写 ICO 容器生成，几何形状直接复用 `app/tray.py` 的
  `icon_pixmap`，和运行时的托盘图标不会长得不一样。
- **UPX 始终关闭**：压缩后的 Qt DLL 经常直接起不来，省那点体积不值。
- 打包时排除了约 50 个用不到的 Qt 子模块和 `tkinter` / `sqlite3` 等标准库，
  单文件版才压到 44 MB（`email`、`http.client` 这些是取数要用的，不能排）。
- 首次启动单文件版会比目录版慢一些（要先把自己解压到临时目录）；介意的话用
  `-Mode onedir`，顺便也能减少杀毒软件对 PyInstaller 单文件包的误报。
- exe 的文件属性（版本号、产品名、版权）在 `packaging/version_info.txt`，
  改版本时要和 `app/__init__.py` 里的 `VERSION` 一起改——`build.ps1` 会校验两者一致，
  不一致直接停下来报错。

---

## 使用

- **展开 / 收起**：鼠标移到屏幕右边缘的细条上即展开，移开 0.3 秒后收起。
- **打开设置**：点卡片左下角的齿轮，或托盘菜单的「设置…」。
- **看详情**：鼠标悬停在某个服务上会显示该服务各窗口的额度、重置时间，以及**为什么会变色**。
- **立刻刷新**：托盘菜单「立即刷新」（正常每 60 秒自动刷新一次）。
- **开机自启**：设置窗口最下面「启动」里的「开机自启」（托盘菜单里也有一个）。默认不开；
  勾上并保存即生效，取消勾选并保存就移除自启项。改完要下次登录才看得出来。

---

## 配置

首次点「保存」时写入 `%APPDATA%\TokenQuota\config.json`（原子写，不留半截文件）。
配置文件损坏或字段非法时会整体回落到默认值——配置坏了最多丢设置，不会让面板起不来。

开机自启**不在**这个文件里：它直接读写真机上的自启项，系统里那一项才是唯一事实，
免得出现「设置说开着、系统里其实没有」的互相矛盾。所以换机器、手删注册表项之后，
设置窗口里的勾选状态都会如实跟着变。

```json
{
  "version": 1,
  "services": { "codex": true, "opencode": true },
  "rule": {
    "low_enabled": true,
    "low_pct": 20.0,
    "pace_enabled": true,
    "pace_gap_pct": 30.0
  },
  "colors": { "ok": "#2fbf71", "warn": "#f5a524", "danger": "#f2555a" }
}
```

| 字段 | 含义 |
| --- | --- |
| `services` | 每个服务是否显示（至少保留一个，否则卡片是空的） |
| `rule.low_enabled` / `low_pct` | 剩余额度 ≤ 该百分比时进入**危险**档（默认 20%） |
| `rule.pace_enabled` / `pace_gap_pct` | 剩余额度与剩余时间的差距 ≥ 该百分点时进入**注意**档（默认 30） |
| `colors` | 三档各自的颜色，`#rrggbb` |

---

## 变色规则

| 档位 | 条件 | 默认色 |
| --- | --- | --- |
| **危险** | 剩余额度 ≤ 20% | 珊瑚红 `#f2555a` |
| **注意** | 剩余额度与剩余时间的差距 ≥ 30 个百分点 | 琥珀橙 `#f5a524` |
| **正常** | 其余情况 | 薄荷绿 `#2fbf71` |

「注意」档是双向的，两种情况都会触发：

- 时间快过半了额度还剩一大截 → 重置前用不完，浪费了；
- 额度掉得比时间快 → 按当前速度撑不到下次重置。

危险档优先于注意档。折叠细条的颜色取该服务**最坏的**那一行，高度取 5H 窗口的剩余额度
（变化最快，最值得一眼看到）。

---

## 数据来源

两个订阅各有一个取值路径，**都是非官方接口**，上游改动随时可能让它们失效：

### Codex

| 顺序 | 路径 | 说明 |
| --- | --- | --- |
| 主 | `codex.exe app-server --stdio` + JSON-RPC `account/rateLimits/read` | 由 app-server 自己刷新 OAuth，不受 access token 约 1 小时过期的影响；冷启动约 2 秒 |
| 兜底 | `~/.codex/sessions/**/rollout-*.jsonl` 里最后一条 `token_count` 事件 | 新鲜度 = 你上次跑 Codex 的时间 |

- `codex.exe` 不在 `PATH`，程序按 `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` 查找
  （bin 目录名带版本 hash，会随版本变化），可用 `OPENAI_CODEX_CLI_PATH` /
  `CODEX_CLI_PATH` 指定。
- 只读主额度（`rateLimits`，即 `limitId="codex"`），不展示 `rateLimitsByLimitId` 里的
  gpt-reserve 等旁路额度。

### OpenCode Go

- `GET https://opencode.ai/zen/go/v1/usage`，只需要 `Authorization: Bearer <key>`。
- key 来源：环境变量 `OPENCODE_API_KEY`，否则读本地 `~/.local/share/opencode/auth.json`
  里的 `opencode-go` 条目。
- 响应里的 `percent` 是**已用**百分比，长条按 `100 - percent` 填充。
- 该端点没有写进公开文档，属于非官方接口，失败会走降级处理。

### 失败时会怎样

| 情形 | 面板表现 |
| --- | --- |
| 正常 | 无提示 |
| 数据超过 15 分钟没更新过 | 标题行出现橙色 `!`，提示「数据已过期」 |
| 本轮取数失败但还有旧数据 | 橙色 `!` +「实时取数失败（原因），显示 N 分钟前的数据」 |
| 完全没有数据 | 数值显示 `—`，提示失败原因 |

全部服务都失败时，刷新间隔会从 60 秒按 30 → 60 → 120 → 240 → 300 秒退避，任一成功即恢复。

---

## 隐私与安全

- **只读本机凭证，不复制、不上传、不落盘**：OpenCode Go 的 key 从环境变量或本机
  `auth.json` 读取，仅在请求头里使用；Codex 侧由官方 `codex app-server` 进程自行管理
  OAuth，本程序不接触 token。
- **不做任何上报**：程序只与本机 `codex.exe` 和 `opencode.ai` 通信，没有统计、遥测或第三方请求。
- **配置文件不含凭证**：`%APPDATA%\TokenQuota\config.json` 只存显示偏好（服务开关、阈值、配色）。
- 代码里没有任何硬编码密钥；日志与提示文案不打印 key。

---

## 项目结构

```
token-quota/
├── run.pyw                   入口（配合 pythonw.exe 无控制台启动）
├── requirements.txt          运行依赖（PySide6）
├── requirements-dev.txt      构建依赖（PyInstaller）
├── build.ps1 / build.cmd     一键打包脚本
├── packaging/
│   ├── entry.py              PyInstaller 打包入口
│   ├── TokenQuota.spec       打包配置（单文件 / 目录版共用）
│   ├── make_icon.py          零依赖生成 ICO（复用 app/tray.py 的图标几何）
│   ├── TokenQuota.ico        打包用图标
│   └── version_info.txt      exe 文件属性（版本号 / 产品名 / 版权）
└── app/
    ├── main.py               组装：取数线程 / 面板 / 托盘 / 设置窗口
    ├── spec.py               呈现规则（纯函数、不依赖 Qt）：尺寸、配色、文案、告警等级
    ├── panel.py              自绘面板窗口：贴边、折叠、悬停、点击穿透、绘制
    ├── settings_ui.py        设置窗口
    ├── config.py             配置读写（原子写 + 容错回落）
    ├── assets.py             服务元数据 + 内联 SVG 图标
    ├── model.py              额度数据模型与窗口归槽
    ├── poller.py             后台取数线程（失败保留旧数据 + 指数退避）
    ├── providers/
    │   ├── codex.py          app-server JSON-RPC 主路径 + session JSONL 兜底
    │   └── opencode_go.py    /zen/go/v1/usage
    ├── tray.py               托盘图标与菜单
    ├── autostart.py          开机自启（HKCU Run 项，源码 / exe 两种形态）
    └── single_instance.py    命名互斥体单实例保护
```

几个设计取向：

- 呈现规则集中在 `app/spec.py`，是**不导入 Qt 的纯函数**，因此可以脱离 GUI 单独断言。
- 视图只有一条写路径：取数结果、设置保存、定时重算都汇聚到同一个重建函数，
  避免「设置改了但某处没跟上」。
- 卡片是不透明圆角矩形，没有使用逐像素透明——绕开 Qt 的透明渲染坑。

---

## 开发

```powershell
python -m compileall -q app run.pyw   # 语法自检
.\build.ps1 -Mode both -Clean         # 打包两种形态，验证打包链路
```

新增一个订阅需要动四处：`app/assets.py` 的 `SERVICES` 加一条、
`app/providers/` 加一个 `fetch_xxx`、`app/poller.py` 的 `_FETCHERS` 注册，
以及（如果需要）在 `Service(slots=..., show_exp=...)` 里声明显示哪些额度和是否显示 EXP。

---

## 已知限制

- 仅支持 Windows。
- 面板固定贴右边缘，不能改到左/上/下。
- 一次只跑一个实例，无法同时盯两块屏。
- 额度提醒只有颜色变化，没有弹窗通知或声音。
- 两个数据源都是非官方接口，上游一改就可能失效；失效时面板会显示陈旧标记而不是假装正常。

## 免责声明

本项目与 OpenAI、OpenCode 均无关联，只是读取本机已有登录态来展示你自己的额度数字。
接口行为可能随时变化，请以各家官方客户端显示的额度为准。

## 许可

[MIT](LICENSE)。
