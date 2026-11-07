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
npx playwright install chromium
npm test
```

Drafts are saved locally and recovered only through an explicit Resume action.
Recovered drafts are marked unverified; links never automatically restore them.
The editor stores no credentials, execution commands, or relay configuration.
Explicit links are checked before enabling local execution commands; opening
one never runs a pipeline. CID loads verify length and SHA-512 before decoding.
Bash must be reviewed in the local-run dialog before copying its command.

`src/modl-render.js` embeds modl's standalone `renderDiagram` from pinned,
byte-identical vendor files. Host callbacks provide dragging, panning and zoom;
links use safe HTTP(S) navigation. The Fragment Kit shell supplies mobile tabs,
sharing, QR, draft recovery and verified offline caching. The site builder
includes only public editor assets and generates the offline hash manifest.

The Apptron target remains disabled until the required overlay's runtime
release passes its real VM boot check. HashBin publishing and canonical-origin
migration still require app registration. See `../EDITOR_PLAN.md` for status.
