// Temporary adapter until modl publishes its standalone renderDiagram module.
import {parseSource, COLORS} from '../vendor/modl/parse.js';
import {layeredPositions, groupBounds, extraShape} from '../vendor/modl/diagram-features.js';
const el = (tag, attrs={}, text) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
};
export function renderModl(src, positions, marks=[], onMove=()=>{}) {
  const model = parseSource(src), pos = layeredPositions(model, positions);
  const boxes = groupBounds(model, pos), svg = el('svg', {width:'100%', height:'100%', role:'img', 'aria-label':'MODL diagram'});
  const values = Object.values(pos), width=Math.max(500,...values.map(p=>p[0]+100)), height=Math.max(320,...values.map(p=>p[1]+80));
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  for (const [id, box] of boxes) {
    svg.append(el('rect',{x:box.x,y:box.y,width:box.w,height:box.h,fill:'none',stroke:'#94a69b','stroke-dasharray':'6 4'}));
    svg.append(el('text',{x:box.x+8,y:box.y+18,fill:'#41594e'},model.nodes.get(id).text||id));
  }
  for (const edge of model.edges) {
    const a=pos[edge.from], b=pos[edge.to]; if(!a||!b)continue;
    svg.append(el('path',{d:`M${a[0]+55},${a[1]} L${b[0]-65},${b[1]} l-9,-5 m9,5 l-9,5`,fill:'none',stroke:marks.includes('L'+edge.line)?'#d22':COLORS[edge.color]||'#60766f','stroke-width':2}));
  }
  for(const [id,node] of model.nodes) {
    if(node.isGroup||!pos[id])continue;
    const [x,y]=pos[id], g=el('g',{'data-node-id':id});
    let shape=extraShape(node.shape,x,y,120,65);
    if(!shape)shape=node.shape==='square'?['rect',{x:x-60,y:y-32,width:120,height:64,rx:3}]:node.shape==='hex'?['polygon',{points:`${x-45},${y-32} ${x+45},${y-32} ${x+60},${y} ${x+45},${y+32} ${x-45},${y+32} ${x-60},${y}`}]:['ellipse',{cx:x,cy:y,rx:60,ry:32}];
    g.append(el(shape[0],{...shape[1],fill:'#f4f8ed',stroke:marks.includes(id)?'#d22':COLORS[node.color]||'#60766f','stroke-width':2}));
    g.append(el('text',{x,y,'text-anchor':'middle','dominant-baseline':'middle','font-size':12,fill:'#182f2b'},(node.text||id).slice(0,26)));
    g.style.cursor='grab';g.onpointerdown=event=>{
      event.preventDefault();g.setPointerCapture(event.pointerId);
      g.onpointermove=move=>{const point=new DOMPoint(move.clientX,move.clientY).matrixTransform(svg.getScreenCTM().inverse());pos[id]=[point.x,point.y];g.setAttribute('transform',`translate(${point.x-x},${point.y-y})`);};
      g.onpointerup=()=>{g.onpointermove=null;onMove();};
    };svg.append(g);
  }
  return svg;
}
