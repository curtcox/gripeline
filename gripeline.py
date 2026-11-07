#!/usr/bin/env python3
"""gripeline — transpile a Graphviz `dot` or `modl` file into a bash script.

See SPEC.md (Draft 0.4). The emitted bash is the normative meaning of a graph.

Stages:  parse -> extract/resolve roles -> static check (§9) -> transpile (§§4-8).

CLI:
    gripeline build <file>         print transpiled bash to stdout
    gripeline run   <file>         transpile then exec under bash; propagate status
    gripeline check <file>         run only the §9 static check; exit 0 or 65
        --lang=dot|modl            override language detection
        --annotate[=out]           also write a diagnostic-annotated copy
        --strict                   ordering ambiguity is an error
        --infer-style              also read recommended visual conventions (off)
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field


# ==========================================================================
# Tokenizer (dot)
# ==========================================================================
class Tok:
    def __init__(self, kind, val):
        self.kind = kind
        self.val = val

    def __repr__(self):
        return f"Tok({self.kind},{self.val!r})"


def tokenize(s: str):
    toks = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "#":
            while i < n and s[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            while i < n and s[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            i += 2
            while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n:
                if s[j] == "\\" and j + 1 < n:
                    nxt = s[j + 1]
                    if nxt == '"':
                        buf.append('"')
                        j += 2
                        continue
                    if nxt == "\\":
                        buf.append("\\")
                        j += 2
                        continue
                    buf.append("\\")
                    buf.append(nxt)
                    j += 2
                    continue
                if s[j] == '"':
                    break
                buf.append(s[j])
                j += 1
            toks.append(Tok("STR", "".join(buf)))
            i = j + 1
            continue
        if c in "{}[]=;,:":
            toks.append(Tok(c, c))
            i += 1
            continue
        if c == "-" and i + 1 < n and s[i + 1] == ">":
            toks.append(Tok("EDGE", "->"))
            i += 2
            continue
        if c == "-" and i + 1 < n and s[i + 1] == "-":
            toks.append(Tok("EDGE", "--"))
            i += 2
            continue
        if c.isalnum() or c in "_.+":
            j = i
            while j < n and (s[j].isalnum() or s[j] in "_.+"):
                j += 1
            toks.append(Tok("ID", s[i:j]))
            i = j
            continue
        # unknown char -> skip
        i += 1
    toks.append(Tok("EOF", None))
    return toks


# ==========================================================================
# AST / model
# ==========================================================================
@dataclass
class Node:
    id: str
    attrs: dict = field(default_factory=dict)
    cluster: str | None = None  # innermost enclosing cluster id (raw)
    order: int = 0
    role: str = "program"
    extra_suffix: list = field(default_factory=list)  # synthetic redirects (dataflow)
    pos: int | None = None  # source position (dot: token offset; modl: line number)


@dataclass
class Edge:
    tail: str
    tail_port: str | None
    head: str
    head_port: str | None
    attrs: dict = field(default_factory=dict)
    cluster: str | None = None
    order: int = 0
    pos: int | None = None  # source position (dot: token offset; modl: line number)


@dataclass
class Cluster:
    id: str
    attrs: dict = field(default_factory=dict)
    parent: str | None = None
    order: int = 0
    pos: int | None = None


RESERVED_SHAPE = {"box": "program", "note": "file", "cds": "stream"}

# modl vocabulary — must match modl's js/editor.js (NODE_SIZES, NODE_SHAPES,
# EDGE_STYLES, COLORS) exactly; tests/run.py cross-checks against it.
MODL_SHAPES = {"none", "circle", "square", "diamond", "triangle", "hex"}
MODL_SIZES = {"tiny", "small", "normal", "big", "bigger", "huge"}
MODL_LINE_STYLES = {"solid", "dashed", "dotted", "bold"}
MODL_COLORS = {
    "gray", "black", "white", "red", "orange", "yellow",
    "green", "teal", "blue", "purple", "pink", "brown",
}
MODL_NODE_LABEL_MAX = 22
MODL_EDGE_LABEL_MAX = 28
MODL_ROLE_SHAPES = {
    "square": "program",
    "hex": "file",
    "triangle": "stream",
    "diamond": "value",
}
MODL_STYLE_KINDS = {
    "solid": "data",
    "bold": "data",
    "dotted": "data",
    "dashed": "control",
}

VALID_NODE_ROLES = {
    "program", "file", "stream", "value", "op", "coproc",
    "for", "while", "until", "if", "function", "subshell", "group",
}
VALID_CLUSTER_ROLES = {"subshell", "group", "function", "for", "while", "until"}
VALID_EDGE_KINDS = {"pipe", "seq", "and", "or", "redirect"}
VALID_MAPPINGS = {"commands", "dataflow", "typed"}
VALID_SHELLS = {"bash"}

_VALID_SHELL_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VALID_MODL_ID = re.compile(r"^[A-Za-z0-9_:\-]+$")  # modl's isValidId


@dataclass
class Model:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    clusters: dict[str, Cluster] = field(default_factory=dict)
    graph_attrs: dict = field(default_factory=dict)
    directed: bool = True
    lang: str = "dot"
    role_shapes: dict[str, str] = field(default_factory=lambda: dict(RESERVED_SHAPE))
    line_styles: dict[str, str] = field(default_factory=dict)
    problems: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_lines: dict = field(default_factory=dict)


class GripError(Exception):
    pass


# ==========================================================================
# Parser (dot front end)
# ==========================================================================
class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.clusters: dict[str, Cluster] = {}
        self.graph_attrs: dict = {}
        self.directed = True
        self.order = 0
        self._anon = 0

    def peek(self, k=0):
        return self.toks[self.pos + k]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.next()
        if t.kind != kind:
            raise GripError(f"expected {kind}, got {t.kind} {t.val!r}")
        return t

    def nextorder(self):
        self.order += 1
        return self.order

    # --- top ---
    def parse(self):
        t = self.peek()
        if t.kind == "ID" and t.val == "strict":
            self.next()
        t = self.next()
        if t.kind != "ID" or t.val not in ("digraph", "graph"):
            raise GripError("expected graph/digraph")
        self.directed = t.val == "digraph"
        if self.peek().kind in ("ID", "STR"):
            self.next()  # graph name
        self.expect("{")
        scope = ScopeCtx(cluster=None, node_def={}, edge_def={},
                         attr_target=self.graph_attrs)
        self.parse_stmts(scope)
        return self

    def to_model(self) -> Model:
        return Model(
            nodes=self.nodes,
            edges=self.edges,
            clusters=self.clusters,
            graph_attrs=self.graph_attrs,
            directed=self.directed,
            lang="dot",
            role_shapes=dict(RESERVED_SHAPE),
            line_styles={},
        )

    def parse_node_id(self):
        t = self.next()
        name = t.val
        port = None
        while self.peek().kind == ":":
            self.next()
            p = self.next().val
            if port is None:
                port = p
            # else: compass; ignore
        return name, port

    def parse_attrs(self):
        attrs = {}
        while self.peek().kind == "[":
            self.next()
            while self.peek().kind != "]" and self.peek().kind != "EOF":
                k = self.next().val
                v = "true"
                if self.peek().kind == "=":
                    self.next()
                    v = self.next().val
                attrs[k] = v
                if self.peek().kind in (",", ";"):
                    self.next()
            if self.peek().kind == "]":
                self.next()
        return attrs

    def ensure_node(self, name, scope, pos=None):
        if name in self.clusters:
            return
        if name not in self.nodes:
            nd = Node(id=name, attrs=dict(scope.node_def), cluster=scope.cluster,
                      order=self.nextorder(), pos=self.pos if pos is None else pos)
            self.nodes[name] = nd

    def parse_stmts(self, scope):
        while True:
            t = self.peek()
            if t.kind == "}" or t.kind == "EOF":
                return
            if t.kind in (";", ","):
                self.next()
                continue
            if t.kind == "{":
                self.parse_subgraph(scope, None)
                continue
            if t.kind == "ID" and t.val == "subgraph":
                self.next()
                name = None
                if self.peek().kind in ("ID", "STR"):
                    name = self.next().val
                self.parse_subgraph(scope, name)
                continue
            if t.kind == "ID" and t.val in ("node", "edge", "graph") and \
                    self.peek(1).kind == "[":
                kind = self.next().val
                a = self.parse_attrs()
                if kind == "node":
                    scope.node_def.update(a)
                elif kind == "edge":
                    scope.edge_def.update(a)
                else:
                    scope.attr_target.update(a)
                continue
            # ID-led: node, edge, or graph-attr assignment
            if t.kind in ("ID", "STR"):
                tok_pos = self.pos
                name, port = self.parse_node_id()
                nt = self.peek()
                if nt.kind == "=" and port is None:
                    self.next()
                    val = self.next().val
                    scope.attr_target[name] = val
                    continue
                if nt.kind == "EDGE":
                    self.parse_edge_stmt(name, port, scope, tok_pos)
                    continue
                # node statement
                a = self.parse_attrs()
                if name not in self.clusters:
                    self.ensure_node(name, scope, pos=tok_pos)
                    self.nodes[name].attrs.update(a)
                continue
            # fallback skip
            self.next()

    def parse_edge_stmt(self, first_name, first_port, scope, tok_pos=None):
        edge_pos = self.pos if tok_pos is None else tok_pos
        endpoints = [(first_name, first_port)]
        while self.peek().kind == "EDGE":
            self.next()
            if self.peek().kind == "{":
                # subgraph endpoint -- not supported richly; skip its body
                self.parse_subgraph(scope, None)
                endpoints.append((None, None))
                continue
            if self.peek().kind == "ID" and self.peek().val == "subgraph":
                self.next()
                nm = None
                if self.peek().kind in ("ID", "STR"):
                    nm = self.next().val
                self.parse_subgraph(scope, nm)
                endpoints.append((nm, None))
                continue
            name, port = self.parse_node_id()
            endpoints.append((name, port))
        a = self.parse_attrs()
        for (tn, tp) in endpoints:
            if tn is not None:
                self.ensure_node(tn, scope, pos=edge_pos)
        for i in range(len(endpoints) - 1):
            tn, tp = endpoints[i]
            hn, hp = endpoints[i + 1]
            if tn is None or hn is None:
                continue
            e = Edge(tail=tn, tail_port=tp, head=hn, head_port=hp,
                     attrs={**scope.edge_def, **a}, cluster=scope.cluster,
                     order=self.nextorder(), pos=edge_pos)
            self.edges.append(e)

    def parse_subgraph(self, scope, name):
        sub_pos = self.pos
        if name is None or not name.startswith("cluster"):
            # anonymous or non-cluster subgraph: still its own scope for defaults,
            # but treated as transparent for execution. Give it a synthetic id.
            self._anon += 1
            cid = name if name else f"__anon{self._anon}"
        else:
            cid = name
        cl = Cluster(id=cid, parent=scope.cluster, order=self.nextorder(), pos=sub_pos)
        self.clusters[cid] = cl
        self.expect("{")
        child = ScopeCtx(cluster=cid, node_def=dict(scope.node_def),
                         edge_def=dict(scope.edge_def), attr_target=cl.attrs)
        self.parse_stmts(child)
        self.expect("}")


@dataclass
class ScopeCtx:
    cluster: str | None
    node_def: dict
    edge_def: dict
    attr_target: dict


def parse_dot(src: str) -> Model:
    toks = tokenize(src)
    return Parser(toks).parse().to_model()


# ==========================================================================
# Parser (modl front end)
# ==========================================================================
# JavaScript's /\s/ (modl lexes with it), so whitespace splits exactly as modl does.
_JS_WS = frozenset(
    "\t\n\v\f\r       　﻿"
    + "".join(chr(c) for c in range(0x2000, 0x200B))
)


@dataclass
class ModlPiece:
    """One lexed piece of a modl line: ws | arrow | comment | word.

    `start`/`end` are column offsets into the line. For a word, `val` is
    modl's value (quotes of each string removed) and `quoted` says whether any
    string was part of it. For a comment, `val` is the text after `#`.
    """
    kind: str
    start: int
    end: int
    val: str = ""
    quoted: bool = False


def _lex_modl_line(line: str) -> list[ModlPiece]:
    """A line-for-line port of modl's lexLine (js/editor.js).

    A quote (" or ') opens a string only at the start of a word or right after
    a closing quote, and only if the same quote character closes it later on
    the line; otherwise it is an ordinary character. Inside a string, `->`,
    `#` and whitespace are text. A `#` at column 0 or after whitespace starts
    a comment; `->` outside strings is always an arrow, even mid-word.
    """
    pieces: list[ModlPiece] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in _JS_WS:
            j = i
            while j < n and line[j] in _JS_WS:
                j += 1
            pieces.append(ModlPiece("ws", i, j))
            i = j
        elif c == "#" and (i == 0 or line[i - 1] in _JS_WS):
            pieces.append(ModlPiece("comment", i, n, line[i + 1:]))
            break
        elif line.startswith("->", i):
            pieces.append(ModlPiece("arrow", i, i + 2))
            i += 2
        else:
            start = i
            val: list[str] = []
            quoted = False
            can_open = True
            while i < n and line[i] not in _JS_WS and not line.startswith("->", i):
                q = line[i]
                close = line.find(q, i + 1) if (can_open and q in "\"'") else -1
                if close >= 0:
                    val.append(line[i + 1:close])
                    quoted = True
                    i = close + 1
                else:
                    val.append(q)
                    can_open = False
                    i += 1
            pieces.append(ModlPiece("word", start, i, "".join(val), quoted))
    return pieces


def _split_modl_comment(line: str) -> tuple[str, str | None, int]:
    """Return (code_part, comment_body_or_None, comment_col) using modl's lexer."""
    for p in _lex_modl_line(line):
        if p.kind == "comment":
            return line[:p.start], p.val, p.start
    return line, None, len(line)


def _looks_like_modl_url(tok: str | None) -> bool:
    return bool(tok) and tok.startswith(("/", "http://", "https://", "mailto:", "www."))


@dataclass
class ModlAttrs:
    """Result of modl's parseAttrs: indices into the attribute word list."""
    size: int | None = None
    style: int | None = None   # node shape or edge line style
    color: int | None = None
    url: int | None = None
    text: int | None = None    # index of the first text word, if text was given


def _modl_parse_attrs(words: list[ModlPiece], kind: str) -> ModlAttrs:
    """A port of modl's parseAttrs: slots are matched strictly in the order
    size, shape|line-style, color, url, then the rest is text. Quoted words
    never fill a slot."""
    toks = [None if w.quoted else w.val for w in words]

    def tok(k):
        return toks[k] if k < len(toks) else None

    a = ModlAttrs()
    i = 0
    if tok(i):
        if tok(i) in MODL_SIZES:
            a.size = i
            i += 1
        styles = MODL_SHAPES if kind == "node" else MODL_LINE_STYLES
        if tok(i) and tok(i) in styles:
            a.style = i
            i += 1
    if tok(i) and tok(i) in MODL_COLORS:
        a.color = i
        i += 1
    if _looks_like_modl_url(tok(i)):
        a.url = i
        i += 1
    if i < len(words):
        a.text = i
    return a


def _modl_text(line: str, words: list[ModlPiece], start: int) -> tuple[str, str]:
    """Return (raw_text, display_text) for words[start:].

    raw_text is the exact source slice (D1); display_text is what modl shows
    (word values joined with single spaces). Text whose display is blank
    (``""``, ``''``) is the empty label.
    """
    display = " ".join(w.val for w in words[start:])
    if display.strip() == "":
        return "", display
    return line[words[start].start:words[-1].end], display


def _parse_pragma_tokens(body: str, lineno: int) -> list[str]:
    """Tokenize a #gl pragma body after stripping any trailing # comment.

    Values inside `key="value"` may use dot-style `\\"` and `\\\\` escapes.
    Raises ValueError with an E10 reason on unclosed quotes.
    """
    # Strip trailing `# ...` comment outside quotes (respecting backslash escapes)
    in_quote = False
    i = 0
    n = len(body)
    cut = n
    while i < n:
        c = body[i]
        if in_quote and c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == '"':
            in_quote = not in_quote
        elif not in_quote and c == "#" and (i == 0 or body[i - 1] in " \t"):
            cut = i
            break
        i += 1
    if in_quote:
        raise ValueError(f"line {lineno}: unclosed quote in #gl pragma")

    s = body[:cut]
    tokens: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in " \t\r":
            i += 1
        if i >= n:
            break
        buf: list[str] = []
        in_q = False
        while i < n:
            c = s[i]
            if not in_q and c in " \t\r":
                break
            if not in_q and c == '"':
                in_q = True
                i += 1
                continue
            if in_q:
                if c == "\\" and i + 1 < n:
                    nxt = s[i + 1]
                    if nxt in ('"', "\\"):
                        buf.append(nxt)
                    else:
                        buf.append("\\")
                        buf.append(nxt)
                    i += 2
                    continue
                if c == '"':
                    in_q = False
                    i += 1
                    continue
                buf.append(c)
                i += 1
            else:
                buf.append(c)
                i += 1
        if in_q:
            raise ValueError(f"line {lineno}: unclosed quote in #gl pragma")
        tokens.append("".join(buf))
    return tokens


def _parse_kv_pairs(tokens: list[str], lineno: int) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for tok in tokens:
        if "=" not in tok:
            raise ValueError(f'line {lineno}: expected key=value in #gl pragma, got "{tok}"')
        k, v = tok.split("=", 1)
        if not k:
            raise ValueError(f'line {lineno}: empty key in #gl pragma "{tok}"')
        pairs.append((k, v))
    return pairs


class ModlParser:
    def __init__(self, src: str):
        self.src = src
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.clusters: dict[str, Cluster] = {}
        self.graph_attrs: dict = {}
        self.problems: list[tuple[str, str]] = []
        self.warnings: list[str] = []
        self.raw_lines: dict = {}
        self.order = 0
        self.scope_stack: list[ScopeCtx] = [
            ScopeCtx(cluster=None, node_def={}, edge_def={}, attr_target=self.graph_attrs)
        ]
        self._explicit_role_nodes: set[str] = set()
        self._standin_text: dict[str, str] = {}
        # nodes so far named only by `#gl node ID` (modl never draws them)
        self._pragma_only: set[str] = set()
        # lints whose verdict depends on the final mapping: (lineno, kind, msg)
        self._deferred_lints: list[tuple[int, str, str]] = []
        self._lints: list[tuple[int, str]] = []

    def nextorder(self) -> int:
        self.order += 1
        return self.order

    @property
    def current_scope(self) -> ScopeCtx:
        return self.scope_stack[-1]

    def add_e10(self, msg: str):
        self.problems.append(("E10", f"[E10] {msg}"))

    def validate_id(self, w: ModlPiece, lineno: int) -> str:
        # modl's idError: quoted ids may hold anything but nothing; the id is
        # the word's value exactly (no whitespace normalization).
        if w.quoted:
            if w.val == "":
                raise GripError(f"Line {lineno}: empty node id")
            return w.val
        if not _VALID_MODL_ID.match(w.val):
            raise GripError(f'Line {lineno}: invalid node id "{w.val}"')
        return w.val

    def ensure_node(self, nid: str, lineno: int, drawn: bool = True) -> Node | None:
        """Get or create node `nid`.

        `drawn` is False when the mention is a `#gl node` pragma, which modl
        never sees. Such a node only joins a scope (and gets block defaults)
        at its first drawn mention; one never drawn at all is an E10.
        """
        if nid in self.clusters:
            return None
        nd = self.nodes.get(nid)
        scope = self.current_scope
        if nd is None:
            nd = Node(id=nid, attrs=dict(scope.node_def) if drawn else {},
                      cluster=scope.cluster if drawn else None,
                      order=self.nextorder(), pos=lineno)
            self.nodes[nid] = nd
            if not drawn:
                self._pragma_only.add(nid)
        elif drawn and nid in self._pragma_only:
            self._pragma_only.discard(nid)
            nd.attrs = {**scope.node_def, **nd.attrs}
            nd.cluster = scope.cluster
            nd.order = self.nextorder()
            nd.pos = lineno
        return nd

    def apply_node_pragmas(self, nd: Node | None, nid: str, pairs: list[tuple[str, str]], lineno: int):
        if nid in self.clusters:
            for k, _v in pairs:
                if k == "role":
                    self.add_e10(f'line {lineno}: group id "{nid}" cannot also have a node role')
                else:
                    self.add_e10(f'line {lineno}: group id "{nid}" cannot take node pragma "{k}"')
            return
        if nd is None:
            return
        for k, v in pairs:
            if k == "role":
                if v not in VALID_NODE_ROLES:
                    self.add_e10(f'line {lineno}: invalid role "{v}"')
                else:
                    nd.attrs["gl_role"] = v
                    self._explicit_role_nodes.add(nid)
            elif k == "name":
                if not v:
                    self.add_e10(f"line {lineno}: empty name in #gl pragma")
                else:
                    nd.attrs["gl_name"] = v
            elif k in ("append", "async"):
                if v not in ("true", "false"):
                    self.add_e10(f'line {lineno}: invalid {k} value "{v}" (expected true or false)')
                else:
                    nd.attrs[f"gl_{k}"] = v
            elif k == "raw":
                nd.attrs["gl_raw"] = v
            else:
                self.add_e10(f'line {lineno}: unknown node pragma key "{k}"')

    def parse_edge_pragmas(self, pairs: list[tuple[str, str]], lineno: int) -> tuple[dict, str | None, str | None]:
        attrs: dict = {}
        tail_port: str | None = None
        head_port: str | None = None
        for k, v in pairs:
            if k == "edge":
                if v not in VALID_EDGE_KINDS:
                    self.add_e10(f'line {lineno}: invalid edge kind "{v}"')
                else:
                    attrs["gl_edge"] = v
            elif k == "stderr":
                if not v:
                    self.add_e10(f"line {lineno}: empty stderr value in #gl pragma")
                else:
                    attrs["gl_stderr"] = v
            elif k == "fd":
                if not v:
                    self.add_e10(f"line {lineno}: empty fd value in #gl pragma")
                else:
                    attrs["gl_fd"] = v
            elif k == "name":
                if not v:
                    self.add_e10(f"line {lineno}: empty name in #gl pragma")
                else:
                    attrs["gl_name"] = v
            elif k == "from":
                if port_to_fd(v) is None:
                    self.add_e10(f'line {lineno}: invalid port name "{v}" in from=')
                else:
                    tail_port = v
            elif k == "to":
                if port_to_fd(v) is None:
                    self.add_e10(f'line {lineno}: invalid port name "{v}" in to=')
                else:
                    head_port = v
            else:
                self.add_e10(f'line {lineno}: unknown edge pragma key "{k}"')
        return attrs, tail_port, head_port

    def handle_whole_line_pragma(self, body: str, lineno: int):
        try:
            tokens = _parse_pragma_tokens(body, lineno)
        except ValueError as e:
            self.add_e10(str(e))
            return

        if not tokens:
            self.add_e10(f"line {lineno}: empty #gl pragma")
            return

        head = tokens[0]
        if head == "end":
            if len(tokens) > 1:
                self.add_e10(f"line {lineno}: unexpected arguments after #gl end")
            if len(self.scope_stack) <= 1:
                self.add_e10(f"line {lineno}: unbalanced #gl end (no open block)")
            else:
                cl_id = self.current_scope.cluster
                self.scope_stack.pop()
                if cl_id and cl_id in self.clusters:
                    cl = self.clusters[cl_id]
                    if cl.attrs.get("gl_role") in ("for", "while", "until") \
                            and "gl_loop" not in cl.attrs and cl_id in self._standin_text:
                        cl.attrs["gl_loop"] = self._standin_text[cl_id]
            return

        if head == "begin":
            if len(tokens) < 2 or "=" in tokens[1]:
                self.add_e10(f"line {lineno}: #gl begin requires a block id")
                return
            cid = tokens[1]
            try:
                pairs = _parse_kv_pairs(tokens[2:], lineno)
            except ValueError as e:
                self.add_e10(str(e))
                return

            if cid in self._explicit_role_nodes:
                self.add_e10(f'line {lineno}: group id "{cid}" cannot also have a node role')
            if cid in self.nodes:
                nd = self.nodes.pop(cid)
                self._pragma_only.discard(cid)
                if "label" in nd.attrs:
                    self._standin_text[cid] = nd.attrs["label"]

            parent_scope = self.current_scope
            cl = Cluster(id=cid, parent=parent_scope.cluster,
                         order=self.nextorder(), pos=lineno)
            self.clusters[cid] = cl
            node_def = dict(parent_scope.node_def)
            edge_def = dict(parent_scope.edge_def)

            for k, v in pairs:
                if k == "role":
                    if v not in VALID_CLUSTER_ROLES:
                        self.add_e10(f'line {lineno}: invalid block role "{v}"')
                    else:
                        cl.attrs["gl_role"] = v
                elif k == "name":
                    if not v:
                        self.add_e10(f"line {lineno}: empty name in #gl begin")
                    else:
                        cl.attrs["gl_name"] = v
                elif k == "loop":
                    if not v:
                        self.add_e10(f"line {lineno}: empty loop header in #gl begin")
                    else:
                        cl.attrs["gl_loop"] = v
                elif k == "default.role":
                    if v not in VALID_NODE_ROLES:
                        self.add_e10(f'line {lineno}: invalid default.role "{v}"')
                    else:
                        node_def["gl_role"] = v
                elif k == "default.edge":
                    if v not in VALID_EDGE_KINDS:
                        self.add_e10(f'line {lineno}: invalid default.edge "{v}"')
                    else:
                        edge_def["gl_edge"] = v
                else:
                    self.add_e10(f'line {lineno}: unknown block pragma key "{k}"')

            if cl.attrs.get("gl_role") in ("for", "while", "until") \
                    and "gl_loop" not in cl.attrs and cid in self._standin_text:
                cl.attrs["gl_loop"] = self._standin_text[cid]

            self.scope_stack.append(
                ScopeCtx(cluster=cid, node_def=node_def, edge_def=edge_def, attr_target=cl.attrs)
            )
            return

        if head == "node":
            if len(tokens) < 3 or "=" in tokens[1]:
                self.add_e10(f"line {lineno}: #gl node requires an ID and key=value attributes")
                return
            nid = tokens[1]
            try:
                pairs = _parse_kv_pairs(tokens[2:], lineno)
            except ValueError as e:
                self.add_e10(str(e))
                return
            nd = self.ensure_node(nid, lineno, drawn=False)
            self.apply_node_pragmas(nd, nid, pairs, lineno)
            return

        if head == "edge":
            self.add_e10(f"line {lineno}: whole-line #gl edge is not supported; use a trailing pragma on the edge line")
            return

        # Graph-level pragma: #gl key=val ...
        try:
            pairs = _parse_kv_pairs(tokens, lineno)
        except ValueError as e:
            self.add_e10(str(e))
            return

        for k, v in pairs:
            if k == "mapping":
                if v not in VALID_MAPPINGS:
                    self.add_e10(f'line {lineno}: invalid mapping "{v}" (expected commands, dataflow, or typed)')
                else:
                    self.graph_attrs["gl_mapping"] = v
            elif k == "prologue":
                self.graph_attrs["gl_prologue"] = v
            elif k == "shell":
                if v not in VALID_SHELLS:
                    self.add_e10(f'line {lineno}: unsupported shell "{v}"')
                else:
                    self.graph_attrs["gl_shell"] = v
            else:
                self.add_e10(f'line {lineno}: unknown graph pragma key "{k}"')

    def parse(self) -> Model:
        # modl splits on \r?\n only (not str.splitlines' wider set).
        for lineno, line in enumerate(re.split(r"\r?\n", self.src), start=1):
            pieces = _lex_modl_line(line)
            comment = next((p for p in pieces if p.kind == "comment"), None)
            pragma_body: str | None = None
            if comment is not None and comment.val.startswith("gl") and (
                len(comment.val) == 2 or comment.val[2] in " \t"
            ):
                pragma_body = comment.val[2:]

            words = [p for p in pieces if p.kind == "word"]
            has_arrow = any(p.kind == "arrow" for p in pieces)
            if not words and not has_arrow:
                if pragma_body is not None:
                    self.handle_whole_line_pragma(pragma_body, lineno)
                continue

            # Background: exactly one unquoted color word and no arrow.
            if not has_arrow and len(words) == 1 and not words[0].quoted \
                    and words[0].val in MODL_COLORS:
                if pragma_body is not None:
                    self.add_e10(f"line {lineno}: #gl pragma on a background line (it has no element to attach to)")
                continue

            if has_arrow:
                self._parse_edge_line(line, pieces, pragma_body, lineno)
            else:
                self._parse_node_line(line, words, pragma_body, lineno)

        if len(self.scope_stack) > 1:
            unclosed = self.scope_stack[-1].cluster
            self.add_e10(f'unbalanced #gl begin "{unclosed}" (missing #gl end)')

        for nid in sorted(self._pragma_only, key=lambda x: self.nodes[x].order):
            nd = self.nodes.pop(nid)
            self.add_e10(f'line {nd.pos}: #gl node "{nid}" names a node that is not in the diagram')

        dataflow = self.graph_attrs.get("gl_mapping", "typed") == "dataflow"
        for lineno, kind, txt in self._deferred_lints:
            if kind == "solid_control" and not dataflow:
                self._lints.append((lineno,
                    f'line {lineno}: warning: solid edge has text "{txt}" '
                    f'(use "dashed {txt}" for control flow)'))
            elif kind == "solid_control" and dataflow:
                self._lints.append((lineno,
                    f'line {lineno}: warning: edge text "{txt}" runs as a command in the dataflow '
                    f'mapping (use #gl edge={"and" if txt == "&&" else "or"} for control flow)'))
            elif kind == "dataflow_dashed" and dataflow:
                self._lints.append((lineno,
                    f"line {lineno}: warning: dashed edge is a data edge in the dataflow mapping "
                    f"(add #gl edge=and|or|seq to make it control flow)"))
        self.warnings.extend(msg for _ln, msg in sorted(self._lints, key=lambda t: t[0]))

        return Model(
            nodes=self.nodes,
            edges=self.edges,
            clusters=self.clusters,
            graph_attrs=self.graph_attrs,
            directed=True,
            lang="modl",
            role_shapes=dict(MODL_ROLE_SHAPES),
            line_styles=dict(MODL_STYLE_KINDS),
            problems=self.problems,
            warnings=self.warnings,
            raw_lines=self.raw_lines,
        )

    def _pragma_pairs(self, pragma_body: str | None, lineno: int) -> list[tuple[str, str]]:
        if pragma_body is None:
            return []
        try:
            ptoks = _parse_pragma_tokens(pragma_body, lineno)
            if not ptoks:
                self.add_e10(f"line {lineno}: empty #gl pragma")
                return []
            return _parse_kv_pairs(ptoks, lineno)
        except ValueError as e:
            self.add_e10(str(e))
            return []

    def _slot_order_lint(self, words: list[ModlPiece], a: ModlAttrs, kind: str, lineno: int):
        """Warn when text starts with an attribute keyword: modl fills slots
        strictly in order (size, shape|style, color, url), so an out-of-order
        keyword silently becomes text, both in the picture and in the command."""
        if a.text is None or words[a.text].quoted:
            return
        w = words[a.text].val
        styles = MODL_SHAPES if kind == "node" else MODL_LINE_STYLES
        if w in MODL_SIZES or w in styles or w in MODL_COLORS:
            order = "size, shape, color, url" if kind == "node" else "size, line style, color, url"
            self._lints.append((lineno,
                f'line {lineno}: warning: "{w}" is out of modl\'s attribute order ({order}) '
                f"and became {kind} text"))

    def _url_lint(self, words: list[ModlPiece], a: ModlAttrs, what: str, lineno: int):
        if a.url is not None and words[a.url].val.startswith("/"):
            url = words[a.url].val
            self._lints.append((lineno,
                f'line {lineno}: warning: "{url}" filled the URL slot, not {what} (quote it to include it)'))

    def _parse_node_line(self, line: str, words: list[ModlPiece],
                         pragma_body: str | None, lineno: int):
        nid = self.validate_id(words[0], lineno)
        attr_words = words[1:]
        a = _modl_parse_attrs(attr_words, "node")
        shape = attr_words[a.style].val if a.style is not None else None

        raw_text: str | None = None
        display_text = ""
        if a.text is not None:
            raw_text, display_text = _modl_text(line, attr_words, a.text)

        self._url_lint(attr_words, a, "command text", lineno)
        self._slot_order_lint(attr_words, a, "node", lineno)
        if len(display_text) > MODL_NODE_LABEL_MAX:
            self._lints.append((lineno,
                f'line {lineno}: warning: node "{nid}" label is {len(display_text)} chars '
                f'(modl shows at most {MODL_NODE_LABEL_MAX})'))

        pairs = self._pragma_pairs(pragma_body, lineno)

        if nid in self.clusters:
            if raw_text is not None:
                self._standin_text[nid] = raw_text
                cl = self.clusters[nid]
                if cl.attrs.get("gl_role") in ("for", "while", "until") and "gl_loop" not in cl.attrs:
                    cl.attrs["gl_loop"] = raw_text
            if pairs:
                self.apply_node_pragmas(None, nid, pairs, lineno)
            return

        nd = self.ensure_node(nid, lineno)
        assert nd is not None
        if shape is not None:
            nd.attrs["shape"] = shape
            if shape in MODL_ROLE_SHAPES and nid not in self._explicit_role_nodes:
                # Shape overrides block default.role unless node has explicit #gl role
                nd.attrs.pop("gl_role", None)
        if raw_text is not None:
            nd.attrs["label"] = raw_text
        if pairs:
            self.apply_node_pragmas(nd, nid, pairs, lineno)

    def _parse_edge_line(self, line: str, pieces: list[ModlPiece],
                         pragma_body: str | None, lineno: int):
        segs: list[list[ModlPiece]] = [[]]
        for p in pieces:
            if p.kind == "arrow":
                segs.append([])
            elif p.kind == "word":
                segs[-1].append(p)
        # modl drops segments without words; fewer than two left is malformed.
        non_empty = [s for s in segs if s]
        if len(non_empty) < 2:
            raise GripError(f"Line {lineno}: malformed edge line")

        # Words after the id are attributes only in the last segment.
        endpoint_ids = [self.validate_id(s[0], lineno) for s in non_empty]
        last = non_empty[-1]
        attr_words = last[1:]
        a = _modl_parse_attrs(attr_words, "edge")
        style = attr_words[a.style].val if a.style is not None else None

        raw_text: str | None = None
        display_text = ""
        if a.text is not None:
            raw_text, display_text = _modl_text(line, attr_words, a.text)

        # For --annotate: where `red` goes so modl still reads the slots in
        # order (size, style, color, ...): replace the color, or insert after
        # the last of id/size/style.
        if a.color is not None:
            color_span = (attr_words[a.color].start, attr_words[a.color].end)
        else:
            color_span = None
        anchor = a.style if a.style is not None else a.size
        color_insert_col = attr_words[anchor].end if anchor is not None else last[0].end
        self.raw_lines[lineno] = {
            "kind": "edge",
            "color_span": color_span,
            "color_insert_col": color_insert_col,
        }

        pragma_attrs: dict = {}
        tail_port: str | None = None
        head_port: str | None = None
        pairs = self._pragma_pairs(pragma_body, lineno)
        if pairs:
            pragma_attrs, tail_port, head_port = self.parse_edge_pragmas(pairs, lineno)

        self._url_lint(attr_words, a, "edge text", lineno)
        self._slot_order_lint(attr_words, a, "edge", lineno)
        if len(display_text) > MODL_EDGE_LABEL_MAX:
            self._lints.append((lineno,
                f"line {lineno}: warning: edge label is {len(display_text)} chars "
                f"(modl shows at most {MODL_EDGE_LABEL_MAX})"))
        if "gl_edge" not in pragma_attrs:
            if (style or "solid") != "dashed" and raw_text in ("&&", "||"):
                self._deferred_lints.append((lineno, "solid_control", raw_text))
            if style == "dashed":
                self._deferred_lints.append((lineno, "dataflow_dashed", ""))

        for nid in endpoint_ids:
            self.ensure_node(nid, lineno)

        scope = self.current_scope
        edge_attrs = dict(scope.edge_def)
        if style is not None:
            edge_attrs["style"] = style
            if style == "dashed":
                # Explicit dashed style overrides default.edge unless #gl edge= is set
                edge_attrs.pop("gl_edge", None)
        if raw_text is not None:
            edge_attrs["label"] = raw_text
        edge_attrs.update(pragma_attrs)

        for i in range(len(endpoint_ids) - 1):
            e = Edge(
                tail=endpoint_ids[i],
                tail_port=tail_port,
                head=endpoint_ids[i + 1],
                head_port=head_port,
                attrs=dict(edge_attrs),
                cluster=scope.cluster,
                order=self.nextorder(),
                pos=lineno,
            )
            self.edges.append(e)


def parse_modl(src: str) -> Model:
    return ModlParser(src).parse()


# ==========================================================================
# Port / fd helpers
# ==========================================================================
def port_to_fd(port):
    if port is None:
        return None
    p = str(port).lower()
    if p in ("in", "stdin", "0"):
        return 0
    if p in ("out", "stdout", "1"):
        return 1
    if p in ("err", "stderr", "2"):
        return 2
    if p.isdigit():
        return int(p)
    return None


# ==========================================================================
# Engine: roles, checks, emission
# ==========================================================================
class Engine:
    def __init__(self, model: Model | Parser):
        if isinstance(model, Parser):
            model = model.to_model()
        self.model = model
        self.p = model
        self.nodes = model.nodes
        self.edges = model.edges
        self.clusters = model.clusters
        self.graph_attrs = model.graph_attrs
        self.mapping = self.graph_attrs.get("gl_mapping", "typed")
        self.problems: list[tuple[str, str]] = list(model.problems)
        self.warnings: list[str] = list(model.warnings)
        self.offending_nodes: set[str] = set()
        self.offending_edges: set[int] = set()
        self.prepared = False

    # ----- role & edge-kind resolution -----
    def optext(self, node: Node):
        if "label" in node.attrs:
            return node.attrs["label"]
        return node.id

    def resolve_roles(self):
        for nd in self.nodes.values():
            nd.role = self.role_of(nd)

    def role_of(self, nd: Node):
        a = nd.attrs
        if "gl_role" in a:
            return a["gl_role"]
        if "gl_raw" in a:
            return "program"
        shape = a.get("shape")
        if shape in self.model.role_shapes:
            return self.model.role_shapes[shape]
        if shape == "oval" and self.model.lang == "dot":
            return "value" if self.mapping == "dataflow" else "program"
        # mapping default
        if self.mapping == "dataflow":
            return "value"
        return "program"

    def edge_kind(self, e: Edge) -> str | None:
        if "gl_edge" in e.attrs:
            return e.attrs["gl_edge"]
        style = e.attrs.get("style")
        if style and self.model.line_styles.get(style) == "control":
            if self.mapping != "dataflow":
                txt = e.attrs.get("label", "").strip()
                if txt == "&&":
                    return "and"
                if txt == "||":
                    return "or"
                if txt in ("", ";"):
                    return "seq"
                return "invalid_control"
        return None

    def cluster_kind(self, cid):
        cl = self.clusters[cid]
        if cl.attrs.get("gl_loop"):
            return "loop"
        r = cl.attrs.get("gl_role")
        if r == "function":
            return "function"
        if r == "subshell":
            return "subshell"
        if r == "group":
            return "group"
        if r in ("for", "while", "until"):
            return "loop"
        return "transparent"

    def effective_scope(self, cid):
        while cid is not None and self.cluster_kind(cid) == "transparent":
            cid = self.clusters[cid].parent
        return cid

    def prepare(self):
        if self.prepared:
            return
        if self.p.directed:
            self.resolve_roles()
            if self.mapping == "dataflow":
                self.dataflow_transform()
        self.prepared = True

    # ----- static checks (§9) -----
    def run_checks(self):
        if not self.p.directed:
            self.problems.append(("E01",
                "[E01] graph is not a digraph; data flow needs direction, use digraph"))
            return self.problems  # nothing else meaningful

        self.prepare()

        # E02: program node with empty operation text
        for nd in self.nodes.values():
            if nd.role in ("program", "op") and "gl_raw" not in nd.attrs:
                if "label" in nd.attrs and nd.attrs["label"].strip() == "":
                    self.problems.append(("E02",
                        f'[E02] node "{nd.id}" has no operation (empty label)'))
                    self.offending_nodes.add(nd.id)

        # classify edges (lightweight) for checks
        data_edges = []   # (tail,head) pipe/data edges between nodes
        ctrl_adj = {}     # control graph
        fd_inputs = {}    # (node, fd) -> count of plain data inputs
        fd_edges = {}     # (node, fd) -> list of Edge
        captures = {}     # value -> set of producers
        capture_names = {}  # value -> list of resolved var names
        capture_edges = {}  # value -> list of Edge
        dups = {}         # node -> list of (srcfd,dstfd)
        dup_edges = {}    # node -> list of Edge
        redir_fd = {}     # node -> set of fds with a redirect

        for e in self.edges:
            te = self.endpoint_role(e.tail)
            he = self.endpoint_role(e.head)
            ge = self.edge_kind(e)
            if ge == "invalid_control":
                loc = f"line {e.pos}: " if self.model.lang == "modl" and e.pos else ""
                txt = e.attrs.get("label", "").strip()
                self.problems.append(("E11",
                    f'[E11] {loc}dashed edge {e.tail} -> {e.head} has invalid control text "{txt}" (expected &&, ||, or ;)'))
                if e.pos:
                    self.offending_edges.add(e.pos)
                continue
            if ge in ("seq", "and", "or"):
                ctrl_adj.setdefault(e.tail, []).append(e.head)
                ctrl_adj.setdefault(e.head, [])
                continue
            # E07: port naming an fd on a file/value node
            for who, port in ((e.tail, e.tail_port), (e.head, e.head_port)):
                if port is not None and port_to_fd(port) is not None:
                    r = self.endpoint_role(who)
                    if r in ("file", "value"):
                        self.problems.append(("E07",
                            f'[E07] "{who}:{port}" — file nodes have no fd {port_to_fd(port)}'))
                        self.offending_nodes.add(who)
                        if e.pos:
                            self.offending_edges.add(e.pos)
            if te == "value":
                continue  # varuse ordering
            if he == "value":
                captures.setdefault(e.head, set()).add(e.tail)
                vname = e.attrs.get("gl_name") or self.nodes[e.head].attrs.get("gl_name") or e.head
                capture_names.setdefault(e.head, []).append(vname)
                capture_edges.setdefault(e.head, []).append(e)
                continue
            if te == "file" and he == "file":
                self.problems.append(("E06",
                    f"[E06] edge {e.tail} -> {e.head}: file -> file has no program between them"))
                self.offending_nodes.update((e.tail, e.head))
                if e.pos:
                    self.offending_edges.add(e.pos)
                continue
            if te == "file":  # read redirect
                continue
            if he == "file":  # write redirect
                fd = port_to_fd(e.tail_port) or 1
                redir_fd.setdefault(e.tail, set()).add(fd)
                continue
            if e.tail == e.head:  # dup
                s = port_to_fd(e.tail_port)
                d = port_to_fd(e.head_port)
                dups.setdefault(e.tail, []).append((s, d))
                dup_edges.setdefault(e.tail, []).append(e)
                continue
            # proc -> proc : pipe (or fd routing)
            data_edges.append((e.tail, e.head))
            hfd = port_to_fd(e.head_port)
            hfd = 0 if hfd is None else hfd
            if self.endpoint_role(e.head) == "op":
                continue
            fd_inputs[(e.head, hfd)] = fd_inputs.get((e.head, hfd), 0) + 1
            fd_edges.setdefault((e.head, hfd), []).append(e)

        # E03
        for (node, fd), cnt in fd_inputs.items():
            if cnt >= 2:
                self.problems.append(("E03",
                    f'[E03] fd {fd} of "{node}" has {cnt} inputs; use fan-in (gl_role=op / cat)'))
                self.offending_nodes.add(node)
                for e in fd_edges.get((node, fd), []):
                    if e.pos:
                        self.offending_edges.add(e.pos)

        # E08
        for v, prods in captures.items():
            if len(prods) >= 2:
                self.problems.append(("E08",
                    f'[E08] value "{v}" captured by {len(prods)} commands'))
                self.offending_nodes.add(v)
                for e in capture_edges.get(v, []):
                    if e.pos:
                        self.offending_edges.add(e.pos)

        # E09
        for node, dl in dups.items():
            ok_single = len(dl) == 1 and dl[0] == (2, 1)
            conflict = bool(redir_fd.get(node, set()) & {d for (_s, d) in dl if d is not None})
            if not ok_single or conflict:
                self.problems.append(("E09",
                    f'[E09] fd dups on "{node}" are order-sensitive; use gl_raw'))
                self.offending_nodes.add(node)
                for e in dup_edges.get(node, []):
                    if e.pos:
                        self.offending_edges.add(e.pos)

        # E05 control cycle
        cyc = find_cycle(ctrl_adj)
        if cyc:
            self.problems.append(("E05",
                f'[E05] ordering cycle among {",".join(cyc)}'))
            cset = set(cyc)
            self.offending_nodes.update(cset)
            for e in self.edges:
                if e.tail in cset and e.head in cset and self.edge_kind(e) in ("seq", "and", "or"):
                    if e.pos:
                        self.offending_edges.add(e.pos)

        # E04 data cycle (unless coproc/loop declared)
        dadj = {}
        for (t, h) in data_edges:
            dadj.setdefault(t, []).append(h)
            dadj.setdefault(h, [])
        dcyc = find_cycle(dadj)
        if dcyc and not self.cycle_declared(dcyc):
            a = dcyc[0]
            b = dcyc[1] if len(dcyc) > 1 else dcyc[0]
            self.problems.append(("E04",
                f"[E04] data cycle {a} -> {b} -> {a} without loop/coproc semantics"))
            cset = set(dcyc)
            self.offending_nodes.update(cset)
            for e in self.edges:
                if e.tail in cset and e.head in cset and self.edge_kind(e) not in ("seq", "and", "or"):
                    if e.pos:
                        self.offending_edges.add(e.pos)

        # E12: value / function name must be a valid shell identifier
        for cid, cl in self.clusters.items():
            if self.cluster_kind(cid) == "function":
                fname = cl.attrs.get("gl_name", cid)
                if not _VALID_SHELL_ID.match(fname):
                    self.problems.append(("E12",
                        f'[E12] function name "{fname}" is not a valid shell identifier'))
        for v, names in capture_names.items():
            for vname in names:
                if not _VALID_SHELL_ID.match(vname):
                    self.problems.append(("E12",
                        f'[E12] variable name "{vname}" is not a valid shell identifier'))
                    self.offending_nodes.add(v)
                    break
        for nid, nd in self.nodes.items():
            if nd.role == "value" and nid not in captures:
                label = nd.attrs.get("label", nd.id)
                vname = label.split("=", 1)[0] if "=" in label else nd.attrs.get("gl_name", nd.id)
                if not _VALID_SHELL_ID.match(vname):
                    self.problems.append(("E12",
                        f'[E12] variable name "{vname}" is not a valid shell identifier'))
                    self.offending_nodes.add(nid)

        # E13: a loop needs a header, and a loop/subshell/group/function needs
        # a body (bash rejects `do done`, `( )`, `{ }`; `while :` would never end).
        for cid, cl in sorted(self.clusters.items(), key=lambda kv: kv[1].order):
            kind = self.cluster_kind(cid)
            if kind == "transparent":
                continue
            loc = f"line {cl.pos}: " if self.model.lang == "modl" and cl.pos else ""
            what = {"loop": "loop", "function": "function"}.get(kind, kind)
            if kind == "loop" and not cl.attrs.get("gl_loop"):
                self.problems.append(("E13",
                    f'[E13] {loc}loop "{cid}" has no loop header (set loop="for x in ..." / gl_loop)'))
                self.offending_nodes.add(cid)
            has_body = any(
                nd.role in self.UNIT_ROLES and self.effective_scope(nd.cluster) == cid
                for nd in self.nodes.values()
            ) or any(
                self.cluster_kind(c.id) in self.UNIT_CLUSTER_KINDS
                and self.effective_scope(c.parent) == cid
                for c in self.clusters.values()
            )
            if not has_body:
                hint = (" (in modl, a node belongs to the block where it is first mentioned)"
                        if self.model.lang == "modl" else "")
                self.problems.append(("E13",
                    f'[E13] {loc}{what} "{cid}" has an empty body{hint}'))
                self.offending_nodes.add(cid)

        return self.problems

    def cycle_declared(self, cyc):
        for nid in cyc:
            nd = self.nodes.get(nid)
            if nd and nd.role == "coproc":
                return True
            if nd and nd.cluster is not None:
                cid = nd.cluster
                # any enclosing loop cluster?
                while cid is not None:
                    if self.cluster_kind(cid) == "loop":
                        return True
                    cid = self.clusters[cid].parent
        return False

    def endpoint_role(self, name):
        if name in self.clusters:
            k = self.cluster_kind(name)
            return "cluster"
        nd = self.nodes.get(name)
        if nd is None:
            return "program"
        return nd.role

    # ======================================================================
    # Emission
    # ======================================================================
    def transpile(self):
        self.prepare()

        # function definitions first
        out = []
        prologue = self.graph_attrs.get("gl_prologue", "set -euo pipefail")
        out.append(prologue)

        for cid, cl in sorted(self.clusters.items(), key=lambda kv: kv[1].order):
            if self.cluster_kind(cid) == "function":
                name = cl.attrs.get("gl_name", cid)
                body = self.process_scope(cid)
                out.append(f"{name}() {{")
                out.extend(body)
                out.append("}")

        out.extend(self.process_scope(None))
        text = "\n".join(out)
        if not text.endswith("\n"):
            text += "\n"
        return text

    # ----- dataflow -> typed model -----
    def dataflow_transform(self):
        old_nodes = self.nodes
        old_edges = self.edges
        indeg = {nid: 0 for nid in old_nodes}
        outdeg = {nid: 0 for nid in old_nodes}
        for e in old_edges:
            outdeg[e.tail] = outdeg.get(e.tail, 0) + 1
            indeg[e.head] = indeg.get(e.head, 0) + 1

        new_nodes: dict[str, Node] = {}
        new_edges: list[Edge] = []
        order = [0]

        def no():
            order[0] += 1
            return order[0]

        def is_file(nid):
            nd = old_nodes.get(nid)
            return nd is not None and nd.role == "file"

        # file nodes carry over
        for nid, nd in old_nodes.items():
            if nd.role == "file":
                new_nodes[nid] = Node(id=nid, attrs=dict(nd.attrs), role="file",
                                      order=nd.order, pos=nd.pos)

        # input producer nodes (non-file, no in-edges, bearing a real command label)
        producers = {}
        for nid, nd in old_nodes.items():
            if nd.role != "file" and indeg.get(nid, 0) == 0 and outdeg.get(nid, 0) > 0 \
                    and "label" in nd.attrs:
                pn = Node(id=nid, attrs={"label": self.optext(nd)}, role="program",
                          order=nd.order, pos=nd.pos)
                new_nodes[nid] = pn
                producers[nid] = pn

        # consumer programs: a node explicitly given the program role (box /
        # square / gl_role=program) that has inputs reads them on stdin and,
        # like a producer, feeds its own out-edges. Without this a sink or
        # middle program was mistaken for a wire and silently dropped.
        consumers = {}
        for nid, nd in old_nodes.items():
            if nd.role == "program" and indeg.get(nid, 0) > 0:
                pn = Node(id=nid, attrs={"label": self.optext(nd)}, role="program",
                          order=nd.order, pos=nd.pos)
                for k in ("gl_raw", "gl_async"):
                    if k in nd.attrs:
                        pn.attrs[k] = nd.attrs[k]
                new_nodes[nid] = pn
                producers[nid] = pn
                consumers[nid] = pn

        # producer edge index for each wire (head -> list of edge indices)
        producer_of = {}
        for k, e in enumerate(old_edges):
            producer_of.setdefault(e.head, []).append(k)

        # one program node per labeled edge
        edge_node_id = {}
        for k, e in enumerate(old_edges):
            label = e.attrs.get("label", "")
            pid = f"__e{k}"
            pn = Node(id=pid, attrs={"label": label}, role="program",
                      order=no(), pos=e.pos)
            # gl_stderr / gl_fd on producer (tail)
            new_nodes[pid] = pn
            edge_node_id[k] = pid

        merge_made = {}

        def feed_tail(e, k, pid):
            x = e.tail
            x_producers = [j for j in producer_of.get(x, []) if j != k]
            if is_file(x) and not x_producers:
                # genuine input file -> read redirect on the consuming program
                new_edges.append(Edge(tail=x, tail_port=None, head=pid,
                                      head_port=None, order=no(), pos=e.pos))
                return
            if x in producers:
                new_edges.append(Edge(tail=x, tail_port=None, head=pid,
                                      head_port=None, order=no(), pos=e.pos))
                # gl_stderr/gl_fd attaches to producer command
                self._attach_edge_fd(e, producers[x])
                return
            # x is a wire (non-file with producers) OR file already handled
            prods = [j for j in producer_of.get(x, []) if j != k]
            if len(prods) == 1:
                src = edge_node_id[prods[0]]
                new_edges.append(Edge(tail=src, tail_port=None, head=pid,
                                      head_port=None, order=no(), pos=e.pos))
                self._attach_edge_fd(e, new_nodes[src])
            elif len(prods) >= 2:
                mid = merge_made.get(x)
                if mid is None:
                    mid = f"__merge_{x}"
                    new_nodes[mid] = Node(id=mid, attrs={"label": "cat"},
                                          role="op", order=no(), pos=e.pos)
                    for j in prods:
                        new_edges.append(Edge(tail=edge_node_id[j], tail_port=None,
                                              head=mid, head_port=None, order=no(), pos=e.pos))
                    merge_made[x] = mid
                new_edges.append(Edge(tail=mid, tail_port=None, head=pid,
                                      head_port=None, order=no(), pos=e.pos))

        for k, e in enumerate(old_edges):
            pid = edge_node_id[k]
            feed_tail(e, k, pid)
            y = e.head
            if is_file(y) or y in consumers:
                new_edges.append(Edge(tail=pid, tail_port=None, head=y,
                                      head_port=None, order=no(), pos=e.pos))
            # else: y is wire/output; consumers pull from pid via their tail wiring

        self.nodes = new_nodes
        self.edges = new_edges
        # dataflow cases have no clusters
        self.clusters = {}

    def _attach_edge_fd(self, e, node: Node):
        st = e.attrs.get("gl_stderr")
        if st == "2>&1":
            node.extra_suffix.append("2>&1")
        elif st:
            node.extra_suffix.append(f"2> {st}")
        fd = e.attrs.get("gl_fd")
        if fd:
            node.extra_suffix.append(fd)

    # ----- per-scope emission -----
    # ----- edge scoping -----
    UNIT_ROLES = ("program", "op", "value", "coproc", "stream")
    UNIT_CLUSTER_KINDS = ("loop", "subshell", "group")
    _NOT_A_UNIT = object()

    def unit_home(self, name):
        """The effective scope in which endpoint `name` is a unit, or
        _NOT_A_UNIT for endpoints that are not units (files: they are paths,
        usable from any scope)."""
        if name in self.clusters:
            return self.effective_scope(self.clusters[name].parent)
        nd = self.nodes.get(name)
        if nd is None or nd.role not in self.UNIT_ROLES:
            return self._NOT_A_UNIT
        return self.effective_scope(nd.cluster)

    def _scope_chain(self, scope):
        chain = []
        while scope is not None:
            chain.append(scope)
            scope = self.effective_scope(self.clusters[scope].parent)
        chain.append(None)
        return chain

    def edge_scope(self, e):
        """The scope that emits edge `e`: the innermost scope holding both
        endpoints, not the block the edge happened to be written in (an edge
        written at top level between two loop members belongs to the loop)."""
        ht, hh = self.unit_home(e.tail), self.unit_home(e.head)
        if ht is self._NOT_A_UNIT and hh is self._NOT_A_UNIT:
            return self.effective_scope(e.cluster)
        if ht is self._NOT_A_UNIT:
            return hh
        if hh is self._NOT_A_UNIT:
            return ht
        inner = set(self._scope_chain(hh))
        for sc in self._scope_chain(ht):
            if sc in inner:
                return sc
        return None

    def lift(self, name, scope_id):
        """Map endpoint `name` to the unit that represents it in `scope_id`:
        itself, or the enclosing loop/subshell/group that is a unit there."""
        h = self.unit_home(name)
        if h is self._NOT_A_UNIT or h == scope_id:
            return name
        cid = name if name in self.clusters else self.nodes[name].cluster
        while cid is not None:
            cl = self.clusters[cid]
            if self.cluster_kind(cid) in self.UNIT_CLUSTER_KINDS \
                    and self.effective_scope(cl.parent) == scope_id:
                return cid
            cid = cl.parent
        return name

    def process_scope(self, scope_id):
        nodes = [nd for nd in self.nodes.values()
                 if self.effective_scope(nd.cluster) == scope_id]
        edges = []
        for e in self.edges:
            if self.edge_scope(e) != scope_id:
                continue
            t, h = self.lift(e.tail, scope_id), self.lift(e.head, scope_id)
            if (t, h) != (e.tail, e.head):
                e = Edge(tail=t, tail_port=e.tail_port, head=h, head_port=e.head_port,
                         attrs=e.attrs, cluster=e.cluster, order=e.order, pos=e.pos)
            edges.append(e)
        child_clusters = [c for c in self.clusters.values()
                          if self.effective_scope(c.parent) == scope_id
                          and self.cluster_kind(c.id) in ("loop", "subshell", "group")]

        # unit set: program/op/value/coproc/stream nodes + loop/subshell/group clusters
        units = {}  # id -> ('node'|'cluster')
        for nd in nodes:
            if nd.role in ("program", "op", "value", "coproc", "stream"):
                units[nd.id] = "node"
        for c in child_clusters:
            units[c.id] = "cluster"

        # per-unit redirect structures
        reads = {u: [] for u in units}
        writes = {u: [] for u in units}
        dups = {u: [] for u in units}
        is_op = {u: (self.endpoint_role(u) == "op") for u in units}
        async_flag = {u: False for u in units}

        # seed dataflow synthetic suffixes
        for u in units:
            if units[u] == "node":
                nd = self.nodes[u]
                for s in nd.extra_suffix:
                    writes[u].append(s)
                if nd.attrs.get("gl_async") == "true":
                    async_flag[u] = True

        pipe_succ = {u: [] for u in units}
        pipe_pred = {u: [] for u in units}
        ctrl_andor = []   # (tail, head, op)
        order_edges = []  # (tail, head) ordering only
        captures = {}     # value_id -> (producer_id, name)
        loop_stdin = {}   # cluster -> file read string

        for e in edges:
            te = self.endpoint_role(e.tail)
            he = self.endpoint_role(e.head)
            ge = self.edge_kind(e)
            if ge in ("and", "or"):
                op = "&&" if ge == "and" else "||"
                ctrl_andor.append((e.tail, e.head, op))
                continue
            if ge == "seq":
                order_edges.append((e.tail, e.head))
                continue
            if te == "value" and he != "value":
                order_edges.append((e.tail, e.head))
                continue
            if he == "value":
                name = e.attrs.get("gl_name") or self.nodes[e.head].attrs.get("gl_name") or e.head
                captures[e.head] = (e.tail, name)
                continue
            if te == "file" and he in ("program", "op", "coproc", "stream", "cluster"):
                fd = port_to_fd(e.head_port)
                path = self.file_path(e.tail)
                if he == "cluster":
                    loop_stdin[e.head] = path
                else:
                    pre = "" if fd in (0, None) else str(fd)
                    reads[e.head].append(f"{pre}< {path}")
                continue
            if he == "file" and te in ("program", "op", "coproc", "stream", "cluster"):
                fd = port_to_fd(e.tail_port)
                path = self.file_path(e.head)
                fnode = self.nodes[e.head]
                app = fnode.attrs.get("gl_append") == "true"
                opstr = ">>" if app else ">"
                if fd in (1, None):
                    writes[e.tail].append(f"{opstr} {path}")
                else:
                    writes[e.tail].append(f"{fd}{opstr} {path}")
                continue
            if e.tail == e.head and te in ("program", "op"):
                s = port_to_fd(e.tail_port)
                d = port_to_fd(e.head_port)
                if s is not None and d is not None:
                    dups[e.tail].append(f"{s}>&{d}")
                continue
            # pipe / fd routing between distinct proc-ish units
            if e.tail in units and e.head in units:
                pipe_succ[e.tail].append(e.head)
                pipe_pred[e.head].append(e.tail)

        # ---- components via union-find over pipe + capture ----
        uf = UnionFind(list(units))
        for u in units:
            for v in pipe_succ[u]:
                uf.union(u, v)
        for vid, (prod, name) in captures.items():
            if vid in units and prod in units:
                uf.union(vid, prod)

        comps = {}
        for u in units:
            comps.setdefault(uf.find(u), []).append(u)

        # capture producers should not also be emitted as standalone:
        # they live inside the capture component (handled by render).

        # ---- render each component ----
        def order_of(u):
            if units[u] == "node":
                return self.nodes[u].order
            return self.clusters[u].order

        def render_cmd(u, include_writes=True):
            if units[u] == "cluster":
                return self.render_cluster(u, loop_stdin.get(u))
            nd = self.nodes[u]
            base = nd.attrs.get("gl_raw")
            if base is None:
                base = self.optext(nd)
            parts = [base] + reads[u]
            if include_writes:
                parts += writes[u]
            parts += dups[u]
            return " ".join(p for p in parts if p != "")

        def render_downstream(u, comp):
            cmd = render_cmd(u)
            succ = [v for v in pipe_succ[u] if v in comp]
            if not succ:
                return cmd
            if len(succ) == 1:
                return cmd + " | " + render_downstream(succ[0], comp)
            base = render_cmd(u, include_writes=False)
            branches = [render_downstream(s, comp) for s in succ]
            main = " ".join(writes[u])
            s = base + " | tee " + " ".join(f">({b})" for b in branches)
            if main:
                s += " " + main
            return s

        def render_upstream(u, comp):
            cmd = render_cmd(u)
            pred = [v for v in pipe_pred[u] if v in comp]
            if is_op[u] and pred:
                subs = " ".join(f"<({render_upstream(p, comp)})" for p in pred)
                return cmd + " " + subs
            if len(pred) == 1:
                return render_upstream(pred[0], comp) + " | " + cmd
            return cmd

        def render_component(comp):
            cset = set(comp)
            # coproc special
            coprocs = [u for u in comp if units[u] == "node"
                       and self.nodes[u].role == "coproc"]
            if coprocs:
                lines = []
                for u in sorted(comp, key=order_of):
                    if units[u] == "node" and self.nodes[u].role == "coproc":
                        lines.append("coproc { " + self.optext(self.nodes[u]) + "; }")
                    else:
                        lines.append(render_cmd(u))
                return "\n".join(lines)
            # capture component
            cap_vals = [u for u in comp if u in captures]
            if cap_vals:
                v = cap_vals[0]
                prod, name = captures[v]
                if prod in cset:
                    inner = render_upstream(prod, cset)
                else:
                    inner = render_cmd(prod) if prod in units else prod
                return f"{name}=$({inner})"
            # value definition only
            vals = [u for u in comp if units[u] == "node"
                    and self.nodes[u].role == "value"]
            if vals and all(self.nodes[u].role == "value" for u in comp):
                v = vals[0]
                return self.value_def(self.nodes[v])
            # fan-in?
            has_fanin = any(is_op[u] and len([v for v in pipe_pred[u] if v in cset]) >= 1
                            for u in comp)
            sinks = [u for u in comp if not [v for v in pipe_succ[u] if v in cset]]
            sources = [u for u in comp if not [v for v in pipe_pred[u] if v in cset]]
            if has_fanin and sinks:
                return render_upstream(sinks[0], cset)
            src = sources[0] if sources else sorted(comp, key=order_of)[0]
            return render_downstream(src, cset)

        comp_str = {}
        comp_order = {}
        for root, comp in comps.items():
            comp_str[root] = render_component(comp)
            comp_order[root] = min(order_of(u) for u in comp)

        unit_comp = {u: uf.find(u) for u in units}

        # ---- fusion via and/or ----
        fuf = UnionFind(list(comps.keys()))
        andor_between = {}
        for (t, h, op) in ctrl_andor:
            if t in unit_comp and h in unit_comp:
                ct, ch = unit_comp[t], unit_comp[h]
                fuf.union(ct, ch)
                andor_between[(ct, ch)] = op

        groups = {}
        for root in comps:
            groups.setdefault(fuf.find(root), []).append(root)

        group_str = {}
        group_order = {}
        for groot, members in groups.items():
            if len(members) == 1:
                s = comp_str[members[0]]
            else:
                # order comps within group by andor edges (topo)
                gadj = {m: [] for m in members}
                gindeg = {m: 0 for m in members}
                for (a, b), op in andor_between.items():
                    if a in gadj and b in gadj:
                        gadj[a].append(b)
                        gindeg[b] += 1
                order_list = topo(gadj, gindeg, comp_order)
                s = comp_str[order_list[0]]
                for i in range(1, len(order_list)):
                    op = andor_between.get((order_list[i - 1], order_list[i]), ";")
                    s += f" {op} " + comp_str[order_list[i]]
            group_str[groot] = s
            group_order[groot] = min(comp_order[m] for m in members)

        # ---- ordering between groups ----
        comp_group = {}
        for groot, members in groups.items():
            for m in members:
                comp_group[m] = groot
        gadj = {g: [] for g in groups}
        gindeg = {g: 0 for g in groups}
        seen = set()
        for (t, h) in order_edges:
            if t in unit_comp and h in unit_comp:
                gt = comp_group[unit_comp[t]]
                gh = comp_group[unit_comp[h]]
                if gt != gh and (gt, gh) not in seen:
                    gadj[gt].append(gh)
                    gindeg[gh] += 1
                    seen.add((gt, gh))
        order_list = topo(gadj, gindeg, group_order)

        lines = []
        any_async = False
        for g in order_list:
            s = group_str[g]
            members = groups[g]
            units_in = [u for m in members for u in comps[m]]
            if len(units_in) == 1 and async_flag.get(units_in[0]):
                s = s + " &"
                any_async = True
            lines.append(s)
        if any_async:
            lines.append("wait")
        return lines

    def value_def(self, nd: Node):
        label = nd.attrs.get("label", nd.id)
        if "=" in label:
            return label
        name = nd.attrs.get("gl_name", nd.id)
        return f"{name}={label}"

    def file_path(self, nid):
        nd = self.nodes.get(nid)
        if nd is None:
            return nid
        return self.optext(nd)

    def render_cluster(self, cid, stdin_path=None):
        kind = self.cluster_kind(cid)
        body = self.process_scope(cid)
        body_text = "\n".join(body)
        cl = self.clusters[cid]
        if kind == "loop":
            header = cl.attrs["gl_loop"]  # E13 guarantees a header
            s = header + "; do\n" + body_text + "\ndone"
            if stdin_path:
                s += f" < {stdin_path}"
            return s
        if kind == "subshell":
            return "(\n" + body_text + "\n)"
        if kind == "group":
            return "{\n" + body_text + "\n}"
        return body_text


# ==========================================================================
# Small utilities
# ==========================================================================
class UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def topo(adj, indeg, order_key):
    ready = sorted([n for n in adj if indeg[n] == 0], key=lambda n: order_key[n])
    out = []
    indeg = dict(indeg)
    while ready:
        n = ready.pop(0)
        out.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort(key=lambda x: order_key[x])
    # any remaining (cycle) appended in order
    for n in adj:
        if n not in out:
            out.append(n)
    return out


def find_cycle(adj):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    parent = {}
    cyc = []

    def dfs(u):
        color[u] = GRAY
        for v in adj.get(u, []):
            if v not in color:
                color[v] = WHITE
                parent[v] = u
            if color.get(v, WHITE) == WHITE:
                parent[v] = u
                r = dfs(v)
                if r:
                    return r
            elif color.get(v) == GRAY:
                # found cycle v..u
                path = [u]
                x = u
                while x != v and x in parent:
                    x = parent[x]
                    path.append(x)
                path.reverse()
                return path
        color[u] = BLACK
        return None

    for n in list(adj):
        if color.get(n, WHITE) == WHITE:
            r = dfs(n)
            if r:
                return r
    return None


# ==========================================================================
# Share-link decoding & Front-end dispatcher
# ==========================================================================
def is_url_arg(arg: str) -> bool:
    return arg.startswith(("http://", "https://"))


def decode_share_link(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    frag = parsed.fragment
    if frag.startswith("h1="):
        b64 = frag[3:].split("&", 1)[0]
        try:
            pad = "=" * (-len(b64) % 4)
            raw = base64.urlsafe_b64decode(b64 + pad).decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("src"), str):
                return data["src"]
        except Exception as e:
            raise GripError(f"invalid #h1 share link payload: {e}")
        raise GripError("invalid #h1 share link: missing 'src' field")
    raise GripError(
        "256t CID share links require network access to HashBin; use an #h1= inline share link"
    )


def encode_share_link(src: str, base_url: str = "https://modl.hashbin.page/") -> str:
    payload = json.dumps({"src": src, "pos": {}}, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{base_url}#h1={b64}"


def detect_lang(path: str | None, src: str, lang: str | None = None) -> str:
    if lang:
        if lang not in ("dot", "modl"):
            raise GripError(f"unknown language {lang!r}")
        return lang
    if path:
        if is_url_arg(path):
            return "modl"
        ext = os.path.splitext(path)[1].lower()
        if ext == ".modl":
            return "modl"
        if ext in (".dot", ".gv"):
            return "dot"
    # dot: [strict] (graph|digraph) [ID] "{". A modl node line such as
    # `graph square echo hi` also starts with `graph`, so require the brace.
    toks = tokenize(src)
    k = 0
    if toks[k].kind == "ID" and toks[k].val == "strict":
        k += 1
    if toks[k].kind == "ID" and toks[k].val in ("digraph", "graph"):
        k += 1
        if toks[k].kind in ("ID", "STR"):
            k += 1
        if toks[k].kind == "{":
            return "dot"
    return "modl"


def parse_source(src: str, lang: str = "dot") -> Model:
    if lang == "dot":
        return parse_dot(src)
    if lang == "modl":
        return parse_modl(src)
    raise GripError(f"unsupported language {lang!r}")


def read_input_source(path: str) -> str:
    if is_url_arg(path):
        return decode_share_link(path)
    with open(path) as f:
        return f.read()


def build_engine(path: str, lang: str | None = None) -> Engine:
    src = read_input_source(path)
    resolved_lang = detect_lang(path, src, lang=lang)
    model = parse_source(src, resolved_lang)
    return Engine(model)


def emit_diagnostics(path, problems, stream=None):
    stream = stream or sys.stderr  # resolved per call, so redirection works
    print(f"gripeline: {path} not executable ({len(problems)} problems)", file=stream)
    for code, msg in problems:
        print(f"  - {msg}", file=stream)
    print("exit status: 65", file=stream)


def _format_modl_id(nid: str) -> str:
    """Write `nid` as a modl id word that lexes back to exactly `nid`."""
    if _VALID_MODL_ID.match(nid):
        return nid
    if '"' not in nid:
        return f'"{nid}"'
    if "'" not in nid:
        return f"'{nid}'"
    # Both quote kinds: adjacent strings form one word ("a'b" + 'c"d').
    out, buf = [], ""
    for ch in nid:
        if ch == '"':
            if buf:
                out.append(f'"{buf}"')
            out.append("'\"'")
            buf = ""
        else:
            buf += ch
    if buf:
        out.append(f'"{buf}"')
    return "".join(out)


def annotate(engine: Engine, path: str, problems, out_path: str):
    src = read_input_source(path)
    if engine.model.lang == "modl":
        lines = src.splitlines()
        for lineno in sorted(engine.offending_edges):
            meta = engine.model.raw_lines.get(lineno)
            if meta and 1 <= lineno <= len(lines):
                ln = lines[lineno - 1]
                cspan = meta.get("color_span")
                if cspan is not None:
                    s, e = cspan
                    lines[lineno - 1] = ln[:s] + "red" + ln[e:]
                else:
                    col = meta["color_insert_col"]
                    lines[lineno - 1] = ln[:col] + " red" + ln[col:]
        for nid in sorted(
            engine.offending_nodes,
            key=lambda x: engine.nodes[x].order if x in engine.nodes else 0,
        ):
            lines.append(f"{_format_modl_id(nid)} red")
        for _code, msg in problems:
            lines.append(f"# {msg}")
        with open(out_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        return

    # Produce a diagnostic-annotated copy of the dot file. Best-effort: append
    # gl_error / color hints as a trailing comment block plus per-element attrs
    # for offending nodes referenced in messages.
    notes = ["/* gripeline diagnostics */"]
    for code, msg in problems:
        notes.append(f"// {msg}")
    annotated = src.rstrip() + "\n" + "\n".join(notes) + "\n"
    with open(out_path, "w") as f:
        f.write(annotated)


def main(argv):
    args = argv[1:]
    flags = {"annotate": None, "strict": False, "infer_style": False, "lang": None}
    rest = []
    for a in args:
        if a == "--strict":
            flags["strict"] = True
        elif a == "--infer-style":
            flags["infer_style"] = True
        elif a == "--annotate":
            flags["annotate"] = True
        elif a.startswith("--annotate="):
            flags["annotate"] = a.split("=", 1)[1]
        elif a.startswith("--lang="):
            flags["lang"] = a.split("=", 1)[1]
        else:
            rest.append(a)

    if not rest:
        print("usage: gripeline {build|run|check} <file.dot|file.modl>", file=sys.stderr)
        return 2
    cmd = rest[0]
    if cmd not in ("build", "run", "check"):
        # allow `gripeline file.dot` or `gripeline file.modl` -> build
        if os.path.exists(cmd) or is_url_arg(cmd):
            rest = ["build"] + rest
            cmd = "build"
        else:
            print(f"unknown command {cmd!r}", file=sys.stderr)
            return 2
    if len(rest) < 2:
        print("missing <file.dot|file.modl>", file=sys.stderr)
        return 2
    path = rest[1]

    try:
        engine = build_engine(path, lang=flags["lang"])
    except (GripError, OSError) as e:
        print(f"gripeline: parse error: {e}", file=sys.stderr)
        return 2

    problems = engine.run_checks()

    for w in engine.warnings:
        print(f"gripeline: {w}", file=sys.stderr)

    if flags["annotate"] and problems:
        if isinstance(flags["annotate"], str):
            out_path = flags["annotate"]
        else:
            ext = ".annotated.modl" if engine.model.lang == "modl" else ".annotated.dot"
            base = "share" if is_url_arg(path) else os.path.splitext(path)[0]
            out_path = base + ext
        annotate(engine, path, problems, out_path)

    if cmd == "check":
        if problems:
            emit_diagnostics(path, problems)
            return 65
        return 0

    if problems:
        emit_diagnostics(path, problems)
        return 65

    try:
        bash = engine.transpile()
    except GripError as e:
        print(f"gripeline: {e}", file=sys.stderr)
        return 2

    if cmd == "build":
        sys.stdout.write(bash)
        return 0

    if cmd == "run":
        fd, name = tempfile.mkstemp(suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write(bash)
        try:
            p = subprocess.run(["bash", name])
        finally:
            os.unlink(name)
        return p.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
