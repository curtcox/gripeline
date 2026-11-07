import {shareLink,loadCID,parseCID} from './cid.js';
export function localCommand(src,pos={},cid=null) {
  const target=cid?'t256:'+parseCID(cid).cid:shareLink(src,pos);
  return `gripeline run "${target}"`;
}
export function download(content,name,type='text/plain') {
  const url=URL.createObjectURL(new Blob([content],{type})), anchor=document.createElement('a');
  anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export async function apptronSnapshot(src,lang,python,references=[]) {
  const entries=[['.apptron/envrc',`cd /project\nexport T256_CONFIG=/project/.t256/config.json\npython3 gripeline.py check pipeline.${lang} && echo "Try: python3 gripeline.py run pipeline.${lang}"\n`],[`pipeline.${lang}`,src],['gripeline.py',python],['.t256/config.json',JSON.stringify({providers:{local:{type:'dir',path:'/project/.t256/store',create:true}},sources:['local'],destination:'local'})]];
  const stored=[...new Set(references)].map(reference=>parseCID(reference)).filter(ref=>ref.length>64);
  const estimate=new TextEncoder().encode(src+python).length+4096+stored.reduce((sum,ref)=>sum+Math.ceil(ref.length/3)*4+ref.cid.length+64,0);
  if(estimate>1048576)throw Error('Snapshot exceeds Apptron’s 1 MiB limit. Use a smaller dataset or configure a relay in Apptron.');
  for(const {cid} of stored) {
    const data=await loadCID(cid);
    // txtar's base64 encoding is standard padded base64, not base64url.
    let binary='';for(const byte of data)binary+=String.fromCharCode(byte);
    entries.push([`.t256/store/${parseCID(cid).cid} (base64)`,btoa(binary)]);
  }
  let snapshot='# apptron snapshot v1\noverlay: gallery/gripeline\n';
  for(const [path,content] of entries) {
    if(/^-- .+ --\r?$/m.test(content))throw Error('Source contains a txtar file delimiter; download and run locally instead.');
    snapshot+=`-- ${path} --\n${content}${content.endsWith('\n')?'':'\n'}`;
  }
  if(new TextEncoder().encode(snapshot).length>1048576)throw Error('Snapshot exceeds Apptron’s 1 MiB limit. Use a smaller dataset or configure a relay in Apptron.');
  return snapshot;
}
export async function apptronLink(snapshot) {
  const {default:LZString}=await import('../vendor/lz-string.mjs');
  const url='https://curtcox.github.io/apptron/?compressed='+LZString.compressToEncodedURIComponent(snapshot);
  if(url.length>60000)throw Error('Snapshot link is too long. Download a .txtar snapshot until HashBin publishing is configured.');
  return url;
}
