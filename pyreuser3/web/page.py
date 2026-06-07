"""本地 Vue Web UI 使用的 HTML、CSS 和 TypeScript 模板。"""

from __future__ import annotations

STYLE_CSS = r"""
:root{--bg:#f7f7f4;--panel:#fff;--text:#1c1d1f;--muted:#697078;--line:#d8ddd6;--accent:#176f6b;--red:#b0332e;--green:#227343;--blue:#315f9b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif;font-size:14px;letter-spacing:0}
button,input,textarea{font:inherit}.topbar{border-bottom:1px solid var(--line);background:#fffefb}.topbar-inner{max-width:1180px;margin:0 auto;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{margin:0;font-size:20px;line-height:1.2}.sub{margin:4px 0 0;color:var(--muted);line-height:1.4}.pill{border:1px solid var(--line);border-radius:999px;padding:6px 11px;background:#f3f7f1;color:#10514e;white-space:nowrap}
main{max-width:1180px;margin:0 auto;padding:18px 20px 24px;display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,.82fr);gap:18px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-width:0}
.head{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px}.head h2{margin:0;font-size:15px}.form{padding:16px;display:grid;gap:14px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.inline{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.field{display:grid;gap:6px;min-width:0}.wide{grid-column:1/-1}
label{color:#32363a;font-size:13px;font-weight:650}input,textarea{width:100%;border:1px solid #cfd7cf;border-radius:7px;background:#fff;color:var(--text);padding:9px 10px;outline:none;min-width:0}input[readonly]{background:#f7f8f5;color:#303437}input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(23,111,107,.14)}textarea{min-height:88px;resize:vertical;line-height:1.45}
.path-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px}.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:4px}.primary{border:1px solid #10514e;background:var(--accent);color:#fff;border-radius:7px;padding:10px 15px;min-width:112px;cursor:pointer;font-weight:700}.secondary{border:1px solid var(--line);background:#fbfcfa;color:#263433;border-radius:7px;padding:9px 11px;white-space:nowrap;cursor:pointer}.primary:disabled,.secondary:disabled{cursor:not-allowed;opacity:.62}.notice{color:var(--red);line-height:1.45;word-break:break-word}
.jobs{max-height:244px;overflow:auto}.job{width:100%;border:0;border-bottom:1px solid var(--line);background:transparent;padding:11px 14px;display:grid;grid-template-columns:1fr auto;gap:8px;text-align:left;cursor:pointer}.job:hover,.job.active{background:#f2f7f2}.job-title{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.time{margin-top:3px;color:var(--muted);font-size:12px}
.badge{align-self:start;border-radius:999px;padding:4px 8px;font-size:12px;border:1px solid var(--line);white-space:nowrap}.queued,.running{color:var(--blue);background:#eef4fb;border-color:#cbd9ee}.done{color:var(--green);background:#eef8f1;border-color:#c8e2cf}.failed{color:var(--red);background:#fff0ef;border-color:#e8cbc8}
.detail{padding:14px;display:grid;gap:12px;min-height:360px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.metric{border:1px solid var(--line);border-radius:7px;padding:10px;background:#fbfcfa}.metric span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.metric strong{font-size:18px}
pre{margin:0;padding:12px;border:1px solid var(--line);border-radius:7px;background:#1f2424;color:#f4f6ee;min-height:180px;max-height:420px;overflow:auto;line-height:1.5;white-space:pre-wrap;word-break:break-word}.empty,.muted{color:var(--muted)}
@media(max-width:980px){main{grid-template-columns:1fr}}@media(max-width:680px){.topbar-inner,.actions{align-items:stretch;flex-direction:column}.grid,.inline,.metrics,.path-row{grid-template-columns:1fr}main{padding:12px}.primary,.secondary{width:100%}}
"""

APP_TS = r"""
declare const Vue:any;
type JobStatus="queued"|"running"|"done"|"failed";
interface Job{id:string;kind:string;status:JobStatus;createdAt:number;updatedAt:number;logs?:string[];result?:Record<string,any>|null;error?:string|null}
interface JobsResponse{jobs:Job[];rootDir:string}
const{createApp,computed,nextTick,onMounted,reactive,ref,watch}=Vue;

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

createApp({
  setup(){
    const activeJobId=ref<string|null>(null);
    const busy=ref(false);
    const connectionLabel=ref("已连接");
    const jobs=ref<Job[]>([]);
    const logBox=ref<HTMLElement|null>(null);
    const logRenderState=reactive({jobId:null as string|null,text:""});
    const notice=ref("");
    const rootDir=ref("");
    const exportForm=reactive({
      inputDir:"",schemaPath:"",outputDir:"",
      il2cppDumpPath:"",treeDepth:"auto",excludeRegexes:"",
      userMagic:"0x00525355",rszMagic:"0x005A5352"
    });

    const activeJob=computed<Job|null>(()=>jobs.value.find(job=>job.id===activeJobId.value)||null);
    const activeTotals=computed(()=>collectTotals(activeJob.value?.result));
    function jobLogText(job:Job|null){
      if(!job)return "选择或启动一个任务。";
      const lines=job.logs?[...job.logs]:[];
      if(job.error)lines.push(`[错误] ${job.error}`);
      if(job.result)lines.push(JSON.stringify(job.result,null,2));
      return lines.join("\n")||"任务已提交，等待日志。";
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
        connectionLabel.value="已连接";
      }catch{connectionLabel.value="连接中断"}
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
    function jobName(job:Job){return `导出 #${job.id}`}
    function statusLabel(status:JobStatus){return {queued:"排队",running:"运行中",done:"完成",failed:"失败"}[status]||status}
    function formatTime(value:number){return value?new Date(value*1000).toLocaleString():""}

    watch(activeJob,()=>{nextTick(renderActiveLog)},{deep:true,immediate:true});
    onMounted(()=>{renderActiveLog();refreshJobs();window.setInterval(refreshJobs,1200)});
    return{activeJob,activeJobId,activeTotals,busy,connectionLabel,exportForm,formatTime,jobName,jobs,logBox,notice,pickPath,rootDir,selectJob,statusLabel,submitExport};
  }
}).mount("#app");
"""

INDEX_HTML = (
    r"""<!doctype html>
<html lang="zh-CN">
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
      <div><h1>RE User3 JSON Web</h1><p class="sub">仅支持 .user.3 解包导出，所有路径请通过选择按钮指定。</p></div>
      <div class="pill">{{ connectionLabel }}</div>
    </div></header>

    <main>
      <section class="panel">
        <div class="head"><h2>导出 .user.3 为 JSON</h2><span class="muted">解包任务</span></div>
        <form class="form" @submit.prevent="submitExport">
          <div class="grid">
            <div class="field wide"><label>输入目录或 .user.3 文件</label><div class="path-row"><input v-model="exportForm.inputDir" readonly placeholder="请选择目录或 .user.3 文件"><button class="secondary" type="button" @click="pickPath(exportForm,'inputDir','directory','选择包含 .user.3 的目录')">选择目录</button><button class="secondary" type="button" @click="pickPath(exportForm,'inputDir','file','选择 .user.3 文件',[['user3 文件','*.user.3'],['所有文件','*.*']])">选择文件</button></div></div>
            <div class="field wide"><label>RE_RSZ 模板 JSON</label><div class="path-row"><input v-model="exportForm.schemaPath" readonly placeholder="请选择 RE_RSZ 模板 JSON"><button class="secondary" type="button" @click="pickPath(exportForm,'schemaPath','file','选择 RE_RSZ 模板 JSON',[['JSON 文件','*.json'],['所有文件','*.*']])">选择文件</button></div></div>
            <div class="field wide"><label>JSON 输出目录</label><div class="path-row"><input v-model="exportForm.outputDir" readonly placeholder="请选择 JSON 输出目录"><button class="secondary" type="button" @click="pickPath(exportForm,'outputDir','directory','选择 JSON 输出目录')">选择目录</button></div></div>
            <div class="field wide"><label>il2cpp_dump.json</label><div class="path-row"><input v-model="exportForm.il2cppDumpPath" readonly placeholder="请选择 il2cpp_dump.json"><button class="secondary" type="button" @click="pickPath(exportForm,'il2cppDumpPath','file','选择 il2cpp_dump.json',[['JSON 文件','*.json'],['所有文件','*.*']])">选择文件</button></div></div>
          </div>
          <div class="inline">
            <div class="field"><label>树深度</label><input v-model="exportForm.treeDepth" autocomplete="off"></div>
            <div class="field"><label>USR magic</label><input v-model="exportForm.userMagic" autocomplete="off"></div>
            <div class="field"><label>RSZ magic</label><input v-model="exportForm.rszMagic" autocomplete="off"></div>
          </div>
          <div class="field"><label>排除正则</label><textarea v-model="exportForm.excludeRegexes" spellcheck="false"></textarea></div>
          <div class="actions"><button class="primary" type="submit" :disabled="busy">开始导出</button><div class="notice">{{ notice }}</div></div>
        </form>
      </section>

      <aside class="panel">
        <div class="head"><h2>任务</h2><span class="muted">{{ jobs.length }} 个</span></div>
        <div v-if="jobs.length" class="jobs">
          <button v-for="job in jobs" :key="job.id" class="job" :class="{active:activeJobId===job.id}" @click="selectJob(job.id)">
            <span><span class="job-title">{{ jobName(job) }}</span><span class="time">{{ formatTime(job.updatedAt) }}</span></span>
            <span class="badge" :class="job.status">{{ statusLabel(job.status) }}</span>
          </button>
        </div>
        <div v-else class="empty">暂无任务。</div>
        <div class="detail">
          <div class="metrics">
            <div class="metric"><span>总数</span><strong>{{ activeTotals.total }}</strong></div>
            <div class="metric"><span>成功</span><strong>{{ activeTotals.success }}</strong></div>
            <div class="metric"><span>失败</span><strong>{{ activeTotals.failed }}</strong></div>
          </div>
          <pre ref="logBox">选择或启动一个任务。</pre>
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
      if(!window.Vue||!window.ts){document.body.innerHTML="<div style='padding:24px;font-family:Segoe UI,Microsoft YaHei,sans-serif'>Vue 或 TypeScript CDN 加载失败。</div>";return}
      var source=document.getElementById("app-ts").textContent;
      var output=window.ts.transpile(source,{target:window.ts.ScriptTarget.ES2020,module:window.ts.ModuleKind.None});
      var script=document.createElement("script");script.textContent=output;document.body.appendChild(script);
    })();
  </script>
</body>
</html>
"""
)
