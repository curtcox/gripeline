import {classifyEnvironments,nativeEnvironments} from './environments.js';
import {mountWorkspace} from './workspace.js';
import {renderDot} from './dot-render.js';
import {renderModl} from './modl-render.js';
import {shareLink,decode64,loadCID,unwrapDiagram} from './cid.js';
import {localCommand,download,apptronSnapshot,apptronLink} from './run-targets.js';
const $=id=>document.getElementById(id), source=$('source');
const inventory=await(await fetch('portable-tools.json')).json();
let targets={};
let workspace,revision=0,loadRevision=0,timer,result=null,positions=Object.create(null),cid=null;
const worker=new Worker(new URL('./transpile.js',import.meta.url),{type:'module'});
const report=text=>{$('diagnostics').textContent=text;};
function invalidate() {result=null;revision++;$('run-dialog').close();$('bash').textContent='';for(const id of ['local','apptron','download-bash'])$(id).disabled=true;}
function check(){invalidate();$('status').textContent='Checking…';worker.postMessage({id:revision,src:source.value,lang:$('language').value,portable:$('portable').checked});}
function edited(){loadRevision++;cid=null;workspace?.saveDraft();invalidate();$('status').textContent='Waiting for edit…';clearTimeout(timer);timer=setTimeout(check,250);}
source.addEventListener('input',edited);$('language').onchange=edited;$('portable').onchange=edited;
worker.onerror=event=>{invalidate();$('status').textContent='Runtime unavailable';report(event.message);};
worker.onmessage=async({data})=>{
  if(data.id!==revision)return;
  if(data.error){$('status').textContent='Runtime unavailable';report(data.error);return;}
  result=data.result;$('bash').textContent=result.bash;
  $('status').textContent=result.problems.length?'Needs attention':`Checked · ${result.lang}`;
  report([...result.problems.map(p=>`${p.code}${p.line?' · line '+p.line:''}: ${p.message}`),...result.warnings].join('\n')||'Static checks passed. Review the bash before running.');
  targets=classifyEnvironments(result,inventory);
  $('download-bash').disabled=!result.bash;
  $('local').disabled=!result.bash||!nativeEnvironments.some(environment=>targets[environment].status!=='unsupported');
  $('apptron').disabled=true;$('apptron').title=targets.apptron.reason;
  $('badges').replaceChildren();
  for(const [environment,target] of Object.entries(targets)){
    const badge=document.createElement('span');
    badge.textContent=`${environment} · ${target.status==='needs'?'needs '+target.missing.join(', '):target.status==='unsupported'?'not supported':'runs'}`;
    badge.title=target.reason||inventory.assumptions;$('badges').append(badge);
  }
  try{
    $('diagram-note').textContent=result.lang==='dot'?'Graphviz layout':'Drag nodes to arrange';
    const diagram=result.lang==='dot'?await renderDot(source.value,result.marks):renderModl(source.value,positions,result.marks,()=>workspace?.saveDraft());
    if(data.id===revision)$('diagram').replaceChildren(diagram);
  }catch(error){if(data.id===revision)$('diagram').textContent='Preview: '+error.message;}
};
$('share').onclick=async()=>{try{const url=shareLink(source.value,positions);history.replaceState(null,'',url);await navigator.clipboard.writeText(url);$('status').textContent='Share link copied';}catch(error){report(error.message);}};
$('download-source').onclick=()=>download(source.value,'pipeline.'+(result?.lang||$('language').value||'modl'));
$('download-bash').onclick=()=>{if(result?.bash)download(result.bash,'pipeline.sh');};
const platform=(navigator.userAgentData?.platform||navigator.platform||'').toLowerCase();
$('run-environment').value=platform.includes('win')?'windows':platform.includes('mac')?'macos':'linux';
function updateLocalTarget(){const target=targets[$('run-environment').value];$('copy').disabled=target?.status==='unsupported';$('run-target-note').textContent=target?.reason||(target?.missing.length?'Additional tools required: '+target.missing.join(', ')+'. ':'')+inventory.assumptions;}
$('run-environment').onchange=updateLocalTarget;
$('local').onclick=()=>{if(!result?.bash)return;$('review').textContent=result.bash;$('command').value=localCommand(source.value,positions,cid);updateLocalTarget();$('run-dialog').showModal();};
$('close').onclick=()=>$('run-dialog').close();$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('command').value);$('copy').textContent='Copied';}catch(error){report(error.message);}};
// Prepared for the pinned overlay release; links never execute automatically.
$('apptron').onclick=async()=>{if(!result?.bash)return;const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;try{const python=await(await fetch('gripeline.py')).text();const snapshot=await apptronSnapshot(source.value,result.lang,python,result.cids);const link=await apptronLink(snapshot);if(popup)popup.location=link;}catch(error){popup?.close();report(error.message);}};
async function loadHash(){
  const loading=++loadRevision;
  if(!location.hash)return;
  if(location.hash.length>1500000)throw Error("Diagram link exceeds the size limit");
  const fragment=location.hash.slice(1);
  const state=fragment.startsWith('h1=')?unwrapDiagram(new TextDecoder('utf-8',{fatal:true}).decode(decode64(fragment.slice(3).split('&')[0]))):unwrapDiagram(new TextDecoder('utf-8',{fatal:true}).decode(await loadCID(fragment)));
  if(loading!==loadRevision)return;
  if(new TextEncoder().encode(state.src).length>1048576)throw Error("Diagram exceeds the 1 MiB limit");
  workspace?.opened();
  source.value=state.src;positions=state.pos;cid=fragment.startsWith('h1=')?null:fragment;
}
window.addEventListener('hashchange',()=>{invalidate();loadHash().then(check).catch(error=>report(error.message));});
try{await loadHash();check();}catch(error){invalidate();$('status').textContent='Link could not be loaded';report(error.message);}
try{
  const response=await fetch('gallery.json');if(!response.ok)throw Error('Gallery unavailable');const gallery=await response.json();
  for(const [index,item] of gallery.entries()) {const option=document.createElement('option');option.value=index;option.textContent=item.name;$('gallery').append(option);}
  $('gallery').onchange=()=>{const item=gallery[$('gallery').value];if(!item)return;source.value=item.src;$('language').value=item.lang;positions=Object.create(null);edited();};
}catch{/* Gallery is optional during local source development. */}

workspace=mountWorkspace({getSnapshot:()=>({src:source.value,pos:positions}),onPreview:()=>{if(result)check();},onRestore:async value=>{loadRevision++;cid=null;source.value=value.src;positions=value.pos;$('language').value='';check();},onLoad:async outcome=>{
  const url=new URL(outcome.kind==='cid'?location.href:outcome.href);if(outcome.kind==='cid')url.hash=outcome.cid;
  location.hash=url.hash;
}});
