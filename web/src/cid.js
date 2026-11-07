export const encode64 = bytes => { let s=''; for(const b of bytes)s+=String.fromCharCode(b); return btoa(s).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,''); };
export const decode64 = text => Uint8Array.from(atob(text.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-text.length%4)%4)), c=>c.charCodeAt(0));
export function parseCID(reference) {
  const cid=reference.replace(/^t256:/,'').split('.')[0];
  if(!/^[A-Za-z0-9_-]{8,94}$/.test(cid))throw Error('Invalid CID');
  const head=decode64(cid.slice(0,8)), payload=decode64(cid.slice(8));
  const length=head.reduce((n,b)=>n*256+b,0);
  if(encode64(payload)!==cid.slice(8)||payload.length!==(length<=64?length:64))throw Error('Invalid CID length or padding');
  return {cid,length,payload};
}
export async function loadCID(reference) {
  const {cid,length,payload}=parseCID(reference);
  if(length<=64)return payload;
  const response=await fetch('https://256t.us/'+cid);
  if(!response.ok)throw Error('CID load failed: '+response.status);
  const data=new Uint8Array(await response.arrayBuffer());
  if(data.length!==length||encode64(new Uint8Array(await crypto.subtle.digest('SHA-512',data)))!==cid.slice(8))throw Error('CID verification failed');
  return data;
}
export function unwrapDiagram(text) {
  let value;try{value=JSON.parse(text);}catch{return {src:text,pos:{}};}
  if(typeof value?.src!=='string')throw Error('Saved diagram must contain source text');
  if(value.format&&value.format!=='hashbin-diagram'||value.version!==undefined&&value.version!==1)throw Error('Unsupported diagram envelope');
  const pos=Object.create(null);
  for(const [key,pair] of Object.entries(value.pos??{})) {
    if(!Array.isArray(pair)||pair.length!==2||!pair.every(Number.isFinite))throw Error('Invalid diagram position');
    pos[key]=pair;
  }
  return {src:value.src,pos};
}
export function shareLink(src,pos={},base=location.href) {
  const url=new URL(base);url.search='';url.hash='h1='+encode64(new TextEncoder().encode(JSON.stringify({src,pos})));return url.href;
}
