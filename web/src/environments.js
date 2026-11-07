export const nativeEnvironments=['linux','macos','windows'];
export function classifyEnvironments(result,inventory,{apptronReady=false,apptronReason='The verified Apptron runtime is not available on this site yet'}={}) {
  const requirements=[...new Set([...(result.requires??[]),...(result.commands??[])])];
  return Object.fromEntries([...nativeEnvironments,'apptron'].map(environment=>{
    let reason;
    if(result.problems?.length)reason='Fix the static-check problems first';
    else if(result.environments?.length&&!result.environments.includes(environment))reason='Excluded by the diagram’s environment declaration';
    else if(environment==='apptron'&&!apptronReady)reason=apptronReason;
    const tools=new Set([...inventory.common,...inventory.environments[environment]]),missing=requirements.filter(tool=>!tools.has(tool));
    return[environment,{status:reason?'unsupported':missing.length?'needs':'runs',missing,reason}];
  }));
}
