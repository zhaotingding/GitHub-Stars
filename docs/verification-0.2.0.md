# 0.2.0 验收记录

日期：2026-11-06；基线提交：`af08c90`（0.1.1）。目标仓库：`zhaotingding/GitHub-Stars`；开发分支：`zhouhuijun/research-assistant`。

## 环境与隔离

- 新拉取源码独立目录：`/home/suangfa/tp/GitHub-Stars++`；项目专用Conda环境：`/home/suangfa/tp/.task_envs/github-stars`，未修改base或旧项目环境。
- Linux/WSLg，Python3.11.18；OpenAI SDK2.54.0、Pydantic2.14.3、HTTPX0.28.1、pytest9.2.0、Ruff0.17.4。
- 数据库、配置、原图和成稿使用测试临时目录；凭据由测试替身提供。模型使用实际SDK序列化和HTTPX MockTransport，不请求真实模型。
- GUI使用真实Tk/WSLg；Windows凭据协议测试用受控ctypes替身模拟平台和API，仅验证引用、UTF-8与缓冲清理，不等于真实Windows凭据库读取。

## 执行结果

在专用环境、源码根目录执行：

```powershell
conda run -n github-stars --no-capture-output python -s -m pytest -q
conda run -n github-stars --no-capture-output python -s -m ruff check src tests tools
conda run -n github-stars --no-capture-output python -s -m pip --isolated check
conda run -n github-stars --no-capture-output python -s -m github_stars --check-environment
```

本机Linux使用该专用环境的绝对Python路径执行对应命令，测试正常用户权限和真实桌面连接分别核对。

| 检查 | 结果 |
| --- | --- |
| 完整pytest | 157 passed，无跳过 |
| 新增研究相关检查 | 96项：引擎/图片36、检索/存储53、真实研究界面7 |
| 原有功能回归 | 61项，覆盖发现、筛选、教程、恢复、邮件替身、主题和启动器契约 |
| Ruff | All checks passed |
| pip依赖兼容性 | No broken requirements found |
| 环境检查 | valid=true；user_site=false；所有运行依赖来自github-stars Conda prefix |
| 版本与源码关联 | 源码与editable包元数据均为0.2.0，指向当前新目录 |
| CLI冒烟 | 临时空库0API、只读状态、同ID复用、无许可附件拒绝 |
| Git差异检查 | 无冲突标记和空白错误 |

源码目录按项目约定保留`++`名称；修改目录后重新建立editable关联，不复制旧应用配置或凭据。

## 关键行为证据

**资料与引用。** 冻结当前项目/README/历史范围，忽略名单、重复ID、无效ID和超限输入被拒绝；相关表达和字符检索、SQL字段边界、未来时间过滤、真实截断标记、数值不同的重复判断及GitHub链接约束均有检查。模型只能引用本题真正提供的来源；格式、工具和引用非法时停止，不付费自动修复。

**恢复与费用。** 真实SDK请求体检查独立用途、模型、等级、输出结构、关闭重试及凭据来源；已接受响应用GET取回，本地完整响应不再请求；取回一步后等待明确继续。中断无ID维持未知；达到调用/工具/时间/估算费用/自然周上限不再POST。调用实际返回的Token更高时阻止后续超限，未知用量不按零计算。创建周、模型和偏好不会被之后设置变化替换。

**停止与事务。** 停止在准备阶段可阻止首次POST；发送后停止不会执行下一工具。任务推进和步骤应用同事务，注入失败会回滚且再次恢复只应用一次。取消与应用争用写锁，迟到结果不会把已停止任务改回完成。

**图片。** 无逐题许可时零文件读取/零POST；验证静态PNG结构、CRC、行/像素和解压边界，拒绝动画、损坏/异常文件和符号链接。标准模式第二张附件在读取前拒绝，Agent双图按五步及原限额执行。图片使用独立模型/费率/凭据；同内容成功缓存不重发，未知原图跨问题不重复上传。原文件删除后，已接受原响应仍可取回；通用缓存先成功而任务应用失败时可恢复，不增加调用。

**数据与界面。** 真正的旧schema2数据库保留原项目、研究状态、Star快照、周报、生成任务、原响应和状态；已有无SHA README首次刷新不重复归档。到期清理输入与原响应，保留自然周归属和用量；未知图片占用不会被当成未发送。轻量收藏到期后可查看、删除，取消收藏返回明确状态。真实Tk验证来源引用跳转、主题、最低尺寸、后台线程、运行中停止、独立同ID继续/恢复、历史不自动提交及逐题图片许可复位。

## 未覆盖范围

未调用真实付费API、真实SMTP或真实采集数据；这些测试不证明真实模型准确率、推荐效果或邮件进入收件箱。没有运行被收集的仓库代码，也没有验证其安装命令、实验、显存或性能。

Windows原生凭据库、轻量EXE实际构建/双击、计划任务安装及长时间常驻仍需在目标Windows机器验收；Linux上的契约替身或WSLg不能替代这些证据。

新用途需要用户明确启用并配置模型、凭据与估算费率，图片还需逐题许可。金额由本地费率和Token预留计算，不代表供应商账单硬封顶。引用存在只证明来源身份可追溯，不等于结论已独立核实。
