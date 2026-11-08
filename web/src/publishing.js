import {HashBinStore,HashBinPanel,createConfig,bounded} from '../vendor/fragment-kit-v0.3.5/src/index.js';
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
  const loadSDK=options.loadSDK??(()=>import('../vendor/fragment-kit-v0.3.5/vendor/hashbin-sdk-v0.4.0.mjs'));
  const store=new HashBinStore({config,type,...options,loadSDK:async()=>{
    const sdk=await loadSDK();
    return{...sdk,HashBinClient:class extends sdk.HashBinClient{
      publish(payload,settings){return super.publish(payload,{...settings,mode:'redirect'});}
    }};
  }});
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
  const openSave=panel.openSave.bind(panel);
  panel.openSave=async()=>{panel.confirm.hidden=false;await openSave();if(!panel.confirm.disabled)panel.message.append(' Review opens on HashBin in this tab, then returns to your diagram.');};
  const published=panel.published.bind(panel);
  panel.published=async hash=>{
    const result=await published(hash);
    if(result?.cid&&!result.error){
      panel.status.textContent='Saved to HashBin.';
      if(panel.snapshot?.kind==='apptron'){
        const link=document.createElement('a');link.href=apptronURL(result.cid);link.textContent='Open saved Apptron snapshot';
        panel.message.replaceChildren(link);panel.confirm.hidden=true;panel.ui.open();
      }
    }
    return result;
  };
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
