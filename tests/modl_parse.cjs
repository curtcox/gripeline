// Run modl's own parser (from a curtcox/modl checkout) on modl sources and
// print what it parsed as JSON. Used by tests/run.py for the modl-valid
// parity check, so gripeline's Python port is compared with the real thing.
//
//   node tests/modl_parse.cjs <modl-repo>  < {"name": "<modl source>", ...}
//   -> {"name": {nodes: {id: {shape, text}}, edges: [{from, to, style, text}],
//                background, errors}, ...}
//
// Imports modl’s standalone parser without evaluating editor UI code.
"use strict";
const fs = require("fs");
const path = require("path");

const repo = process.argv[2];
const {pathToFileURL} = require("url");
(async () => {
const {parseSource} = await import(pathToFileURL(path.join(repo, "js", "parse.js")).href);
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [name, text] of Object.entries(input)) {
  const r = parseSource(text);
  out[name] = {
    nodes: Object.fromEntries([...r.nodes].map(([id, n]) => [id, { shape: n.shape, text: n.text }])),
    edges: r.edges.map(e => ({ from: e.from, to: e.to, style: e.style, text: e.text, fromPort:e.fromPort, toPort:e.toPort, rawText:e.rawText })),
    background: r.background,
    errors: r.errors,
  };
}
process.stdout.write(JSON.stringify(out));

})().catch(error => { console.error(error); process.exitCode=1; });
