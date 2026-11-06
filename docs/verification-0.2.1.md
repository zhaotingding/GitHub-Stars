# 0.2.1 验收记录

日期：2026-11-06；基线：`22448bc`（0.2.0）；分支：`zhouhuijun/research-assistant`。

## 本轮范围

- 独立设置页、右上角入口、左侧分类，API/模型/Key入口集中展示；保留原配置结构。
- 中文字体选择、研究区最小窗口布局，以及WSL图形启动兼容。
- 无凭据服务时的匿名GitHub读取与明确密钥错误，不添加明文存储。
- 版本、使用说明、界面截图及本机启动说明。

## 环境与命令

使用项目独立Conda环境，Python3.11.18；没有修改base或系统文件。业务依赖版本沿用0.2.0。

本机Conda Tk8.6.15没有Xft，实际曾将中文渲染为`\uXXXX`。首次部署仅验证窗口存在，遗漏显示效果，本轮以截图和字形回归补验。

本机GUI使用系统已安装、支持Xft的Tk8.6及Noto Sans CJK SC。该选择仅作用于GUI子进程；业务Python仍使用独立环境。`tools/wsl_launcher.py`检查Conda Tk链接，必要时选择现有系统库，不更改Conda包、系统文件或base。

```bash
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtk8.6.so \
TK_LIBRARY=/usr/share/tcltk/tk8.6 \
/home/suangfa/tp/.task_envs/github-stars/bin/python -s -m pytest -q

/home/suangfa/tp/.task_envs/github-stars/bin/python -s -m ruff check src tests tools
/home/suangfa/tp/.task_envs/github-stars/bin/python -s -m pip --isolated check
/home/suangfa/tp/.task_envs/github-stars/bin/python -s -m github_stars --check-environment
bash -n tools/start_wsl.sh
git diff --check
```

以上绝对路径是本机证据，其他机器使用自己的专用环境。Windows原生不使用Linux的LD_PRELOAD配置。

## 结果

| 检查 | 结果 |
| --- | --- |
| 完整pytest | 166 passed，无跳过，15.62秒 |
| 相对0.2.0新增检查 | 凭据兼容8项，实际中文字形1项 |
| 设置交互 | 真实Tk验证右上角按钮、主设置页、默认API分类、跨分类切换、模型字段集中、保存和最小窗口 |
| 研究界面 | 引用点击、来源阅读、小窗口尺寸、后台任务、附件许可等原有回归通过 |
| 其他功能 | 原有采集、筛选、教程、Agent、图片、恢复、迁移及用量回归通过 |
| 字体 | 中文显示宽度小于字面Unicode转义串，实际字体为Noto Sans CJK SC |
| 设置截图 | 使用临时空白配置截取并人工查看，中文、分类、表单和保存按钮正常 |
| 本机应用更新 | 原快捷方式启动0.2.1，真实进程存活、可见窗口唯一；仓库WSL启动器重复启动返回已有窗口提示 |
| Ruff、依赖检查、shell语法、差异检查 | 通过 |
| 版本 | 源码和editable包均更新为0.2.1，环境检查valid=true、user_site=false |

凭据检查覆盖：无服务匿名GitHub、环境变量优先、必需密钥缺失提示、已有后端错误不降级，以及保存失败不写YAML。所有密钥都是测试占位值。

设置截图见[界面图片](images/settings-0.2.1.png)，操作步骤见[使用说明](0.2.1_使用说明.md)。

## 真实业务边界

- 本机曾真实尝试匿名导入`zhaotingding/GitHub-Stars`，GitHub返回403限流，实际导入0个项目；没有把退出码0当作导入成功。
- 未执行真实付费模型、真实SMTP或被研究仓库代码；自动化测试使用临时数据库、模拟API和凭据。测试不证明真实模型回答质量、邮件送达或实验性能。
- Windows原生Conda、系统凭据库、EXE构建、计划任务及长时间常驻仍需目标机器验收；本机的Windows桌面快捷方式启动的是WSL/WSLg应用。
- 图形验收依赖此机系统Tk和中文字体。其他Linux机器需要核对自身渲染库和字体，不能仅凭环境检查valid=true推断中文显示正常。
- 不提交个人配置、数据库、启动日志、实际密钥或独立环境；本轮没有启用自动采集、模型或邮件。
