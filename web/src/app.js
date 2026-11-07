import {mountPublishing} from './publishing.js';
import {checkApptronRuntime} from './apptron-runtime.js';
import {classifyEnvironments,nativeEnvironments} from './environments.js';
import {mountWorkspace} from './workspace.js';
import {renderDot} from './dot-render.js';
import {renderModl} from './modl-render.js';
import {shareLink,decode64,loadCID,unwrapDiagram} from './cid.js';
import {localCommand,download,apptronSnapshot,apptronLink} from './run-targets.js';
const $=id=>document.getElementById(id), source=$('source');
const [inventory,apptronPin]=await Promise.all(['portable-tools.json','apptron-runtime.json'].map(async path=>(await fetch(path)).json()));
let targets={},compilerSource=null,apptronState={ready:false,reason:'Checking Apptron availability…'};
let workspace,publishing,revision=0,loadRevision=0,timer,result=null,positions=Object.create(null),cid=null;
const worker=new Worker(new URL('./transpile.js',import.meta.url),{type:'module'});
const report=text=>{$('diagnostics').textContent=text;};
function invalidate() {result=null;revision++;$('run-dialog').close();$('bash').textContent='';for(const id of ['local','apptron','download-bash'])$(id).disabled=true;}
function check(){invalidate();$('status').textContent='Checking…';worker.postMessage({id:revision,src:source.value,lang:$('language').value,portable:$('portable').checked});}
function edited(){publishing?.discardSnapshot();publishing?.cancelLoad();loadRevision++;cid=null;workspace?.saveDraft();invalidate();$('status').textContent='Waiting for edit…';clearTimeout(timer);timer=setTimeout(check,250);}
source.addEventListener('input',edited);$('language').onchange=edited;$('portable').onchange=edited;
worker.onerror=event=>{invalidate();$('status').textContent='Runtime unavailable';report(event.message);};
worker.onmessage=async({data})=>{
  if(data.type==='compiler'){compilerSource=data.source;return;}
  if(data.id!==revision)return;
  if(data.error){$('status').textContent='Runtime unavailable';report(data.error);return;}
  result=data.result;$('bash').textContent=result.bash;
  $('status').textContent=result.problems.length?'Needs attention':`Checked · ${result.lang}`;
  report([...result.problems.map(p=>`${p.code}${p.line?' · line '+p.line:''}: ${p.message}`),...result.warnings].join('\n')||'Static checks passed. Review the bash before running.');
  refreshTargets();
  try{
    $('diagram-note').textContent=result.lang==='dot'?'Graphviz layout':'Drag nodes to arrange';
    const diagram=result.lang==='dot'?await renderDot(source.value,result.marks):renderModl(source.value,positions,result.marks,()=>workspace?.saveDraft());
    if(data.id===revision)$('diagram').replaceChildren(diagram);
  }catch(error){if(data.id===revision)$('diagram').textContent='Preview: '+error.message;}
};
function refreshTargets(){if(!result)return;
  targets=classifyEnvironments(result,inventory,{apptronReady:apptronState.ready,apptronReason:apptronState.reason});
  $('download-bash').disabled=!result.bash;
  $('local').disabled=!result.bash||!nativeEnvironments.some(environment=>targets[environment].status!=='unsupported');
  $('apptron').disabled=targets.apptron.status!=='runs';$('apptron').title=targets.apptron.reason||(targets.apptron.missing.length?'Additional VM tools required: '+targets.apptron.missing.join(', '):apptronState.reason);
  $('badges').replaceChildren();
  for(const [environment,target] of Object.entries(targets)){
    const badge=document.createElement('span');
    badge.textContent=`${environment} · ${target.status==='needs'?'needs '+target.missing.join(', '):target.status==='unsupported'?'not supported':'runs'}`;
    badge.title=target.reason||inventory.assumptions;$('badges').append(badge);
  }
}
void checkApptronRuntime(apptronPin).then(state=>{apptronState=state;refreshTargets();});
$('share').onclick=async()=>{try{const url=shareLink(source.value,positions);history.replaceState(null,'',url);await navigator.clipboard.writeText(url);$('status').textContent='Share link copied';}catch(error){report(error.message);}};
$('download-source').onclick=()=>download(source.value,'pipeline.'+(result?.lang||$('language').value||'modl'));
$('download-bash').onclick=()=>{if(result?.bash)download(result.bash,'pipeline.sh');};
const platform=(navigator.userAgentData?.platform||navigator.platform||'').toLowerCase();
$('run-environment').value=platform.includes('win')?'windows':platform.includes('mac')?'macos':'linux';
function updateLocalTarget(){const target=targets[$('run-environment').value];$('copy').disabled=target?.status==='unsupported';$('run-target-note').textContent=target?.reason||(target?.missing.length?'Additional tools required: '+target.missing.join(', ')+'. ':'')+inventory.assumptions;}
$('run-environment').onchange=updateLocalTarget;
$('local').onclick=()=>{if(!result?.bash)return;$('review').textContent=result.bash;$('command').value=localCommand(source.value,positions,cid);updateLocalTarget();$('run-dialog').showModal();};
$('close').onclick=()=>$('run-dialog').close();$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('command').value);$('copy').textContent='Copied';}catch(error){report(error.message);}};
// Capture the reviewed source and the exact compiler loaded by the worker.
$('apptron').onclick=async()=>{
  if(!result?.bash||!compilerSource||!apptronState.ready||targets.apptron.status!=='runs')return;
  const reviewed={src:source.value,lang:result.lang,cids:[...result.cids],compiler:compilerSource,pos:structuredClone(positions)};
  const popup=window.open('about:blank','_blank');if(!popup){report('Allow a new tab to open Apptron.');return;}popup.opener=null;
  let snapshot;
  try{snapshot=await apptronSnapshot(reviewed.src,reviewed.lang,reviewed.compiler,reviewed.cids);popup.location=await apptronLink(snapshot,apptronPin.baseUrl);}
  catch(error){popup.close();report(error.message);if(snapshot){publishing.offerSnapshot(snapshot,reviewed);download(snapshot,'pipeline.txtar');report(error.message+' A snapshot was downloaded. On the canonical editor, More → Save Apptron snapshot offers a reviewed HashBin save and an Apptron CID link.');}}
};
async function loadHash(){
  publishing?.cancelLoad();publishing?.discardSnapshot();
  const loading=++loadRevision;
  if(!location.hash||new URLSearchParams(location.hash.slice(1)).has('hashbin_publish'))return;
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

workspace=mountWorkspace({getSnapshot:()=>({src:source.value,pos:positions}),onPreview:()=>{if(result)check();},onRestore:async value=>{publishing?.cancelLoad();publishing?.discardSnapshot();loadRevision++;cid=null;source.value=value.src;positions=value.pos;$('language').value='';check();},onLoad:async outcome=>{
  const url=new URL(outcome.kind==='cid'?location.href:outcome.href);if(outcome.kind==='cid')url.hash=outcome.cid;
  location.hash=url.hash;
}});

publishing=mountPublishing({apptronBase:apptronPin.baseUrl,container:workspace.shell.drawer.body,getSnapshot:()=>({src:source.value,pos:positions}),onLoad:async(value,savedCid)=>{
  loadRevision++;workspace.shell.drawer.dialog.close();workspace.opened();source.value=value.src;positions=value.pos;cid=savedCid;if(savedCid){const url=new URL(location.href);url.hash=savedCid;url.search='';history.replaceState(null,'',url);}$('language').value='';check();
},onSaved:async(savedCid,_fingerprint,href)=>{cid=savedCid;history.replaceState(null,'',href);}});
if(new URLSearchParams(location.hash.slice(1)).has('hashbin_publish')){
  await publishing.published(location.hash);
  if(new URLSearchParams(location.hash.slice(1)).has('hashbin_publish'))history.replaceState(null,'',location.pathname);
}
