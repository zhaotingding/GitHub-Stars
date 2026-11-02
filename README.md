# GitHub Stars++

每天观察 GitHub，每周只读几项。当前版本 **0.1.0**，面向 Windows 上的个人 AI 研究者。

它把公开项目发现、研究相关性筛选、中文导读与教程、邮件周报串成一条可持续运行的流程。默认关注深度伪造检测、计算机视觉、自监督、强化学习，同时保留少量 AI Agent、MCP 和研究工具名额。

## 0.1.0 已提供

- **每日发现**：GitHub 官方 REST API，多条研究／热点查询，高星活跃项目与近 45 天新项目；默认每条最多 20 项，每次最多读取 12 份 README。结果去重保存到 SQLite。
- **每周少量推荐**：默认每周最多 3 项，其中热点最多 1 项；低于质量门槛不推荐，不凑数。同一作者每期最多一项，90 天内不重复推荐。
- **解释入选理由**：研究／热点关键词、活跃度、Star、README 完整度、许可证、本地跨日 Star 变化。首日没有增速证据就显示未知。
- **桌面阅读**：项目搜索、收藏、忽略、恢复候选、每周精选、历史周报、HTML／Markdown 导出、运行与 AI 用量记录。
- **OpenAI 教程**：填写账户可用的模型 ID 和 API Key 后，生成中文概述、研究联系、入门步骤与限制。有调用次数和输出 Token 上限，缓存成稿，可恢复已返回结果。
- **邮件推送**：SMTP SSL／STARTTLS，纯文本＋HTML 周报，独立发送状态。空周报不自动发送。
- **定时运行**：窗口内自动检查，另有 Windows 计划任务用于关闭窗口后运行；任务互斥、每日去重、当前周补跑。

这是一套有限采样的个性化发现工具，不是 GitHub 全站排行榜，也不读取新闻或声称捕获全部 AI 热点。0.1.0 使用可解释的规则筛选；模型负责解读与教程，不负责替你认定项目有效。

## 首次安装

前提：已安装 Conda，Windows 10/11，Python 3.11。普通 PowerShell 即可，前提是对源码与所选环境有写权限。不要安装到 base，不要使用 `pip --user`，不需要 venv。

在项目目录执行；仅在环境不存在时创建：

```powershell
conda create -n github-stars python=3.11 pip -y
conda run -n github-stars --no-capture-output python -s -m pip install --no-user -e .
conda run -n github-stars --no-capture-output python -s -m pip check
conda run -n github-stars --no-capture-output python -s -m github_stars --check-environment
conda run -n github-stars --no-capture-output python -s -m github_stars
```

环境检查应输出 `valid: true`，Python 与第三方模块属于同一个 Conda prefix，`user_site: false`。Conda 名称实际解析到哪里由你本机配置决定，不要求某个固定磁盘路径。创建／安装失败时先解决目录权限或网络问题，不要继续运行或改成用户级安装。

如果采用自定义环境名，后续安装、启动、构建和计划任务都使用同一名称。双击 EXE 的默认名称仍是 `github-stars`，可以用 `--env 自定义名称` 明确选择。

## 第一次使用

1. 打开 **偏好与连接 → 研究画像**，确认背景、研究关键词与热点关键词。画像文字用于教程个性化；候选筛选使用关键词和“检索来源”中的查询，两者需按需要一起调整。
2. 在 **检索来源** 可保存 GitHub Token。公开仓库可匿名检索，但匿名 REST 额度较小、可能被同一出口其他请求共享；Token 仅用于读取，不需要仓库写权限。限流时保留已采集数据，日志显示原因，之后再试。
3. 点击 **立即采集**。查看候选的原始介绍、匹配理由和来源。收藏用于优先选择，忽略后不再入选；恢复可撤销忽略。
4. 点击 **每周精选 → 生成本周精选**。同一自然周复用同一份选集；请完成采集、调整偏好后再生成。已生成的历史选集保留当时元数据，后续收藏／忽略不重写历史。
5. 配置 OpenAI 后可对选中项目点击 **生成教程**。每周自动任务也会为本周入选项目生成教程。无 API 时，应用提供原始简介、事实指标和通用阅读路线，不把它称为 AI 教程。
6. 配置邮件后可点击 **发送邮件**，默认周五到期后自动发送。SMTP 接受只代表服务器收件，不保证最终投递到收件箱；也请检查垃圾邮件。

不需要在聊天中发送密钥。在应用中输入并保存即可。

## OpenAI 设置与收费边界

在 **OpenAI 教程** 填写你账户可用、支持 Responses 和结构化输出的模型 ID，保存 API Key，勾选启用。首版固定使用官方 `https://api.openai.com/v1`，不默默改投第三方接口。应用不替你猜测模型可用性或最新价格。

默认每周最多 **3 次请求**，每次最多 **5000 输出 Token**，每份 README 最多发送 **20000 字符**。这是调用次数和长度限制，**不是金额预算**。失败与未知提交也占用当周次数；已完成缓存、查询原响应不算新建生成请求。运行与用量页显示服务端实际返回的输入／输出 Token，未知用量不会计作零。

启用后，入选仓库的公开元数据、README 节选和你填写的研究画像会发送给 OpenAI。请求使用 `store=true`，以便有响应 ID 时查询原结果；是否仍能取回取决于服务端保留状态。不要在画像填写不希望提交的个人资料。

教程只以提供的 README 快照为依据。没有安装、代码执行或实验验证；官方步骤与模型建议要求区分。README 内容被作为低权限材料，生成内容不会自动执行。模型仍可能出错，运行命令前应回看官方来源。

- **已完成**：再次点击复用缓存。
- **received / invalid**：保留原响应、响应 ID 与已知用量；先点击“恢复结果”。格式不正确或输出截断不能自动当作成稿。
- **unknown**：断线／中断导致结果不明，不自动重新 POST。有 ID 时尝试恢复，无 ID 时需先核对服务端记录。
- **明确重新生成**：界面会提示可能再次产生费用，确认后新建请求，仍受每周次数上限约束。

## 邮件配置

在 **邮件推送** 填写 SMTP 服务器、端口、加密方式、用户名、发件邮箱、收件邮箱，以及密码或邮箱提供商的授权码。常见配置为 SSL 465 或 STARTTLS 587，具体以邮箱官方说明为准。首版每份周报支持一个收件地址。

勾选“启用每周邮件”并保存后，下次到期任务可发送邮件；若本周已到周报时间且已有选集，可能在下一次自动检查立即发送。

连接／认证阶段失败标记 `failed`，自动流程至少间隔 6 小时重试。进入发送阶段后断线标记 `unknown`，先检查收件箱，只有明确重发才再提交。已确认 `sent` 的周报不自动重发，SMTP 不提供跨网络断线的严格 exactly-once 保证。

## 关闭窗口后的自动运行

在项目目录、当前 Windows 用户的 PowerShell 中执行：

```powershell
./tools/install_schedule.ps1
Get-ScheduledTask -TaskName 'GitHub Stars++'
Get-ScheduledTaskInfo -TaskName 'GitHub Stars++'
```

预期任务状态为 `Ready`。任务以当前用户、普通权限运行；不保存 Windows 密码。每小时触发一次及登录时触发，内部按配置判断是否需要工作。默认北京时间每天 09:00 之后首次检查采集，每周五 19:00 之后首次检查生成并推送。

**需要电脑开机且当前用户已登录；锁屏可运行，关机、睡眠或退出登录时无法检查。** 重新可用后只补当前日期／当前周，不追补所有历史周、不会连续轰炸邮件。窗口内每分钟检查和计划任务共享锁，避免并发重复工作。保持界面开启也能自动检查，但不会让电脑保持唤醒。

计划任务固定绑定安装时解析到的 `pythonw.exe` 和当前源码路径。移动环境或源码后，在新位置重新安装计划任务；同名任务若属于其他目录，脚本拒绝覆盖，需要先移除旧任务或指定不同名称。只改业务源码／设置无需重装任务。

移除自动任务（不会删除数据）：

```powershell
./tools/install_schedule.ps1 -Remove
```

也可在应用设置关闭“启用自动检查”；任务仍存在，但每次触发后立即结束。

## 轻量 EXE

本机首版已构建的入口是根目录 `GitHub Stars++.exe`。它启动源码，业务代码修改后重开即可生效；它不能脱离源码和 Conda 环境独立运行，不附带 `_internal` 业务运行时。

```powershell
conda run -n github-stars --no-capture-output '.\GitHub Stars++.exe'
```

直接双击要求 `CONDA_EXE` 或 PATH 可以找到 `conda.exe`；找不到时会给出说明。不要修改系统 PATH 来绕过不明故障，可以在命令行明确传 `--conda`。构建入口：

```powershell
conda run -n github-stars --no-capture-output python -s -m pip install --no-user -e '.[build]'
conda run -n github-stars --no-capture-output python -s tools/build_launcher.py
```

构建产物在 `dist/`；根目录没有启动器时会首次复制，有旧入口时保留旧文件，验证新产物后再替换。EXE 不提交 Git。

## 数据、配置与升级

| 内容 | 位置 | 处理方式 |
| --- | --- | --- |
| 源码／默认配置／测试／文档 | `src/`、`tools/`、`tests/`、`docs/` | Git 管理 |
| 独立运行环境 | Conda `github-stars` | 不放源码仓库，不删除重建作为日常升级 |
| 个人配置 | 根目录 `config.local.yaml` | GUI 保存，Git 忽略，保留用户内容 |
| 密钥／SMTP 授权码 | Windows 凭据库 | 按资料根隔离，不写 YAML／数据库 |
| 仓库、历史、反馈、AI 用量 | `data/stars.sqlite3` | 用户数据，Git 忽略 |
| 可读周报 | `data/reports/` | HTML 与 Markdown，可以重新导出 |

默认资料根是项目根；CLI 可用 `--root '其他路径'`，也可用 `GITHUB_STARS_ROOT`。除测试外，不随意更换正在使用的资料根。环境变量 `OPENAI_API_KEY`、`GITHUB_TOKEN`、`GITHUB_STARS_SMTP_PASSWORD` 优先于凭据库；计划任务不保证继承你某个终端临时设置的变量，日常建议用界面保存。

普通源码更新保留原环境、`config.local.yaml` 和整个 `data/`，依赖变化才重新执行 editable 安装。不要用空模板覆盖个人设置。移动源码后需重新建立 editable 关联；换资料根或 Windows 用户后，凭据库命名空间不同，需要重新配置密钥。

备份 SQLite 前关闭应用并停用计划任务，或使用 SQLite 一致性备份 API；不要把仍在写入的单个 `.sqlite3` 文件当作完整备份。未来更高 schema 的数据库会拒绝被 0.1.0 打开，避免静默降级。

## 开发与验证

执行目录为项目根，专用环境需要写权限：

```powershell
conda run -n github-stars --no-capture-output python -s -m pip install --no-user -e '.[dev]'
conda run -n github-stars --no-capture-output python -s -m pytest -q
conda run -n github-stars --no-capture-output python -s -m ruff check src tests tools
```

测试使用临时数据库、模拟密钥、GitHub／OpenAI HTTP 响应和 SMTP；不调用付费 API、不发送真实邮件。GUI 测试需要桌面，缺少显示环境时明确跳过。验收边界见 [0.1.0 验收记录](docs/verification-0.1.0.md)。

命令行也可直接使用：`python -s -m github_stars scan`、`digest`、`tick`、`status`。`digest` 固定选集并导出，不主动发送；`tick` 执行到期采集、自动教程和邮件。

实现分工与后续方向见 [设计说明](docs/design.md)。

## 接口依据

- [GitHub 仓库搜索 API](https://docs.github.com/en/rest/search/search#search-repositories)：有限查询结果、搜索专属限额。
- [GitHub README API](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme)：README 内容与来源。
- [GitHub REST 限流说明](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)：认证与匿名限额的差异。
- [OpenAI Python SDK](https://developers.openai.com/api/reference/python)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)：Responses、JSON Schema、实际用量及响应对象。

接口实现于 2026-11-02 核对官方文档；本机真实调用和模拟测试分别记录，不以文档支持代替账户联通验收。
