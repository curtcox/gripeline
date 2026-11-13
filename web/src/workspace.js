import {createConfig,createShell,mountMobileTabs,createShareDialog,createQrDialog,OfflineClient,LocalDrafts,createStorage} from '../vendor/fragment-kit-v0.4.3/src/index.js';
import {shareLink,decode64,unwrapDiagram,parseCID} from './cid.js';
export function mountWorkspace({getSnapshot,onLoad,onPreview,onRestore}) {
  const current=new URL(location.href);current.hash='';current.search='';current.pathname=current.pathname.replace(/index\.html$/,'');
  const config=createConfig({slug:'gripeline',name:'gripeline',storagePrefix:'gripeline',canonicalOrigin:'https://gripeline.hashbin.page/',recoveryOrigin:current.href,repo:'curtcox/gripeline',docs:'https://curtcox.github.io/gripeline/spec.html',gallery:current.href,documentType:'modl',maxBytes:1048576});
  const original=document.querySelector('body>header'),shell=createShell({config});
  shell.header.append(document.getElementById('status'));shell.toolbar.append(document.getElementById('share'));original.remove();
  shell.offlineStatus.textContent='Preparing offline copy…';shell.draftStatus.textContent='Links never run automatically';
  const drafts=new LocalDrafts({storage:createStorage({prefix:config.storagePrefix}),key:'draft',parse:text=>unwrapDiagram(text)});
  drafts.mount(shell.drawer.body,async value=>{drafts.opened();await onRestore(value);shell.draftStatus.textContent='Saved draft is unverified — review the visible bash before running';shell.drawer.dialog.close();});
  document.getElementById('draft-note').textContent='Saved drafts are unverified. Resuming loads visible source for checking and review; it never runs a pipeline. Explicit links always open their linked source.';
  const urlState={
    build:doc=>{const href=shareLink(doc.src,doc.pos);return{href,long:href,fallback:href,qrCandidate:href};},
    parse:href=>{const fragment=new URL(href).hash.slice(1);if(fragment.startsWith('h1='))return{kind:'source',doc:unwrapDiagram(new TextDecoder('utf-8',{fatal:true}).decode(decode64(fragment.slice(3).split('&')[0])))};return{kind:'cid',cid:parseCID(fragment).cid};},
  };
  const share=createShareDialog({urlState,getSnapshot});
  // No diagram can execute in this page. Remove the kit's optional autorun control.
  share.dialog.querySelector('#share-run').parentElement.remove();
  share.dialog.querySelectorAll('button').forEach(button=>{if(button.textContent==='Shorten link')button.hidden=true;});
  document.getElementById('share').onclick=()=>share.open();
  const qr=createQrDialog({config,urlState,onLoad});
  const button=document.createElement('button');button.id='qr';button.textContent='QR code';button.onclick=()=>qr.open(urlState.build(getSnapshot()).href);shell.toolbar.append(button);
  const panels=[...document.querySelectorAll('.panels>section')].map((panel,index)=>({label:['Source','Diagram','Bash','Diagnostics'][index],panel}));
  const tabs=mountMobileTabs({desktop:true,container:shell.toolbar,panels,onChange:index=>{if(index===1)onPreview();}});
  const update=document.createElement('button');update.textContent='Update offline copy';update.hidden=true;shell.drawer.body.append(update);
  const offline=new OfflineClient({onStatus:status=>{shell.offlineStatus.textContent=status.ready?'Editor available offline':'Offline copy incomplete';},onUpdate:()=>{update.hidden=false;}});
  const repair=document.createElement('button');repair.textContent='Repair offline copy';repair.onclick=()=>offline.repair().catch(error=>{shell.offlineStatus.textContent=error.message;});shell.drawer.body.append(repair);
  update.onclick=()=>{navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});offline.activateUpdate();};
  offline.init().catch(error=>{shell.offlineStatus.textContent=error.message;});
  return{shell,tabs,opened:()=>drafts.opened(),saveDraft:()=>{
    if(new TextEncoder().encode(getSnapshot().src).length>config.maxBytes){shell.draftStatus.textContent='Draft exceeds the size limit — download to keep your work';return;}
    if(drafts.attempt(getSnapshot(),true))shell.draftStatus.textContent='Draft saved locally — unverified';
  }};
}
