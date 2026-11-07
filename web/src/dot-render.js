let renderer;
export async function renderDot(src,marks=[]) {
  renderer ??= import('../vendor/viz.mjs').then(module => module.instance());
  const viz = await renderer;
  const svg = viz.renderSVGElement(src);
  // Graphviz can preserve URLs from untrusted source. Keep the preview inert.
  for (const el of svg.querySelectorAll('script,foreignObject,image')) el.remove();
  for (const el of [svg, ...svg.querySelectorAll('*')]) for (const attr of [...el.attributes]) {
    if (/^on/i.test(attr.name) || /href$/i.test(attr.name)) el.removeAttribute(attr.name);
  }
  for(const group of svg.querySelectorAll('g.node')) {
    if(marks.includes(group.querySelector('title')?.textContent))for(const shape of group.querySelectorAll('polygon,ellipse,path'))shape.setAttribute('stroke','#d22');
  }
  return svg;
}
