# Local editor

Build with `python3 site/build.py`, then serve `site/_site/` over HTTP and open
`/editor/`. The source checkout does not duplicate `gripeline.py`; the site
builder copies the exact compiler and generates the gallery.

Runtime dependencies are checked in and pinned by SHA-256 in
`vendor/vendor.lock.json`. Run `python3 scripts/vendor.py` to verify them or add
`--fetch` to restore missing files. Pyodide 0.27.7 is self-hosted and loaded in a
module worker; Viz 3.12.0 loads only for dot rendering. No Python package
installation is needed. Asset notices live next to the vendored files. The vendor directory is about
15 MiB before HTTP compression.

For optional browser tests (Node development tools only):

```sh
python3 site/build.py
cd web
npm ci
npx playwright install chromium firefox webkit
npm test
```

Drafts are saved locally and recovered only through an explicit Resume action.
Recovered drafts are marked unverified; links never automatically restore them.
The editor stores no credentials, execution commands, or relay configuration.
Explicit links are checked before enabling local execution commands; opening
one never runs a pipeline. CID loads verify length and SHA-512 before decoding, reject documents over
1 MiB before fetching, and bound streamed responses by the declared length.
Bash must be reviewed in the local-run dialog before copying its command.

`src/modl-render.js` embeds modl's standalone `renderDiagram` from pinned,
byte-identical vendor files. Host callbacks provide dragging, panning and zoom;
links use safe HTTP(S) navigation. The Fragment Kit shell supplies full-pane and split views,
sharing, QR, draft recovery and verified offline caching. The site builder
includes only public editor assets and generates the offline hash manifest.

The Apptron runtime has passed the real VM boot check and all six portable
gallery executions. The editor verifies the deployed runtime lock, manifest
and overlay before enabling handoff, and embeds the exact checked compiler. HashBin publishing uses the pinned Fragment Kit store and panel with in-tab review
and verified source restoration on return, with source-only
diagram envelopes and typed Apptron snapshots. The store never persists credentials.
Only the canonical origin may publish; its public client ID must be registered
for `https://gripeline.hashbin.page/`. The issued public client is
`app_dc8bf51a-ebee-4ef0-879e-1cccbfc1a01b`. A missing registration keeps Save disabled.
The shared recovery adapter accepts only source, finite positions and draft history.
It retains the old copy and rejects credential or execution settings. See `../EDITOR_PLAN.md` for status.


Optional live VM acceptance (requires network and downloads the real runtime):

```sh
node tests/live-apptron.mjs
```

This opens an inert snapshot at Apptron's canonical origin, presses Run explicitly,
and verifies the exact embedded compiler and a non-inline CID store produce the
expected output without enabling VM networking.

Prepared interface update: adopts Fragment Kit 0.3.5 for compact controls, readable buttons and a scrollable More menu with a fixed Close control. The release and deployment are pending; the local compiler and execution isolation are unchanged.
