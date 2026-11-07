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
    worker.onmessage=({data})=>pending.get(data.id)(data);
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
