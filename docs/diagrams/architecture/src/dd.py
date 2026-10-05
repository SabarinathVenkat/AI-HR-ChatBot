"""Tiny generator for diagram-design style SVG/HTML (default skin).

Enforces: 4px grid, rounded orthogonal connectors (r=8), masked labels with an 8px gap,
fan-out attach points, arrows-before-boxes z-order, hop arcs on crossings, and reports
geometry problems (connector behind a non-endpoint box, label mask over a node, parallel
overlap) so layouts can be fixed before export.
"""
import html
import math

PAPER = "#f5f5f5"
INK = "#2d3142"
MUTED = "#4f5d75"
SOFT = "#7a8399"
ACCENT = "#eb6c36"
LINK = "#2e5aa8"

KINDS = {
    "backend": dict(fill="#ffffff", stroke=INK, dash=None),
    "focal": dict(fill="rgba(235,108,54,0.08)", stroke=ACCENT, dash=None),
    "store": dict(fill="rgba(45,49,66,0.05)", stroke=MUTED, dash=None),
    "external": dict(fill="rgba(45,49,66,0.03)", stroke="rgba(45,49,66,0.30)", dash=None),
    "input": dict(fill="rgba(79,93,117,0.10)", stroke=SOFT, dash=None),
    "optional": dict(fill="rgba(45,49,66,0.02)", stroke="rgba(45,49,66,0.20)", dash="4,3"),
    "security": dict(fill="rgba(235,108,54,0.05)", stroke="rgba(235,108,54,0.50)", dash="4,4"),
}

LINE_STYLES = {
    "default": (MUTED, "arrow"),
    "accent": (ACCENT, "arrow-accent"),
    "link": (LINK, "arrow-link"),
}


def r4(v):
    return int(math.floor(v / 4.0 + 0.5)) * 4


def ceil4(v):
    return int(math.ceil(v / 4.0)) * 4


def lw(text):
    """mask width for an 8px mono label"""
    return ceil4(len(text) * 5.6 + 8)


def esc(s):
    return html.escape(s, quote=False)


class Node:
    def __init__(self, nid, x, y, w, h, name, sub=None, tag=None, kind="backend", center=False):
        for v in (x, y, w, h):
            assert v % 4 == 0, "grid violation for %s: %s" % (nid, (x, y, w, h))
        self.id, self.x, self.y, self.w, self.h = nid, x, y, w, h
        self.name, self.tag, self.kind, self.center = name, tag, kind, center
        self.sub = [] if sub is None else ([sub] if isinstance(sub, str) else list(sub))

    # attach points ----------------------------------------------------
    def _k(self, length, k, n):
        return r4(length * k / float(n + 1))

    def top(self, k=1, n=1):
        return (self.x + self._k(self.w, k, n), self.y)

    def bottom(self, k=1, n=1):
        return (self.x + self._k(self.w, k, n), self.y + self.h)

    def left(self, k=1, n=1):
        return (self.x, self.y + self._k(self.h, k, n))

    def right(self, k=1, n=1):
        return (self.x + self.w, self.y + self._k(self.h, k, n))

    def rect(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)


class Conn:
    def __init__(self, pts, src, dst, label, seg, t, side, style, dashed, marker):
        self.pts, self.src, self.dst = pts, src, dst
        self.label, self.seg, self.t, self.side = label, seg, t, side
        self.style, self.dashed, self.marker = style, dashed, marker

    def segments(self):
        return [(self.pts[i][0], self.pts[i][1], self.pts[i + 1][0], self.pts[i + 1][1])
                for i in range(len(self.pts) - 1)]


def _open_overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0) > 0.01


class Diagram:
    def __init__(self, slug, W, H, title, eyebrow, desc, explain, legend, wide=False):
        assert W % 4 == 0 and H % 4 == 0
        self.slug, self.W, self.H = slug, W, H
        self.title, self.eyebrow, self.desc = title, eyebrow, desc
        self.explain, self.legend, self.wide = explain, legend, wide
        self.zones, self.nodes, self.conns = [], {}, []
        self.warnings = []

    # builders ---------------------------------------------------------
    def zone(self, x, y, w, h, label, lx=12):
        for v in (x, y, w, h, lx):
            assert v % 4 == 0, "zone grid %s" % label
        self.zones.append((x, y, w, h, label, lx))

    def node(self, nid, x, y, w, h, name, sub=None, tag=None, kind="backend", center=False):
        n = Node(nid, x, y, w, h, name, sub, tag, kind, center)
        assert nid not in self.nodes, nid
        self.nodes[nid] = n
        if len(name) * 6.6 > w - 16:
            self.warnings.append("name too wide in %s: %r (w=%d)" % (nid, name, w))
        for s in n.sub:
            if len(s) * 4.9 > w - 16:
                self.warnings.append("sub too wide in %s: %r (w=%d)" % (nid, s, w))
        return n

    def conn(self, pts, src=None, dst=None, label=None, seg=0, t=0.5, side="auto",
             style="default", dashed=False, marker=True):
        for p in pts:
            assert p[0] % 4 == 0 and p[1] % 4 == 0, "conn grid %s->%s %s" % (src, dst, p)
        for i in range(len(pts) - 1):
            assert pts[i][0] == pts[i + 1][0] or pts[i][1] == pts[i + 1][1], \
                "diagonal connector %s->%s" % (src, dst)
        c = Conn(pts, src, dst, label, seg, t, side, style, dashed, marker)
        self.conns.append(c)
        return c

    # geometry ---------------------------------------------------------
    def _label_rect(self, c):
        if not c.label:
            return None
        a = c.pts[c.seg]
        b = c.pts[c.seg + 1]
        w = lw(c.label)
        if a[1] == b[1]:  # horizontal
            mx = a[0] + (b[0] - a[0]) * c.t
            x = r4(mx - w / 2.0)
            y = a[1] - 20 if c.side in ("auto", "above") else a[1] + 8
        else:
            my = a[1] + (b[1] - a[1]) * c.t
            y = r4(my - 6)
            x = a[0] + 8 if c.side in ("auto", "right") else a[0] - 8 - w
        return (x, y, w, 12)

    def check(self):
        W = self.warnings
        nodes = list(self.nodes.values())
        masks = []
        for c in self.conns:
            m = self._label_rect(c)
            if m:
                masks.append((c, m))
        # connector vs node
        for c in self.conns:
            for (x1, y1, x2, y2) in c.segments():
                for n in nodes:
                    if n.id in (c.src, c.dst):
                        continue
                    r = n.rect()
                    if _open_overlap(min(x1, x2), max(x1, x2), r[0], r[2]) and \
                            _open_overlap(min(y1, y2), max(y1, y2), r[1], r[3]):
                        W.append("connector %s->%s passes behind %s" % (c.src, c.dst, n.id))
                    elif x1 == x2 and r[0] < x1 < r[2] and _open_overlap(min(y1, y2), max(y1, y2), r[1], r[3]):
                        W.append("connector %s->%s passes behind %s" % (c.src, c.dst, n.id))
                    elif y1 == y2 and r[1] < y1 < r[3] and _open_overlap(min(x1, x2), max(x1, x2), r[0], r[2]):
                        W.append("connector %s->%s passes behind %s" % (c.src, c.dst, n.id))
        # connector vs connector (parallel overlap / closeness)
        for i, a in enumerate(self.conns):
            for b in self.conns[i + 1:]:
                for s in a.segments():
                    for u in b.segments():
                        if s[1] == s[3] and u[1] == u[3]:
                            if abs(s[1] - u[1]) < 12 and _open_overlap(min(s[0], s[2]), max(s[0], s[2]), min(u[0], u[2]), max(u[0], u[2])):
                                W.append("parallel horizontals too close: %s->%s / %s->%s (y %d,%d)" % (a.src, a.dst, b.src, b.dst, s[1], u[1]))
                        if s[0] == s[2] and u[0] == u[2]:
                            if abs(s[0] - u[0]) < 12 and _open_overlap(min(s[1], s[3]), max(s[1], s[3]), min(u[1], u[3]), max(u[1], u[3])):
                                W.append("parallel verticals too close: %s->%s / %s->%s (x %d,%d)" % (a.src, a.dst, b.src, b.dst, s[0], u[0]))
        # label masks
        for c, m in masks:
            mx0, my0, mx1, my1 = m[0], m[1], m[0] + m[2], m[1] + m[3]
            for n in nodes:
                r = n.rect()
                if _open_overlap(mx0, mx1, r[0], r[2]) and _open_overlap(my0, my1, r[1], r[3]):
                    inside = mx0 >= r[0] and mx1 <= r[2] and my0 >= r[1] and my1 <= r[3]
                    if not inside:
                        W.append("label %r (%s->%s) overlaps node %s" % (c.label, c.src, c.dst, n.id))
            for c2 in self.conns:
                for (x1, y1, x2, y2) in c2.segments():
                    if _open_overlap(min(x1, x2) - 0.5, max(x1, x2) + 0.5, mx0, mx1) and \
                            _open_overlap(min(y1, y2) - 0.5, max(y1, y2) + 0.5, my0, my1):
                        W.append("label %r (%s->%s) overlaps connector %s->%s" % (c.label, c.src, c.dst, c2.src, c2.dst))
            for c3, m3 in masks:
                if c3 is c:
                    continue
                if _open_overlap(mx0, mx1, m3[0], m3[0] + m3[2]) and _open_overlap(my0, my1, m3[1], m3[1] + m3[3]):
                    W.append("label masks collide: %r / %r" % (c.label, c3.label))
            if mx0 < 8 or my0 < 8 or mx1 > self.W - 8 or my1 > self.H - 60:
                W.append("label %r outside safe area" % c.label)
        for n in nodes:
            if n.x < 16 or n.y < 16 or n.x + n.w > self.W - 16 or n.y + n.h > self.H - 56:
                W.append("node %s near/out of canvas edge" % n.id)
        return W

    # rendering --------------------------------------------------------
    def _vsegs(self, skip):
        out = []
        for c in self.conns:
            if c is skip:
                continue
            for (x1, y1, x2, y2) in c.segments():
                if x1 == x2:
                    out.append((x1, min(y1, y2), max(y1, y2)))
        return out

    def _path(self, c, r=8):
        pts = c.pts
        vs = self._vsegs(c)
        d = "M%d,%d" % pts[0]
        pen = pts[0]
        n = len(pts)
        for i in range(1, n):
            p0, p1 = pts[i - 1], pts[i]
            dx = (p1[0] > p0[0]) - (p1[0] < p0[0])
            dy = (p1[1] > p0[1]) - (p1[1] < p0[1])
            last = i == n - 1
            ex = p1[0] if last else p1[0] - dx * r
            ey = p1[1] if last else p1[1] - dy * r
            if dy == 0 and dx != 0:
                lo, hi = min(pen[0], ex), max(pen[0], ex)
                hops = sorted([v[0] for v in vs
                               if lo + 12 <= v[0] <= hi - 12 and v[1] < p0[1] < v[2]],
                              reverse=(dx < 0))
                for cx in hops:
                    d += " H%d a8,8 0 0,%d %d,0" % (cx - dx * 8, 1 if dx > 0 else 0, dx * 16)
                d += " H%d" % ex
            elif dx == 0 and dy != 0:
                d += " V%d" % ey
            if not last:
                q = pts[i + 1]
                dx2 = (q[0] > p1[0]) - (q[0] < p1[0])
                dy2 = (q[1] > p1[1]) - (q[1] < p1[1])
                nx, ny = p1[0] + dx2 * r, p1[1] + dy2 * r
                d += " Q%d,%d %d,%d" % (p1[0], p1[1], nx, ny)
                pen = (nx, ny)
            else:
                pen = (ex, ey)
        return d

    def _render_node(self, n):
        k = KINDS[n.kind]
        dash = ' stroke-dasharray="%s"' % k["dash"] if k["dash"] else ""
        o = []
        o.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s"/>' % (n.x, n.y, n.w, n.h, PAPER))
        o.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s" stroke="%s" stroke-width="1"%s/>'
                 % (n.x, n.y, n.w, n.h, k["fill"], k["stroke"], dash))
        cx = n.x + n.w // 2
        if n.tag:
            tcol = k["stroke"] if n.kind in ("backend", "focal", "store", "input") else MUTED
            tw = ceil4(len(n.tag) * 5.6 + 8)
            o.append('<rect x="%d" y="%d" width="%d" height="12" rx="2" fill="transparent" stroke="%s" stroke-opacity="0.45" stroke-width="0.8"/>'
                     % (n.x + 8, n.y + 6, tw, tcol))
            o.append('<text x="%d" y="%d" fill="%s" fill-opacity="0.85" font-size="8" font-family="\'Geist Mono\', monospace" text-anchor="middle" letter-spacing="0.08em">%s</text>'
                     % (n.x + 8 + tw // 2, n.y + 15, k["stroke"], esc(n.tag)))
        nsub = len(n.sub)
        if n.center:
            ny = n.y + n.h // 2 - 4 * nsub + 4
        elif n.tag:
            ny = n.y + 38 if nsub else n.y + 40
        else:
            ny = n.y + (n.h // 2 + 4 - 6 * nsub)
        o.append('<text x="%d" y="%d" fill="%s" font-size="12" font-weight="600" font-family="\'Geist\', sans-serif" text-anchor="middle">%s</text>'
                 % (cx, ny, INK, esc(n.name)))
        for i, s in enumerate(n.sub):
            o.append('<text x="%d" y="%d" fill="%s" font-size="8" font-family="\'Geist Mono\', monospace" text-anchor="middle">%s</text>'
                     % (cx, ny + 16 + 12 * i, MUTED, esc(s)))
        return "\n".join(o)

    def svg(self):
        W, H = self.W, self.H
        o = []
        o.append('<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="%s-title %s-desc">'
                 % (W, H, self.slug, self.slug))
        o.append('<title id="%s-title">%s</title>' % (self.slug, esc(self.title)))
        o.append('<desc id="%s-desc">%s</desc>' % (self.slug, esc(self.desc)))
        o.append('<defs>')
        o.append('<marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="%s"/></marker>' % MUTED)
        o.append('<marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="%s"/></marker>' % ACCENT)
        o.append('<marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="%s"/></marker>' % LINK)
        o.append('</defs>')
        o.append('<rect width="100%%" height="100%%" fill="%s"/>' % PAPER)
        # zones
        for (x, y, w, h, label, lx) in self.zones:
            o.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="rgba(45,49,66,0.02)" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>' % (x, y, w, h))
            lwid = ceil4(len(label) * 7.4 + 12)
            o.append('<rect x="%d" y="%d" width="%d" height="12" rx="2" fill="%s"/>' % (x + lx, y + 4, lwid, PAPER))
            o.append('<text x="%d" y="%d" fill="rgba(45,49,66,0.45)" font-size="8" font-family="\'Geist Mono\', monospace" letter-spacing="0.14em">%s</text>'
                     % (x + lx + 6, y + 13, esc(label)))
        # connectors then labels
        for c in self.conns:
            col, mk = LINE_STYLES[c.style]
            dash = ' stroke-dasharray="4,3"' if c.dashed else ""
            sw = 1 if c.dashed else 1.2
            marker = ' marker-end="url(#%s)"' % mk if c.marker else ""
            o.append('<path d="%s" fill="none" stroke="%s" stroke-width="%s"%s%s/>' % (self._path(c), col, sw, dash, marker))
        for c in self.conns:
            m = self._label_rect(c)
            if m:
                x, y, w, h = m
                o.append('<rect x="%d" y="%d" width="%d" height="12" rx="2" fill="%s"/>' % (x, y, w, PAPER))
                o.append('<text x="%d" y="%d" fill="%s" font-size="8" font-family="\'Geist Mono\', monospace" text-anchor="middle" letter-spacing="0.06em">%s</text>'
                         % (x + w // 2, y + 9, SOFT, esc(c.label)))
        for n in self.nodes.values():
            o.append(self._render_node(n))
        o.append(self._legend())
        o.append('</svg>')
        return "\n".join(o)

    def _legend(self):
        W, H = self.W, self.H
        o = []
        o.append('<line x1="40" y1="%d" x2="%d" y2="%d" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>' % (H - 52, W - 40, H - 52))
        o.append('<text x="40" y="%d" fill="%s" font-size="8" font-family="\'Geist Mono\', monospace" letter-spacing="0.14em">LEGEND</text>' % (H - 28, MUTED))
        x = 112
        for kind, key, label in self.legend:
            if kind == "node":
                k = KINDS[key]
                dash = ' stroke-dasharray="%s"' % k["dash"] if k["dash"] else ""
                o.append('<rect x="%d" y="%d" width="20" height="12" rx="3" fill="%s" stroke="%s" stroke-width="1"%s/>' % (x, H - 38, k["fill"], k["stroke"], dash))
                x += 28
            else:
                col, mk = LINE_STYLES[key.replace("-dashed", "")]
                dash = ' stroke-dasharray="4,3"' if key.endswith("-dashed") else ""
                o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.2"%s marker-end="url(#%s)"/>' % (x, H - 32, x + 24, H - 32, col, dash, mk))
                x += 32
            o.append('<text x="%d" y="%d" fill="%s" font-size="8" font-family="\'Geist Mono\', monospace">%s</text>' % (x, H - 29, MUTED, esc(label)))
            x += ceil4(len(label) * 5.0) + 28
        assert x < W, "legend too wide for %s (%d)" % (self.slug, x)
        return "\n".join(o)

    def html(self):
        svg = self.svg()
        if self.wide:
            svgcss = "svg { width: %dpx; max-width: none; display: block; }" % self.W
        else:
            svgcss = "svg { width: 100%%; min-width: 900px; max-width: %dpx; display: block; }" % self.W
        paras = "\n".join("      <p>%s</p>" % esc(p) for p in self.explain)
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>%(title)s</title>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&family=Noto+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@400&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --color-paper: #f5f5f5; --color-ink: #2d3142; --color-muted: #4f5d75; --color-accent: #eb6c36;
      --font-sans: 'Geist', system-ui, sans-serif;
      --font-serif: 'Instrument Serif', 'Noto Serif KR', serif;
      --font-mono: 'Geist Mono', ui-monospace, monospace;
    }
    body { font-family: var(--font-sans); background: var(--color-paper); color: var(--color-ink); padding: 3rem 2rem; }
    .frame { width: max-content; max-width: 100%%; margin: 0 auto; }
    .eyebrow { font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase; color: var(--color-muted); margin-bottom: 0.5rem; }
    h1 { font-family: var(--font-serif); font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem); font-weight: 400; letter-spacing: -0.02em; line-height: 1.15; margin-bottom: 1.5rem; }
    .scroll { overflow-x: auto; }
    %(svgcss)s
    .explain { margin-top: 1.5rem; max-width: 72ch; font-size: 0.9rem; line-height: 1.55; color: var(--color-ink); }
    .explain p + p { margin-top: 0.6rem; }
    .explain .eyebrow { margin-bottom: 0.4rem; }
    .colophon { margin-top: 2rem; padding-top: 0.75rem; border-top: 1px solid rgba(45,49,66,0.12); font-family: var(--font-mono); font-size: 0.62rem; letter-spacing: 0.08em; color: var(--color-muted); }
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">%(eyebrow)s</p>
    <h1>%(title)s</h1>
    <div class="scroll">
%(svg)s
    </div>
    <div class="explain">
      <p class="eyebrow">In plain words</p>
%(paras)s
    </div>
    <p class="colophon">HR Chat Agent · sample policies are illustrative, not Ideas2IT's actual policy · source: docs/ARCHITECTURE.md (as built)</p>
  </div>
</body>
</html>
""" % dict(title=esc(self.title), eyebrow=esc(self.eyebrow), svg=svg, paras=paras, svgcss=svgcss)
