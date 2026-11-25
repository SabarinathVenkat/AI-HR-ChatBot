"""Builds the two RMG platform architecture diagrams (HTML with inline SVG, a standalone SVG, and a PNG each).

  python docs/diagrams/rmg-platform/build_rmg_platform.py

Outputs, next to this file:
  rmg-platform-overview.html / .svg / .png   one app, one Skill per task (the whole architecture)
  rmg-platform-skills.html / .svg / .png     the skill library: what is built, what is in the app, what is proposed
  *-titled.png                               the same picture with its title above it, for pasting into an email

This script is the source. Edit the text or the layout here and run it again; the PNG step needs Playwright with Chromium
(`pip install playwright` then `playwright install chromium`).

Style: the Diagram Design skill's editorial system, in the Ideas2IT portal colours. Slide size (1280x720, the "presentation"
type ramp: names 16, sublabels 12, arrow labels 12, eyebrows 8). Every coordinate is a multiple of 4.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1280, 720

PAPER = "#f4f6fb"
INK = "#0a1730"
MUTED = "#4a5a73"
SOFT = "#7a879c"
ACCENT = "#0d9488"   # teal: the one or two pieces that matter most
LINK = "#2563eb"     # blue: calls to and from Claude
RULE = "rgba(10,23,48,0.14)"

FONTS = ("https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600"
         "&family=Geist+Mono:wght@400;500;600&display=swap")

MONO = "'Geist Mono', monospace"
SANS = "'Geist', sans-serif"
SERIF = "'Instrument Serif', serif"

NODE_STYLES = {
    "app":   dict(fill="#ffffff", stroke=INK, sw=1, dash=None),
    "new":   dict(fill="rgba(10,23,48,0.02)", stroke="rgba(10,23,48,0.40)", sw=1, dash="4,3"),
    "focal": dict(fill="rgba(13,148,136,0.08)", stroke=ACCENT, sw=1.2, dash=None),
    "store": dict(fill="rgba(10,23,48,0.05)", stroke=MUTED, sw=1, dash=None),
    "input": dict(fill="rgba(74,90,115,0.10)", stroke=SOFT, sw=1, dash=None),
}


class Svg:
    """Collects drawing layers in z-order (zones, arrows, nodes, legend) and checks the layout rules before output."""

    def __init__(self, slug: str, title: str, desc: str):
        self.slug, self.title, self.desc = slug, title, desc
        self.zones, self.arrows, self.nodes, self.legend = [], [], [], []
        self.node_boxes: list[tuple[str, int, int, int, int]] = []
        self.masks: list[tuple[str, int, int, int, int]] = []

    # ---- zones ---------------------------------------------------------------------------------------------------
    def zone(self, x, y, w, h, label, kind="plain"):
        if kind == "boundary":   # a trust boundary: dashed, in the accent colour
            fill, stroke, dash = "rgba(13,148,136,0.04)", "rgba(13,148,136,0.55)", ' stroke-dasharray="4,4"'
        elif kind == "proposed":
            fill, stroke, dash = "rgba(10,23,48,0.015)", "rgba(10,23,48,0.30)", ' stroke-dasharray="4,3"'
        else:
            fill, stroke, dash = "rgba(10,23,48,0.025)", RULE, ""
        lw = round(len(label) * 5.92 + 12)
        cx = x + w // 2
        self.zones.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="0.8"{dash}/>'
            f'<rect x="{cx - lw // 2}" y="{y + 4}" width="{lw}" height="12" rx="2" fill="{PAPER}"/>'
            f'<text x="{cx}" y="{y + 13}" fill="{MUTED}" font-size="8" font-family="{MONO}" text-anchor="middle" '
            f'letter-spacing="0.14em">{esc(label)}</text>')

    # ---- arrows ----------------------------------------------------------------------------------------------------
    def path(self, d, color=MUTED, marker="arrow", dashed=False, width=1.2):
        dash = ' stroke-dasharray="4,3"' if dashed else ""
        end = f' marker-end="url(#{marker})"' if marker else ""
        self.arrows.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash}{end}/>')

    def hlabel(self, cx, y_line, text, color=SOFT):
        """A label above a horizontal segment, with a 6px gap between its mask and the stroke."""
        w = round(len(text) * 7.92 + 12)
        w += w % 2
        x, top = cx - w // 2, y_line - 22
        self.masks.append((text, x, top, w, 16))
        self.arrows.append(f'<rect x="{x}" y="{top}" width="{w}" height="16" rx="2" fill="{PAPER}"/>'
                           f'<text x="{cx}" y="{y_line - 10}" fill="{color}" font-size="12" font-family="{MONO}" '
                           f'text-anchor="middle" letter-spacing="0.06em">{esc(text)}</text>')

    def vlabel(self, x_line, y_mid, text, color=SOFT):
        """A label beside a vertical segment, 10px to its right."""
        w = round(len(text) * 7.92 + 12)
        w += w % 2
        x, top = x_line + 10, y_mid - 8
        self.masks.append((text, x, top, w, 16))
        self.arrows.append(f'<rect x="{x}" y="{top}" width="{w}" height="16" rx="2" fill="{PAPER}"/>'
                           f'<text x="{x + 6}" y="{y_mid + 4}" fill="{color}" font-size="12" font-family="{MONO}" '
                           f'letter-spacing="0.06em">{esc(text)}</text>')

    def raw_arrow(self, markup):
        self.arrows.append(markup)

    # ---- nodes -----------------------------------------------------------------------------------------------------
    def node(self, x, y, w, h, name, sub1="", sub2="", tag="", style="app"):
        s = NODE_STYLES[style]
        dash = f' stroke-dasharray="{s["dash"]}"' if s["dash"] else ""
        cx = x + w // 2
        parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>',
                 f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{s["fill"]}" stroke="{s["stroke"]}" '
                 f'stroke-width="{s["sw"]}"{dash}/>']
        if tag:
            tw = round(len(tag) * 5.4 + 12)
            tw += tw % 4
            parts.append(f'<rect x="{x + 8}" y="{y + 6}" width="{tw}" height="12" rx="2" fill="transparent" '
                         f'stroke="{s["stroke"]}" stroke-opacity="0.5" stroke-width="0.8"/>'
                         f'<text x="{x + 8 + tw // 2}" y="{y + 15}" fill="{s["stroke"]}" font-size="8" font-family="{MONO}" '
                         f'text-anchor="middle" letter-spacing="0.08em">{esc(tag)}</text>')
        top = y + 42 if sub1 else y + h // 2 + 6
        parts.append(f'<text x="{cx}" y="{top}" fill="{INK}" font-size="16" font-weight="600" font-family="{SANS}" '
                     f'text-anchor="middle">{esc(name)}</text>')
        if sub1:
            parts.append(f'<text x="{cx}" y="{y + 60}" fill="{MUTED}" font-size="12" font-family="{MONO}" '
                         f'text-anchor="middle">{esc(sub1)}</text>')
        if sub2:
            parts.append(f'<text x="{cx}" y="{y + 76}" fill="{MUTED}" font-size="12" font-family="{MONO}" '
                         f'text-anchor="middle">{esc(sub2)}</text>')
        self.nodes.append("".join(parts))
        self.node_boxes.append((name, x, y, w, h))

    def strip(self, x, y, w, h, line1, line2):
        """A wide caption box (not a component): one headline and one mono line."""
        cx = x + w // 2
        self.nodes.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#ffffff" stroke="{RULE}" stroke-width="1"/>'
            f'<text x="{cx}" y="{y + 26}" fill="{INK}" font-size="16" font-weight="600" font-family="{SANS}" '
            f'text-anchor="middle">{esc(line1)}</text>'
            f'<text x="{cx}" y="{y + 46}" fill="{MUTED}" font-size="12" font-family="{MONO}" text-anchor="middle">{esc(line2)}</text>')

    def message(self, text, y):
        self.nodes.append(f'<text x="{W // 2}" y="{y}" fill="{INK}" font-size="16" font-style="italic" font-family="{SERIF}" '
                          f'text-anchor="middle">{esc(text)}</text>')

    # ---- legend ----------------------------------------------------------------------------------------------------
    def legend_strip(self, items):
        y = H - 60
        out = [f'<line x1="40" y1="{y - 8}" x2="{W - 40}" y2="{y - 8}" stroke="{RULE}" stroke-width="0.8"/>',
               f'<text x="40" y="{y + 20}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">LEGEND</text>']
        x = 120
        for kind, text in items:
            if kind == "solid":
                out.append(f'<rect x="{x}" y="{y + 10}" width="24" height="12" rx="2" fill="#ffffff" stroke="{INK}"/>')
            elif kind == "teal":
                out.append(f'<rect x="{x}" y="{y + 10}" width="24" height="12" rx="2" fill="rgba(13,148,136,0.08)" stroke="{ACCENT}" stroke-width="1.2"/>')
            elif kind == "dashed":
                out.append(f'<rect x="{x}" y="{y + 10}" width="24" height="12" rx="2" fill="rgba(10,23,48,0.02)" '
                           f'stroke="rgba(10,23,48,0.40)" stroke-dasharray="4,3"/>')
            elif kind == "arrow":
                out.append(f'<line x1="{x}" y1="{y + 16}" x2="{x + 24}" y2="{y + 16}" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#arrow)"/>')
            elif kind == "link":
                out.append(f'<line x1="{x}" y1="{y + 16}" x2="{x + 24}" y2="{y + 16}" stroke="{LINK}" stroke-width="1.2" marker-end="url(#arrow-link)"/>')
            elif kind == "fail":
                out.append(f'<line x1="{x}" y1="{y + 16}" x2="{x + 24}" y2="{y + 16}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3" marker-end="url(#arrow)"/>')
            elif kind == "stop":
                out.append(f'<line x1="{x}" y1="{y + 16}" x2="{x + 16}" y2="{y + 16}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3"/>'
                           f'<line x1="{x + 20}" y1="{y + 8}" x2="{x + 20}" y2="{y + 24}" stroke="{INK}" stroke-width="2"/>')
            out.append(f'<text x="{x + 32}" y="{y + 20}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.08em">{esc(text)}</text>')
            x += 32 + round(len(text) * 5.4) + 28
        self.legend.append("".join(out))

    # ---- checks and output -------------------------------------------------------------------------------------------
    def check(self):
        """Fail loudly if a label mask overlaps a node (the node would cover the text) or a node is off the 4px grid."""
        problems = []
        for text, mx, my, mw, mh in self.masks:
            for name, nx, ny, nw, nh in self.node_boxes:
                if mx < nx + nw and mx + mw > nx and my < ny + nh and my + mh > ny:
                    problems.append(f"label '{text}' overlaps node '{name}'")
        for name, x, y, w, h in self.node_boxes:
            if any(v % 4 for v in (x, y, w, h)):
                problems.append(f"node '{name}' is off the 4px grid")
        if problems:
            raise SystemExit("Layout problems:\n  " + "\n  ".join(problems))

    def svg(self):
        self.check()
        return (
            f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-labelledby="{self.slug}-title {self.slug}-desc">\n'
            f'  <title id="{self.slug}-title">{esc(self.title)}</title>\n'
            f'  <desc id="{self.slug}-desc">{esc(self.desc)}</desc>\n'
            '  <defs>\n'
            f'    <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>\n'
            f'    <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>\n'
            f'    <marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{LINK}"/></marker>\n'
            '  </defs>\n'
            f'  <rect width="100%" height="100%" fill="{PAPER}"/>\n'
            + "\n".join(f"  {z}" for z in self.zones) + "\n"
            + "\n".join(f"  {a}" for a in self.arrows) + "\n"
            + "\n".join(f"  {n}" for n in self.nodes) + "\n"
            + "\n".join(f"  {leg}" for leg in self.legend) + "\n"
            '</svg>')


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =====================================================================================================================
# Diagram 1: the whole architecture
# =====================================================================================================================
def overview() -> Svg:
    d = Svg("rmg-platform-overview", "RMG platform: one app, one Skill per task",
            "Architecture of the RMG platform: people use the app, which owns sign-in, workflow, data and enforcement; a task "
            "router picks one Skill per task from a skill library that runs in Claude's isolated sandbox; every result comes "
            "back through the app's guardrails and a person's approval, and a Skill can never reach the data directly.")

    # zones: people | the app | Claude's isolated runtime
    d.zone(40, 80, 200, 260, "PEOPLE")
    d.zone(300, 80, 576, 440, "THE APP: OWNS IDENTITY, WORKFLOW, DATA, ENFORCEMENT")
    d.zone(936, 80, 304, 296, "CLAUDE: ISOLATED RUNTIME", kind="boundary")

    # arrows first (z-order), then nodes
    d.path("M228,164 H324")                                                   # 1 submit
    d.hlabel(276, 164, "1 SUBMIT")
    d.path("M548,164 H628")                                                   # 3 pick
    d.hlabel(588, 164, "3 PICK")
    d.path("M852,164 H956", color=LINK, marker="arrow-link")                  # 4 skill + files in
    d.hlabel(904, 164, "4 FILES IN", color=LINK)
    d.path("M1088,208 V264")                                                  # 5 run
    d.vlabel(1088, 236, "5 RUN SCRIPTS")
    d.path("M956,308 H852", color=LINK, marker="arrow-link")                  # 6 output back
    d.hlabel(904, 308, "6 OUTPUT", color=LINK)
    d.path("M628,308 H548")                                                   # pass
    d.hlabel(588, 308, "PASS")
    d.path("M740,264 V208", dashed=True, width=1)                             # 7 fail loop
    d.vlabel(740, 236, "7 FAIL: FIX")
    d.path("M436,352 V444 Q436,452 444,452 H628")                             # 9 record
    d.hlabel(536, 452, "9 RECORD")
    d.path("M324,308 H148 Q140,308 140,300 V208")                             # 9 delivered
    d.hlabel(236, 308, "9 DELIVERED")
    # the blocked shortcut: stops at the boundary of the app, never enters
    d.raw_arrow(f'<path d="M1088,352 V444 Q1088,452 1080,452 H892" fill="none" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3"/>')
    d.raw_arrow(f'<line x1="888" y1="440" x2="888" y2="464" stroke="{INK}" stroke-width="2"/>')
    d.hlabel(986, 452, "NO DIRECT DATA ACCESS")

    d.node(52, 120, 176, 88, "Users", "RMG staff, Associates", "Leads, Platform admin", style="input")
    d.node(324, 120, 224, 88, "Portal + Workflow", "2 sign-in, role check", "requests, versions", tag="BUILT")
    d.node(628, 120, 224, 88, "Task router", "3 picks the skill", "for the task type", tag="NEW", style="new")
    d.node(324, 264, 224, 88, "Human review", "8 approve or", "send back", tag="BUILT")
    d.node(628, 264, 224, 88, "Guardrails (in code)", "7 grounding, layout, schema", "fail: loop back or reject", tag="BUILT", style="focal")
    d.node(628, 408, 224, 88, "Data + audit log", "requests, versions, files", "JDs, HR data, secrets", tag="BUILT", style="store")
    d.node(956, 120, 264, 88, "Skill library", "SKILL.md + scripts + templates", "one skill per RMG task", tag="1 OF 6 BUILT", style="focal")
    d.node(956, 264, 264, 88, "Sandbox", "no internet, no installs", "files in, files out", tag="NEW", style="new")

    # hosting caption under the app
    d.nodes.append(f'<rect x="300" y="540" width="576" height="40" rx="6" fill="rgba(10,23,48,0.03)" stroke="{RULE}" stroke-width="0.8"/>'
                   f'<text x="588" y="564" fill="{MUTED}" font-size="12" font-family="{MONO}" text-anchor="middle">'
                   'HOSTED: Docker image on RunPod, network volume for data</text>')
    d.message("The app owns identity, workflow, data and enforcement. Skills own task know-how. A skill never touches the data directly.", 624)
    d.legend_strip([("solid", "BUILT TODAY"), ("dashed", "NEW"), ("teal", "KEY PIECE"), ("arrow", "PERMITTED PATH"),
                    ("link", "CALL TO CLAUDE"), ("fail", "FAIL LOOP"), ("stop", "BLOCKED")])
    return d


# =====================================================================================================================
# Diagram 2: the skill library
# =====================================================================================================================
def skills() -> Svg:
    d = Svg("rmg-platform-skills", "The RMG skill library: one Skill for each task",
            "The skill library: one Skill for the resume tailoring task is built today, two more tasks exist as app features and "
            "could become Skills, and three more are proposed; a task router picks the Skill for each task.")

    d.zone(296, 80, 944, 152, "BUILT TODAY")
    d.zone(296, 280, 944, 152, "PROPOSED", kind="proposed")

    # router to each group: two elbows from separate attach points on the router's right edge
    d.path("M232,232 H264 Q272,232 272,224 V164 Q272,156 280,156 H296")
    d.path("M232,280 H264 Q272,280 272,288 V348 Q272,356 280,356 H296")

    d.node(56, 212, 176, 88, "Task router", "picks by task type", "or skill description", tag="NEW", style="new")

    d.node(320, 120, 272, 88, "Resume tailoring", "rmg-resume-tailor", "Polish or Deep match", tag="SKILL", style="focal")
    d.node(632, 120, 272, 88, "JD briefing", "analysis + briefing", "written when a JD is added", tag="IN THE APP")
    d.node(944, 120, 272, 88, "Layout + template check", "Word file vs template", "fixed at download", tag="IN THE APP")

    d.node(320, 320, 272, 88, "Candidate matching", "ranks people for a JD", "gaps as questions", tag="PROPOSED", style="new")
    d.node(632, 320, 272, 88, "Availability + allocation", "who is free, and when", "uses HR leave data", tag="PROPOSED", style="new")
    d.node(944, 320, 272, 88, "Bench + skill gaps", "who is on the bench", "which skills to grow", tag="PROPOSED", style="new")

    d.strip(296, 460, 944, 64, "Every skill is a folder: SKILL.md + scripts + templates",
            "SKILL.md holds the rules and steps, scripts run the checks, templates hold the company files")
    d.message("Skills run in Claude's sandbox with no internet. The app passes files in and out and checks every result in code.", 624)
    d.legend_strip([("teal", "SKILL BUILT"), ("solid", "FEATURE IN THE APP TODAY"), ("dashed", "PROPOSED OR NEW"),
                    ("arrow", "ROUTES TO")])
    return d


# =====================================================================================================================
# Pages and export
# =====================================================================================================================
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link href="{fonts}" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --paper: {paper}; --ink: {ink}; --muted: {muted}; --serif: 'Instrument Serif', serif; --mono: 'Geist Mono', monospace; }}
    body {{ font-family: 'Geist', system-ui, sans-serif; background: var(--paper); color: var(--ink); min-height: 100vh;
           display: flex; align-items: center; justify-content: center; padding: 3rem 2rem; }}
    .frame {{ max-width: 1280px; width: 100%; padding: 1.5rem; }}
    .eyebrow {{ font-family: var(--mono); font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase;
               color: var(--muted); margin-bottom: 0.5rem; }}
    h1 {{ font-family: var(--serif); font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem); font-weight: 400; letter-spacing: -0.02em;
         line-height: 1.15; margin-bottom: 1.5rem; }}
    svg {{ width: 100%; min-width: 900px; display: block; }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">{eyebrow}</p>
    <h1>{title}</h1>
{svg}
  </div>
</body>
</html>
"""


def standalone_svg(svg_markup: str) -> str:
    """The diagram alone, as strict XML: the fonts are loaded with an @import (with & written as &amp;)."""
    style = ("<style>@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&amp;family=Geist:wght@400;500;600"
             "&amp;family=Geist+Mono:wght@400;500;600&amp;display=swap');</style>")
    merged = svg_markup.replace("<defs>", "<defs>\n    " + style, 1)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + merged + "\n"


def write(slug: str, diagram: Svg, eyebrow: str) -> Path:
    markup = diagram.svg()
    html = PAGE.format(title=diagram.title, fonts=FONTS, paper=PAPER, ink=INK, muted=MUTED, eyebrow=eyebrow,
                       svg="\n".join("    " + line for line in markup.splitlines()))
    page = HERE / f"{slug}.html"
    page.write_text(html, encoding="utf-8")
    (HERE / f"{slug}.svg").write_text(standalone_svg(markup), encoding="utf-8")
    return page


def png(pages: list[Path], scale: int = 2) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed, so no PNG was made. pip install playwright; playwright install chromium")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=scale, viewport={"width": 1400, "height": 900})
        for source in pages:
            page.goto(source.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.locator("svg").first.screenshot(path=str(source.with_suffix(".png")))  # the diagram alone
            page.locator(".frame").screenshot(path=str(source.with_name(source.stem + "-titled.png")))  # with its title
        browser.close()


def main() -> int:
    pages = [write("rmg-platform-overview", overview(), "RMG platform · architecture"),
             write("rmg-platform-skills", skills(), "RMG platform · the skill library")]
    png(pages)
    for page in pages:
        print("wrote", page.name, "and its .svg and .png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
