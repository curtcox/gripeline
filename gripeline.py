#!/usr/bin/env python3
"""gripeline — transpile a Graphviz `dot` file into a bash script.

See SPEC.md (Draft 0.3). The emitted bash is the normative meaning of a graph.

Stages:  parse -> extract/resolve roles -> static check (§9) -> transpile (§§4-8).

CLI:
    gripeline build <file.dot>     print transpiled bash to stdout
    gripeline run   <file.dot>     transpile then exec under bash; propagate status
    gripeline check <file.dot>     run only the §9 static check; exit 0 or 65
        --annotate[=out.dot]       also write a diagnostic-annotated dot copy
        --strict                   ordering ambiguity is an error
        --infer-style              also read recommended visual conventions (off)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field


# ==========================================================================
# Tokenizer
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


@dataclass
class Edge:
    tail: str
    tail_port: str | None
    head: str
    head_port: str | None
    attrs: dict = field(default_factory=dict)
    cluster: str | None = None
    order: int = 0


@dataclass
class Cluster:
    id: str
    attrs: dict = field(default_factory=dict)
    parent: str | None = None
    order: int = 0


class GripError(Exception):
    pass


# ==========================================================================
# Parser
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

    def ensure_node(self, name, scope):
        if name in self.clusters:
            return
        if name not in self.nodes:
            nd = Node(id=name, attrs=dict(scope.node_def), cluster=scope.cluster,
                      order=self.nextorder())
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
                name, port = self.parse_node_id()
                nt = self.peek()
                if nt.kind == "=" and port is None:
                    self.next()
                    val = self.next().val
                    scope.attr_target[name] = val
                    continue
                if nt.kind == "EDGE":
                    self.parse_edge_stmt(name, port, scope)
                    continue
                # node statement
                a = self.parse_attrs()
                if name not in self.clusters:
                    self.ensure_node(name, scope)
                    self.nodes[name].attrs.update(a)
                continue
            # fallback skip
            self.next()

    def parse_edge_stmt(self, first_name, first_port, scope):
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
                self.ensure_node(tn, scope)
        for i in range(len(endpoints) - 1):
            tn, tp = endpoints[i]
            hn, hp = endpoints[i + 1]
            if tn is None or hn is None:
                continue
            e = Edge(tail=tn, tail_port=tp, head=hn, head_port=hp,
                     attrs={**scope.edge_def, **a}, cluster=scope.cluster,
                     order=self.nextorder())
            self.edges.append(e)

    def parse_subgraph(self, scope, name):
        if name is None or not name.startswith("cluster"):
            # anonymous or non-cluster subgraph: still its own scope for defaults,
            # but treated as transparent for execution. Give it a synthetic id.
            self._anon += 1
            cid = name if name else f"__anon{self._anon}"
        else:
            cid = name
        cl = Cluster(id=cid, parent=scope.cluster, order=self.nextorder())
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


RESERVED_SHAPE = {"box": "program", "note": "file", "cds": "stream"}


# ==========================================================================
# Engine: roles, checks, emission
# ==========================================================================
class Engine:
    def __init__(self, parser: Parser):
        self.p = parser
        self.nodes = parser.nodes
        self.edges = parser.edges
        self.clusters = parser.clusters
        self.graph_attrs = parser.graph_attrs
        self.mapping = self.graph_attrs.get("gl_mapping", "typed")
        self.problems: list[tuple[str, str]] = []
        self.prepared = False

    # ----- role resolution -----
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
        if shape in RESERVED_SHAPE:
            return RESERVED_SHAPE[shape]
        if shape == "oval":
            return "value" if self.mapping == "dataflow" else "program"
        # mapping default
        if self.mapping == "dataflow":
            return "value"
        return "program"

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

        # classify edges (lightweight) for checks
        data_edges = []   # (tail,head) pipe/data edges between nodes
        ctrl_adj = {}     # control graph
        fd_inputs = {}    # (node, fd) -> count of plain data inputs
        captures = {}     # value -> set of producers
        dups = {}         # node -> list of (srcfd,dstfd)
        redir_fd = {}     # node -> set of fds with a redirect

        for e in self.edges:
            te = self.endpoint_role(e.tail)
            he = self.endpoint_role(e.head)
            ge = e.attrs.get("gl_edge")
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
            if te == "value":
                continue  # varuse ordering
            if he == "value":
                captures.setdefault(e.head, set()).add(e.tail)
                continue
            if te == "file" and he == "file":
                self.problems.append(("E06",
                    f"[E06] edge {e.tail} -> {e.head}: file -> file has no program between them"))
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
                continue
            # proc -> proc : pipe (or fd routing)
            data_edges.append((e.tail, e.head))
            hfd = port_to_fd(e.head_port)
            hfd = 0 if hfd is None else hfd
            if self.endpoint_role(e.head) == "op":
                continue
            fd_inputs[(e.head, hfd)] = fd_inputs.get((e.head, hfd), 0) + 1

        # E03
        for (node, fd), cnt in fd_inputs.items():
            if cnt >= 2:
                self.problems.append(("E03",
                    f'[E03] fd {fd} of "{node}" has {cnt} inputs; use fan-in (gl_role=op / cat)'))

        # E08
        for v, prods in captures.items():
            if len(prods) >= 2:
                self.problems.append(("E08",
                    f'[E08] value "{v}" captured by {len(prods)} commands'))

        # E09
        for node, dl in dups.items():
            ok_single = len(dl) == 1 and dl[0] == (2, 1)
            conflict = bool(redir_fd.get(node, set()) & {d for (_s, d) in dl if d is not None})
            if not ok_single or conflict:
                self.problems.append(("E09",
                    f'[E09] fd dups on "{node}" are order-sensitive; use gl_raw'))

        # E05 control cycle
        cyc = find_cycle(ctrl_adj)
        if cyc:
            self.problems.append(("E05",
                f'[E05] ordering cycle among {",".join(cyc)}'))

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
                                      order=nd.order)

        # input producer nodes (non-file, no in-edges, bearing a real command label)
        producers = {}
        for nid, nd in old_nodes.items():
            if nd.role != "file" and indeg.get(nid, 0) == 0 and outdeg.get(nid, 0) > 0 \
                    and "label" in nd.attrs:
                pn = Node(id=nid, attrs={"label": self.optext(nd)}, role="program",
                          order=nd.order)
                new_nodes[nid] = pn
                producers[nid] = pn

        # producer edge index for each wire (head -> list of edge indices)
        producer_of = {}
        for k, e in enumerate(old_edges):
            producer_of.setdefault(e.head, []).append(k)

        # one program node per labeled edge
        edge_node_id = {}
        for k, e in enumerate(old_edges):
            label = e.attrs.get("label", "")
            pid = f"__e{k}"
            pn = Node(id=pid, attrs={"label": label}, role="program", order=no())
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
                                      head_port=None, order=no()))
                return
            if x in producers:
                new_edges.append(Edge(tail=x, tail_port=None, head=pid,
                                      head_port=None, order=no()))
                # gl_stderr/gl_fd attaches to producer command
                self._attach_edge_fd(e, producers[x])
                return
            # x is a wire (non-file with producers) OR file already handled
            prods = [j for j in producer_of.get(x, []) if j != k]
            if len(prods) == 1:
                src = edge_node_id[prods[0]]
                new_edges.append(Edge(tail=src, tail_port=None, head=pid,
                                      head_port=None, order=no()))
                self._attach_edge_fd(e, new_nodes[src])
            elif len(prods) >= 2:
                mid = merge_made.get(x)
                if mid is None:
                    mid = f"__merge_{x}"
                    new_nodes[mid] = Node(id=mid, attrs={"label": "cat"},
                                          role="op", order=no())
                    for j in prods:
                        new_edges.append(Edge(tail=edge_node_id[j], tail_port=None,
                                              head=mid, head_port=None, order=no()))
                    merge_made[x] = mid
                new_edges.append(Edge(tail=mid, tail_port=None, head=pid,
                                      head_port=None, order=no()))

        for k, e in enumerate(old_edges):
            pid = edge_node_id[k]
            feed_tail(e, k, pid)
            y = e.head
            if is_file(y):
                new_edges.append(Edge(tail=pid, tail_port=None, head=y,
                                      head_port=None, order=no()))
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
    def process_scope(self, scope_id):
        nodes = [nd for nd in self.nodes.values()
                 if self.effective_scope(nd.cluster) == scope_id]
        edges = [e for e in self.edges
                 if self.effective_scope(e.cluster) == scope_id]
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
            ge = e.attrs.get("gl_edge")
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
        return f"{nd.id}={label}"

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
            header = cl.attrs.get("gl_loop", "while :")
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
# CLI
# ==========================================================================
def build_engine(path):
    with open(path) as f:
        src = f.read()
    toks = tokenize(src)
    parser = Parser(toks).parse()
    return Engine(parser)


def emit_diagnostics(path, problems, stream=sys.stderr):
    print(f"gripeline: {path} not executable ({len(problems)} problems)", file=stream)
    for code, msg in problems:
        print(f"  - {msg}", file=stream)
    print("exit status: 65", file=stream)


def annotate(engine, path, problems, out_path):
    # Produce a diagnostic-annotated copy of the dot file. Best-effort: append
    # gl_error / color hints as a trailing comment block plus per-element attrs
    # for offending nodes referenced in messages.
    with open(path) as f:
        src = f.read()
    notes = ["/* gripeline diagnostics */"]
    for code, msg in problems:
        notes.append(f"// {msg}")
    annotated = src.rstrip() + "\n" + "\n".join(notes) + "\n"
    with open(out_path, "w") as f:
        f.write(annotated)


def main(argv):
    args = argv[1:]
    flags = {"annotate": None, "strict": False, "infer_style": False}
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
        else:
            rest.append(a)

    if not rest:
        print("usage: gripeline {build|run|check} <file.dot>", file=sys.stderr)
        return 2
    cmd = rest[0]
    if cmd not in ("build", "run", "check"):
        # allow `gripeline file.dot` -> build
        if os.path.exists(cmd):
            rest = ["build"] + rest
            cmd = "build"
        else:
            print(f"unknown command {cmd!r}", file=sys.stderr)
            return 2
    if len(rest) < 2:
        print("missing <file.dot>", file=sys.stderr)
        return 2
    path = rest[1]

    try:
        engine = build_engine(path)
    except (GripError, OSError) as e:
        print(f"gripeline: parse error: {e}", file=sys.stderr)
        return 2

    problems = engine.run_checks()

    if flags["annotate"] and problems:
        out_path = flags["annotate"] if isinstance(flags["annotate"], str) \
            else (os.path.splitext(path)[0] + ".annotated.dot")
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
