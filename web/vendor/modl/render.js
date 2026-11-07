// Shared MODL SVG renderer. No editor startup, persistence, navigation, or execution.
import {COLORS, NODE_SHAPES} from './parse.js';
import {layeredPositions, groupBounds, extraShape} from './diagram-features.js';
  const NODE_W = 110;
  const NODE_H = 64;

  export function nodeScale(size) {
    if (size === "tiny") return 0.25;
    if (size === "small") return 0.5;
    if (size === "big") return 2.0;
    if (size === "bigger") return 4.0;
    if (size === "huge") return 8.0;
    return 1.0; // normal
  }

  function hexToRgb(hex) {
    const h = hex.replace("#", "").trim();
    const v = parseInt(h, 16);
    if (h.length !== 6 || Number.isNaN(v)) return { r: 200, g: 200, b: 200 };
    return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
  }

  function rgba(hex, a) {
    const { r, g, b } = hexToRgb(hex);
    return `rgba(${r},${g},${b},${a})`;
  }

  function luminance(hex) {
    const { r, g, b } = hexToRgb(hex);
    const srgb = [r, g, b].map(v => {
      const x = v / 255;
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
  }

  function applyEdgeStyle(style, colorName) {
    const color = COLORS[colorName] || COLORS.gray;
    const props = {
      stroke: color,
      "stroke-width": (style === "bold") ? 3.5 : 2.2,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "stroke-dasharray": "",
    };
    if (style === "dashed") props["stroke-dasharray"] = "10 7";
    if (style === "dotted") props["stroke-dasharray"] = "2 7";
    return props;
  }

  function markerIdFor(colorName) {
    return `arrow-${colorName}`;
  }

  function buildMarkers(defsEl) {
    // Create one arrow marker per color name to match edge stroke.
    for (const name of Object.keys(COLORS)) {
      const col = COLORS[name];
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", markerIdFor(name));
      marker.setAttribute("markerWidth", "10");
      marker.setAttribute("markerHeight", "10");
      marker.setAttribute("refX", "9");
      marker.setAttribute("refY", "5");
      marker.setAttribute("orient", "auto");
      marker.setAttribute("markerUnits", "strokeWidth");

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      path.setAttribute("fill", col);

      marker.appendChild(path);
      defsEl.appendChild(marker);
    }
  }

  function nodeRadius(shape, size) {
    // Rough collision/edge endpoint offset
    const sc = nodeScale(size);
    if (shape === "none") return 4 * sc;
    if (shape === "circle") return Math.max(NODE_W, NODE_H) * 0.32 * sc;
    if (shape === "triangle" || shape === "diamond" || shape === "hex") return Math.max(NODE_W, NODE_H) * 0.36 * sc;
    return Math.max(NODE_W, NODE_H) * 0.34 * sc; // square-ish
  }

  function imageNodeSize(n, img) {
    if (!n.sizeGiven && img.width && img.height) return { w: img.width, h: img.height };
    const sc = nodeScale(n.size);
    const boxW = NODE_W * sc, boxH = NODE_H * sc;
    if (!img.width || !img.height) return { w: boxW, h: boxH };
    const k = Math.min(boxW / img.width, boxH / img.height);
    return { w: img.width * k, h: img.height * k };
  }

  // Distance from the center of a convex polygon (points relative to that center) to its edge along (ux, uy)
  function rayExit(points, ux, uy) {
    let best = Infinity;
    for (let i = 0; i < points.length; i++) {
      const [px, py] = points[i];
      const [qx, qy] = points[(i + 1) % points.length];
      const ex = qx - px, ey = qy - py;
      const den = ux * ey - uy * ex;
      if (Math.abs(den) < 1e-9) continue;
      const t = (px * ey - py * ex) / den;
      const s = (px * uy - py * ux) / den;
      if (t > 0 && s >= -1e-9 && s <= 1 + 1e-9) best = Math.min(best, t);
    }
    return Number.isFinite(best) ? best : 0;
  }

  function rectPoints(hw, hh) {
    return [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
  }

  // Geometry of an image node relative to its center, or null if the node isn't showing an image.
  // An explicitly given shape becomes a frame drawn around the image.
  function imageLayout(n, nodeImage) {
    const img = n.url ? nodeImage(n.url) : null;
    if (!img) return null;
    const { w, h } = imageNodeSize(n, img);
    const sc = n.sizeGiven ? nodeScale(n.size) : 1;
    const shape = (n.shapeGiven && NODE_SHAPES.includes(n.shape) && n.shape !== "none") ? n.shape : "";
    const pad = shape ? Math.max(3, 6 * sc) : 0;
    const W = w / 2 + pad, H = h / 2 + pad;

    let frame = null;
    let outline;
    if (shape === "circle") {
      frame = { r: Math.hypot(W, H) };
    } else if (shape === "square") {
      frame = { points: rectPoints(W, H), rx: Math.min(12 * sc, W, H) };
    } else if (shape === "diamond") {
      frame = { points: [[0, -2 * H], [2 * W, 0], [0, 2 * H], [-2 * W, 0]] };
    } else if (shape === "triangle") {
      frame = { points: [[0, -3 * H], [2 * W, H], [-2 * W, H]] };
    } else if (shape === "hex") {
      const hw = W / 0.55;
      frame = { points: [[-W, -H], [W, -H], [hw, 0], [W, H], [-W, H], [-hw, 0]] };
    }
    if (frame && frame.points) outline = frame.points;
    else if (!frame) outline = rectPoints(w / 2 + 2, h / 2 + 2);

    const bounds = frame && frame.r
      ? { left: -frame.r, top: -frame.r, right: frame.r, bottom: frame.r }
      : {
          left: Math.min(...outline.map(p => p[0])),
          top: Math.min(...outline.map(p => p[1])),
          right: Math.max(...outline.map(p => p[0])),
          bottom: Math.max(...outline.map(p => p[1])),
        };

    return {
      w, h, sc, frame, bounds,
      reach: (ux, uy) => (frame && frame.r) ? frame.r : rayExit(outline, ux, uy),
    };
  }

  // reachA/reachB give the distance from a node's center to its edge in a direction
  function edgeEndpoints(a, b, reachA, reachB) {
    const ax = a[0], ay = a[1];
    const bx = b[0], by = b[1];
    const dx = bx - ax, dy = by - ay;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;

    const ra = reachA(ux, uy);
    const rb = reachB(-ux, -uy);

    const x1 = ax + ux * ra;
    const y1 = ay + uy * ra;
    const x2 = bx - ux * rb;
    const y2 = by - uy * rb;

    return { x1, y1, x2, y2, ux, uy, len };
  }

  function truncateLabel(s, n) {
    if (!s) return "";
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }


/** Render a parsed MODL model into an existing SVG.
 * positions is updated only to supply missing layout coordinates.
 * Pointer and link behavior belong to the embedding editor through callbacks.
 * imageInfo(url) returns cached {width,height} or null; the renderer fetches nothing.
 * Returns the viewport group so hosts can update their camera without a redraw.
 */
export function renderDiagram($svg, diagram, opts = {}) {
  const state = {pos: opts.positions ?? Object.create(null), rawText: opts.rawText === true};
  layeredPositions(diagram, state.pos);
  const viewport = opts.viewport ?? {scale: 1, tx: 0, ty: 0};
  let viewportGroup;
  const startPan = opts.onPan ?? (() => {}), startDrag = opts.onDrag ?? (() => {});
  const safeOpen = opts.onLink ?? (() => {});
  function applyViewportTransform() {
    viewportGroup.setAttribute('transform', `translate(${viewport.tx} ${viewport.ty}) scale(${viewport.scale})`);
    $svg.toggleAttribute('data-modl-simple', viewport.scale < 0.1 || viewport.scale > 8);
  }
    // Setup svg coordinate system in pixels
    const rect = $svg.getBoundingClientRect();
    const W = Math.max(400, rect.width);
    const H = Math.max(300, rect.height);

    $svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    $svg.style.touchAction = "none";
    $svg.innerHTML = "";

    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    buildMarkers(defs);
    const detailStyle = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    detailStyle.textContent = 'svg[data-modl-simple] [filter] { filter: none; }';
    defs.appendChild(detailStyle);
    $svg.appendChild(defs);

    // A subtle grid background
    const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bg.setAttribute("x", "0"); bg.setAttribute("y", "0");
    bg.setAttribute("width", W); bg.setAttribute("height", H);
    bg.setAttribute("fill", diagram.background ? COLORS[diagram.background] || "transparent" : "transparent");
    bg.style.cursor = "grab";
    bg.addEventListener("pointerdown", (ev) => startPan(ev));
    $svg.appendChild(bg);

    // Draw edges under nodes
    viewportGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const edgeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const nodeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    viewportGroup.appendChild(edgeLayer);
    viewportGroup.appendChild(nodeLayer);
    $svg.appendChild(viewportGroup);
    applyViewportTransform();

    const imageLayouts = new Map();
    for (const [id, n] of diagram.nodes.entries()) {
      const layout = imageLayout(n, opts.imageInfo ?? (() => null));
      if (layout) imageLayouts.set(id, layout);
    }
    const reachOf = (node) => {
      const box=boxes?.get(node.id);
      if(box)return (ux,uy)=>Math.min(Math.abs(box.w/2/(ux||1e-9)),Math.abs(box.h/2/(uy||1e-9)));
      const layout = imageLayouts.get(node.id);
      return layout ? layout.reach : () => nodeRadius(node.shape, node.size);
    };

    const boxes=groupBounds(diagram,state.pos);
    const marks=new Set(opts.marks ?? []);
    const svgEl=(tag,attrs={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);return el;};
    for(const[id,box]of boxes){
      const n=diagram.nodes.get(id),g=svgEl('g',{'data-group-id':id});
      g.appendChild(svgEl('rect',{x:box.x,y:box.y,width:box.w,height:box.h,rx:12,fill:'rgba(100,120,140,.08)',stroke:COLORS[n.color]??COLORS.gray,'stroke-dasharray':'6 4'}));
      const title=svgEl('text',{x:box.x+12,y:box.y+22,fill:COLORS[n.color]??COLORS.gray});title.textContent=state.rawText?n.rawText??n.text:n.text||id;g.appendChild(title);viewportGroup.insertBefore(g,edgeLayer);
    }
    const position=id=>{const box=boxes.get(id);return box?[box.x+box.w/2,box.y+box.h/2]:state.pos[id];};
    // Edge rendering
    for (const e of diagram.edges) {
      const fromPos = position(e.from);
      const toPos = position(e.to);
      const fromNode = diagram.nodes.get(e.from);
      const toNode = diagram.nodes.get(e.to);
      if (!fromPos || !toPos || !fromNode || !toNode) continue;

      const { x1, y1, x2, y2, ux, uy } = edgeEndpoints(fromPos, toPos, reachOf(fromNode), reachOf(toNode));

      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");

      g.setAttribute('data-edge-line',e.line);
      if(marks.has('L'+e.line)){g.style.filter='drop-shadow(0 0 5px red)';}
      for(const [text,x,y]of[[e.fromPort,x1-uy*12,y1+ux*12],[e.toPort,x2-uy*12,y2+ux*12]])if(text){const label=svgEl('text',{x,y,fill:'currentColor','font-size':11});label.textContent=text;g.appendChild(label);}
      // Visible stroke
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", `M ${x1} ${y1} L ${x2} ${y2}`);

      const styleProps = applyEdgeStyle(e.style || "solid", e.color || "gray");
      for (const [k, v] of Object.entries(styleProps)) p.setAttribute(k, v);

      p.setAttribute("fill", "none");
      p.setAttribute("marker-end", `url(#${markerIdFor(e.color || "gray")})`);

      if(e.style==='double'){
        const second=p.cloneNode();second.setAttribute('d',`M ${x1-uy*5} ${y1+ux*5} L ${x2-uy*5} ${y2+ux*5}`);second.removeAttribute('marker-end');g.appendChild(second);
      }
      // Hover text
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      const tText = [
        `${e.from} -> ${e.to}`,
        e.text ? `text: ${e.text}` : "",
        e.url ? `link: ${e.url}` : ""
      ].filter(Boolean).join("\n");
      title.textContent = tText;
      g.appendChild(title);
      g.setAttribute("tabindex","0");g.setAttribute("aria-label",tText);

      // Click overlay for edges (fatter invisible stroke)
      const hit = document.createElementNS("http://www.w3.org/2000/svg", "path");
      hit.setAttribute("d", `M ${x1} ${y1} L ${x2} ${y2}`);
      hit.setAttribute("fill", "none");
      hit.setAttribute("stroke", "transparent");
      hit.setAttribute("stroke-width", "14");
      hit.style.cursor = e.url ? "pointer" : "default";
      hit.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (e.url) safeOpen(e.url);
      });

      // Edge label (optional)
      if (e.text) {
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const edgeTextScale = nodeScale(e.size || "normal");
        // Offset label slightly perpendicular
        const px = -uy, py = ux;
        const tx = mx + px * 10;
        const ty = my + py * 10;

        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", tx);
        label.setAttribute("y", ty);
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("dominant-baseline", "middle");
        label.setAttribute("font-family", "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial");
        label.setAttribute("font-size", String(Math.max(10, Math.round(12 * edgeTextScale))));
        label.setAttribute("fill", "rgba(232,237,243,0.85)");
        label.setAttribute("paint-order", "stroke");
        label.setAttribute("stroke", "rgba(0,0,0,0.6)");
        label.setAttribute("stroke-width", "3");
        label.style.pointerEvents = "none";
        if(state.rawText)label.setAttribute('font-family','monospace');
        label.textContent = (state.rawText ? e.rawText??e.text : truncateLabel(e.text, 28));
        g.appendChild(label);
      }

      g.appendChild(p);
      g.appendChild(hit);
      edgeLayer.appendChild(g);
    }

    // Node rendering
    for (const [id, n] of diagram.nodes.entries()) {
      if(n.isGroup)continue;
      const pos = state.pos[id];
      if (!pos) continue;
      const x = pos[0], y = pos[1];

      const sc = nodeScale(n.size);
      const w = NODE_W * sc;
      const h = NODE_H * sc;

      const col = COLORS[n.color] || COLORS.gray;
      const fillCol = rgba(col, 0.18);
      const strokeCol = rgba(col, 0.85);
      const labelCol = luminance(col) < 0.38 ? "rgba(248,250,252,0.95)" : "rgba(15,23,42,0.92)";

      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("data-node-id", id);
      if(marks.has(id)||marks.has('L'+n.line))g.style.filter='drop-shadow(0 0 5px red)';
      g.setAttribute('tabindex','0');
      g.style.cursor = "grab";

      // Hover text
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      const tText = [
        id,
        n.text ? `text: ${n.text}` : "",
        n.url ? `link: ${n.url}` : ""
      ].filter(Boolean).join("\n");
      title.textContent = tText;
      g.appendChild(title);
      g.setAttribute("aria-label",tText);

      const layout = imageLayouts.get(id);
      if (layout) {
        renderImageNode(g, n, id, x, y, layout, fillCol, strokeCol);
        g.addEventListener("pointerdown", (ev) => startDrag(ev, id));
        nodeLayer.appendChild(g);
        continue;
      }

      // Shape
      const shape = (n.shape && NODE_SHAPES.includes(n.shape)) ? n.shape : "circle";
      let el;

      const custom=extraShape(shape,x,y,w,h);
      if(custom){el=svgEl(custom[0],custom[1]);}
      else if (shape === "none") {
        el = null;
      } else if (shape === "circle") {
        el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        el.setAttribute("cx", x);
        el.setAttribute("cy", y);
        el.setAttribute("r", Math.min(w, h) * 0.42);
      } else if (shape === "square") {
        el = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        el.setAttribute("x", x - w / 2);
        el.setAttribute("y", y - h / 2);
        el.setAttribute("width", w);
        el.setAttribute("height", h);
        el.setAttribute("rx", 12 * sc);
      } else if (shape === "diamond") {
        el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        const pts = [
          [x, y - h/2],
          [x + w/2, y],
          [x, y + h/2],
          [x - w/2, y],
        ].map(p => p.join(",")).join(" ");
        el.setAttribute("points", pts);
      } else if (shape === "triangle") {
        el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        const pts = [
          [x, y - h/2],
          [x + w/2, y + h/2],
          [x - w/2, y + h/2],
        ].map(p => p.join(",")).join(" ");
        el.setAttribute("points", pts);
      } else if (shape === "hex") {
        el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        const hw = w/2, hh = h/2;
        const pts = [
          [x - hw*0.55, y - hh],
          [x + hw*0.55, y - hh],
          [x + hw,      y],
          [x + hw*0.55, y + hh],
          [x - hw*0.55, y + hh],
          [x - hw,      y],
        ].map(p => p.join(",")).join(" ");
        el.setAttribute("points", pts);
      } else {
        // fallback
        el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        el.setAttribute("cx", x);
        el.setAttribute("cy", y);
        el.setAttribute("r", Math.min(w, h) * 0.42);
      }

      if (el) {
        el.setAttribute("fill", fillCol);
        el.setAttribute("stroke", strokeCol);
        el.setAttribute("stroke-width", "2.2");
        el.setAttribute("filter", "drop-shadow(0px 8px 18px rgba(0,0,0,0.45))");
        el.style.pointerEvents = "all";

        // Click to follow link
        if (n.url) {
          el.style.cursor = "pointer";
          el.addEventListener("click", (ev) => {
            // If dragging, ignore click (handled by drag logic)
            if (opts.getDragging?.()?.id === id) return;
            ev.stopPropagation();
            safeOpen(n.url);
          });
        }

        g.appendChild(el);
      } else {
        // Invisible hit target so "none" nodes remain draggable/clickable.
        const hit = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        hit.setAttribute("x", x - w / 2);
        hit.setAttribute("y", y - h / 2);
        hit.setAttribute("width", w);
        hit.setAttribute("height", h);
        hit.setAttribute("fill", "transparent");
        hit.setAttribute("stroke", "none");
        hit.style.pointerEvents = "all";
        if (n.url) {
          hit.style.cursor = "pointer";
          hit.addEventListener("click", (ev) => {
            if (opts.getDragging?.()?.id === id) return;
            ev.stopPropagation();
            safeOpen(n.url);
          });
        }
        g.appendChild(hit);
      }

      // Label: prefer node text; fallback to id
      const labelText = n.text ? (state.rawText ? n.rawText??n.text : truncateLabel(n.text, 22)) : id;
      const textEl = document.createElementNS("http://www.w3.org/2000/svg", "text");
      textEl.setAttribute("x", x);
      textEl.setAttribute("y", y);
      textEl.setAttribute("text-anchor", "middle");
      textEl.setAttribute("dominant-baseline", "middle");
      textEl.setAttribute("font-family", "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial");
      textEl.setAttribute("font-size", String(Math.max(10, Math.round(13 * sc))));
      textEl.setAttribute("font-weight", "700");
      textEl.setAttribute("fill", (shape === "none") ? strokeCol : labelCol);
      textEl.style.pointerEvents = "none";
      textEl.textContent = labelText;

      g.appendChild(textEl);

      // Drag handlers
      g.addEventListener("pointerdown", (ev) => startDrag(ev, id));

      nodeLayer.appendChild(g);
    }
  return {viewportGroup};
  function renderImageNode(g, n, id, x, y, layout, fillCol, strokeCol) {
    const { w, h, sc, frame, bounds } = layout;
    const shadow = "drop-shadow(0px 8px 18px rgba(0,0,0,0.45))";

    if (frame) {
      let el;
      if (frame.r) {
        el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        el.setAttribute("cx", x);
        el.setAttribute("cy", y);
        el.setAttribute("r", frame.r);
      } else if (frame.rx !== undefined) {
        el = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        el.setAttribute("x", x + bounds.left);
        el.setAttribute("y", y + bounds.top);
        el.setAttribute("width", bounds.right - bounds.left);
        el.setAttribute("height", bounds.bottom - bounds.top);
        el.setAttribute("rx", frame.rx);
      } else {
        el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        el.setAttribute("points", frame.points.map(([px, py]) => `${x + px},${y + py}`).join(" "));
      }
      el.setAttribute("fill", fillCol);
      el.setAttribute("stroke", strokeCol);
      el.setAttribute("stroke-width", "2.2");
      el.setAttribute("filter", shadow);
      el.style.pointerEvents = "none";
      g.appendChild(el);
    }

    const image = document.createElementNS("http://www.w3.org/2000/svg", "image");
    image.setAttribute("href", n.url);
    image.setAttribute("x", x - w / 2);
    image.setAttribute("y", y - h / 2);
    image.setAttribute("width", w);
    image.setAttribute("height", h);
    image.setAttribute("preserveAspectRatio", "xMidYMid meet");
    if (!frame) image.setAttribute("filter", shadow);
    image.style.pointerEvents = "none";
    g.appendChild(image);

    // Transparent hit target covering the whole node so it stays draggable/clickable
    const hit = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    hit.setAttribute("x", x + bounds.left);
    hit.setAttribute("y", y + bounds.top);
    hit.setAttribute("width", bounds.right - bounds.left);
    hit.setAttribute("height", bounds.bottom - bounds.top);
    hit.setAttribute("fill", "transparent");
    hit.setAttribute("stroke", "none");
    hit.style.pointerEvents = "all";
    hit.style.cursor = "pointer";
    hit.addEventListener("click", (ev) => {
      if (opts.getDragging?.()?.id === id) return;
      ev.stopPropagation();
      safeOpen(n.url);
    });
    g.appendChild(hit);

    if (n.text) {
      const fontSize = Math.max(10, Math.round(13 * sc));
      const textEl = document.createElementNS("http://www.w3.org/2000/svg", "text");
      textEl.setAttribute("x", x);
      textEl.setAttribute("y", y + bounds.bottom + 4 + fontSize / 2);
      textEl.setAttribute("text-anchor", "middle");
      textEl.setAttribute("dominant-baseline", "middle");
      textEl.setAttribute("font-family", "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial");
      textEl.setAttribute("font-size", String(fontSize));
      textEl.setAttribute("font-weight", "700");
      textEl.setAttribute("fill", "rgba(232,237,243,0.92)");
      textEl.setAttribute("paint-order", "stroke");
      textEl.setAttribute("stroke", "rgba(0,0,0,0.6)");
      textEl.setAttribute("stroke-width", "3");
      textEl.style.pointerEvents = "none";
      if(state.rawText)textEl.setAttribute('font-family','monospace');
      textEl.textContent = (state.rawText ? n.rawText??n.text : truncateLabel(n.text, 22));
      g.appendChild(textEl);
    }
  }

}
