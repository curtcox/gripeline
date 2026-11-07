import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import LZString from '../vendor/lz-string.mjs';
import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const root=path.resolve('..');
test('every fixture has identical bash in the worker and CLI',async({page})=>{
  await page.goto('/editor/');
  await expect(page.locator('#status')).toContainText('Checked');
  const fixtures=JSON.parse(execFileSync('python3',['-c',`import sys,json; from pathlib import Path; sys.path.insert(0,'tests'); import run; print(json.dumps([{'src':getattr(c,l),'lang':l} for p in sorted(Path('tests/cases').rglob('*.case')) for c in [run.parse_case(p)] for l in ['dot','modl'] if getattr(c,l)]))`],{cwd:root,encoding:'utf8'}));
  const browserResults=await page.evaluate(async fixtures=>{
    const worker=new Worker('/editor/src/transpile.js',{type:'module'}), pending=new Map();
    worker.onmessage=({data})=>{if(data.type!=='compiler')pending.get(data.id)(data);};
    const results=[];
    for(const [id,fixture] of fixtures.entries())results.push(await new Promise(resolve=>{pending.set(id,resolve);worker.postMessage({id,...fixture,portable:false});}));
    worker.terminate();return results;
  },fixtures);
  for(const [index,fixture] of fixtures.entries()){
    const cli=execFileSync('python3',['-c',`import json,sys,gripeline; print(json.dumps(gripeline.gripeline_api(sys.stdin.read(),sys.argv[1])))`,fixture.lang],{cwd:root,input:fixture.src,encoding:'utf8'});
    expect(browserResults[index].error).toBeUndefined();expect(browserResults[index].result).toEqual(JSON.parse(cli));
  }
});
test('diagnostics disable run, and valid dot shows a reviewed command',async({page})=>{
  await page.goto('/editor/');
  await page.getByLabel('Diagram source').fill('digraph { a [label=""]; }');
  await expect(page.locator('#diagnostics')).toContainText('E02');
  await expect(page.getByRole('button',{name:'Run locally',exact:true})).toBeDisabled();
  await page.getByLabel('Diagram source').fill('digraph { a [label="echo hi"]; }');
  await expect(page.locator('#status')).toContainText('Checked · dot');
  await expect(page.locator('#diagram svg')).toBeVisible();
  await page.getByRole('button',{name:'Run locally',exact:true}).click();
  await expect(page.locator('#review')).toContainText('echo hi');
  await expect(page.getByLabel('Local run command')).toHaveValue(/gripeline run .*#h1=/);
});
test('links do not open execution targets',async({page,context})=>{
  const payload=Buffer.from(JSON.stringify({src:'a square echo hi',pos:{}})).toString('base64url');
  await page.goto('/editor/#h1='+payload);
  await expect(page.locator('#bash')).toContainText('echo hi');
  expect(context.pages()).toHaveLength(1);
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByLabel('Diagram source')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('native modl shapes, styles, dragging and zoom work in the editor',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(String(error)));
  await page.goto('/editor/');
  await page.getByLabel('Diagram source').fill('a hex red Source\nb note blue File\na -> b dashed green Link');
  await expect(page.locator('[data-node-id="a"] polygon')).toBeVisible();
  await expect(page.locator('[data-node-id="b"] path')).toBeVisible();
  await expect(page.locator('[data-edge-line="3"] path').first()).toHaveAttribute('stroke-dasharray','10 7');
  const node=page.locator('[data-node-id="a"] polygon'), initial=await node.getAttribute('points'),box=await node.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+30,box.y+box.height/2+20);await page.mouse.up();
  await expect(node).not.toHaveAttribute('points',initial);
  const before=await page.locator('#diagram svg > g').getAttribute('transform');
  await page.mouse.wheel(0,-100);
  await expect(page.locator('#diagram svg > g')).not.toHaveAttribute('transform',before);
  expect(errors).toEqual([]);
});
test('Fragment Kit shares source, renders QR and switches mobile panels',async({page})=>{
  await page.goto('/editor/');
  await expect(page.locator('#status')).toContainText('Checked');
  await page.getByRole('button',{name:'Share link',exact:true}).click();
  await expect(page.getByLabel('Share link',{exact:true})).toHaveValue(/#h1=/);
  await expect(page.getByText('Run on open',{exact:true})).toHaveCount(0);
  await page.locator('#share-dialog .fk-close').click();
  await page.getByRole('button',{name:'QR code',exact:true}).click();
  await expect(page.locator('#qr-code svg')).toBeVisible();
  await page.locator('#qr-dialog .fk-close').click();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('tab',{name:'Bash',exact:true}).click();
  await expect(page.locator('#bash')).toBeVisible();
  await expect(page.getByLabel('Diagram source')).toBeHidden();
  await page.getByRole('tab',{name:'Source',exact:true}).click();
  await expect(page.getByLabel('Diagram source')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('verified offline copy reloads and recompiles without network',async({page,context})=>{
  await page.goto('/editor/');
  await expect(page.locator('#offline-status')).toHaveText('Editor available offline',{timeout:60000});
  await page.reload();await expect(page.locator('#status')).toContainText('Checked');
  await context.setOffline(true);await page.reload();
  await expect(page.locator('#status')).toContainText('Checked');
  await page.getByLabel('Diagram source').fill('a square echo offline');
  await expect(page.locator('#bash')).toContainText('echo offline');
  await context.setOffline(false);
});
test('explicit links preserve drafts and recovery stays visibly unverified',async({page,context})=>{
  await page.goto('/editor/');await expect(page.locator('#status')).toContainText('Checked');
  await page.getByLabel('Diagram source').fill('a square echo saved-draft');
  const payload=Buffer.from(JSON.stringify({src:'a square echo linked-source',pos:{}})).toString('base64url');
  await page.goto('/editor/#h1='+payload);await expect(page.locator('#bash')).toContainText('linked-source');
  await page.getByRole('button',{name:'More',exact:true}).click();
  await page.getByRole('button',{name:'Resume saved work',exact:true}).click();
  await expect(page.locator('#draft-preview')).toContainText('saved-draft');
  await page.getByRole('button',{name:'Resume selected draft',exact:true}).click();
  await expect(page.locator('#bash')).toContainText('saved-draft');
  await expect(page.locator('#draft-status')).toContainText('unverified');
  expect(context.pages()).toHaveLength(1);
  await page.getByRole('button',{name:'Run locally',exact:true}).click();
  await expect(page.locator('#review')).toContainText('saved-draft');
});
test('environment declarations gate local commands and show missing tools',async({page})=>{
  await page.goto('/editor/');
  await page.getByLabel('Diagram source').fill('#gl env apptron\na square printf hi');
  await expect(page.locator('#status')).toContainText('Checked');
  await expect(page.getByRole('button',{name:'Run locally',exact:true})).toBeDisabled();
  await page.getByLabel('Diagram source').fill('#gl env linux\n#gl requires jq\na square jq .');
  await expect(page.locator('#badges')).toContainText('linux · needs jq');
  await page.getByRole('button',{name:'Run locally',exact:true}).click();
  await page.locator('#run-environment').selectOption('windows');
  await expect(page.getByRole('button',{name:'Copy command',exact:true})).toBeDisabled();
  await page.locator('#run-environment').selectOption('linux');
  await expect(page.getByRole('button',{name:'Copy command',exact:true})).toBeEnabled();
  await expect(page.locator('#run-target-note')).toContainText('jq');
});

test.describe('verified Apptron handoff',()=>{
 test.use({serviceWorkers:'block'});
 test('snapshot includes the exact checked compiler and never auto-runs',async({page,context})=>{
  const commit='a'.repeat(40),overlay='c'.repeat(64),manifest=JSON.stringify({commit,securityVersion:1,files:{'overlays/gripeline.tar.gz':{sha256:overlay}}});
  const manifestSha256=createHash('sha256').update(manifest).digest('hex');
  const pin={version:1,baseUrl:'https://curtcox.github.io/apptron/',commit,release:'runtime-test',manifestSha256,overlaySha256:overlay};
  await page.route('**/editor/apptron-runtime.json',route=>route.fulfill({json:pin}));
  await page.route('https://curtcox.github.io/apptron/runtime.lock',route=>route.fulfill({json:{commit,release:pin.release,manifestSha256},headers:{'Access-Control-Allow-Origin':'*'}}));
  await page.route(`https://curtcox.github.io/apptron/runtime/${commit}/runtime.json`,route=>route.fulfill({body:manifest,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*'}}));
  await context.route('https://curtcox.github.io/apptron/?compressed=*',route=>route.fulfill({body:'<p>Press Run in Apptron</p>',contentType:'text/html'}));
  await page.goto('/editor/');
  await page.getByLabel('Diagram source').fill('a square echo apptron');
  const button=page.getByRole('button',{name:'Run in Apptron',exact:true});await expect(button).toBeEnabled();
  const popupPromise=page.waitForEvent('popup');await button.click();const popup=await popupPromise;
  await popup.waitForURL('https://curtcox.github.io/apptron/?compressed=*');
  const snapshot=LZString.decompressFromEncodedURIComponent(new URL(popup.url()).searchParams.get('compressed'));
  expect(snapshot).toContain('-- pipeline.modl --\na square echo apptron\n');
  expect(snapshot).toContain('-- gripeline.py --\n'+readFileSync(path.join(root,'gripeline.py'),'utf8'));
  expect(snapshot).toContain('check pipeline.modl');expect(snapshot).not.toMatch(/^python3 gripeline.py run/m);
  expect(await popup.evaluate(()=>window.opener===null)).toBe(true);
 });
});
