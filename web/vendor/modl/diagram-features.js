// Deterministic layered layout. Existing coordinates always win.
export function layeredPositions(diagram, positions) {
  const nodes=[...diagram.nodes.values()].filter(n=>!n.isGroup), ids=nodes.map(n=>n.id);
  const rank=new Map(ids.map(id=>[id,0])), incoming=new Map(ids.map(id=>[id,[]])), outgoing=new Map(ids.map(id=>[id,[]]));
  for(const e of diagram.edges)if(rank.has(e.from)&&rank.has(e.to)&&e.from!==e.to){outgoing.get(e.from).push(e.to);incoming.get(e.to).push(e.from);}
  const degree=new Map(ids.map(id=>[id,incoming.get(id).length])), queue=ids.filter(id=>!degree.get(id));
  for(let i=0;i<queue.length;i++)for(const to of outgoing.get(queue[i])){rank.set(to,Math.max(rank.get(to),rank.get(queue[i])+1));degree.set(to,degree.get(to)-1);if(!degree.get(to))queue.push(to);}
  // Cyclic components retain source order in the first rank.
  const layers=[];for(const id of ids)(layers[rank.get(id)]??=[]).push(id);
  for(let pass=0;pass<4;pass++){
    const order=new Map(layers.flatMap(layer=>layer.map((id,i)=>[id,i])));
    for(const layer of layers){const score=id=>{const neighbors=(pass%2?outgoing:incoming).get(id);return neighbors.length?neighbors.reduce((sum,n)=>sum+order.get(n),0)/neighbors.length:order.get(id);};layer.sort((a,b)=>score(a)-score(b)||ids.indexOf(a)-ids.indexOf(b));}
  }
  layers.forEach((layer,x)=>layer.forEach((id,y)=>{if(!positions[id])positions[id]=[120+x*260,120+y*160];}));
  return positions;
}
export function groupBounds(diagram, positions) {
  const boxes=new Map();
  for(const n of [...diagram.nodes.values()].reverse().filter(n=>n.isGroup)){
    const children=[...diagram.nodes.values()].filter(c=>c.group===n.id);
    const rects=children.map(c=>boxes.get(c.id)??(positions[c.id]?{x:positions[c.id][0]-65,y:positions[c.id][1]-40,w:130,h:80}:null)).filter(Boolean);
    const x=rects.length?Math.min(...rects.map(r=>r.x))-30:40, y=rects.length?Math.min(...rects.map(r=>r.y))-50:40;
    const w=rects.length?Math.max(...rects.map(r=>r.x+r.w))-x+30:150,h=rects.length?Math.max(...rects.map(r=>r.y+r.h))-y+30:100;
    boxes.set(n.id,{x,y,w,h});
  }
  return boxes;
}
export function extraShape(shape,x,y,w,h) {
  const l=x-w/2,r=x+w/2,t=y-h/2,b=y+h/2;
  if(shape==='oval')return ['ellipse',{cx:x,cy:y,rx:w/2,ry:h/2}];
  if(shape==='stadium')return ['rect',{x:l,y:t,width:w,height:h,rx:h/2}];
  if(shape==='parallelogram')return ['polygon',{points:`${l+w*.2},${t} ${r},${t} ${r-w*.2},${b} ${l},${b}`}];
  if(shape==='note')return ['path',{d:`M${l},${t} H${r-15} L${r},${t+15} V${b} H${l} Z M${r-15},${t} V${t+15} H${r}`}];
  if(shape==='subroutine')return ['path',{d:`M${l},${t} H${r} V${b} H${l} Z M${l+12},${t} V${b} M${r-12},${t} V${b}`}];
  if(shape==='cylinder')return ['path',{d:`M${l},${t+10} A${w/2},10 0 0 1 ${r},${t+10} V${b-10} A${w/2},10 0 0 1 ${l},${b-10} Z M${l},${t+10} A${w/2},10 0 0 0 ${r},${t+10}`}];
  return null;
}
export function marksFromURL(href){return new Set((new URLSearchParams(new URL(href).hash.slice(1)).get('mark')??'').split(',').filter(Boolean));}
