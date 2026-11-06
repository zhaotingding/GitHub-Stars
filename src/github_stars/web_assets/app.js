'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; };
let state=null, csrf='', selectedProject=null, selectedResearch=null, settings=null, currentPage='radar', polling=false;
const titles={radar:'项目雷达',research:'项目研究',weekly:'每周精选',settings:'设置',logs:'运行记录'};
const completed=new Set();
let initialized=false,lastResearch='',stopped=false;
let projectSearchResults=null,searchTimer=null,selectedProjectName='';
const statusNames={running:'运行中',queued:'等待执行',done:'已完成',failed:'未完成',unknown:'结果未知',empty:'没有匹配资料',limited:'达到限制',paused:'可取回结果',blocked:'提交未知',continuable:'等待继续',cancelled:'已停止',archived:'已收藏'};
function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
async function api(path,data){
  const options={credentials:'same-origin',cache:'no-store'};
  if(data!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Stars-CSRF':csrf};options.body=JSON.stringify(data);}
  const response=await fetch(path,options); const result=await response.json();
  if(!response.ok)throw new Error(result.error||'请求未完成'); return result;
}
function safe(task){return async event=>{try{await task(event);}catch(error){notice(error.message,true);}};}
function button(text,callback,cls=''){const node=el('button',text,cls);node.type='button';node.addEventListener('click',safe(callback));return node;}
function link(text,address){const node=el('a',text);try{const url=new URL(address);if(url.protocol==='https:'&&url.hostname==='github.com'){node.href=url.href;node.target='_blank';node.rel='noopener noreferrer';}}catch{}return node;}
async function action(name,args={}){
  const id=crypto.randomUUID().replaceAll('-','');
  const result=await api('/api/action',{id,action:name,args});
  if(name==='research')selectedResearch=id;
  notice('任务已提交，可在运行记录中查看。');await refresh();return result;
}
async function control(name,args){const result=await api('/api/control',{action:name,args});if(result.state==='deleted'&&selectedResearch===args.job_id)clearResearch();await refresh();}
function clearResearch(){
  selectedResearch=null;lastResearch='';
  const box=$('research-answer');box.classList.add('empty');box.textContent='选择历史记录，或提交一个新问题。';
  for(const id of ['research-controls','research-sources'])$(id).replaceChildren();
  for(const id of ['source-text','research-trace','research-organization'])$(id).textContent='';
  $('sources-details').open=false;
}
function switchPage(name){currentPage=name;document.querySelectorAll('.page').forEach(page=>page.classList.toggle('hidden',page.id!=='page-'+name));document.querySelectorAll('#navigation button').forEach(b=>b.classList.toggle('active',b.dataset.page===name));$('page-title').textContent=titles[name];notice(name==='settings'?'修改后点击保存。网页输入的Key仅用于当前应用进程。':'当前使用本机资料库，任务进度可在运行记录中查看。');if(name==='settings'&&!settings)loadSettings().catch(e=>notice(e.message,true));if(name==='logs')loadLogs().catch(e=>notice(e.message,true));}
async function refresh(){
  if(polling||stopped)return;polling=true;
  try{
    state=await api('/api/state');csrf=state.csrf;
    document.documentElement.dataset.theme=state.theme;$('theme-choice').value=state.theme;
    $('version').textContent='版本 '+state.version+' · 浏览器操作';$('summary').textContent=state.project_count+' 个项目 · '+(state.busy?'任务运行中':'准备就绪');
    document.querySelectorAll('.task-button').forEach(node=>node.disabled=state.busy);$('save-settings').disabled=state.busy;
    renderProjects();renderHistory();renderWeeks();renderOperations();
    const oldScope=$('research-scope').value;$('research-scope').replaceChildren(new Option('全部本地项目',''));
    for(const repo of state.projects)$('research-scope').add(new Option(repo.name,String(repo.id)));
    $('research-scope').value=oldScope;
    if(selectedProject&&!Array.from($('research-scope').options).some(option=>option.value===String(selectedProject)))$('research-scope').add(new Option(selectedProjectName,String(selectedProject)));
    if(oldScope)$('research-scope').value=oldScope;
    for(const operation of state.operations){
      if(['done','failed','unknown'].includes(operation.state)&&!completed.has(operation.id)){
        completed.add(operation.id);const result=JSON.parse(operation.result||'{}');
        if(result.research_job_id&&selectedResearch===operation.id)selectedResearch=result.research_job_id;
        if(initialized){notice(operation.error||result.message||'任务已结束',operation.state!=='done');if(selectedProject)await loadProject(selectedProject);}
      }
    }
    if(selectedResearch&&[...state.research,...state.bookmarks].some(job=>job.id===selectedResearch))await loadResearch(selectedResearch);
    initialized=true;
    if(currentPage==='logs')await loadLogs();
  }finally{polling=false;}
}
function renderProjects(){
  const query=$('search').value.toLowerCase();const list=$('project-list');list.replaceChildren();
  for(const repo of (projectSearchResults??state.projects).filter(r=>(r.name+' '+r.description).toLowerCase().includes(query))){
    const item=button('',()=>loadProject(repo.id),'project-card'+(repo.id===selectedProject?' selected':''));
    item.append(el('div',repo.name,'project-name'),el('div',repo.description,'project-description'),el('div','★ '+repo.stars+'　·　匹配 '+Number(repo.score).toFixed(1)+'　·　'+(state.study_states[repo.study_state]||repo.study_state),'meta'));list.append(item);
  }
  if(!list.childElementCount)list.append(el('p','暂无项目。先导入仓库，或点击立即采集。','muted'));
}
async function loadProject(id){
  const repo=await api('/api/project?id='+encodeURIComponent(id));selectedProject=id;renderProjects();
  selectedProjectName=repo.name;if(!Array.from($('research-scope').options).some(option=>option.value===String(id)))$('research-scope').add(new Option(repo.name,String(id)));
  const box=$('project-detail');box.replaceChildren(el('h2',repo.name),link('在 GitHub 中查看','https://github.com/'+repo.name),el('p',repo.metadata.description||'作者未填写简介','muted'));
  const tools=el('div',undefined,'toolbar');const status=el('select');status.setAttribute('aria-label','项目研究状态');
  for(const [value,label]of Object.entries(state.study_states))status.add(new Option(label,value));status.value=repo.study_state;
  status.addEventListener('change',safe(()=>control('study_state',{repo_id:id,state:status.value})));tools.append(status);
  for(const [label,name]of [['初始分析','analysis'],['生成教程','tutorial']])tools.append(button(label,()=>action(name,{repo_id:id}),'task-button'));
  const download=el('a','下载已有教程');download.href='/api/tutorial?id='+id;tools.append(download);box.append(tools);
  box.append(button('围绕该项目提问',()=>{$('research-scope').value=String(id);switchPage('research');$('question').focus();}));
  if(repo.analysis){box.append(el('h3','初始分析'),el('pre',JSON.stringify(repo.analysis,null,2)));}
  if(repo.legacy?.length){const legacy=el('details');legacy.append(el('summary','旧版本记录'),el('pre',JSON.stringify(repo.legacy,null,2)));box.append(legacy);}
  if(repo.jobs.length){const jobs=el('details');jobs.append(el('summary','生成任务与恢复'));for(const job of repo.jobs){const row=el('div',undefined,'operation');row.append(el('span',job.kind+' · '+job.status+' '+(job.error||'')));if(['submitting','unknown','received','invalid'].includes(job.status)&&['analysis','tutorial'].includes(job.kind))row.append(button('取回原结果',()=>action('recover',{repo_id:id,kind:job.kind})));jobs.append(row);}box.append(jobs);}
  const readme=el('details');readme.open=true;readme.append(el('summary','README 原文'),el('pre',repo.readme||'尚未保存README。'));box.append(readme);
  if(state.busy)box.querySelectorAll('.task-button').forEach(b=>b.disabled=true);
}
function renderHistory(){const box=$('research-history');box.replaceChildren();const seen=new Set();for(const job of [...state.research,...state.bookmarks]){if(seen.has(job.id))continue;seen.add(job.id);const node=button(job.question,()=>{selectedResearch=job.id;return loadResearch(job.id);},'history-card');box.append(node);}if(!box.childElementCount)box.append(el('p','完成第一个问题后，研究记录会保存在这里。','muted'));}
async function loadResearch(id){
  let job;try{job=await api('/api/research?id='+encodeURIComponent(id));}catch(error){if(state.busy)return;throw error;}
  if(selectedResearch!==id)return;
  const snapshot=JSON.stringify(job);if(snapshot===lastResearch)return;lastResearch=snapshot;$('source-text').textContent='';
  const box=$('research-answer');box.classList.remove('empty');box.replaceChildren(el('h2',job.question),el('p',(statusNames[job.state]||job.state)+' · '+(job.calls||0)+' 次调用','muted'));
  for(const claim of job.result?.claims||[]){const row=el('div',undefined,'claim');row.append(el('div',claim.text));for(const label of claim.sources||[])row.append(button('['+label+']',()=>showSource(job,label),'citation'));box.append(row);}
  if(job.error)box.append(el('p',job.error,'muted'));for(const text of job.result?.limitations||[])box.append(el('p',text,'muted'));
  const controls=$('research-controls');controls.replaceChildren();
  if(job.can_resume)controls.append(button('取回原结果',()=>action('research_resume',{job_id:id})));
  if(job.can_continue)controls.append(button('明确继续',()=>action('research_continue',{job_id:id})));
  if(['running','paused','continuable','blocked'].includes(job.state))controls.append(button('停止后续步骤',()=>control('research_cancel',{job_id:id})));
  if(['done','archived'].includes(job.state))controls.append(button(job.saved?'取消收藏':'收藏回答',()=>control('research_bookmark',{job_id:id,saved:!job.saved})));
  if(job.state==='done')for(const [label,rating]of [['有用','useful'],['不相关','irrelevant'],['清除反馈','clear']])controls.append(button(label,()=>control('research_feedback',{job_id:id,rating})));
  const sources=$('research-sources');sources.replaceChildren();for(const source of job.sources||[])sources.append(button('['+source.label+'] '+source.name,()=>showSource(job,source.label),'citation'));
  $('research-trace').textContent=(job.trace||[]).map((entry,i)=>(i+1)+'. '+entry.action+'\n'+entry.detail).join('\n\n');
  $('research-organization').textContent=JSON.stringify(job.organization||{},null,2);
}
function showSource(job,label){const source=(job.sources||[]).find(s=>s.label===label);if(!source)return;const text=source.text||'此收藏仅保留答案与来源位置，原文已到期清理，请重新打开来源核对。';$('sources-details').open=true;$('source-text').textContent='['+source.label+'] '+source.name+'\n来源：'+source.url+'\n版本：'+source.sha+'\n采集：'+source.captured+'\n\n'+text;$('source-text').scrollIntoView({behavior:'smooth',block:'nearest'});}
function renderWeeks(){const previous=$('weeks').value;$('weeks').replaceChildren();for(const row of state.digests)$('weeks').add(new Option(row.week+' · '+row.note,row.week));if(previous)$('weeks').value=previous;}
function renderOperations(){const box=$('operations');box.replaceChildren();for(const row of state.operations){const item=el('div',undefined,'operation');item.append(el('strong',row.action+' · '+row.state),el('div',row.error||JSON.parse(row.result||'{}').message||'','muted'));box.append(item);}}
async function loadLogs(){const logs=await api('/api/logs');$('logs-text').textContent=JSON.stringify(logs,null,2);}
async function loadSettings(){
  settings=await api('/api/config');const nav=$('settings-nav'),form=$('settings-form');nav.replaceChildren();form.replaceChildren();
  settings.schema.forEach((category,index)=>{
    const section=el('section');section.className='setting-section'+(index?' hidden':'');section.dataset.category=category.name;section.append(el('h2',category.name));
    const tab=button(category.name,()=>{form.querySelectorAll('.setting-section').forEach(s=>s.classList.toggle('hidden',s!==section));nav.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b===tab));});if(!index)tab.classList.add('active');nav.append(tab);
    if(category.name==='API连接'||category.name==='邮件推送'){
      section.append(el('p','网页输入的密钥仅用于本次应用进程，不写入配置或日志。留空保留已有凭据；文本凭据来源选 local。','note'));
      const keys=category.name==='API连接'?[['openai','模型 API Key'],['github','GitHub Token（可选）']]:[['smtp','SMTP 授权码']];
      for(const [kind,label]of keys){const field=el('div',undefined,'field');const input=el('input');input.type='password';input.autocomplete='new-password';input.dataset.secret=kind;input.id='secret-'+kind;const lab=el('label',label);lab.htmlFor=input.id;field.append(lab,input);section.append(field);}
    }
    for(const spec of category.fields){
      const field=el('div',undefined,'field'),value=settings.config[spec.section][spec.key];let input;
      if(spec.choices.length){input=el('select');for(const choice of spec.choices)input.add(new Option(choice,choice));input.value=value;}
      else if(spec.type==='list'||spec.key==='prompt'||spec.key==='description'){input=el('textarea');input.rows=spec.key==='prompt'?8:4;input.value=Array.isArray(value)?value.join('\n'):value;}
      else{input=el('input');input.type=spec.type==='bool'?'checkbox':['int','float'].includes(spec.type)?'number':'text';if(spec.type==='bool')input.checked=value;else input.value=value;if(spec.type==='float')input.step='any';}
      input.dataset.section=spec.section;input.dataset.key=spec.key;input.dataset.type=spec.type;input.id='setting-'+spec.section+'-'+spec.key;const label=el('label',spec.label);label.htmlFor=input.id;field.append(label,input);section.append(field);
    }
    form.append(section);
  });
}
async function saveSettings(){
  const config=structuredClone(settings.config),entered={};
  for(const input of $('settings-form').querySelectorAll('[data-section]')){let value=input.type==='checkbox'?input.checked:input.value;if(input.dataset.type==='list')value=value.split('\n').map(v=>v.trim()).filter(Boolean);if(['int','float'].includes(input.dataset.type)){if(!String(value).trim())throw new Error('数值不能为空');value=Number(value);if(!Number.isFinite(value)||(input.dataset.type==='int'&&!Number.isInteger(value)))throw new Error('请输入有效数值');}config[input.dataset.section][input.dataset.key]=value;}
  for(const input of $('settings-form').querySelectorAll('[data-secret]'))if(input.value.trim())entered[input.dataset.secret]=input.value;
  const result=await api('/api/settings',{config,revision:settings.revision,secrets:entered});
  settings.config=config;settings.revision=result.revision;document.querySelectorAll('[data-secret]').forEach(input=>input.value='');notice(result.message);
}
async function ask(){
  const input=$('images'),images=Array.from(input.files),allow=$('allow-images').checked;
  if(images.length&&!allow)throw new Error('请先勾选“仅本题允许读图”。');
  const attachments=[];for(const file of images){if(file.size>2000000||!file.name.toLowerCase().endsWith('.png'))throw new Error('请选择每张最多2MB的PNG。');const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('无法读取附件'));reader.readAsDataURL(file);});attachments.push({data});}
  const scope=$('research-scope').value;
  await action('research',{question:$('question').value,mode:$('research-mode').value,repo_ids:scope?[Number(scope)]:null,allow_images:allow,attachments});
  input.value='';$('allow-images').checked=false;
}
document.querySelectorAll('#navigation button').forEach(node=>node.addEventListener('click',()=>switchPage(node.dataset.page)));
$('refresh').addEventListener('click',safe(refresh));$('scan').addEventListener('click',safe(()=>action('scan')));$('import').addEventListener('click',safe(()=>action('import',{text:$('import-text').value})));
$('search').addEventListener('input',()=>{clearTimeout(searchTimer);const query=$('search').value;searchTimer=setTimeout(async()=>{try{projectSearchResults=query?(await api('/api/projects?q='+encodeURIComponent(query))).projects:null;if($('search').value===query)renderProjects();}catch(error){notice(error.message,true);}},200);});$('ask').addEventListener('click',safe(ask));$('digest').addEventListener('click',safe(()=>action('digest')));
$('view-week').addEventListener('click',safe(async()=>{$('weekly-text').textContent=(await api('/api/digest?week='+encodeURIComponent($('weeks').value))).text;}));
$('save-settings').addEventListener('click',safe(saveSettings));$('reload-settings').addEventListener('click',safe(async()=>{await loadSettings();notice('已重新读取保存的设置。');}));$('settings-form').addEventListener('submit',event=>event.preventDefault());
$('stop-server').addEventListener('click',safe(async()=>{if(!window.confirm('停止本机网页服务后，此页面将断开。确认停止？'))return;const result=await api('/api/shutdown',{});stopped=true;notice(result.message);document.querySelectorAll('button').forEach(button=>button.disabled=true);}));
$('theme-choice').addEventListener('change',safe(async()=>{const current=await api('/api/config');const choice=$('theme-choice').value;const result=await api('/api/settings',{config:{appearance:{theme:choice}},revision:current.revision,secrets:{}});if(settings&&settings.revision===current.revision){settings.config.appearance.theme=choice;settings.revision=result.revision;}document.documentElement.dataset.theme=choice;notice('主题已保存。');}));
for(const format of ['html','markdown'])$('export-'+format).addEventListener('click',safe(()=>{const week=$('weeks').value;if(!week)throw new Error('请先选择已有周报');window.location.assign('/api/report?week='+encodeURIComponent(week)+'&format='+format);}));
for(const [id,retry]of [['send-mail',false],['retry-mail',true]])$(id).addEventListener('click',safe(async()=>{const week=$('weeks').value;if(!week)throw new Error('请先选择已有周报');if(!window.confirm(retry?'明确重发可能产生重复邮件。确认已经检查原邮件状态？':'将使用已保存SMTP设置发送选中的周报，是否继续？'))return;await action('email',{week,retry});}));
refresh().then(()=>{notice('已连接本机资料库。先导入项目，或在设置中配置API。');setInterval(()=>refresh().catch(e=>notice(e.message,true)),1500);}).catch(e=>notice(e.message,true));
