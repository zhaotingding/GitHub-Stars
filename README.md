# GitHub Stars++

每天发现值得知道的开源项目，用两分钟初始分析决定是否深入，再主动生成可实践的教程。当前版本 **0.2.1**，提供桌面及本机浏览器界面，面向时间有限的 AI 研究者。

0.2.1将配置集中到独立“设置”页，右上角可直接进入“API连接”；左侧分类管理模型、研究、筛选、定时和邮件设置。同时修复WSL中文显示，增加本机启动入口。完整步骤见 [0.2.1使用说明](docs/0.2.1_使用说明.md)。

新增完整本机网页端：项目雷达、研究、周报、设置和运行记录均可在浏览器操作，与桌面共用业务及数据。运行`python -s -m github_stars web --open-browser`，或在WSL使用`bash tools/start_web.sh`；默认地址`http://127.0.0.1:8765/`。桌面右上角也可打开“网页端”。详细步骤见[网页端使用说明](docs/网页端使用说明.md)。

具身智能方向的实际操作、逐项验收、截图与小额用量明细见[图文实操指南](docs/具身智能_网页端实操与功能验收_20261106.md)。

默认关注深度伪造检测、计算机视觉、自监督、强化学习，兼顾 AI Agent、MCP 和研究工具。程序提供每日有限采样和每周少量推荐，也支持把阅读资料中看到的仓库直接收进项目雷达。

新增“项目研究”：对本地项目资料提问并查看引用，组织README版本和跨天Star观测，按题允许PNG截图理解，保存关注点、收藏和反馈，并用有界Agent补查资料。四阶段改动、配置和完整操作实例见 [智能化升级说明 README](docs/README_智能化升级说明.md)。已有采集、初始分析、主动教程和邮件周报继续使用原入口。

## 日常使用

1. **收集项目**：点击“立即采集”，或点击“粘贴仓库链接”，粘贴网址／包含 Markdown 链接的文字。粘贴后自动导入；一次最多 10 个不同仓库，重复链接去重，`tree`、`blob` 等子路径归一到所属仓库。手动导入直接查询仓库，不受 Star 和画像门槛限制。
2. **整理研究状态**：在列表的“研究状态”栏选择“待研究、收藏、已研究、重点、正在研究”。重点优先，已研究不再进入新周报；“打开 GitHub”位于每行操作位置。详情用于阅读原始介绍和初始分析。
3. **快速判断价值**：启用模型后，首次初始分析说明项目做什么、核心思想、值得使用的功能、与你研究的联系、如何开始使用及相关项目。已有分析复用，可在“任务与恢复”查看状态。
4. **决定深入后生成教程**：点击“生成 HTML 教程”会新建一次教程请求。成功后打开本地交互 HTML，按概念、流程、实践、配置、相关项目和改进／PR 路线学习。“打开已有教程”只打开已有结果，不重新调用模型。
5. **每周阅读少量精选**：默认周五 19:00 准备周报，最多 3 项，其中热点最多 1 项；不足门槛就少推。可导出 HTML／Markdown，配置 SMTP 后邮件推送。

推荐使用关键词、活跃度、README、许可证和 Star 观测规则，不是 GitHub 全站排行榜。没有跨日快照时 Star 增速显示未知；研究状态和规则分数不等于项目效果验证。

## 主题与本地设置

程序默认深色，可以切换浅色。主题写入根目录 `config.local.yaml` 的 `appearance.theme`，应用到当前主界面、导入、状态选择、恢复和提示等应用窗口。已有 YAML 缺少主题时只补默认主题，不覆盖个人 API 或研究偏好。

```yaml
appearance:
  theme: dark  # dark 或 light
```

HTML 教程导出时使用应用当前主题，页面内可独立切换深浅色，流程、代码区和实践步骤同步变化。

## 初始分析与深入教程

两类任务独立配置、计数和保存结果，共用所选 OpenAI 凭据。模型 API 默认关闭；请先在“设置 → API连接”设置模型与凭据，再勾选启用。各用途次数、Token和超时在左侧相应分类设置。

| 设置 | 初始分析 `ai` | 深入教程 `tutorial` |
| --- | --- | --- |
| 用途 | 两分钟判断是否值得深入 | 20–40 分钟理解并开始实践 |
| 模型 | `ai.model`，由你填写 | 默认 `gpt-6-luna`，可改为账户可用模型 |
| 服务等级 | 默认 `default` | 默认 `flex` |
| 每次输出 Token 上限 | 4000 | 18000 |
| README 输入字符上限 | 20000 | 60000 |
| 超时 | 180 秒 | 900 秒 |
| 每周新建请求上限 | 10 次 | 3 次 |
| 提示词 | `ai.prompt`，可编辑 | `tutorial.prompt`，可编辑 |
| 触发 | 主动；可选首次打开项目／周报入选时自动分析 | 仅主动点击生成 |

表中是新配置默认值。升级时个人已有设置保持原值，例如 0.1.0 保存的每周请求数不会自动改成 10。`ai.auto_analyze` 默认 `true`，但只有 `ai.enabled` 启用后才工作；不希望打开项目时调用模型，可以关闭它。定时任务只生成短分析，**不会自动生成深入教程**。

教程使用独立模型和更大的材料／输出预算。默认 Luna＋Flex 用于控制成本；实际可用性、费用取决于账户、模型与服务端。Flex 不可用、输出截断或连接中断时，不自动切换更贵档位或重新提交。这些是调用次数和长度限制，**不是金额预算**。

在“提示词”页分别编辑初始分析和教程提示词。默认教程要求：用具体输入输出解释思想；提供有来源的环境、安装、最小示例、配置、成功判据和排障；比较材料中真实出现的相关项目；给出小实验、改进、测试与 PR 路线。修改只影响下一次新请求，不改写在途任务或历史结果。

### API 凭据

在“设置 → API连接”选择 `local`、`msgx` 或 `autogpu`：

- `local` 使用本项目保存的 API Key；`OPENAI_API_KEY` 环境变量优先。
- `msgx`／`autogpu` 复用当前 Windows 用户已保存的相应应用 OpenAI 凭据。只在请求时读取原条目，不复制密钥、不新建旧应用凭据，不改变原应用配置。
- 找不到条目或无法读取时明确提示，不自动改用另一来源。已存凭据、可读取与真实请求成功分别判断。

本版本使用官方 OpenAI Responses 和结构化输出，固定连接官方 API。无需把密钥发到聊天里或写入 YAML。GitHub Token 和 SMTP 授权码仍分别保存为本项目凭据；终端临时变量不保证被 Windows 计划任务继承。

无系统凭据服务时，公开GitHub资料允许匿名访问；其他密钥可通过启动环境提供。WSL字体兼容启动使用`bash tools/start_wsl.sh`，可用`GITHUB_STARS_PYTHON`指定独立环境解释器。其Xft兼容方案及凭据步骤见[使用说明](docs/0.2.1_使用说明.md#9-wsl启动与中文显示)。

### 请求、恢复与证据

请求保存用途、模型、等级、预算、提示词和材料快照。返回后先记录原响应、响应 ID、实际模型／等级和已知 Token，再校验成稿。用量页按用途显示；失败／未知提交也占用该用途周次数，未知用量不计作零费用。

- **初始分析完成**：再次查看复用结果。
- **教程完成**：每次点击“生成 HTML 教程”表示重新生成；只想阅读请点“打开已有教程”。
- **received / invalid**：保留原响应和用量，先在“任务与恢复”尝试恢复；截断或结构不完整不能作为成稿。
- **unknown**：无响应 ID 时需先核对服务端记录；有 ID 时可 GET 原响应。恢复／打开不新建生成请求，明确重新生成才再 POST。

公开元数据、README 节选、研究画像，以及生成教程时已有的初始分析会发送给所选 OpenAI 账户。请求使用 `store=true`，原响应取回仍受服务端保留状态约束。

教程以提供资料为依据，未安装仓库、运行命令或验证性能；相关项目只引用材料给出的真实链接，缺项明确标注，建议与作者主张分开。模型内容作为文字进入固定 HTML 模板，不执行模型生成的脚本。

## HTML 教程怎么学习

文件保存在 `data/tutorials/<仓库ID>-<任务ID>.html`，可直接双击离线打开，无 CDN、远程字体或图片依赖。页面包含概念示例、逐节点流程、实践步骤导航、代码复制、预期结果与排障、配置表、相关项目、贡献路线和检查点答案。

实践进度可勾选、保存、重置；勾选代表你亲自核对，不是程序实测。复制不会执行命令；浏览器不允许直接复制时会选中文字供手动复制。外部来源链接需联网。完成首轮实践后，选一个可验证的小改进，阅读上游贡献说明、补测试，再准备 PR。

## 首次安装与启动

前提：已安装 Conda，Windows 10/11，Python 3.11。普通 PowerShell 即可，前提是对源码与环境有写权限。使用独立环境，不使用 base、`pip --user` 或嵌套 venv。

在项目目录执行；仅在环境不存在时创建：

```powershell
conda create -n github-stars python=3.11 pip -y
conda run -n github-stars --no-capture-output python -s -m pip install --no-user -e .
conda run -n github-stars --no-capture-output python -s -m pip check
conda run -n github-stars --no-capture-output python -s -m github_stars --check-environment
conda run -n github-stars --no-capture-output python -s -m github_stars
```

环境检查应输出 `valid: true`，Python 与依赖来自同一 Conda prefix，`user_site: false`。环境位置由本机配置决定；安装失败先解决权限或网络问题，再运行应用。自定义环境名时，安装、启动、构建和计划任务均使用同一名称。

根目录 `GitHub Stars++.exe` 是源码启动器，不能脱离源码和环境运行；业务源码更新后重开即可。默认选择 `github-stars`，可用 `--env` 指定其他专用环境。

```powershell
conda run -n github-stars --no-capture-output '.\GitHub Stars++.exe'
```

直接双击要求 `CONDA_EXE` 或 PATH 可以找到 `conda.exe`，也可通过 `--conda` 指定。只有启动器实现或资源变化才重建：

```powershell
conda run -n github-stars --no-capture-output python -s -m pip install --no-user -e '.[build]'
conda run -n github-stars --no-capture-output python -s tools/build_launcher.py
```

产物在 `dist/`；根目录已有启动器时保留旧文件，验证后再替换。EXE 不提交 Git。

## 每周推荐、邮件与自动运行

“研究画像”背景用于个性化解释；关键词和“检索来源”查询用于发现与规则筛选。GitHub Token 可选，匿名额度较小且可能被同出口请求共享；限流时保留数据，查看记录后再试。

每周默认最多 3 项，单作者每期至多一项，90 天内推荐过的项目排除。同周复用选集，研究状态变化不重写历史。手动导入能进入雷达，进入周报仍需满足推荐规则。最近采集未完整成功时不封存新周报；空选集不自动发信。

在“邮件推送”填写 SMTP 服务器、端口、SSL／STARTTLS、用户名、发件邮箱、一个收件邮箱及授权码。启用后到期任务可能立即使用新设置发送当前周报。SMTP 接受代表服务器收件，不保证进入收件箱。

连接／认证失败为 `failed`，至少间隔 6 小时自动重试；发送阶段断线为 `unknown`，先检查收件箱，再决定是否重发。`sent` 周报不自动重发。

关闭窗口后需要 Windows 计划任务。在项目目录、当前 Windows 用户的 PowerShell 执行：

```powershell
./tools/install_schedule.ps1
Get-ScheduledTask -TaskName 'GitHub Stars++'
Get-ScheduledTaskInfo -TaskName 'GitHub Stars++'
```

预期状态 `Ready`。当前用户普通权限运行，不保存 Windows 密码；每小时及登录时判断是否到期。默认北京时间每天 09:00 后首次检查采集，周五 19:00 后准备周报、可选短分析并发送邮件。

**电脑需要开机且用户已登录；锁屏可运行，睡眠、关机或退出登录时无法检查。** 重新可用后只补当前日期／当前周。窗口计时器和任务共享锁，程序不保持电脑唤醒。

任务绑定安装时 `pythonw.exe` 与源码路径。只改源码／设置无需重装；移动环境或源码后重新安装。同名任务若属于其他目录会拒绝覆盖。移除任务保留环境与数据：

```powershell
./tools/install_schedule.ps1 -Remove
```

也可在应用内关闭自动检查。

## 数据与从旧版本升级

| 内容 | 位置 | 管理方式 |
| --- | --- | --- |
| 源码／共享默认值／测试／说明 | `src/`、`tools/`、`tests/`、`docs/` | Git 管理 |
| 独立环境 | Conda `github-stars` | 日常升级复用，不混入源码 |
| 主题与个人设置 | `config.local.yaml` | GUI 保存，Git 忽略 |
| 密钥／授权码 | Windows 凭据库 | 本地条目按资料根隔离；可只读复用所选既有 API 条目 |
| 仓库、状态、历史、用量 | `data/stars.sqlite3` | 用户数据，Git 忽略 |
| 周报／交互教程 | `data/reports/`、`data/tutorials/` | 可独立阅读，可从完成结果重新导出 |

schema 1→2 增加研究状态、手动来源、任务用途／设置，保留项目、Star 快照、历史选集、原响应和用量。旧收藏映射为收藏；旧忽略继续排除，设置新研究状态后可恢复。旧结果保留为 `legacy`，在“任务与恢复”查看，不与新分析／教程混用。升级后的数据库不要再用 0.1.0 打开。

0.2.0的schema 2→3增加独立研究任务、逐步用量、轻量收藏、图片缓存和README版本表，保留此前项目、选集、AI任务和邮件状态。补归档当前已保存的README，无法补造更早版本；升级后的数据库不要再用0.1.1打开。

保留原环境、`config.local.yaml` 和整个 `data/`；依赖变化才更新安装。缺失的新设置从默认值补齐，个人已有模型、预算、提示词保持原值，不用空模板覆盖。

默认资料根为项目根，可通过 `--root '其他路径'` 或 `GITHUB_STARS_ROOT` 指定。移动源码后重建 editable 关联；更换资料根或 Windows 用户后，本项目凭据命名空间可能不同，既有应用凭据也不保证可用。备份 SQLite 前关闭写入者并停用任务，或使用 SQLite 一致性备份 API，运行中的单个数据库文件不一定完整。

## 开发与验证

在项目根、可写专用环境中执行：

```powershell
conda run -n github-stars --no-capture-output python -s -m pip install --no-user -e '.[dev]'
conda run -n github-stars --no-capture-output python -s -m pytest -q
conda run -n github-stars --no-capture-output python -s -m ruff check src tests tools
```

测试使用临时数据库、模拟密钥、GitHub／OpenAI HTTP 响应与 SMTP，不新建真实收费请求或发送真实邮件。GUI 需要桌面，浏览器渲染与 SDK 模拟分别验收。范围见 [0.1.1 验收记录](docs/verification-0.1.1.md)，[0.1.0](docs/verification-0.1.0.md) 保留为历史。

当前0.2.1验证与未实测范围见 [0.2.1验收记录](docs/verification-0.2.1.md)；0.2.0的157项历史回归见 [0.2.0验收记录](docs/verification-0.2.0.md)。

CLI 可用 `python -s -m github_stars scan`、`digest`、`tick`、`status`；`digest` 固定选集并导出，`tick` 执行到期采集、可选短分析和邮件。架构见 [设计说明](docs/design.md)。

## 接口依据

- [GitHub 搜索](https://docs.github.com/en/rest/search/search#search-repositories)、[README](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme)、[REST 限流](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)：有限查询与公开元数据。
- [OpenAI Python SDK](https://developers.openai.com/api/reference/python)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)：请求、响应状态与结构化结果。
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)、[Flex Processing](https://developers.openai.com/api/docs/guides/flex-processing)：教程默认模型与档位，实际能力、费用、账户权限仍需核对。

文档支持、模拟测试、浏览器渲染和真实账户生成分别记录，未执行的收费／投递不表述为通过。
