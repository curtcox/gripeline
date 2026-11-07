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

The editor stores no drafts, credentials, settings, or relay configuration.
Explicit links are checked before enabling local execution commands; opening
one never runs a pipeline. CID loads verify length and SHA-512 before decoding.
Bash must be reviewed in the local-run dialog before copying its command.

`src/modl-render.js` is a temporary preview adapter over modl's pinned parser
and layout helpers; it is not the extracted upstream renderer. It does not yet
support all of modl's image, style, zoom, and pan behavior. Apptron snapshot
helpers are tested but the Run target stays disabled until the required
upstream overlay has a verified release. HashBin publishing, offline caching,
QR and Fragment Kit shell/draft integration are still pending. See
`../EDITOR_PLAN.md` for the complete phase status.
