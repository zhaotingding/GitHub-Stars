# GitHub Stars++ 项目约定

- 产品和目录使用 `GitHub Stars++`／`GitHub-Stars++`，不用 PlusPlus。Python 包与 Conda 环境名为 `github_stars`／`github-stars`。
- 当前版本唯一来源是 `src/github_stars/__init__.py`。应用设置用 YAML，开发说明用 Markdown。
- 一项目一个 Conda 环境，PowerShell 用 `conda run -n github-stars --no-capture-output python -s ...`。不使用 base、用户 site 或嵌套 venv。
- 保留 `config.local.yaml`、`data/`、系统凭据与无关改动；这些内容不提交 Git。中文本地提交，远程 push 单独授权。
- 默认测试使用临时目录和模拟 API／SMTP。不得把模拟教程、SMTP 接受或任务退出码当作真实生成、收件箱投递或业务采集成功。
- 调度、CLI、GUI 共用 `Service.run`；生成／邮件状态与结果持久化。未知提交不自动重发。
- 初始分析与教程独立用途；长教程只允许主动触发。主题默认深色并写本地 YAML，普通应用窗口与控件共用主题。

## 项目技能索引

| 触发任务 | Skill |
| --- | --- |
| GitHub 采集、质量筛选、自然周期、重复推荐与周报 | [stars-discovery-digest](.agents/skills/stars-discovery-digest/SKILL.md) |
| AI 教程请求、结果恢复、Token 用量与邮件投递 | [stars-generation-delivery](.agents/skills/stars-generation-delivery/SKILL.md) |

安装、运行、计划任务和资料保留见 [README](README.md)。当前证据见 [0.2.1 验收记录](docs/verification-0.2.1.md)，不代表未来版本或其他机器已通过。
