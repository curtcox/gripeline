import {createConfig,createUrlState,bounded} from '../vendor/fragment-kit-v0.4.3/src/index.js';
import settings from '../fragment-kit.config.json' with {type:'json'};
import {shareLink,unwrapDiagram} from './cid.js';
export const config=createConfig(settings);
export const type={type:'gripeline',settingsKeys:['lang','portable'],normalize(value){const options=value.gripeline??value;const language=options.language??'';if(!['','dot','modl'].includes(language))throw Error('Unsupported diagram language.');return{src:bounded(value?.src,config.maxBytes),gripeline:{language,portable:options.portable!==false,pos:unwrapDiagram(JSON.stringify({src:'',pos:options.pos??{}})).pos}};},isDefault:()=>false};
export const urlState=createUrlState({config,type,legacyWriter:(doc,{url,run})=>{const link=new URL(shareLink(doc.src,doc.gripeline.pos,url.href));if(doc.gripeline.language)link.searchParams.set('lang',doc.gripeline.language);if(!doc.gripeline.portable)link.searchParams.set('portable','0');if(run===false)link.searchParams.set('run','0');return link.href;}});

// AI is a separate opt-in entry point; document loading never creates a connection.
type.ai={"describe":"Gripeline pipeline diagram src, MODL or DOT. Preserve language, portable checks and diagram positions. Compilation produces visible bash data in a trusted worker; never execute bash. Accepted changes require explicit Check and separate execution review.","paths":["/src"]};
