import {parseSource} from '../vendor/modl/parse.js';
import {renderDiagram} from '../vendor/modl/render.js';
const cameras = new WeakMap();
export function renderModl(src, positions, marks=[], onMove=()=>{}) {
  const model=parseSource(src), svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('width','100%');svg.setAttribute('height','100%');svg.setAttribute('role','img');svg.setAttribute('aria-label','MODL diagram');
  const viewport=cameras.get(positions)??{scale:1,tx:0,ty:0};cameras.set(positions,viewport);
  for(const id of Object.keys(positions))if(!model.nodes.has(id))delete positions[id];
  let dragging=null,panning=null;
  const point=event=>new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse());
  const capture=event=>{event.preventDefault();event.stopPropagation();svg.setPointerCapture(event.pointerId);};
  const draw=()=>renderDiagram(svg,model,{positions,marks,viewport,getDragging:()=>dragging,
    onDrag:(event,id)=>{
      if(event.button!==0||dragging||panning)return;
      capture(event);dragging={id,pointer:event.pointerId,start:point(event),original:[...positions[id]]};
    },
    onPan:event=>{
      if(![0,1].includes(event.button)||dragging||panning)return;
      capture(event);panning={pointer:event.pointerId,start:point(event),tx:viewport.tx,ty:viewport.ty};
    },
    onLink:url=>{try{if(['http:','https:'].includes(new URL(url).protocol))window.open(url,'_blank','noopener,noreferrer');}catch{}},
  });
  svg.addEventListener('pointermove',event=>{
    if(dragging?.pointer===event.pointerId){const p=point(event);positions[dragging.id]=[dragging.original[0]+(p.x-dragging.start.x)/viewport.scale,dragging.original[1]+(p.y-dragging.start.y)/viewport.scale];draw();}
    else if(panning?.pointer===event.pointerId){const p=point(event);viewport.tx=panning.tx+p.x-panning.start.x;viewport.ty=panning.ty+p.y-panning.start.y;draw();}
  });
  const finish=event=>{if(dragging?.pointer===event.pointerId){dragging=null;onMove();}if(panning?.pointer===event.pointerId)panning=null;};
  for(const event of ['pointerup','pointercancel','lostpointercapture'])svg.addEventListener(event,finish);
  svg.addEventListener('wheel',event=>{
    event.preventDefault();if(dragging||panning)return;
    const p=point(event),next=Math.min(1000,Math.max(.001,viewport.scale*Math.exp(Math.max(-2,Math.min(2,-event.deltaY*.002)))));
    const factor=next/viewport.scale;viewport.tx=p.x-(p.x-viewport.tx)*factor;viewport.ty=p.y-(p.y-viewport.ty)*factor;viewport.scale=next;draw();
  },{passive:false});
  draw();requestAnimationFrame(()=>{if(svg.isConnected)draw();});
  return svg;
}
