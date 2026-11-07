import {HashBinStore,HashBinPanel,createConfig,bounded} from '../vendor/fragment-kit-v0.3.4/src/index.js';
import {unwrapDiagram,loadCID} from './cid.js';
export const canonicalOrigin='https://gripeline.hashbin.page/';
export function normalizeSnapshot(value) {
  if(value?.kind==='apptron'){bounded(value.src,1048576);return{kind:'apptron',src:value.src};}
  const doc=unwrapDiagram(JSON.stringify(value));bounded(JSON.stringify(doc),1048576);return doc;
}
export function serializeSnapshot(value) {
  const doc=normalizeSnapshot(value);
  return JSON.stringify(doc.kind==='apptron'?{format:'hashbin-diagram',version:1,type:'apptron',src:doc.src}:{format:'hashbin-diagram',version:1,...doc});
}
export function parseSnapshot(payload) {
  let value;try{value=JSON.parse(payload);}catch{return unwrapDiagram(payload);}
  if(value?.type==='apptron'){
    if(value.format!=='hashbin-diagram'||value.version!==1||typeof value.src!=='string')throw Error('Invalid Apptron snapshot');
    return{kind:'apptron',src:value.src};
  }
  return unwrapDiagram(payload);
}
export function createDiagramStore({config, ...options}) {
  const type={type:'gripeline',fileName:'pipeline.json',contentType:'application/json',normalize:normalizeSnapshot};
  const store=new HashBinStore({config,type,...options});
  store.documents={...store.documents,normalize:normalizeSnapshot,serialize:serializeSnapshot,parse:parseSnapshot};
  store.load=async input=>unwrapDiagram(new TextDecoder('utf-8',{fatal:true}).decode(await loadCID(store.cid(input))));
  return store;
}
export function mountPublishing({container,getSnapshot,onLoad,onSaved,apptronBase}) {
  const config=createConfig({slug:'gripeline',name:'gripeline',storagePrefix:'gripeline',canonicalOrigin,recoveryOrigin:'https://curtcox.github.io/gripeline/editor/',repo:'curtcox/gripeline',docs:'https://curtcox.github.io/gripeline/spec.html',gallery:canonicalOrigin,documentType:'gripeline',maxBytes:1048576});
  const store=createDiagramStore({config});
  let mode='diagram',pending=null;
  const apptronURL=cid=>{const url=new URL(apptronBase);url.hash=cid;return url.href;};
  const panel=new HashBinPanel({store,container,getSnapshot:()=>mode==='apptron'?pending:getSnapshot(),getFingerprint:()=>JSON.stringify(getSnapshot()),onLoad:async(value,savedCid)=>{
    mode=value.kind==='apptron'?'apptron':'diagram';panel.snapshot=value;
    if(mode==='apptron'){if(value.diagram)await onLoad(normalizeSnapshot(value.diagram),null);}
    else await onLoad(value,savedCid);
  },onSaved:async(cid,fingerprint,href)=>{if(mode!=='apptron')await onSaved(cid,fingerprint,href);},urlState:{link:(base,cid)=>{if(mode==='apptron')return apptronURL(cid);const url=new URL(base);url.hash=cid;url.search='';return url.href;}}});
  const allowed=location.origin===new URL(canonicalOrigin).origin&&!!config.hashbinClientId;
  if(!allowed){
    panel.saveButton.disabled=true;
    panel.status.textContent=location.origin!==new URL(canonicalOrigin).origin?'Save on gripeline.hashbin.page once its registration is complete.':'HashBin saving awaits app registration.';
  }
  panel.saveButton.onclick=()=>{mode='diagram';panel.openSave();};
  const snapshotButton=document.createElement('button');snapshotButton.textContent='Save Apptron snapshot';snapshotButton.id='snapshot-save';snapshotButton.hidden=true;snapshotButton.disabled=!allowed;container.append(snapshotButton);
  snapshotButton.onclick=()=>{mode='apptron';panel.openSave();};
  panel.discardSnapshot=()=>{snapshotButton.hidden=true;};
  panel.offerSnapshot=(src,diagram)=>{pending={kind:'apptron',src,diagram:normalizeSnapshot(diagram)};snapshotButton.hidden=false;};
  return panel;
}
