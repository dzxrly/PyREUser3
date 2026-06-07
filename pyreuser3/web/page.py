"""Embed the Web UI HTML, CSS, and TypeScript strings returned by the local server.

The page contains bilingual UI text, browser-language detection, path pickers, job
polling, and log rendering.
"""

from __future__ import annotations

STYLE_CSS = r"""
:root{--bg:#f7f7f4;--panel:#fff;--text:#1c1d1f;--muted:#697078;--line:#d8ddd6;--accent:#176f6b;--red:#b0332e;--green:#227343;--blue:#315f9b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif;font-size:14px;letter-spacing:0}
button,input,textarea{font:inherit}.topbar{border-bottom:1px solid var(--line);background:#fffefb}.topbar-inner{max-width:1180px;margin:0 auto;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{margin:0;font-size:20px;line-height:1.2}.sub{margin:4px 0 0;color:var(--muted);line-height:1.4}.pill{border:1px solid var(--line);border-radius:999px;padding:6px 11px;background:#f3f7f1;color:#10514e;white-space:nowrap}
.top-actions{display:flex;align-items:center;gap:10px}.lang-toggle{display:flex;border:1px solid var(--line);border-radius:7px;background:#fbfcfa;overflow:hidden}.lang-button{border:0;background:transparent;color:#384044;padding:7px 10px;min-width:48px;cursor:pointer;font-weight:700}.lang-button+.lang-button{border-left:1px solid var(--line)}.lang-button.active{background:var(--accent);color:#fff}
main{max-width:1180px;margin:0 auto;padding:18px 20px 24px;display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,.82fr);gap:18px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-width:0}
.head{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px}.head h2{margin:0;font-size:15px}.form{padding:16px;display:grid;gap:14px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.inline{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.field{display:grid;gap:6px;min-width:0}.wide{grid-column:1/-1}
label{color:#32363a;font-size:13px;font-weight:650}input,textarea{width:100%;border:1px solid #cfd7cf;border-radius:7px;background:#fff;color:var(--text);padding:9px 10px;outline:none;min-width:0}input[readonly]{background:#f7f8f5;color:#303437}input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(23,111,107,.14)}textarea{min-height:88px;resize:vertical;line-height:1.45}
.path-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px}.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:4px}.primary{border:1px solid #10514e;background:var(--accent);color:#fff;border-radius:7px;padding:10px 15px;min-width:112px;cursor:pointer;font-weight:700}.secondary{border:1px solid var(--line);background:#fbfcfa;color:#263433;border-radius:7px;padding:9px 11px;white-space:nowrap;cursor:pointer}.primary:disabled,.secondary:disabled{cursor:not-allowed;opacity:.62}.notice{color:var(--red);line-height:1.45;word-break:break-word}
.jobs{max-height:244px;overflow:auto}.job{width:100%;border:0;border-bottom:1px solid var(--line);background:transparent;padding:11px 14px;display:grid;grid-template-columns:1fr auto;gap:8px;text-align:left;cursor:pointer}.job:hover,.job.active{background:#f2f7f2}.job-title{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.time{margin-top:3px;color:var(--muted);font-size:12px}
.badge{align-self:start;border-radius:999px;padding:4px 8px;font-size:12px;border:1px solid var(--line);white-space:nowrap}.queued,.running{color:var(--blue);background:#eef4fb;border-color:#cbd9ee}.done{color:var(--green);background:#eef8f1;border-color:#c8e2cf}.failed{color:var(--red);background:#fff0ef;border-color:#e8cbc8}
.detail{padding:14px;display:grid;gap:12px;min-height:360px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.metric{border:1px solid var(--line);border-radius:7px;padding:10px;background:#fbfcfa}.metric span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.metric strong{font-size:18px}
pre{margin:0;padding:12px;border:1px solid var(--line);border-radius:7px;background:#1f2424;color:#f4f6ee;min-height:180px;max-height:420px;overflow:auto;line-height:1.5;white-space:pre-wrap;word-break:break-word}.empty,.muted{color:var(--muted)}
@media(max-width:980px){main{grid-template-columns:1fr}}@media(max-width:680px){.topbar-inner,.actions{align-items:stretch;flex-direction:column}.top-actions{width:100%;justify-content:space-between}.grid,.inline,.metrics,.path-row{grid-template-columns:1fr}main{padding:12px}.primary,.secondary{width:100%}}
"""

APP_TS = r"""
declare const Vue:any;
type JobStatus="queued"|"running"|"done"|"failed";
type Language="en"|"zh";
interface Job{id:string;kind:string;status:JobStatus;createdAt:number;updatedAt:number;logs?:string[];result?:Record<string,any>|null;error?:string|null}
interface JobsResponse{jobs:Job[];rootDir:string}
const{createApp,computed,nextTick,onMounted,reactive,ref,watch}=Vue;

const I18N={
  en:{
    allFiles:"All files",
    appTitle:"RE User3 JSON Web",
    browseDirectory:"Choose Directory",
    browseFile:"Choose File",
    connected:"Connected",
    disconnected:"Disconnected",
    dialogIl2cpp:"Select il2cpp_dump.json",
    dialogInputDirectory:"Select a directory containing .user.3 files",
    dialogInputFile:"Select a .user.3 file",
    dialogOutputDirectory:"Select a JSON output directory",
    dialogSchema:"Select an RE_RSZ schema JSON",
    errorLabel:"Error",
    excludeRegexes:"Exclude Regexes",
    exportPanel:"Export .user.3 to JSON",
    inputPath:"Input Directory or .user.3 File",
    inputPathPlaceholder:"Select a directory or .user.3 file",
    jobExport:"Export",
    jobs:"Jobs",
    jsonFiles:"JSON files",
    jsonOutput:"JSON Output Directory",
    jsonOutputPlaceholder:"Select a JSON output directory",
    language:"Language",
    logSelectJob:"Select or start a job.",
    logWaiting:"Job submitted; waiting for logs.",
    metricFailed:"Failed",
    metricSuccess:"Success",
    metricTotal:"Total",
    noJobs:"No jobs yet.",
    rszMagic:"RSZ magic",
    schema:"RE_RSZ Schema JSON",
    schemaPlaceholder:"Select an RE_RSZ schema JSON",
    startExport:"Start Export",
    statusDone:"Done",
    statusFailed:"Failed",
    statusQueued:"Queued",
    statusRunning:"Running",
    subtitle:"Exports .user.3 files to JSON. Select all paths with the picker buttons.",
    taskKindExport:"Export job",
    treeDepth:"Tree Depth",
    user3Files:"user3 files",
    userMagic:"USR magic"
  },
  zh:{
    allFiles:"所有文件",
    appTitle:"RE User3 JSON Web",
    browseDirectory:"选择目录",
    browseFile:"选择文件",
    connected:"已连接",
    disconnected:"连接中断",
    dialogIl2cpp:"选择 il2cpp_dump.json",
    dialogInputDirectory:"选择包含 .user.3 的目录",
    dialogInputFile:"选择 .user.3 文件",
    dialogOutputDirectory:"选择 JSON 输出目录",
    dialogSchema:"选择 RE_RSZ 模板 JSON",
    errorLabel:"错误",
    excludeRegexes:"排除正则",
    exportPanel:"导出 .user.3 为 JSON",
    inputPath:"输入目录或 .user.3 文件",
    inputPathPlaceholder:"请选择目录或 .user.3 文件",
    jobExport:"导出",
    jobs:"任务",
    jsonFiles:"JSON 文件",
    jsonOutput:"JSON 输出目录",
    jsonOutputPlaceholder:"请选择 JSON 输出目录",
    language:"语言",
    logSelectJob:"选择或启动一个任务。",
    logWaiting:"任务已提交，等待日志。",
    metricFailed:"失败",
    metricSuccess:"成功",
    metricTotal:"总数",
    noJobs:"暂无任务。",
    rszMagic:"RSZ magic",
    schema:"RE_RSZ 模板 JSON",
    schemaPlaceholder:"请选择 RE_RSZ 模板 JSON",
    startExport:"开始导出",
    statusDone:"完成",
    statusFailed:"失败",
    statusQueued:"排队",
    statusRunning:"运行中",
    subtitle:"支持将 .user.3 解包导出为 JSON，所有路径请通过选择按钮指定。",
    taskKindExport:"解包任务",
    treeDepth:"树深度",
    user3Files:"user3 文件",
    userMagic:"USR magic"
  }
} as const;
type TextKey=keyof typeof I18N.en;
const STATUS_KEYS:Record<JobStatus,TextKey>={queued:"statusQueued",running:"statusRunning",done:"statusDone",failed:"statusFailed"};

async function requestJson<T>(url:string,init?:RequestInit):Promise<T>{
  const response=await fetch(url,init);
  const body=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(body.error||response.statusText);
  return body as T;
}

function collectTotals(result:Record<string,any>|null|undefined){
  const item=result&&result.user3?result.user3:{};
  return{total:Number(item.total||0),success:Number(item.success||0),failed:Number(item.failed||0)};
}

function detectLanguage():Language{
  const values=navigator.languages&&navigator.languages.length?navigator.languages:[navigator.language||""];
  return values.some(value=>String(value).toLowerCase().startsWith("zh"))?"zh":"en";
}

function htmlLanguage(language:Language){
  return language==="zh"?"zh-CN":"en";
}

createApp({
  setup(){
    const activeJobId=ref<string|null>(null);
    const busy=ref(false);
    const connectionOk=ref(true);
    const jobs=ref<Job[]>([]);
    const language=ref<Language>(detectLanguage());
    const logBox=ref<HTMLElement|null>(null);
    const logRenderState=reactive({jobId:null as string|null,text:""});
    const notice=ref("");
    const rootDir=ref("");
    const exportForm=reactive({
      inputDir:"",schemaPath:"",outputDir:"",
      il2cppDumpPath:"",treeDepth:"auto",excludeRegexes:"",
      userMagic:"0x00525355",rszMagic:"0x005A5352"
    });

    function t(key:TextKey){return I18N[language.value][key]}
    const activeJob=computed<Job|null>(()=>jobs.value.find(job=>job.id===activeJobId.value)||null);
    const activeTotals=computed(()=>collectTotals(activeJob.value?.result));
    const connectionLabel=computed(()=>t(connectionOk.value?"connected":"disconnected"));
    function jobLogText(job:Job|null){
      if(!job)return t("logSelectJob");
      const lines=job.logs?[...job.logs]:[];
      if(job.error)lines.push(`[${t("errorLabel")}] ${job.error}`);
      if(job.result)lines.push(JSON.stringify(job.result,null,2));
      return lines.join("\n")||t("logWaiting");
    }
    function isLogNearBottom(element:HTMLElement){
      return element.scrollHeight-element.scrollTop-element.clientHeight<24;
    }
    function scrollLogToBottom(element:HTMLElement){
      window.requestAnimationFrame(()=>{element.scrollTop=element.scrollHeight});
    }
    function renderActiveLog(){
      const element=logBox.value;
      if(!element)return;
      const job=activeJob.value;
      const text=jobLogText(job);
      const jobId=job?.id||null;
      const previous=logRenderState.jobId===jobId?logRenderState.text:"";
      const switchedJob=logRenderState.jobId!==jobId;
      const shouldFollow=switchedJob||isLogNearBottom(element);

      if(switchedJob||!previous||!text.startsWith(previous)){
        element.textContent=text;
      }else if(text.length>previous.length){
        element.insertAdjacentText("beforeend",text.slice(previous.length));
      }else{
        return;
      }

      logRenderState.jobId=jobId;
      logRenderState.text=text;
      if(shouldFollow)scrollLogToBottom(element);
    }

    function mergeJob(job:Job){
      const index=jobs.value.findIndex(item=>item.id===job.id);
      if(index>=0)jobs.value[index]={...jobs.value[index],...job};
      else jobs.value.unshift(job);
    }
    function mergeJobList(incoming:Job[]){
      jobs.value=incoming.map(job=>{
        const current=jobs.value.find(item=>item.id===job.id);
        return current?{...current,...job,logs:job.logs||current.logs}:job;
      });
    }
    async function refreshActive(){
      if(!activeJobId.value)return;
      try{mergeJob((await requestJson<{job:Job}>(`/api/jobs/${activeJobId.value}`)).job)}catch{}
    }
    async function refreshJobs(){
      try{
        const data=await requestJson<JobsResponse>("/api/jobs");
        rootDir.value=data.rootDir;
        mergeJobList(data.jobs);
        if(!activeJobId.value&&jobs.value.length)activeJobId.value=jobs.value[0].id;
        await refreshActive();
        connectionOk.value=true;
      }catch{connectionOk.value=false}
    }
    async function submitExport(){
      notice.value="";busy.value=true;
      try{
        const data=await requestJson<{jobId:string}>("/api/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...exportForm})});
        activeJobId.value=data.jobId;
        await refreshActive();
      }catch(error){notice.value=error instanceof Error?error.message:String(error)}
      finally{busy.value=false}
    }
    async function pickPath(form:Record<string,any>,key:string,kind:"file"|"directory",title:string,filetypes?:string[][]){
      notice.value="";
      try{
        const data=await requestJson<{path:string}>("/api/pick-path",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind,title,filetypes:filetypes||[]})});
        if(data.path)form[key]=data.path;
      }catch(error){notice.value=error instanceof Error?error.message:String(error)}
    }
    function selectJob(jobId:string){activeJobId.value=jobId;refreshActive()}
    function selectLanguage(value:Language){language.value=value}
    function jobCountLabel(count:number){return language.value==="zh"?`${count} 个`:`${count} job${count===1?"":"s"}`}
    function jobName(job:Job){return `${t("jobExport")} #${job.id}`}
    function statusLabel(status:JobStatus){return t(STATUS_KEYS[status])}
    function formatTime(value:number){return value?new Date(value*1000).toLocaleString():""}

    watch(activeJob,()=>{nextTick(renderActiveLog)},{deep:true,immediate:true});
    watch(language,value=>{document.documentElement.lang=htmlLanguage(value);document.title=t("appTitle");nextTick(renderActiveLog)},{immediate:true});
    onMounted(()=>{renderActiveLog();refreshJobs();window.setInterval(refreshJobs,1200)});
    return{activeJob,activeJobId,activeTotals,busy,connectionLabel,exportForm,formatTime,jobCountLabel,jobName,jobs,language,logBox,notice,pickPath,rootDir,selectJob,selectLanguage,statusLabel,submitExport,t};
  }
}).mount("#app");
"""

INDEX_HTML = (
    r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RE User3 JSON Web</title>
  <style>"""
    + STYLE_CSS
    + r"""</style>
</head>
<body>
  <div id="app">
    <header class="topbar"><div class="topbar-inner">
      <div><h1>{{ t("appTitle") }}</h1><p class="sub">{{ t("subtitle") }}</p></div>
      <div class="top-actions">
        <div class="lang-toggle" role="group" :aria-label="t('language')">
          <button class="lang-button" type="button" :class="{active:language==='en'}" :aria-pressed="language==='en'" @click="selectLanguage('en')">EN</button>
          <button class="lang-button" type="button" :class="{active:language==='zh'}" :aria-pressed="language==='zh'" @click="selectLanguage('zh')">中文</button>
        </div>
        <div class="pill">{{ connectionLabel }}</div>
      </div>
    </div></header>

    <main>
      <section class="panel">
        <div class="head"><h2>{{ t("exportPanel") }}</h2><span class="muted">{{ t("taskKindExport") }}</span></div>
        <form class="form" @submit.prevent="submitExport">
          <div class="grid">
            <div class="field wide"><label>{{ t("inputPath") }}</label><div class="path-row"><input v-model="exportForm.inputDir" readonly :placeholder="t('inputPathPlaceholder')"><button class="secondary" type="button" @click="pickPath(exportForm,'inputDir','directory',t('dialogInputDirectory'))">{{ t("browseDirectory") }}</button><button class="secondary" type="button" @click="pickPath(exportForm,'inputDir','file',t('dialogInputFile'),[[t('user3Files'),'*.user.3'],[t('allFiles'),'*.*']])">{{ t("browseFile") }}</button></div></div>
            <div class="field wide"><label>{{ t("schema") }}</label><div class="path-row"><input v-model="exportForm.schemaPath" readonly :placeholder="t('schemaPlaceholder')"><button class="secondary" type="button" @click="pickPath(exportForm,'schemaPath','file',t('dialogSchema'),[[t('jsonFiles'),'*.json'],[t('allFiles'),'*.*']])">{{ t("browseFile") }}</button></div></div>
            <div class="field wide"><label>{{ t("jsonOutput") }}</label><div class="path-row"><input v-model="exportForm.outputDir" readonly :placeholder="t('jsonOutputPlaceholder')"><button class="secondary" type="button" @click="pickPath(exportForm,'outputDir','directory',t('dialogOutputDirectory'))">{{ t("browseDirectory") }}</button></div></div>
            <div class="field wide"><label>il2cpp_dump.json</label><div class="path-row"><input v-model="exportForm.il2cppDumpPath" readonly :placeholder="t('dialogIl2cpp')"><button class="secondary" type="button" @click="pickPath(exportForm,'il2cppDumpPath','file',t('dialogIl2cpp'),[[t('jsonFiles'),'*.json'],[t('allFiles'),'*.*']])">{{ t("browseFile") }}</button></div></div>
          </div>
          <div class="inline">
            <div class="field"><label>{{ t("treeDepth") }}</label><input v-model="exportForm.treeDepth" autocomplete="off"></div>
            <div class="field"><label>{{ t("userMagic") }}</label><input v-model="exportForm.userMagic" autocomplete="off"></div>
            <div class="field"><label>{{ t("rszMagic") }}</label><input v-model="exportForm.rszMagic" autocomplete="off"></div>
          </div>
          <div class="field"><label>{{ t("excludeRegexes") }}</label><textarea v-model="exportForm.excludeRegexes" spellcheck="false"></textarea></div>
          <div class="actions"><button class="primary" type="submit" :disabled="busy">{{ t("startExport") }}</button><div class="notice">{{ notice }}</div></div>
        </form>
      </section>

      <aside class="panel">
        <div class="head"><h2>{{ t("jobs") }}</h2><span class="muted">{{ jobCountLabel(jobs.length) }}</span></div>
        <div v-if="jobs.length" class="jobs">
          <button v-for="job in jobs" :key="job.id" class="job" :class="{active:activeJobId===job.id}" @click="selectJob(job.id)">
            <span><span class="job-title">{{ jobName(job) }}</span><span class="time">{{ formatTime(job.updatedAt) }}</span></span>
            <span class="badge" :class="job.status">{{ statusLabel(job.status) }}</span>
          </button>
        </div>
        <div v-else class="empty">{{ t("noJobs") }}</div>
        <div class="detail">
          <div class="metrics">
            <div class="metric"><span>{{ t("metricTotal") }}</span><strong>{{ activeTotals.total }}</strong></div>
            <div class="metric"><span>{{ t("metricSuccess") }}</span><strong>{{ activeTotals.success }}</strong></div>
            <div class="metric"><span>{{ t("metricFailed") }}</span><strong>{{ activeTotals.failed }}</strong></div>
          </div>
          <pre ref="logBox">{{ t("logSelectJob") }}</pre>
        </div>
      </aside>
    </main>
  </div>
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <script src="https://unpkg.com/typescript@5/lib/typescript.js"></script>
  <script id="app-ts" type="text/typescript">"""
    + APP_TS
    + r"""</script>
  <script>
    (function(){
      if(!window.Vue||!window.ts){
        var languages=navigator.languages&&navigator.languages.length?navigator.languages:[navigator.language||""];
        var zh=languages.some(function(value){return String(value).toLowerCase().indexOf("zh")===0});
        document.documentElement.lang=zh?"zh-CN":"en";
        document.body.innerHTML="<div style='padding:24px;font-family:Segoe UI,Microsoft YaHei,sans-serif'>"+(zh?"Vue 或 TypeScript CDN 加载失败。":"Vue or TypeScript CDN failed to load.")+"</div>";
        return
      }
      var source=document.getElementById("app-ts").textContent;
      var output=window.ts.transpile(source,{target:window.ts.ScriptTarget.ES2020,module:window.ts.ModuleKind.None});
      var script=document.createElement("script");script.textContent=output;document.body.appendChild(script);
    })();
  </script>
</body>
</html>
"""
)
