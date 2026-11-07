# gripeline site generator

[`build.py`](build.py) builds the published [GitHub Pages](https://curtcox.github.io/gripeline/)
site from the repository sources. It is **Python 3 standard library only**; the
sole external dependency is the Graphviz `dot` CLI, used to render diagrams to
SVG (without it, diagrams degrade to a "source only" note).

```bash
python3 site/build.py [output-dir]   # default output: site/_site/
```

## What it produces

| page                  | content |
|-----------------------|---------|
| `index.html`          | landing page (the README) + a link to the spec and a test-result summary |
| `spec.html`           | [`SPEC.md`](../SPEC.md) rendered to HTML; every ```` ```dot ```` block is shown as **source + rendered SVG** |
| `tests.html`          | conformance test index: one row per case with overall and per-check pass/fail |
| `tests/<name>.html`   | per-test page: source dot, rendered diagram, expected bash/error, the transpiler's actual output, and the per-check breakdown |

## How the test results are produced

`build.py` imports the conformance harness ([`tests/run.py`](../tests/run.py))
and runs its existing checks (`dot-valid`, `lint`, `transpile`, `run`) against
the transpiler named by the `GRIPELINE` environment variable. If `GRIPELINE` is
unset it defaults to `python3 <repo>/gripeline.py`, so a bare
`python3 site/build.py` evaluates the bundled transpiler.

## CI

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) installs
Graphviz, runs this script, and deploys the output to GitHub Pages on every push
to `main`. The build always succeeds and publishes whatever the current pass/fail
state is — failing conformance cases are shown on the site, not hidden.

> **Enabling Pages:** in the repository settings, set **Settings → Pages →
> Build and deployment → Source** to **GitHub Actions** (a one-time step).

The current modl parity checks import `js/parse.js` from the modl checkout.
Use the companion modl changes from MODL_REVIEW_PLAN.md when building locally.

The build copies public files from `web/` and the current `gripeline.py` to `_site/editor/`
and generates `editor/gallery.json` from every fixture source. Browser runtime
assets are checked in under `web/vendor/`; run `python3 scripts/vendor.py`
before building to verify the lock. `python3 scripts/vendor.py --fetch` restores
missing assets and rejects hash mismatches. Tests, dependency installations and
browser traces are excluded; an offline manifest pins every deployed editor asset. No browser dependency installation
is needed by `make check` or the site builder.


The editor's canonical dedicated host is prepared at `https://gripeline.hashbin.page/`.
HashBin's owned-app workflow stages only `site/_site/editor/` assets named by the
compiler-generated offline manifest. The Pages spec and conformance pages retain
their editor links. Public client registration controls canonical publishing; the
shared Pages editor never publishes or stores HashBin credentials.
