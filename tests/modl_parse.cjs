// Run modl's own parser (from a curtcox/modl checkout) on modl sources and
// print what it parsed as JSON. Used by tests/run.py for the modl-valid
// parity check, so gripeline's Python port is compared with the real thing.
//
//   node tests/modl_parse.cjs <modl-repo>  < {"name": "<modl source>", ...}
//   -> {"name": {nodes: {id: {shape, text}}, edges: [{from, to, style, text}],
//                background, errors}, ...}
//
// It slices the vocabulary block and the parsing block out of js/editor.js,
// the same boundaries modl's scripts/check.mjs hash-locks, and evaluates them
// in a fresh VM context. Nothing in the modl repo is modified.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const repo = process.argv[2];
const src = fs.readFileSync(path.join(repo, "js", "editor.js"), "utf8");

function slice(startMarker, endMarker) {
  const i = src.indexOf(startMarker);
  const j = src.indexOf(endMarker, i);
  if (i < 0 || j < 0) {
    console.error(`modl_parse: marker not found in js/editor.js: ${i < 0 ? startMarker : endMarker}`);
    process.exit(3);
  }
  return src.slice(i, j);
}

const vocab = slice("  const NODE_SIZES", "  // -----------------------------\n  // UI wiring");
const parser = slice("  // -----------------------------\n  // Parsing DSL",
                     "  // -----------------------------\n  // Layout + Rendering");

const ctx = {};
vm.createContext(ctx);
vm.runInContext(`${vocab}\n${parser}\n;globalThis.parseSource = parseSource;`, ctx);

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [name, text] of Object.entries(input)) {
  const r = ctx.parseSource(text);
  out[name] = {
    nodes: Object.fromEntries([...r.nodes].map(([id, n]) => [id, { shape: n.shape, text: n.text }])),
    edges: r.edges.map(e => ({ from: e.from, to: e.to, style: e.style, text: e.text })),
    background: r.background,
    errors: r.errors,
  };
}
process.stdout.write(JSON.stringify(out));
