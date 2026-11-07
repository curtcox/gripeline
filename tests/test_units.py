#!/usr/bin/env python3
"""Unit tests for gripeline pieces that .case fixtures can't express:
--annotate output, modl id quoting, language detection, share links, line
splitting, and parity with modl's real parser over modl's own example corpus
plus a set of lexer edge cases.

    python3 tests/test_units.py                 # parity tests skipped
    MODL_REPO=../modl python3 tests/test_units.py

The parity tests need MODL_REPO (a curtcox/modl checkout) and node; without
them they are skipped, not failed. Standard library only.
"""
from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
import gripeline as gl  # noqa: E402

MODL_REPO = os.environ.get("MODL_REPO")
NODE_BIN = shutil.which("node")
HAVE_MODL = bool(MODL_REPO and NODE_BIN and (Path(MODL_REPO) / "js" / "editor.js").is_file())
needs_modl = unittest.skipUnless(HAVE_MODL, "set MODL_REPO to a curtcox/modl checkout (and install node)")


def modl_parse_many(srcs: dict[str, str]) -> dict:
    """Parse each source with modl's own parser (tests/modl_parse.cjs)."""
    p = subprocess.run([NODE_BIN, str(ROOT / "modl_parse.cjs"), MODL_REPO],
                       input=json.dumps(srcs), capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = gl.main(["gripeline", *args])
    return code, out.getvalue(), err.getvalue()


def words(line: str) -> list[gl.ModlPiece]:
    return [p for p in gl._lex_modl_line(line) if p.kind == "word"]


# --------------------------------------------------------------------------
# Lexer edge cases: each must parse the same in gripeline and in modl.
# --------------------------------------------------------------------------
TRICKY = {
    "quoted bracket id": '"a[err]" square echo hi\n"a[err]" -> b',
    "native ports": 'a["2>"] -> b[3] double "hi"',
    "native nested groups": 'g {\nh {\na square echo hi\n}\n}',
    "native shapes": 'a note in\nb cylinder out\nc parallelogram stream\nd stadium stop\ne subroutine f\nf oval end',
    "unicode spans": 'a -> b "☕"  "hello"',

    "single-quoted hash": "a square echo 'x # y'",
    "double-quoted hash": 'a square echo "x # y"',
    "apostrophe then comment": "a square echo it's # comment",
    "mid-word quote is plain": 'a square git log --format="%h #%s"',
    "unmatched quote is plain": 'a square echo 5" # inches',
    "quoted arrow is text": "a square grep -e '->'\nb square cat\na -> b",
    "arrow inside a word": "a->b",
    "empty segment": "a -> -> b",
    "chain with extra words": "a x y -> b z -> c dotted red hi",
    "quoted id keeps whitespace": '"a  b" square x\n"a  b" -> c',
    "single-quoted id with double quote": "'a\"b' square x",
    "adjacent strings form one word": "a square \"x\"'y'z",
    "dash-leading id": "-x square cat",
    "edge slots in order": "a -> b big dashed red /path text",
    "edge slots out of order": "a -> b red dashed text",
    "node slots in order": "a tiny hex red www.example.com hi",
    "node slots out of order": "a red square hi",
    "background color": "red\na square x",
    "quoted color is a node": '"red"',
    "color then shape is a node": "red square",
    "tab separated": "a\tsquare\techo\thi",
    "nbsp is whitespace": "a square echo",
    "hash mid-word": "a square echo a#b",
    "comment only": "  # just a comment",
    "pragma comment": "a square echo hi   #gl async=true",
    "crlf lines": "a square echo\r\nb square cat\r\na -> b\r\n",
    "text cleared by empty string": "a square x\na \"\"",
    "text kept by bare redefinition": "a square x\na big",
    "single-quote empty text": "a square ''",
    "url only": "a /usr/bin/wc",
}

# modl reports these as errors; gripeline must refuse them too (D5).
TRICKY_ERRORS = {
    "dot in id": "not.ok square",
    "empty quoted id": '"" square',
    "trailing arrow": "a ->",
    "leading arrow": "-> b",
    "hash in id": "a#b square",
    "bad id mid-chain": "a -> b.c -> d",
}


def modl_corpus() -> dict[str, str]:
    """modl's own examples: the gallery, the legacy golden example, and every
    `<modl-link src>` and `<pre class="modl">` snippet in docs-src."""
    repo = Path(MODL_REPO)
    corpus: dict[str, str] = {}
    for js in ("js/gallery-catalog.js", "js/legacy-examples.js"):
        text = (repo / js).read_text()
        for k, m in enumerate(re.finditer(r'"src":\s*("(?:[^"\\]|\\.)*")', text)):
            corpus[f"{js}#{k}"] = json.loads(m.group(1))
    for page in sorted((repo / "docs-src").glob("*.html")):
        text = page.read_text()
        for k, m in enumerate(re.finditer(r'<modl-link src="([^"]*)"', text)):
            corpus[f"{page.name} link#{k}"] = html.unescape(m.group(1)).replace("\\n", "\n")
        for k, m in enumerate(re.finditer(r'<pre class="modl"><code>(.*?)</code></pre>', text, re.S)):
            corpus[f"{page.name} pre#{k}"] = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
    return corpus


class ModlParity(unittest.TestCase):
    """gripeline's modl parser vs. modl's own parseSource."""

    def assert_parity(self, srcs: dict[str, str]):
        import run  # tests/run.py: modl_parity_diffs
        js = modl_parse_many(srcs)
        for name, src in srcs.items():
            with self.subTest(name):
                r = js[name]
                if r["errors"]:
                    with self.assertRaises(gl.GripError, msg=f"modl errors: {r['errors']}"):
                        gl.parse_modl(src)
                    continue
                self.assertEqual(run.modl_parity_diffs(src, r), [])

    @needs_modl
    def test_tricky_lines(self):
        self.assert_parity(TRICKY)

    @needs_modl
    def test_tricky_errors_are_errors_in_both(self):
        js = modl_parse_many(TRICKY_ERRORS)
        for name, src in TRICKY_ERRORS.items():
            with self.subTest(name):
                self.assertTrue(js[name]["errors"], "modl accepts this; move it to TRICKY")
                with self.assertRaises(gl.GripError):
                    gl.parse_modl(src)

    @needs_modl
    def test_modl_example_corpus(self):
        corpus = modl_corpus()
        self.assertGreater(len(corpus), 20, "corpus extraction found too few examples")
        self.assert_parity(corpus)

    @needs_modl
    def test_vocabulary_matches_modl(self):
        src = (Path(MODL_REPO) / "js" / "parse.js").read_text()

        def js_list(name):
            m = re.search(rf"const {name} = \[([^\]]*)\]", src)
            return set(re.findall(r'"([^"]+)"', m.group(1)))

        self.assertEqual(gl.MODL_SIZES, js_list("NODE_SIZES"))
        self.assertEqual(gl.MODL_SHAPES, js_list("NODE_SHAPES"))
        self.assertEqual(gl.MODL_LINE_STYLES, js_list("EDGE_STYLES"))
        colors = re.search(r"const COLORS = \{(.*?)\};", src, re.S).group(1)
        self.assertEqual(gl.MODL_COLORS, set(re.findall(r"^\s*(\w+):", colors, re.M)))


class FormatModlId(unittest.TestCase):
    IDS = ["a", "a-b:c_1", "-x", "a b", "a  b", 'a"b', "a'b", 'a"b\'c', '"', "'",
           "x->y", "#x", "a # b", "red", "square", "not.ok"]

    def test_round_trips_through_the_lexer(self):
        for nid in self.IDS:
            with self.subTest(nid=nid):
                ws = words(gl._format_modl_id(nid))
                self.assertEqual(len(ws), 1)
                self.assertEqual(ws[0].val, nid)

    def test_parses_back_as_the_same_node(self):
        for nid in self.IDS:
            with self.subTest(nid=nid):
                m = gl.parse_modl(f"{gl._format_modl_id(nid)} big")
                self.assertEqual(list(m.nodes), [nid])

    @needs_modl
    def test_modl_reads_the_same_id(self):
        srcs = {nid: f"{gl._format_modl_id(nid)} big" for nid in self.IDS}
        js = modl_parse_many(srcs)
        for nid in self.IDS:
            with self.subTest(nid=nid):
                self.assertEqual(js[nid]["errors"], [])
                self.assertEqual(list(js[nid]["nodes"]), [nid])


class Annotate(unittest.TestCase):
    SRC = (
        "m square make\n"
        "i square make install\n"
        "m -> i dashed oops\n"                # E11, style only
        "z square echo\n"
        "z -> i big dashed blue nope\n"       # E11, size + style + color
        "q diamond\n"
        "#gl node q name=my-var\n"            # E12
        "q -> z\n"
    )

    def annotate(self) -> str:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.modl")
            Path(path).write_text(self.SRC)
            code, _out, err = run_cli("check", "--annotate", path)
            self.assertEqual(code, 65, err)
            return Path(d, "a.annotated.modl").read_text()

    def test_red_goes_after_size_and_style(self):
        lines = self.annotate().splitlines()
        self.assertIn("m -> i dashed red oops", lines)
        self.assertIn("z -> i big dashed red nope", lines)   # existing color replaced

    def test_offending_nodes_and_messages_appended(self):
        lines = self.annotate().splitlines()
        self.assertIn("q red", lines)
        self.assertTrue(any(l.startswith("# [E11]") for l in lines))
        self.assertTrue(any(l.startswith("# [E12]") for l in lines))

    def test_annotated_file_keeps_the_original_meaning(self):
        # Styles, shapes and edges are unchanged; only colors and comments differ.
        before, after = gl.parse_modl(self.SRC), gl.parse_modl(self.annotate())
        self.assertEqual([(e.tail, e.head, e.attrs.get("style"), e.attrs.get("label")) for e in before.edges],
                         [(e.tail, e.head, e.attrs.get("style"), e.attrs.get("label")) for e in after.edges])
        self.assertEqual({k: n.attrs.get("shape") for k, n in before.nodes.items()},
                         {k: n.attrs.get("shape") for k, n in after.nodes.items()})

    @needs_modl
    def test_modl_draws_the_annotated_edges_with_their_styles(self):
        import run
        text = self.annotate()
        js = modl_parse_many({"a": text})["a"]
        self.assertEqual(run.modl_parity_diffs(text, js), [])
        styles = {(e["from"], e["to"]): (e["style"], e["text"]) for e in js["edges"]}
        self.assertEqual(styles[("m", "i")], ("dashed", "oops"))
        self.assertEqual(styles[("z", "i")], ("dashed", "nope"))

    def test_loop_without_header_marks_the_group(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.modl")
            Path(path).write_text("#gl begin x role=for\na square echo\n#gl end\n")
            code, _out, _err = run_cli("check", "--annotate", path)
            self.assertEqual(code, 65)
            self.assertIn("x red", Path(d, "l.annotated.modl").read_text().splitlines())


class DetectLang(unittest.TestCase):
    def test_extension_and_override(self):
        self.assertEqual(gl.detect_lang("x.modl", "digraph {}"), "modl")
        self.assertEqual(gl.detect_lang("x.gv", "a -> b"), "dot")
        self.assertEqual(gl.detect_lang("x.modl", "a -> b", lang="dot"), "dot")
        with self.assertRaises(gl.GripError):
            gl.detect_lang(None, "", lang="mermaid")

    def test_sniffing(self):
        dot = ["digraph { a }", "graph{a}", "strict digraph G { a }", 'digraph "my g" {',
               "// c\ndigraph {"]
        modl = ["graph square echo hi", "digraph -> b", "strict square x", "a -> b",
                "digraph", ""]
        for src in dot:
            with self.subTest(src=src):
                self.assertEqual(gl.detect_lang(None, src), "dot")
        for src in modl:
            with self.subTest(src=src):
                self.assertEqual(gl.detect_lang(None, src), "modl")

    def test_share_link_sniffs_language(self):
        self.assertEqual(gl.detect_lang("https://modl.hashbin.page/#h1=x", "digraph {"), "dot")


class ShareLinks(unittest.TestCase):
    def test_round_trip(self):
        src = 'a square echo "hé" # ünï\nb -> a dashed &&\n'
        self.assertEqual(gl.decode_share_link(gl.encode_share_link(src)), src)

    def test_run_from_share_link(self):
        url = gl.encode_share_link("a square echo hi\nb square wc -c\na -> b\n")
        code, out, err = run_cli("build", url)
        self.assertEqual(code, 0, err)
        self.assertIn("echo hi | wc -c", out)

    def test_malformed_cid_links_are_refused(self):
        with self.assertRaisesRegex(gl.GripError, "t256"):
            gl.decode_share_link("https://modl.hashbin.page/#256t.abc")

    def test_bad_payload(self):
        with self.assertRaises(gl.GripError):
            gl.decode_share_link("https://modl.hashbin.page/#h1=!!!")


class LineSplitting(unittest.TestCase):
    def test_crlf_and_form_feed(self):
        m = gl.parse_modl("a square echo hi\r\nb square cat\r\na -> b\r\n")
        self.assertEqual([(e.tail, e.head) for e in m.edges], [("a", "b")])
        self.assertEqual(m.nodes["a"].attrs["label"], "echo hi")
        # modl splits only on \r?\n: a form feed is whitespace inside one line.
        m = gl.parse_modl("a square echo hi\x0cb square cat\n")
        self.assertEqual(list(m.nodes), ["a"])

    def test_line_numbers_count_every_line(self):
        with self.assertRaisesRegex(gl.GripError, r"^Line 4: invalid node id"):
            gl.parse_modl("# c\n\na square x\nbad.id\n")


class EdgeScoping(unittest.TestCase):
    def bash(self, src: str, lang: str = "modl") -> str:
        e = gl.Engine(gl.parse_source(src, lang))
        self.assertEqual(e.run_checks(), [])
        return e.transpile()

    def test_nested_loops_lift_to_the_right_level(self):
        out = self.bash(
            "#gl begin outer loop=\"for a in 1 2\"\n"
            "#gl begin inner loop=\"for b in x y\"\n"
            "p square echo $a $b\n"
            "#gl end\n"
            "q square echo done $a\n"
            "#gl end\n"
            "p -> q dashed ;\n"                # inner member -> outer member
        )
        self.assertIn("for b in x y; do\necho $a $b\ndone\necho done $a", out)

    def test_sibling_groups(self):
        out = self.bash(
            "#gl begin g1 role=subshell\nx square echo one\n#gl end\n"
            "#gl begin g2 role=subshell\ny square cat\n#gl end\n"
            "x -> y\n"                          # member of g1 -> member of g2: g1 | g2
        )
        self.assertIn("(\necho one\n) | (\ncat\n)", out)



class ReviewRegressions(unittest.TestCase):
    def engine(self, src):
        e = gl.Engine(gl.parse_modl(src))
        e.run_checks()
        return e

    def test_duplicate_block(self):
        e = self.engine('#gl begin g role=subshell\na square echo 1\n#gl end\n#gl begin g role=group\nb square echo 2\n#gl end')
        self.assertTrue(any(c == 'E10' and 'duplicate block id "g" (first opened on line 1)' in m for c, m in e.problems))

    def test_ignored_chain_words(self):
        e = self.engine('a square cat x -> b square wc -l')
        self.assertTrue(any('"square cat x" after "a" is ignored' in w for w in e.warnings))

    def test_quoted_control(self):
        e = self.engine('a square true\nb square echo ok\na -> b dashed "&&"')
        self.assertEqual(e.problems, [])
        self.assertIn('true && echo ok', e.transpile())
        e = self.engine('a -> b "&&"')
        self.assertTrue(any('solid edge' in w for w in e.warnings))

    def test_missing_lints(self):
        for comment in ('# gl mapping=typed', '#GL mapping=typed', '#gl:mapping=typed', '#glmapping=typed'):
            self.assertTrue(any('looks like a #gl pragma' in w for w in self.engine(comment).warnings))
        self.assertTrue(any('non-ASCII whitespace' in w for w in self.engine('a square echo\u00a0hi').warnings))
        self.assertFalse(any('non-ASCII whitespace' in w for w in self.engine('a square echo "a\u00a0b"').warnings))
        e = self.engine('g display text\n#gl begin g role=group\na square true\n#gl end')
        self.assertTrue(any('display-only' in w for w in e.warnings))

    def test_cycle_names_and_annotation(self):
        src = '#gl mapping=dataflow\na -> b sort\nb -> c cat\nc -> a uniq\n'
        e = self.engine(src)
        self.assertTrue(any(c == 'E04' for c, m in e.problems))
        self.assertNotIn('__e', str(e.problems))
        self.assertTrue({2, 3, 4} <= e.offending_edges)
        self.assertFalse(e.offending_nodes - set(e.model.nodes))

    def test_full_cycle(self):
        e = self.engine('a -> b -> c -> a')
        self.assertTrue(any('a -> b -> c -> a' in m for c, m in e.problems))

    def test_port_producer_with_upstream_pipe(self):
        e = self.engine('a square gen\nc square cat\nb square consume\na -> c\nc -> b #gl to=3')
        self.assertEqual(e.problems, [])
        self.assertIn('consume 3< <(gen | cat)', e.transpile())

    def test_interdependent_port_routes_are_diagnostic(self):
        e = self.engine('a square gen\nb square consume\na -> b #gl from=2\na -> b #gl to=3')
        self.assertTrue(any(c == 'E09' for c,m in e.problems))

    def test_fd_zero_redirect_is_not_stdout(self):
        e = gl.Engine(gl.parse_dot('digraph { p [shape=box,label="echo ok"]; f [shape=note]; p:0 -> f; p:2 -> p:1; }'))
        self.assertEqual(e.run_checks(), [])

    def test_review_link_keeps_failed_stdout_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'in.modl'
            path.write_text('a hex in\nb hex out\na -> b\n')
            code, out, err = run_cli('check', '--annotate', '--link', str(path))
            self.assertEqual(code, 65)
            self.assertEqual(out, '')
            link = next(line for line in err.splitlines() if line.startswith('https://'))
            self.assertIn('&mark=', link)
            self.assertEqual(gl.decode_share_link(link), path.read_text())
            self.assertFalse((Path(d)/'in.annotated.modl').exists())

    def test_annotation_line_endings(self):
        src = 'x square "a\fb"\r\ny hex g\r\nz hex h\r\ny -> z\r\n'
        with tempfile.TemporaryDirectory() as d:
            path, out = Path(d)/'in.modl', Path(d)/'out.modl'
            path.write_bytes(src.encode())
            e = gl.build_engine(str(path))
            e.run_checks()
            gl.annotate(e, str(path), e.problems, str(out))
            result = out.read_bytes().decode()
            self.assertTrue(result.startswith('x square "a\fb"\r\ny hex g\r\nz hex h\r\ny -> z red\r\n'))

class EditorPrerequisites(unittest.TestCase):
    def test_api_fixtures_match_cli(self):
        import run as harness
        for path in sorted((ROOT / 'cases').rglob('*.case')):
            case = harness.parse_case(path)
            for lang in ('dot', 'modl'):
                src = getattr(case, lang, '')
                if not src:
                    continue
                with self.subTest(path=path.name, lang=lang):
                    result = gl.gripeline_api(src, lang)
                    with tempfile.TemporaryDirectory() as directory:
                        source = Path(directory) / ('input.' + lang)
                        source.write_text(src)
                        code, out, err = run_cli('build', str(source))
                    self.assertEqual(result['bash'], out)
                    self.assertEqual(bool(result['problems']), code != 0)

    def test_stdin(self):
        from unittest.mock import patch
        with patch('sys.stdin', io.StringIO('a square echo hi')):
            code, out, err = run_cli('build', '-')
        self.assertEqual(code, 0, err)
        self.assertIn('echo hi', out)

    def test_cid_input(self):
        from unittest.mock import patch
        payload = json.dumps({'format':'hashbin-diagram', 'version':1,
                              'src':'a square echo hi', 'pos':{}})
        with patch('gripeline.shutil.which', return_value='/bin/t256'), patch(
            'gripeline.subprocess.run', return_value=subprocess.CompletedProcess([], 0, payload, '')
        ) as run:
            self.assertEqual(gl.read_input_source('t256:AAAAAAAA'), 'a square echo hi')
            self.assertEqual(run.call_args.args[0], ['/bin/t256', 'load', 'AAAAAAAA'])

    def test_cid_validation(self):
        self.assertEqual(gl.cid_reference('t256:AAAAAAACaGk.txt'), 'AAAAAAACaGk')
        for value in ('AAAAAAACaGl', 'AAAAAAAA=', 'AAAAAAAB', 't256:abc', 'AAAAAAAA.bad-'):
            with self.subTest(value=value), self.assertRaises(gl.GripError):
                gl.cid_reference(value)

    def test_bash_locator(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'GRIPELINE_BASH':'C:\\Windows\\System32\\bash.exe'}):
            with self.assertRaisesRegex(gl.GripError, 'WSL'):
                gl.locate_bash()

    def test_cid_run_with_stub_t256(self):
        if os.name == 'nt':
            self.skipTest('POSIX executable stub; Windows CID resolution is covered by the mocked test')
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / 't256'
            stub.write_text("#!/bin/sh\nprintf 'a square printf hello\\n'\n")
            stub.chmod(0o755)
            from unittest.mock import patch
            with patch.dict(os.environ, {'PATH': directory + os.pathsep + os.environ['PATH']}):
                result = subprocess.run([sys.executable, str(ROOT.parent / 'gripeline.py'), 'run', 't256:AAAAAAAA'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'hello')

    def test_missing_requirements_report_all(self):
        src = '#gl requires gripeline_missing_one gripeline_missing_two\na square printf should-not-run'
        result = gl.gripeline_api(src)
        process = subprocess.run([gl.locate_bash(), '-c', result['bash']], capture_output=True, text=True)
        self.assertEqual(process.returncode, 127)
        self.assertEqual(process.stdout, '')
        self.assertIn('gripeline_missing_one gripeline_missing_two', process.stderr)

    def test_portable_advice_is_not_an_error(self):
        result = gl.gripeline_api('a square exotic-tool', portable=True)
        self.assertEqual(result['problems'], [])
        self.assertTrue(result['warnings'])

    def test_api_does_no_io(self):
        from unittest.mock import patch
        with patch('builtins.open', side_effect=AssertionError('I/O')), patch(
            'gripeline.subprocess.run', side_effect=AssertionError('process')):
            result = gl.gripeline_api('digraph { a [label="echo hi"]; }', None)
        self.assertEqual(result['problems'], [])
        self.assertIn('echo hi', result['bash'])

if __name__ == "__main__":
    unittest.main(verbosity=2)
