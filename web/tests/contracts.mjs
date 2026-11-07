import {test} from 'node:test';
import assert from 'node:assert/strict';
import {encode64,parseCID,loadCID,unwrapDiagram,shareLink} from '../src/cid.js';
import {apptronSnapshot,apptronLink,localCommand} from '../src/run-targets.js';
import LZString from '../vendor/lz-string.mjs';
const cidOf=bytes=>{const prefix=new Uint8Array(6);prefix[5]=bytes.length;return encode64(prefix)+encode64(bytes);};
test('inline CID and malformed canonical encodings',async()=>{
  assert.equal(new TextDecoder().decode(await loadCID('AAAAAAACaGk')),'hi');
  assert.throws(()=>parseCID('AAAAAAACaGl'));
  assert.throws(()=>unwrapDiagram('{"format":"other","src":"x"}'));
  assert.throws(()=>unwrapDiagram('{"src":"x","pos":{"a":[1,null]}}'));
});
test('CID load verifies hashed bytes',async()=>{
  const data=new Uint8Array(70).fill(65),prefix=new Uint8Array(6);prefix[5]=70;
  const cid=encode64(prefix)+encode64(new Uint8Array(await crypto.subtle.digest('SHA-512',data)));
  const previous=globalThis.fetch;
  try{
    globalThis.fetch=async()=>new Response(data);
    assert.deepEqual(await loadCID(cid),data);
    globalThis.fetch=async()=>new Response(new Uint8Array(70));
    await assert.rejects(loadCID(cid),/verification/);
  }finally{globalThis.fetch=previous;}
});
test('snapshot is inert and survives Apptron compression',async()=>{
  const snapshot=await apptronSnapshot('a square echo hi','modl','# python',[]);
  assert.match(snapshot,/overlay: gallery\/gripeline/);
  assert.match(snapshot,/check pipeline.modl/);
  assert.doesNotMatch(snapshot,/^python3 gripeline.py run/m);
  const link=await apptronLink(snapshot);
  assert.equal(LZString.decompressFromEncodedURIComponent(new URL(link).searchParams.get('compressed')),snapshot);
  await assert.rejects(apptronSnapshot('-- injected --','modl','python',[]),/delimiter/);
  await assert.rejects(apptronSnapshot('x'.repeat(1048576),'modl','python',[]),/1 MiB/);
});
test('local CID command has shell-independent quoting',()=>{
  assert.equal(localCommand('src',{},'AAAAAAAA'),'gripeline run "t256:AAAAAAAA"');
  assert.match(shareLink('a square echo hi',{},'https://example.com/editor/'),/#h1=/);
});
test('oversized referenced content is rejected before a network fetch',async()=>{
  const previous=globalThis.fetch;
  try{
    globalThis.fetch=async()=>{throw Error('unexpected network fetch');};
    const cid=encode64(new Uint8Array([0,0,0,32,0,0]))+encode64(new Uint8Array(64));
    await assert.rejects(apptronSnapshot('a square cat','modl','python',[cid]),/1 MiB/);
  }finally{globalThis.fetch=previous;}
});
test('environment declarations and missing tools determine available targets',async()=>{
  const {classifyEnvironments}=await import('../src/environments.js');
  const inventory={common:['printf','cat','t256'],environments:{linux:['python3'],macos:['python3'],windows:['py'],apptron:['python3']}};
  let targets=classifyEnvironments({commands:['printf'],requires:['jq'],environments:['linux','apptron'],problems:[]},inventory,{apptronReady:true});
  assert.equal(targets.linux.status,'needs');assert.deepEqual(targets.linux.missing,['jq']);
  assert.equal(targets.apptron.status,'needs');assert.equal(targets.windows.status,'unsupported');
  targets=classifyEnvironments({commands:['t256'],problems:[]},inventory,{apptronReady:true});
  assert.equal(targets.apptron.status,'runs');
  targets=classifyEnvironments({problems:[{code:'E02'}]},inventory,{apptronReady:true});
  assert.ok(Object.values(targets).every(target=>target.status==='unsupported'));
});
test('Apptron is enabled only for the pinned manifest and overlay',async()=>{
  const {checkApptronRuntime}=await import('../src/apptron-runtime.js');
  const commit='a'.repeat(40),overlay='c'.repeat(64),raw=JSON.stringify({commit,securityVersion:1,files:{'overlays/gripeline.tar.gz':{sha256:overlay}}});
  const manifestSha256=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw))).toString('hex');
  const pin={version:1,baseUrl:'https://curtcox.github.io/apptron/',commit,release:'runtime-test',manifestSha256,overlaySha256:overlay};
  let lock={commit,release:pin.release,manifestSha256},manifest=raw;
  const fetcher=async url=>new Response(url.endsWith('runtime.lock')?JSON.stringify(lock):manifest);
  assert.equal((await checkApptronRuntime(pin,{fetcher})).ready,true);
  assert.equal((await checkApptronRuntime({...pin,baseUrl:'https://apptron.hashbin.page/'},{fetcher})).ready,true);
  lock={...lock,release:'older-runtime'};assert.equal((await checkApptronRuntime(pin,{fetcher})).ready,false);
  lock={...lock,release:pin.release};manifest=raw+' ';assert.equal((await checkApptronRuntime(pin,{fetcher})).ready,false);
  assert.equal((await checkApptronRuntime({...pin,baseUrl:'https://untrusted.example/'},{fetcher})).ready,false);
});
test('CID loading rejects oversized declarations before fetching and bounds response bytes',async()=>{
  const previous=globalThis.fetch;
  try{
    globalThis.fetch=async()=>{throw Error('unexpected network fetch');};
    const oversized=encode64(new Uint8Array([0,0,0,32,0,0]))+encode64(new Uint8Array(64));
    await assert.rejects(loadCID(oversized),/limit/);
    const declared=encode64(new Uint8Array([0,0,0,0,0,70]))+encode64(new Uint8Array(64));
    globalThis.fetch=async()=>new Response(new Uint8Array(100));
    await assert.rejects(loadCID(declared),/limit/);
  }finally{globalThis.fetch=previous;}
});
test('current typed modl envelopes retain their fractional positions',()=>{
  const loaded=unwrapDiagram(JSON.stringify({format:'hashbin-diagram',version:1,type:'modl',src:'a square cat',modl:{pos:{a:[1.25,2.5]}}}));
  assert.deepEqual(loaded.pos.a,[1.25,2.5]);
});
test('publishing uses inert source and positions with no credential storage',async()=>{
 const {createDiagramStore,serializeSnapshot,parseSnapshot}=await import('../src/publishing.js');
 const config={maxBytes:1048576,storagePrefix:'gripeline',hashbinClientId:'test',canonicalOrigin:'https://gripeline.hashbin.page/',recoveryOrigin:'https://curtcox.github.io/gripeline/editor/'};
 let options,record;
 const store=createDiagramStore({config,redirectUri:config.canonicalOrigin,loadSDK:async()=>({HashBinClient:class{constructor(value){options=value;}async publish(payload,settings){record={payload,settings};const bytes=new TextEncoder().encode(payload),head=new Uint8Array(6);head[4]=bytes.length>>8;head[5]=bytes.length%256;return{cid:encode64(head)+encode64(new Uint8Array(await crypto.subtle.digest('SHA-512',bytes)))};}}})});
 await store.init();assert.throws(()=>options.storage.setItem('token','secret'),/credentials/);
 const snapshot={src:'a square printf hello',pos:{a:[1.25,2.5]},relay:'private',command:'injected'};
 const payload=serializeSnapshot(snapshot);await store.publish(payload,snapshot);
 assert.deepEqual(JSON.parse(record.payload),{format:'hashbin-diagram',version:1,src:snapshot.src,pos:snapshot.pos});
 assert.equal(record.settings.contentType,'application/json');
 assert.deepEqual(JSON.parse(JSON.stringify(store.documents.parse(payload))),{src:snapshot.src,pos:snapshot.pos});
 assert.throws(()=>serializeSnapshot({src:'x',pos:{a:[1,Infinity]}}),/position/);
 const archive='# apptron snapshot v1\n-- file.txt --\ncontent\n';
 assert.deepEqual(parseSnapshot(serializeSnapshot({kind:'apptron',src:archive,diagram:snapshot})),{kind:'apptron',src:archive});
});
