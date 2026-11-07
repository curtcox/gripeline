const hex=bytes=>Array.from(new Uint8Array(bytes),byte=>byte.toString(16).padStart(2,'0')).join('');
export async function checkApptronRuntime(pin,{fetcher=fetch,timeout=8000}={}) {
  const unavailable=reason=>({ready:false,reason});
  if(pin?.version!==1||pin.baseUrl!=='https://curtcox.github.io/apptron/'||!/^[a-f0-9]{40}$/.test(pin.commit)||!['manifestSha256','overlaySha256'].every(key=>/^[a-f0-9]{64}$/.test(pin[key])))return unavailable('No verified Apptron runtime is configured');
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try{
    const get=async path=>{const response=await fetcher(new URL(path,pin.baseUrl).href,{credentials:'omit',cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('Apptron metadata is not available');const text=await response.text();if(text.length>65536)throw Error('Apptron metadata exceeds the size limit');return text;};
    const lock=JSON.parse(await get('runtime.lock'));
    if(lock.release!==pin.release||lock.commit!==pin.commit||lock.manifestSha256!==pin.manifestSha256)return unavailable('Apptron has not deployed this editor’s verified runtime yet');
    const raw=await get(`runtime/${pin.commit}/runtime.json`);
    if(hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))!==pin.manifestSha256)return unavailable('Apptron runtime verification failed');
    const manifest=JSON.parse(raw);
    if(manifest.securityVersion!==1||manifest.commit!==pin.commit||manifest.files?.['overlays/gripeline.tar.gz']?.sha256!==pin.overlaySha256)return unavailable('Apptron’s gripeline overlay does not match the verified release');
    return{ready:true,reason:'Verified Apptron runtime is available'};
  }catch(error){return unavailable(error.name==='AbortError'?'Apptron availability check timed out':'Apptron availability could not be verified');}
  finally{clearTimeout(timer);}
}
