from __future__ import annotations

import html
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


def _text(value):
    return html.escape(str(value or ""), quote=True)  # 所有模型文字只作文本，不解释为 HTML。


def _github_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        parts = parsed.path.strip("/").split("/")
        valid = parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.port in (None, 443)
        valid = valid and not parsed.username and not parsed.password and len(parts) >= 2
        valid = valid and all(re.fullmatch(r"[A-Za-z0-9_.-]+", item) for item in parts[:2])
        valid = valid and not any(unquote(item) in {".", ".."} for item in parts)
        if not valid or any(char.isspace() for char in str(value)) or "\\" in str(value):
            return ""
        return urlunsplit(("https", "github.com", parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        return ""  # 非 GitHub 地址仍以普通文字显示，不生成可点击链接。


def _link(label, address):
    safe = _github_url(address)
    return f'<a href="{_text(safe)}" target="_blank" rel="noopener noreferrer">{_text(label)} ↗</a>' if safe else _text(label)


def _list(items, ordered=False):
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{_text(item)}</li>" for item in items) + f"</{tag}>"


CSS = """
:root{color-scheme:dark;--bg:#101713;--surface:#17231d;--raised:#1c2c23;--ink:#e5eee8;--muted:#9eafa4;
 --line:#31483a;--accent:#a9d8b0;--solid:#b5ddb7;--buttonink:#132319;--code:#101a14;--wash:#203329}
:root[data-theme=light]{color-scheme:light;--bg:#eef3ed;--surface:#fafcf8;--raised:#e6eee3;--ink:#1b3023;
 --muted:#526b59;--line:#c4d4c4;--accent:#285f39;--solid:#2d6c40;--buttonink:#f5fbf2;--code:#e5ede1;--wash:#dcebd9}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:30px}body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.75 "Segoe UI","Microsoft YaHei UI",system-ui,sans-serif}button,a,input{ -webkit-tap-highlight-color:transparent}
button{font:inherit;cursor:pointer;border:1px solid var(--line);border-radius:9px;background:var(--raised);color:var(--ink);padding:8px 15px}
button:hover{border-color:var(--accent)}button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
button:disabled{opacity:.4;cursor:default}a{color:var(--accent);text-underline-offset:4px}p{margin:.5em 0 1em}
h1,h2,h3{line-height:1.35;letter-spacing:-.02em}h1{font-size:clamp(2.1rem,4vw,3.8rem);margin:.5em 0 .4em;max-width:1000px}
h2{font-size:1.65rem;margin:0 0 20px}h3{font-size:1.1rem;margin:0 0 8px}ul,ol{padding-left:23px}li{margin:.5em 0}
pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.8 Consolas,monospace}
.shell{max-width:1440px;margin:auto;padding:24px 46px 70px}.topbar{display:flex;justify-content:space-between;align-items:center;gap:20px;padding-bottom:25px;border-bottom:1px solid var(--line)}
.brand{font-weight:750;letter-spacing:.03em}.eyebrow{font-size:.8rem;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:650}
.hero{padding:52px 0 36px}.hero p{max-width:950px;font-size:1.1rem}.muted,.small{color:var(--muted)}.small{font-size:.86rem}.sources{display:flex;gap:18px;flex-wrap:wrap}
.layout{display:grid;grid-template-columns:205px minmax(0,1fr);gap:42px}.toc{position:sticky;top:25px;align-self:start;padding:21px 0}
.toc a{display:block;color:var(--muted);text-decoration:none;border-left:2px solid var(--line);padding:7px 15px;font-size:.92rem}.toc a:hover{color:var(--accent);border-color:var(--accent)}
main{min-width:0}section{padding:28px 0 38px;border-top:1px solid var(--line)}.sectionhead{display:flex;align-items:baseline;gap:13px}.number{color:var(--accent);font:600 .83rem Consolas,monospace}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:14px}.card,.note,.practice{border:1px solid var(--line);border-radius:13px;background:var(--surface);padding:22px}
.example{background:var(--wash);border-radius:8px;padding:13px 15px;font-size:.93rem}.copytext{white-space:pre-wrap;overflow-wrap:anywhere}
.flow{display:flex;gap:10px;align-items:stretch;overflow:auto;padding-bottom:10px}.flow button{min-width:145px;flex:1;text-align:left;position:relative}
.flow button[aria-pressed=true],.stepnav button[aria-selected=true]{border-color:var(--accent);background:var(--wash)}.flow small{display:block;font-family:Consolas,monospace;color:var(--accent)}
.flowdetail{margin-top:9px;min-height:112px}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:16px}.primary{background:var(--solid);color:var(--buttonink);border-color:transparent;font-weight:650}
.practicegrid{display:grid;grid-template-columns:210px minmax(0,1fr);gap:18px}.stepnav{display:flex;flex-direction:column;gap:8px}.stepnav button{text-align:left;padding:12px 14px;font-size:.93rem}
.stepnav span{display:block;color:var(--muted);font-size:.76rem}.progressline{display:flex;align-items:center;gap:15px;flex-wrap:wrap;margin:0 0 24px}
progress{height:8px;flex:1;min-width:120px;accent-color:var(--accent)}.practice h3{font-size:1.3rem}.label{font-size:.77rem;letter-spacing:.1em;color:var(--accent);font-weight:650;margin:18px 0 6px}
.codebox{border:1px solid var(--line);border-radius:9px;background:var(--code);overflow:hidden;margin:12px 0}.codebar{padding:8px 12px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;font-size:.8rem;color:var(--muted)}.codebar button{padding:3px 10px;font-size:.8rem}.codebox pre{padding:17px}
.outcome{border-left:3px solid var(--accent);padding:10px 15px;background:var(--wash);border-radius:0 7px 7px 0}.completion{display:flex;align-items:center;gap:9px;margin-top:22px;padding-top:18px;border-top:1px solid var(--line)}.completion input{width:18px;height:18px;accent-color:var(--accent)}
.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:.93rem;text-align:left}th,td{vertical-align:top;padding:13px 16px;border-bottom:1px solid var(--line)}th{color:var(--accent);font-size:.8rem;letter-spacing:.04em}td:first-child{font-weight:650}td{min-width:135px}
.checklist{counter-reset:route;list-style:none;padding:0}.checklist li{counter-increment:route;display:flex;gap:17px;padding:13px 0;border-bottom:1px solid var(--line)}.checklist li:before{content:counter(route,decimal-leading-zero);font:600 .95rem Consolas,monospace;color:var(--accent);padding-top:6px}
details{border:1px solid var(--line);border-radius:10px;margin:12px 0;padding:15px 18px;background:var(--surface)}summary{cursor:pointer;font-weight:600}details>p{padding-top:12px;margin-bottom:0}.note{color:var(--muted);font-size:.9rem}.footer{border-top:1px solid var(--line);margin-top:30px;padding-top:22px}
.status{font-size:.82rem;color:var(--accent);min-height:1.6em}.empty{color:var(--muted);padding:18px;border:1px dashed var(--line);border-radius:10px}[hidden]{display:none!important}
@media(max-width:900px){.shell{padding:20px 24px 45px}.layout{grid-template-columns:1fr;gap:10px}.toc{position:static;display:flex;flex-wrap:wrap;padding:0 0 15px;gap:5px}.toc a{border-left:0;padding:4px 9px}.hero{padding:35px 0 25px}.practicegrid{grid-template-columns:1fr}.stepnav{flex-direction:row;overflow:auto}.stepnav button{min-width:145px}.topbar{padding-bottom:18px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{.toc,.topbar button,.controls,.copy,.stepnav,.completion,.progressline{display:none}.shell{padding:0}.layout{display:block}.hero{padding-top:10px}.practice[hidden],.flowdetail[hidden]{display:block!important}.practice{margin:15px 0;break-inside:avoid}body{--bg:#fff;--surface:#fff;--raised:#eee;--ink:#111;--muted:#444;--accent:#244f31;--line:#ccc;--code:#f4f4f4;--wash:#f4f4f4}}
"""


SCRIPT = """
(()=>{
const root=document.documentElement;
document.querySelector('#theme').addEventListener('click',()=>{
 root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';
 document.querySelector('#theme').textContent=root.dataset.theme==='dark'?'切换浅色':'切换深色';
});
const flowButtons=[...document.querySelectorAll('[data-flow]')];
const flowPanels=[...document.querySelectorAll('[data-flow-panel]')];
let flowIndex=0;
function showFlow(index){
 flowIndex=index;
 flowButtons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
 flowPanels.forEach((panel,i)=>panel.hidden=i!==index);
 document.querySelector('#flow-prev').disabled=index===0;
 document.querySelector('#flow-next').disabled=index===flowButtons.length-1;
 document.querySelector('#flow-position').textContent=`${index+1} / ${flowButtons.length}`;
}
flowButtons.forEach((button,i)=>button.addEventListener('click',()=>showFlow(i)));
if(flowButtons.length){document.querySelector('#flow-prev').addEventListener('click',()=>showFlow(Math.max(0,flowIndex-1)));
 document.querySelector('#flow-next').addEventListener('click',()=>showFlow(Math.min(flowButtons.length-1,flowIndex+1)));showFlow(0);}
const stepButtons=[...document.querySelectorAll('[data-step]')];
const stepPanels=[...document.querySelectorAll('[data-step-panel]')];
const boxes=[...document.querySelectorAll('[data-complete]')];
const storageKey='github-stars-practice:'+document.body.dataset.storage+':'+location.pathname;
try{const saved=JSON.parse(localStorage.getItem(storageKey)||'[]');boxes.forEach((box,i)=>box.checked=saved.includes(i));}catch(_error){}
function updateProgress(){
 const done=boxes.filter(box=>box.checked).length;
 const progress=document.querySelector('#practice-progress');
 if(progress){progress.value=done;document.querySelector('#progress-label').textContent=`已完成 ${done} / ${boxes.length} 步`;
  stepButtons.forEach((button,i)=>button.querySelector('span').textContent=boxes[i].checked?'已实践 ✓':'等待实践');}
 try{localStorage.setItem(storageKey,JSON.stringify(boxes.flatMap((box,i)=>box.checked?[i]:[])));}catch(_error){}
}
function showStep(index){stepButtons.forEach((button,i)=>button.setAttribute('aria-selected',String(i===index)));
 stepPanels.forEach((panel,i)=>panel.hidden=i!==index);}
stepButtons.forEach((button,i)=>button.addEventListener('click',()=>showStep(i)));
boxes.forEach(box=>box.addEventListener('change',updateProgress));
if(stepButtons.length){document.querySelector('#reset-progress').addEventListener('click',()=>{boxes.forEach(box=>box.checked=false);updateProgress();});showStep(0);updateProgress();}
document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
 const code=document.getElementById(button.dataset.copy);const status=button.closest('.codebox').nextElementSibling;
 try{if(!navigator.clipboard)throw new Error('unavailable');await navigator.clipboard.writeText(code.textContent);status.textContent='命令已复制；请先核对官方来源，再自行运行。';}
 catch(_error){const range=document.createRange();range.selectNodeContents(code);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);status.textContent='已选中命令，请按 Ctrl+C（macOS：⌘C）复制。';}
}));
})();
"""


def render_tutorial(row: dict, lesson: dict, theme="dark") -> str:
    theme = "light" if theme == "light" else "dark"  # 无效主题回到默认深色。
    repo_name = str(row.get("name", "项目教程"))
    source = _link("README 来源", row.get("readme_url", ""))
    repo = _link(repo_name, "https://github.com/" + repo_name)
    sections = [("concepts", "理解核心思想"), ("workflow", "看懂工作流程"), ("practice", "动手跑通项目"),
                ("configuration", "配置与适配"), ("related", "比较相关项目"), ("contribute", "改进与贡献"), ("checkpoints", "检验理解"), ("evidence", "来源与边界")]
    toc = "".join(f'<a href="#{key}">{index:02d}　{title}</a>' for index, (key, title) in enumerate(sections, 1))

    def section(key, index, title, body):
        return f'<section id="{key}"><div class="sectionhead"><span class="number">{index:02d}</span><h2>{title}</h2></div>{body}</section>'

    concepts = "".join(f'<article class="card"><h3>{_text(item["name"])}</h3><p class="copytext">{_text(item["explanation"])}</p>'
                       f'<div class="example copytext"><strong>用一个例子理解</strong><br>{_text(item["example"])}</div></article>'
                       for item in lesson.get("concepts", []))
    content = section("concepts", 1, "先理解：项目的核心思想", f'<div class="cards">{concepts}</div>' if concepts else '<p class="empty">当前资料未说明核心概念，请回到 README 核对。</p>')

    workflow = lesson.get("workflow", [])
    if workflow:
        buttons = "".join(f'<button type="button" data-flow="{i}" aria-pressed="{str(i == 0).lower()}" aria-controls="flow-{i}"><small>STEP {i + 1:02d}</small>{_text(item["title"])}</button>' for i, item in enumerate(workflow))
        panels = "".join(f'<article id="flow-{i}" class="flowdetail card copytext" data-flow-panel="{i}"{ " hidden" if i else ""}><h3>{_text(item["title"])}</h3>{_text(item["detail"])}</article>' for i, item in enumerate(workflow))
        flow = f'<p class="muted">逐个选择节点，建立从输入到结果的解释链。流程依据材料整理，未执行代码。</p><div class="flow">{buttons}</div>{panels}<div class="controls"><button id="flow-prev" type="button">← 上一步</button><span id="flow-position" class="small"></span><button id="flow-next" type="button">下一步 →</button></div>'
    else:
        flow = '<p class="empty">当前资料不足以确认完整工作流程。</p>'
    content += section("workflow", 2, "把流程连起来", flow)

    steps = lesson.get("steps", [])
    prerequisites = '<div class="note"><strong>开始前，先确认</strong>' + _list(lesson.get("prerequisites", [])) + '</div>'
    if steps:
        step_buttons = "".join(f'<button type="button" data-step="{i}" role="tab" aria-selected="{str(i == 0).lower()}" aria-controls="step-{i}">{i + 1:02d}　{_text(item["title"])}<span>等待实践</span></button>' for i, item in enumerate(steps))
        panels = []
        for i, item in enumerate(steps):
            command = str(item.get("command", "")).strip()
            code = (f'<div class="codebox"><div class="codebar"><span>来源提供的命令／示例 · 不会自动执行</span><button class="copy" type="button" data-copy="code-{i}">复制命令</button></div><pre id="code-{i}">{_text(command)}</pre></div><div class="status" role="status"></div>') if command else '<p class="small">此步来源未提供可直接执行的命令；请按说明核对官方入口。</p>'
            panels.append(f'<article id="step-{i}" class="practice" data-step-panel="{i}" role="tabpanel"{ " hidden" if i else ""}><div class="eyebrow">Practice {i + 1:02d}</div><h3>{_text(item["title"])}</h3><p class="muted copytext">{_text(item["goal"])}</p><div class="label">操作与解释</div><div class="copytext">{_text(item["instructions"])}</div>{code}<div class="label">如何判断这一步成功</div><div class="outcome copytext">{_text(item["expected"])}</div><details><summary>没有得到预期结果？</summary><p class="copytext">{_text(item["troubleshooting"])}</p></details><label class="completion"><input type="checkbox" data-complete="{i}">我已亲自完成并核对这一步</label></article>')
        practice = f'{prerequisites}<p class="small">下列步骤由 AI 根据来源生成，未实际执行。勾选只记录你的实践进度，不代表程序已验证成功。</p><div class="progressline"><span id="progress-label" class="small"></span><progress id="practice-progress" max="{len(steps)}" value="0" aria-label="实践完成进度"></progress><button id="reset-progress" type="button">重置进度</button></div><div class="practicegrid"><div class="stepnav" role="tablist" aria-label="实践步骤">{step_buttons}</div><div>{"".join(panels)}</div></div>'
    else:
        practice = prerequisites + '<p class="empty">当前证据不足以提供实践步骤，避免猜造安装命令。</p>'
    content += section("practice", 3, "用最短路径完成第一次实践", practice)

    rows = "".join(f'<tr><td class="copytext">{_text(item["name"])}</td><td class="copytext">{_text(item["purpose"])}</td><td><pre>{_text(item["example"])}</pre></td><td class="copytext">{_text(item["source"])}</td></tr>' for item in lesson.get("configuration", []))
    config = f'<div class="tablewrap"><table><thead><tr><th>配置项</th><th>解决什么问题</th><th>配置示例</th><th>来源／待核实</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else '<p class="empty">来源未提供明确配置项；请核对项目文档。</p>'
    content += section("configuration", 4, "让配置服务于你的任务", config)

    cards = "".join(f'<article class="card"><h3>{_link(item["name"], item["url"])}</h3><p class="copytext">{_text(item["relationship"])}</p><p class="small copytext"><strong>依据：</strong>{_text(item["evidence"])}</p>{"<p class=small>地址未通过 GitHub 来源检查，仅显示名称。</p>" if not _github_url(item["url"]) else ""}</article>' for item in lesson.get("related_projects", []))
    content += section("related", 5, "知道什么时候换一种工具", '<div class="cards">' + cards + '</div>' if cards else '<p class="empty">当前材料没有可核对的相关项目，不补造推荐。</p>')

    contribute = '<div class="cards"><article class="card"><h3>从可验证的小改进开始</h3>' + _list(lesson.get("improvement_ideas", [])) + '</article><article class="card"><h3>走到一次可审查的 PR</h3>' + _list(lesson.get("contribution_steps", []), ordered=True) + '</article></div><p class="small">改进方向属于待验证建议。提交前回看项目的贡献说明、许可证与现有 Issue。</p>'
    content += section("contribute", 6, "从会用，到能改进与贡献", contribute)
    checkpoints = "".join(f'<details><summary>{_text(item["question"])}</summary><p class="copytext">{_text(item["answer"])}</p></details>' for item in lesson.get("checkpoints", []))
    content += section("checkpoints", 7, "合上教程前，检验你的理解", '<p class="muted">先自己回答，再展开对照。能解释选择和验证方法，比记住命令更有用。</p>' + checkpoints)
    evidence = f'<div class="note"><p class="copytext">{_text(lesson.get("limitations", ""))}</p><p>{source}</p><p class="copytext">README 快照：{_text(row.get("readme_sha") or "未知")}<br>采集时间：{_text(row.get("readme_at") or "未知")}</p><p>教程由 AI 根据有限材料生成，未执行仓库代码、未验证作者性能主张。外部来源链接需要联网；本页内容和交互可离线使用。</p></div>'
    content += section("evidence", 8, "保留来源，也保留不确定性", evidence)
    storage = repo_name + ":" + str(row.get("readme_sha", ""))
    title = lesson.get("title") or repo_name
    return f'''<!doctype html>
<html lang="zh-CN" data-theme="{theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{_text(title)} · GitHub Stars++</title><style>{CSS}</style></head>
<body data-storage="{_text(storage)}"><div class="shell"><header class="topbar"><div class="brand">✦ GitHub Stars++ <span class="small">/ 项目实践课</span></div><button id="theme" type="button">{"切换深色" if theme == "light" else "切换浅色"}</button></header>
<div class="hero"><div class="eyebrow">Understand → Practice → Contribute</div><h1>{_text(title)}</h1><p class="copytext">{_text(lesson.get("summary", ""))}</p><div class="sources"><span>{repo}</span><span class="small">由资料生成 · 未实际执行 · 可离线阅读</span></div></div>
<div class="layout"><nav class="toc" aria-label="教程目录">{toc}</nav><main>{content}</main></div><footer class="footer small">GitHub Stars++ · 把有限的阅读时间，用在理解、实践与改进上。</footer></div><script>{SCRIPT}</script></body></html>'''


def export_tutorial(paths, row, lesson, job_id: int, theme="dark") -> Path:
    folder = paths.data / "tutorials"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{int(row['id'])}-{int(job_id)}.html"  # 不用仓库名称拼文件路径。
    temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(render_tutorial(row, lesson, theme), encoding="utf-8")
    temporary.replace(target)  # 完整写入后再替换，保留可重新导出的独立 HTML。
    return target
