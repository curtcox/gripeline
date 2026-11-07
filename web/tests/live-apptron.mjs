// Optional network acceptance: node web/tests/live-apptron.mjs (downloads the real VM).
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {chromium} from '@playwright/test';
import {apptronSnapshot,apptronLink} from '../src/run-targets.js';
const data=Buffer.alloc(70,65),head=Buffer.alloc(6);head.writeUIntBE(data.length,0,6);
const cid=head.toString('base64url')+createHash('sha512').update(data).digest('base64url');
const source=`input hex t256:${cid}\ncount square wc -c\ninput -> count\n`;
const compiler=await readFile(new URL('../../gripeline.py',import.meta.url),'utf8');
const previous=globalThis.fetch;
let snapshot;
try{globalThis.fetch=async url=>{assert.equal(url,'https://256t.us/'+cid);return new Response(data);};snapshot=await apptronSnapshot(source,'modl',compiler,[cid]);}
finally{globalThis.fetch=previous;}
const browser=await chromium.launch(),page=await browser.newPage();
const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('requestfailed',r=>errors.push(r.url().split('?')[0]+' '+r.failure()?.errorText));
const terminal=()=>page.evaluate(()=>{const b=ApptronOnline.host.frame.contentWindow.apptron.terminal.buffer.active;return Array.from({length:b.length},(_,i)=>b.getLine(i)?.translateToString()).join('\n');});
async function contains(expected,timeout=120000){const end=Date.now()+timeout;while(Date.now()<end){if((await terminal()).includes(expected))return;await new Promise(resolve=>setTimeout(resolve,500));}throw Error('Terminal did not produce '+expected+'\n'+await terminal());}
try{
 await page.goto(await apptronLink(snapshot));
 await page.waitForFunction(()=>crossOriginIsolated&&window.ApptronOnline,null,{timeout:90000});
 console.log('Loaded live Apptron; waiting for initialization');
 await page.evaluate(()=>{window.__acceptanceState='pending';ApptronOnline.initialized.then(()=>window.__acceptanceState='ready',e=>window.__acceptanceState=String(e));});
 await page.waitForFunction(()=>window.__acceptanceState!=='pending',null,{timeout:60000});
 assert.equal(await page.evaluate(()=>window.__acceptanceState),'ready');
 console.log('Initialized; opening remains inert; booting on explicit Run');
 assert.equal(await page.locator('#terminal iframe').count(),0,'Opening the handoff must not boot a VM');
 await page.locator('#run').click();
 await page.waitForFunction(()=>!document.getElementById('run').disabled&&document.getElementById('status').textContent.includes('Running ·'),null,{timeout:180000});
 console.log('VM booted; waiting for static-check prompt');
 await contains('Try: python3 gripeline.py run pipeline.modl');
 await page.evaluate(()=>ApptronOnline.host.sendKey('result=$(python3 gripeline.py run pipeline.modl) && printf "HANDOFF_OK=%s\\n" "$result"\r'));
 await contains('HANDOFF_OK=70');
 assert.equal(await page.evaluate(()=>ApptronOnline.getSource()),snapshot);
 if(process.env.GRIPELINE_HANDOFF_SCREENSHOT)await page.screenshot({path:process.env.GRIPELINE_HANDOFF_SCREENSHOT,fullPage:true});
 console.log('PASS live Apptron: inert handoff, exact compiler, verified non-inline CID store, HANDOFF_OK=70');
}catch(error){
 console.error(await page.evaluate(()=>({status:document.getElementById('status')?.textContent,offline:document.getElementById('offline-status')?.textContent,initialization:window.__acceptanceState})).catch(()=>({})),errors.slice(-10));
 if(process.env.GRIPELINE_HANDOFF_SCREENSHOT)await page.screenshot({path:process.env.GRIPELINE_HANDOFF_SCREENSHOT,fullPage:true}).catch(()=>{});throw error;
}finally{await browser.close();}
