  const NODE_SIZES = ["tiny", "small", "normal", "big", "bigger", "huge"];
  const NODE_SHAPES = ["none", "circle", "square", "diamond", "triangle", "hex", "note", "cylinder", "parallelogram", "stadium", "subroutine", "oval"];
  const EDGE_STYLES = ["solid", "dashed", "dotted", "bold", "double"];

  const COLORS = {
    gray:   "#9aa4b2",
    black:  "#1f2937",
    white:  "#f8fafc",
    red:    "#ef4444",
    orange: "#f97316",
    yellow: "#eab308",
    green:  "#22c55e",
    teal:   "#14b8a6",
    blue:   "#3b82f6",
    purple: "#a855f7",
    pink:   "#ec4899",
    brown:  "#92400e",
  };

  // -----------------------------
  // Parsing DSL
  // -----------------------------
  // Splits a line into pieces: {type: "ws" | "arrow" | "comment", raw} and {type: "word", raw, value, quoted}.
  // A quote opens a string only at the start of a word or right after a closing quote, and only if the same
  // quote character closes it later on the line; otherwise it is an ordinary character. Inside a string,
  // "->", "#" and whitespace are text. Strings and plain characters with nothing between them form one word.
  function lexLine(line) {
    const pieces = [];
    const isWS = (c) => /\s/.test(c);
    let i = 0;
    while (i < line.length) {
      const c = line[i];
      if (isWS(c)) {
        let j = i;
        while (j < line.length && isWS(line[j])) j++;
        pieces.push({ type: "ws", raw: line.slice(i, j) });
        i = j;
      } else if (c === "#" && (i === 0 || isWS(line[i - 1]))) {
        pieces.push({ type: "comment", raw: line.slice(i) });
        break;
      } else if (line.startsWith("->", i)) {
        pieces.push({ type: "arrow", raw: "->" });
        i += 2;
      } else {
        const start = i;
        let value = "";
        let quoted = false;
        let canOpen = true;
        while (i < line.length && !isWS(line[i]) && !line.startsWith("->", i)) {
          const q = line[i];
          const close = (canOpen && (q === '"' || q === "'")) ? line.indexOf(q, i + 1) : -1;
          if (close >= 0) {
            value += line.slice(i + 1, close);
            quoted = true;
            i = close + 1;
          } else {
            value += q;
            canOpen = q === "[";
            i++;
          }
        }
        pieces.push({ type: "word", raw: line.slice(start, i), value, quoted, start, end:i });
      }
    }
    let column=0; for(const p of pieces){p.start=column;column+=p.raw.length;p.end=column;}
    return pieces;
  }

  function looksLikeUrlToken(tok) {
    if (!tok) return false;
    if (tok.startsWith("/")) return true;
    if (tok.startsWith("http://") || tok.startsWith("https://")) return true;
    if (tok.startsWith("mailto:")) return true;
    if (tok.startsWith("www.")) return true;
    return false;
  }

  function normalizeUrl(tok) {
    if (!tok) return "";
    if (tok.startsWith("/")) return "https://" + tok.slice(1);
    if (tok.startsWith("www.")) return "https://" + tok;
    return tok;
  }

  function isValidId(id) {
    // Keep it simple; allow common graph ids
    return /^[A-Za-z0-9_:\-]+$/.test(id);
  }

  // Quoted ids may hold any characters, but not nothing
  function endpoint(word) {
    if(!word.raw.endsWith("]"))return {...word,port:null};
    const match=word.value.match(/^(.*)\[([^\[\]]*)\]$/);
    if(!match)return {...word,port:null};
    return {...word,value:match[1],port:match[2],quoted:word.raw.startsWith('"')||word.raw.startsWith("'")};
  }
  function idError(word, lineNo) {
    word=endpoint(word);
    if (word.quoted) return word.value ? "" : `Line ${lineNo+1}: empty node id`;
    return isValidId(word.value) ? "" : `Line ${lineNo+1}: invalid node id "${word.value}"`;
  }

  function parseAttrs(words, kind) {
    // Order: style, color, url, text
    // But each optional, so we detect by reserved sets. Quoted words are never keywords or URLs.
    const tokens = words.map(w => w.quoted ? null : w.value);
    let i = 0;

    let size = "";
    let style = "";
    let color = "";
    let url = "";
    let text = "";

    if (tokens[i]) {
      if (kind === "node") {
        if (NODE_SIZES.includes(tokens[i])) {
          size = tokens[i++];
        }
        if (tokens[i] && NODE_SHAPES.includes(tokens[i])) {
          style = tokens[i++]; // shape
        }
      } else if (kind === "edge") {
        if (NODE_SIZES.includes(tokens[i])) {
          size = tokens[i++];
        }
        if (tokens[i] && EDGE_STYLES.includes(tokens[i])) {
          style = tokens[i++]; // line style
        }
      }
    }

    if (tokens[i] && Object.prototype.hasOwnProperty.call(COLORS, tokens[i])) {
      color = tokens[i++];
    }

    if (tokens[i] && looksLikeUrlToken(tokens[i])) {
      url = normalizeUrl(tokens[i++]);
    }

    const textGiven = i < words.length;
    if (textGiven) {
      text = words.slice(i).map(w => w.value).join(" ");
    }

    const spans = Object.fromEntries(words.map((w,j)=>[j,{start:w.start,end:w.end}]));
    const textWords=words.slice(i);
    const rawText=textWords.length ? textWords.map((w,j)=> (j ? " ".repeat(Math.max(0,w.start-textWords[j-1].end)) : "")+w.raw).join("") : "";
    return { size, style, color, url, text, textGiven, spans, rawText, textSpan:textGiven?{start:words[i].start,end:words.at(-1).end}:null };
  }

  function parseSource(src) {
    const nodes = new Map(); // id -> {id, size, shape, color, url, text}
    const groups = new Map(), stack=[];
    const edges = [];        // {from,to, size,style,color,url,text, key}
    let background = "";

    const errors = [];
    const lines = src.split(/\r?\n/);

    function ensureNode(id) {
      if (!nodes.has(id)) {
        nodes.set(id, {
          id, group:stack.at(-1)??null,
          size: "normal",
          shape: "circle",
          color: "gray",
          url: "",
          text: "",
          sizeGiven: false,
          shapeGiven: false,
        });
      }
      return nodes.get(id);
    }

    for (let lineNo = 0; lineNo < lines.length; lineNo++) {
      const pieces = lexLine(lines[lineNo]);
      const words = pieces.filter(p => p.type === "word");
      const hasArrow = pieces.some(p => p.type === "arrow");
      if (!words.length && !hasArrow) continue;
      if(words.length===1 && words[0].raw==='}'){
        if(!stack.length)errors.push(`Line ${lineNo+1}: unexpected }`);else stack.pop();
        continue;
      }
      const opens=!hasArrow&&words.at(-1)?.raw==='{' && !words.at(-1).quoted;
      if(opens){words.pop();if(!words.length){errors.push(`Line ${lineNo+1}: group requires an id`);continue;}}

      if (!hasArrow && words.length === 1 && !words[0].quoted
          && Object.prototype.hasOwnProperty.call(COLORS, words[0].value)) {
        background = words[0].value;
        continue;
      }

      if (hasArrow) {
        // Edge line (possibly chain)
        const segs = [[]];
        for (const p of pieces) {
          if (p.type === "arrow") segs.push([]);
          else if (p.type === "word") segs[segs.length - 1].push(p);
        }
        const nonEmpty = segs.filter(s => s.length);
        if (nonEmpty.length < 2) {
          errors.push(`Line ${lineNo+1}: malformed edge line`);
          continue;
        }

        // Last segment may contain attrs after the last node id
        const lastWords = nonEmpty[nonEmpty.length - 1];

        const chainIds = [];
        for (let i = 0; i < nonEmpty.length - 1; i++) {
          const err = idError(nonEmpty[i][0], lineNo);
          if (err) {
            errors.push(err);
            continue;
          }
          chainIds.push(endpoint(nonEmpty[i][0]).value);
        }

        const lastErr = idError(lastWords[0], lineNo);
        if (lastErr) {
          errors.push(lastErr);
          continue;
        }
        chainIds.push(endpoint(lastWords[0]).value);

        const attrs = parseAttrs(lastWords.slice(1), "edge");
        // Apply to every edge in chain
        for (let i = 0; i < chainIds.length - 1; i++) {
          const from = chainIds[i];
          const to = chainIds[i + 1];
          ensureNode(from);
          ensureNode(to);

          edges.push({
            from, to, fromPort:endpoint(nonEmpty[i][0]).port, toPort:endpoint(nonEmpty[i+1][0]).port,
            line:lineNo+1, rawText:attrs.textSpan?lines[lineNo].slice(attrs.textSpan.start,attrs.textSpan.end):"", spans:attrs.spans,
            size: attrs.size || "normal",
            style: attrs.style || "solid",
            color: attrs.color || "gray",
            url: attrs.url || "",
            text: attrs.text || "",
            key: `${from}->${to}#${edges.length}` // allow duplicates
          });
        }
      } else {
        // Node line
        const err = idError(words[0], lineNo);
        if (err) {
          errors.push(err);
          continue;
        }
        const attrs = parseAttrs(words.slice(1), "node");
        const id=endpoint(words[0]).value;
        const n = ensureNode(id);
        if(opens){
          if(groups.has(id)){errors.push(`Line ${lineNo+1}: duplicate group "${id}"`);continue;}
          n.isGroup=true;groups.set(id,n);stack.push(id);
        }
        n.line=lineNo+1;n.spans=attrs.spans;
        if (attrs.size) { n.size = attrs.size; n.sizeGiven = true; }
        if (attrs.style) { n.shape = attrs.style; n.shapeGiven = true; }
        if (attrs.color) n.color = attrs.color;
        if (attrs.url) n.url = attrs.url;
        if (attrs.textGiven) {n.text = attrs.text;n.rawText=lines[lineNo].slice(attrs.textSpan.start,attrs.textSpan.end);}
        // Without text we keep prior text, so a later bare "id" line won't wipe it; "" clears it explicitly.
      }
    }

    // Prune accidental empty duplicates? We'll just keep as parsed.

    if(stack.length)errors.push(`Unclosed group "${stack.at(-1)}"`);
    return { nodes, edges, groups, background, errors };
  }


export { NODE_SIZES, NODE_SHAPES, EDGE_STYLES, COLORS, lexLine, parseAttrs, parseSource, normalizeUrl };
