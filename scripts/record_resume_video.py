"""Record a captioned, narrated walkthrough of the resume builder, driving the real app with the real models.

    pip install imageio-ffmpeg edge-tts pypdfium2    # only for this script; not in requirements
    python scripts/record_resume_video.py            # needs ANTHROPIC_API_KEY in .env; a few cents of model use
    python scripts/record_resume_video.py --no-voice # silent, to check the walkthrough quickly

Writes into docs/video/ (git-ignored, because the files are large):
    resume_builder_walkthrough.mp4 / _narrated.mp4   screen recording, silent and with narration

It uses a temporary database and temporary file storage, so nothing real is touched. The sample resume and job
description are in scripts/demo_data (made up; make them with scripts/make_demo_documents.py). If the Ideas2IT
template is in app/rmg/doc/resume it is used (a local file, never committed); otherwise a generic demo template is.
Downloaded Word files are opened in Word, exported to PDF and shown in the video as pictures, so Word must be installed.

Narration is spoken by Microsoft's online neural voices through edge-tts, so the narration text (only the demo script
below, no data) is sent to that service. Edit NARRATION and re-run to change the words; clips are cached by content.
"""
import asyncio
import hashlib
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["HR_CHAT_AUTOSTART"] = "false"

import uvicorn  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "video"
AUDIO_DIR = OUT / "audio"
DATA = ROOT / "scripts" / "demo_data"
REAL_TEMPLATE = ROOT / "app" / "rmg" / "doc" / "resume" / "Sample Profile_Ideas2it.docx"
CAPTION_H = 64
TOTAL = 21

VOICE = "en-IN-NeerjaNeural"
RATE = "-4%"
GAP = 0.7

JD_TITLE = "Senior Java Developer, Fintech Payments"

NARRATION = {
    0: "This is the Resume Builder, a part of the RMG assistant. It helps an associate prepare a resume for one specific "
       "job, in the company template, without inventing anything. Four people take part. The RMG Head sets things up. "
       "RMG staff ask for resumes. The associate builds theirs with an assistant. And a Competency Lead approves it. "
       "Everything you will see is the real application with real AI models. The people and documents are samples.",
    1: "First, a one time setup by the RMG Head, Rhea. She uploads the company resume template, which is an ordinary "
       "Word file. Before it becomes active, the system checks it is safe, and that it has the parts a resume needs: "
       "name, summary, skills, highlights and projects. Here she tries an ordinary document by mistake, and it is "
       "refused with a clear list of what is missing. Then she uploads the real template, and it is accepted.",
    2: "Rhea also decides which Competency Lead approves which associate. Here four associates are mapped to Lakshmi "
       "Narayan. An associate with no Lead cannot be tagged for a resume, because nobody could approve it.",
    3: "Now RMG staff, Sam, gets a new job opening. He uploads the job description, a Word, PDF or text file. An AI "
       "model reads it into a structured list: the role, the minimum years, the must have skills and the nice to have "
       "skills. It is read once, stored, and can be used for many associates.",
    4: "Sam tags the associates who fit. Here, Ravi Kumar. He could tag several at once. People with no Competency "
       "Lead are listed separately and cannot be tagged. Each tagged person gets a request, and a notification.",
    5: "Ravi signs in, and the bell shows a notification. The request is in his own list. Only Ravi, his Lead and RMG "
       "can see it. For anyone else, it does not exist.",
    6: "Ravi uploads his current resume. The file is checked before anything else: its real type, its size, macros, "
       "password protection, and a limit of five pages. Then he clicks Build. Behind the scenes, an AI model reads the "
       "resume, each project is rewritten for this job, in parallel, and a safety check puts back anything that the "
       "original resume does not support.",
    7: "Here is the result. On the left are the job's requirements and a coverage score. It shows which required "
       "skills are in Ravi's resume, and which are not. A skill he does not have, like Kubernetes, is shown as not in "
       "his resume, and it is never added. Notice also the warning: the job description contained a sentence trying to "
       "give orders to an AI. Documents are treated as untrusted, so it was flagged and ignored.",
    8: "In the middle is the tailored resume. Any line that was reworded carries a tag. On the right is the change "
       "list: what moved, what was reworded, what was dropped, each with before and after, and the reason. It is "
       "computed by code from the two resumes, so it cannot disagree with what really changed. The experience years "
       "are also computed by code from his dates, not by the model.",
    9: "Ravi stays in control. He can edit any line by hand. When he saves, the change list updates straight away.",
    10: "He can remove a line, and move projects up or down. Each of these shows up in the change list too.",
    11: "If something is true but missing from his resume, he can add it as his own statement. It is clearly tagged as "
        "added by you, so the Lead can tell what came from Ravi, rather than from his original resume.",
    12: "He can also ask in plain words. The assistant only picks one edit from a fixed list, and the system checks it "
        "before applying it. He asks for a shorter bullet. He asks what has changed. Then he asks it to mention "
        "Kubernetes, which his resume does not have, and it refuses, and offers to add it as his own statement. The "
        "assistant can reword, but it cannot invent. And he can undo.",
    13: "Ravi can download a draft at any time, in the company template. Until the Lead approves, every download "
        "carries a diagonal DRAFT watermark, so an unapproved resume cannot be mistaken for a final one.",
    14: "Ravi saves a version, and submits for review. Only the associate can submit. While the Lead reviews, editing "
        "is locked.",
    15: "Lakshmi, the Competency Lead, signs in and gets a notification. She sees the resume, the change list, and "
        "anything Ravi added himself, marked for her attention. Only the Lead mapped to this associate can decide.",
    16: "She wants more detail, so she sends it back. A note is required, so the associate knows what to change.",
    17: "Ravi gets a notification, and the status is now changes requested, with her note at the top. He revises, "
        "saves, and submits again.",
    18: "Lakshmi reviews again, and approves.",
    19: "Sam sees on the board that it is approved, with its coverage. He downloads the final resume. This time there "
        "is no watermark, and no draft mark in the file name. Only the approved version is clean.",
    20: "If an approved resume needs to change, the associate can reopen it. The approval is cleared, and the next save "
        "becomes a new version, so the history is kept.",
    21: "That was the whole journey. The assistant rewords but never invents skills. Facts such as experience years are "
        "computed by code. Job descriptions and resumes are treated as untrusted. Every person sees only what is "
        "theirs. Everyone is notified, every version is kept, and only a Lead's approval removes the draft mark. "
        "Thank you.",
}

INIT_SCRIPT = """
(() => {
  const setup = () => {
    const bar = document.createElement('div');
    bar.id = 'demo-caption';
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;height:%(h)dpx;background:#0a1730;color:#fff;' +
      'display:flex;align-items:center;gap:14px;padding:0 20px;z-index:2147483647;box-sizing:border-box;' +
      'font-family:system-ui,Segoe UI,Arial,sans-serif;border-top:3px solid #2563eb;overflow:hidden';
    const badge = document.createElement('span');
    badge.id = 'demo-badge';
    badge.style.cssText = 'background:#2563eb;border-radius:999px;padding:3px 12px;font-weight:700;font-size:14px;white-space:nowrap';
    const text = document.createElement('div');
    text.style.cssText = 'display:flex;flex-direction:column;min-width:0';
    const title = document.createElement('span');
    title.id = 'demo-title';
    title.style.cssText = 'font-weight:700;font-size:18px;line-height:1.2';
    const detail = document.createElement('span');
    detail.id = 'demo-detail';
    detail.style.cssText = 'color:#c4d2ea;font-size:14px;line-height:1.25';
    text.append(title, detail);
    bar.append(badge, text);
    document.body.append(bar);

    const dot = document.createElement('div');
    dot.style.cssText = 'position:fixed;width:20px;height:20px;border-radius:50%%;background:rgba(251,146,60,.9);' +
      'border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.3);z-index:2147483646;pointer-events:none;' +
      'left:-60px;top:-60px;transform:translate(-50%%,-50%%);transition:transform .08s';
    document.body.append(dot);
    document.addEventListener('mousemove', (e) => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', () => { dot.style.transform = 'translate(-50%%,-50%%) scale(.65)'; }, true);
    document.addEventListener('mouseup', () => { dot.style.transform = 'translate(-50%%,-50%%) scale(1)'; }, true);

    const chat = document.getElementById('chat-screen');
    if (document.body.classList.contains('rb')) {
      document.body.style.setProperty('padding-bottom', '%(h)dpx');
    } else if (chat) {
      chat.style.setProperty('min-height', '0', 'important');
      chat.style.setProperty('height', (window.innerHeight - %(h)d) + 'px', 'important');
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();
})();
""" % {"h": CAPTION_H}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_app() -> tuple[uvicorn.Server, str]:
    load_dotenv(ROOT / ".env")
    work = Path(tempfile.mkdtemp())
    os.environ["DB_PATH"] = str(work / "video.db")
    os.environ["DEMO_DATA"] = "true"
    os.environ["RESUME_STORE_DIR"] = str(work / "files")
    from app.config import Settings
    from app.server import create_production_app

    settings = Settings.from_env()
    print(f"models: answer={settings.answer_model} router={settings.router_model}", flush=True)
    app = create_production_app(settings)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server, f"http://127.0.0.1:{port}"


# ---------- narration ----------
def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def narration_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        import imageio_ffmpeg  # noqa: F401
    except ImportError:
        print("edge-tts or imageio-ffmpeg is not installed, so only a silent video will be written")
        return False
    return True


def audio_seconds(path: Path) -> float:
    info = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def narration_clip(text: str) -> tuple[Path, float]:
    """Speech for `text`, cached by content. Generated in a worker thread, because Playwright's own event loop is
    running in this one and asyncio.run cannot start a second loop here."""
    import edge_tts
    from concurrent.futures import ThreadPoolExecutor

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / (hashlib.sha1(f"{VOICE}|{RATE}|{text}".encode()).hexdigest()[:16] + ".mp3")
    if not path.exists() or path.stat().st_size < 2000:
        partial = path.with_suffix(".part")  # written under another name, so a failed download never leaves a bad clip
        partial.unlink(missing_ok=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(str(partial)))).result()
        partial.replace(path)
    return path, audio_seconds(path)


def pregenerate() -> None:
    """Make every narration clip before recording starts, so no scene waits on the voice service."""
    for number, text in NARRATION.items():
        narration_clip(text)
        print(f"  narration {number} ready", flush=True)


class Narrator:
    """Places narration on the video timeline and holds the scene until each clip has finished."""

    def __init__(self, page, enabled: bool) -> None:
        self.page, self.enabled = page, enabled
        self.t0 = time.monotonic()
        self.clips: list[tuple[float, Path]] = []
        self.busy_until = 0.0

    def now(self) -> float:
        return time.monotonic() - self.t0

    def wait(self) -> None:
        remaining = self.busy_until - self.now()
        if remaining > 0:
            self.page.wait_for_timeout(int(remaining * 1000))

    def say(self, text: str) -> None:
        if not self.enabled:
            return
        self.wait()
        path, seconds = narration_clip(text)
        start = self.now()
        self.clips.append((start, path))
        self.busy_until = start + seconds + GAP


def mux(video: Path, clips: list[tuple[float, Path]], target: Path) -> None:
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video)]
    for _, path in clips:
        cmd += ["-i", str(path)]
    delays = [f"[{i}:a]adelay={int(start * 1000)}:all=1[a{i}]" for i, (start, _) in enumerate(clips, start=1)]
    labels = "".join(f"[a{i}]" for i in range(1, len(clips) + 1))
    graph = ";".join(delays + [f"{labels}amix=inputs={len(clips)}:normalize=0:dropout_transition=0[aout]"])
    cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "22", "-preset", "medium", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target)]
    subprocess.run(cmd, check=True)


def to_mp4(webm: Path) -> Path:
    mp4 = webm.with_suffix(".mp4")
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "22", "-preset", "medium", "-movflags", "+faststart", str(mp4)], check=True)
    return mp4


# ---------- driving the page like a person ----------
def caption(page, badge: str, title: str, detail: str = "") -> None:
    page.evaluate("""([b, t, d]) => {
        document.getElementById('demo-badge').textContent = b;
        document.getElementById('demo-title').textContent = t;
        document.getElementById('demo-detail').textContent = d;
    }""", [badge, title, detail])


def point(page, locator, pause: int = 300):
    """Move the pointer onto an element, first scrolling it clear of the sticky header and the caption bar."""
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    if box["y"] + box["height"] > 800 - CAPTION_H - 12 or box["y"] < 80:
        locator.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
        page.wait_for_timeout(250)
        box = locator.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y, steps=22)
    page.wait_for_timeout(pause)
    return x, y


def click(page, locator, pause: int = 300) -> None:
    x, y = point(page, locator, pause)
    page.mouse.click(x, y)


def type_into(page, locator, text: str, replace: bool = False) -> None:
    click(page, locator)
    if replace:
        page.keyboard.press("Control+A")
    page.keyboard.type(text, delay=28)
    page.wait_for_timeout(350)


def choose_file(page, selector: str, path: Path) -> None:
    locator = page.locator(selector)
    point(page, locator, 500)
    locator.set_input_files(str(path))
    page.wait_for_timeout(500)


def say_flash(page, text: str, timeout: int = 60000) -> None:
    expect(page.locator("#message")).to_contain_text(text, timeout=timeout)


def view_button(page, name: str):
    return page.locator("#view").get_by_role("button", name=name)


def open_builder(page) -> None:
    link = page.get_by_role("link", name="Resume builder")
    expect(link).to_be_visible(timeout=20000)
    click(page, link)
    expect(page.locator("#who")).not_to_be_empty(timeout=20000)
    page.wait_for_timeout(900)


def login_as(page, name: str) -> None:
    expect(page.locator("#demo-list button")).to_have_count(13)
    page.wait_for_timeout(900)
    click(page, page.get_by_role("button", name=re.compile(rf"^{name}")))
    page.wait_for_timeout(600)
    click(page, page.get_by_role("button", name="Sign in"))
    expect(page.locator("#chat-screen")).to_be_visible(timeout=30000)
    page.wait_for_timeout(700)
    open_builder(page)


def logout(page) -> None:
    click(page, page.locator("#sign-out"))
    expect(page.locator("#login-screen")).to_be_visible()
    page.wait_for_timeout(700)


def open_request(page) -> None:
    click(page, view_button(page, "Open").first)
    expect(page.locator(".rb-bar .badge")).to_be_visible(timeout=20000)
    page.wait_for_timeout(1200)


def show_notifications(page, hold: int = 3500) -> None:
    click(page, page.locator("#bell"))
    page.wait_for_timeout(hold)
    click(page, page.locator("#bell"))
    page.wait_for_timeout(500)


def scroll_to(page, selector: str, hold: int = 2500) -> None:
    locator = page.locator(selector).first
    locator.scroll_into_view_if_needed()
    point(page, locator, 600)
    page.wait_for_timeout(hold)


def docx_to_pngs(docx: Path, folder: Path) -> list[Path]:
    """Open a .docx in Word, export it to PDF, and render each page to a PNG that looks like the real document."""
    import pypdfium2

    pdf = folder / (docx.stem + ".pdf")
    script = ("$w = New-Object -ComObject Word.Application; $w.Visible = $false; try { "
              f"$d = $w.Documents.Open('{docx}', $false, $true); $d.ExportAsFixedFormat('{pdf}', 17); $d.Close($false) "
              "} finally { try { $w.Quit() } catch {} }")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=180)
    if not pdf.exists():
        raise RuntimeError("Word did not produce a PDF; is Word installed?")
    document = pypdfium2.PdfDocument(str(pdf))
    pages = []
    for number in range(len(document)):
        target = folder / f"{docx.stem}_p{number + 1}.png"
        document[number].render(scale=1.5).to_pil().save(target)
        pages.append(target)
    return pages


def show_pages(page, images: list[Path], title: str) -> None:
    """A full-screen overlay with the pages of a downloaded Word file, as pictures."""
    import base64

    sources = ["data:image/png;base64," + base64.b64encode(p.read_bytes()).decode() for p in images]
    page.evaluate("""([sources, title, h]) => {
        const old = document.getElementById('demo-overlay'); if (old) old.remove();
        const o = document.createElement('div'); o.id = 'demo-overlay';
        o.style.cssText = 'position:fixed;left:0;right:0;top:0;bottom:' + (h + 3) + 'px;background:rgba(7,15,32,.97);z-index:2147483645;' +
          'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:14px;box-sizing:border-box';
        const t = document.createElement('div'); t.textContent = title; t.style.cssText = 'color:#fff;font:600 20px system-ui';
        const row = document.createElement('div'); row.style.cssText = 'display:flex;gap:18px;align-items:flex-start;justify-content:center';
        for (const src of sources) {
          const i = document.createElement('img'); i.src = src;
          i.style.cssText = 'height:calc(100vh - ' + (h + 110) + 'px);width:auto;border:1px solid #334;box-shadow:0 8px 30px rgba(0,0,0,.5);background:#fff';
          row.append(i);
        }
        o.append(t, row); document.body.append(o);
    }""", [sources, title, CAPTION_H])


def hide_pages(page) -> None:
    page.evaluate("() => { const o = document.getElementById('demo-overlay'); if (o) o.remove(); }")


def chat(page, message: str, timeout: int = 120000) -> str:
    before = page.locator(".rb-chat-log .bot").count()
    type_into(page, page.locator("#chat-input"), message)
    click(page, page.locator("#chat-send"))
    expect(page.locator(".rb-chat-log .bot")).to_have_count(before + 1, timeout=timeout)
    reply = page.locator(".rb-chat-log .bot").last.inner_text()
    print(f"  chat {message!r} -> {reply[:120]!r}", flush=True)
    page.wait_for_timeout(2200)
    return reply


# ---------- the walkthrough ----------
def walkthrough(browser, url: str, narrate: bool, template: Path) -> tuple[Path, list[tuple[float, Path]]]:
    work = Path(tempfile.mkdtemp())
    size = {"width": 1280, "height": 800}
    ctx = browser.new_context(viewport=size, record_video_dir=str(work), record_video_size=size, bypass_csp=True,
                              accept_downloads=True)
    ctx.add_init_script(INIT_SCRIPT)
    page = ctx.new_page()
    talk = Narrator(page, narrate)
    state = {"n": None}
    failure = None
    started = time.time()
    page.on("dialog", lambda dialog: dialog.accept())

    def step(n: int, title: str, detail: str = "") -> None:
        if n != state["n"]:
            talk.wait()
            state["n"] = n
            caption(page, f"{n} of {TOTAL}", title, detail)
            talk.say(NARRATION[n])
        else:
            caption(page, f"{n} of {TOTAL}", title, detail)

    def download(button_selector: str, name: str, title: str) -> Path:
        with page.expect_download(timeout=120000) as info:
            click(page, page.locator(button_selector))
        target = work / name
        info.value.save_as(str(target))
        caption(page, f"{state['n']} of {TOTAL}", "Opening the downloaded file in Word", "Shown here exactly as Word renders it")
        pages = docx_to_pngs(target, work)
        show_pages(page, pages, title)
        page.wait_for_timeout(9000)
        hide_pages(page)
        return target

    try:
        page.goto(url)
        caption(page, "Intro", "Resume Builder", "From a job opening to an approved, tailored resume, with the real application and models")
        talk.say(NARRATION[0])
        talk.wait()

        # 1 RMG Head: template
        step(1, "RMG Head: set up the resume template", "A Word template, checked for safety and for the parts a resume needs")
        login_as(page, "Rhea Kapoor")
        click(page, page.get_by_role("button", name="Setup"))
        page.wait_for_timeout(1200)
        choose_file(page, "#tpl-file", DATA / "senior_java_developer_jd.docx")  # not a template: must be refused
        click(page, page.locator("#tpl-go"))
        expect(page.locator("#message")).to_have_class(re.compile("error"), timeout=60000)
        page.wait_for_timeout(4500)
        choose_file(page, "#tpl-file", template)
        click(page, page.locator("#tpl-go"))
        say_flash(page, "Template uploaded", timeout=120000)
        page.wait_for_timeout(3500)

        # 2 Lead mapping
        step(2, "Who approves whom: the Competency Lead mapping", "An associate with no Lead cannot be tagged")
        point(page, page.locator("#map-table"), 800)
        page.wait_for_timeout(5000)
        logout(page)

        # 3 RMG staff: job description
        step(3, "RMG staff: add the job description", "An AI model reads it into role, years, must-have and nice-to-have skills")
        login_as(page, "Sam Joseph")
        choose_file(page, "#jd-file", DATA / "senior_java_developer_jd.docx")
        type_into(page, page.locator("#jd-title"), JD_TITLE)
        click(page, page.locator("#jd-go"))
        say_flash(page, "Job description added", timeout=180000)
        page.wait_for_timeout(2500)

        # 4 tag
        step(4, "Tag the associates who fit the job", "One request per person; people with no Lead cannot be tagged")
        page.locator("#tag-jd").select_option(label=JD_TITLE)
        point(page, page.locator("#tag-people"), 600)
        click(page, page.locator("#tag-people .rb-check", has_text="Ravi Kumar"))
        point(page, page.locator("#blocked-people"), 600)
        page.wait_for_timeout(2500)
        click(page, page.locator("#tag-go"))
        say_flash(page, "Tagged 1")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(2500)
        point(page, page.locator(".rb-table"), 600)
        page.wait_for_timeout(2500)
        logout(page)

        # 5 associate sees it
        step(5, "The associate sees the request and a notification", "Only the associate, their Lead and RMG can see a request")
        login_as(page, "Ravi Kumar")
        show_notifications(page)
        open_request(page)

        # 6 upload and build
        step(6, "Upload the resume and build the tailored draft", "Checked on upload, then read, tailored in parallel and safety-checked")
        choose_file(page, "#resume-file", DATA / "ravi_kumar_resume.docx")
        click(page, page.locator("#upload-resume"))
        say_flash(page, "Resume uploaded")
        page.wait_for_timeout(2500)
        click(page, page.locator("#build"))
        expect(page.locator("#resume")).to_contain_text("Ravi Kumar", timeout=300000)
        say_flash(page, "tailored draft is ready")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(2500)

        # 7 requirements and coverage
        step(7, "Job requirements, coverage and what is not claimed", "Missing skills are never added; instructions hidden in the job description are ignored")
        scroll_to(page, "#coverage", 4500)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1500)
        if page.locator(".rb-warn").count():
            point(page, page.locator(".rb-warn").first, 600)
            page.wait_for_timeout(3000)

        # 8 resume and change log
        step(8, "The tailored resume and the change list", "Tags show what was reworded; the list is computed by code, with before and after")
        scroll_to(page, "#resume .rb-project", 3500)
        scroll_to(page, "#changes", 4000)

        # 9 edit by hand
        step(9, "Edit by hand", "Every line can be changed; the change list updates")
        last_project = page.locator("#resume .rb-project").last
        bullet = last_project.locator(".rb-bullet").first
        current = bullet.locator(".text").inner_text().strip().rstrip(".")
        click(page, bullet.locator(".edit"))
        type_into(page, page.get_by_label("New wording"), f"{current} for the HR team.", replace=True)
        click(page, page.locator(".save-edit"))
        say_flash(page, "Done")
        page.wait_for_timeout(2500)
        scroll_to(page, "#changes", 2500)

        # 10 remove and move
        step(10, "Remove lines and move projects", "Each change appears in the change list")
        project_name = page.locator("#resume .rb-project .pname").first
        click(page, page.locator("#resume .rb-project").first.get_by_role("button", name="Move down project"))
        say_flash(page, "Done")
        page.wait_for_timeout(2500)
        last = page.locator("#resume .rb-project").last
        click(page, last.locator(".rb-bullet").last.locator(".remove"))
        say_flash(page, "Done")
        page.wait_for_timeout(2500)
        scroll_to(page, "#changes", 2500)
        del project_name

        # 11 add a fact
        step(11, "Add a fact of your own", "Added as your own statement, and marked for the Lead")
        click(page, page.locator("#resume .add-fact").first)
        type_into(page, page.get_by_label("A fact about you"), "Mentored two junior engineers on secure coding practices.")
        click(page, page.locator(".save-fact"))
        say_flash(page, "Done")
        page.wait_for_timeout(2500)
        scroll_to(page, "#resume .badge.o-user_added", 2500)

        # 12 chat
        step(12, "Ask for changes in plain words", "The assistant picks one checked edit; it can reword but never invent")
        scroll_to(page, "#chat", 800)
        chat(page, "Make the first bullet of the Payment Gateway project shorter.")
        chat(page, "What did you change so far?")
        chat(page, "Mention Kubernetes in the Payment Gateway description.")
        chat(page, "Undo my last change.")

        # 13 draft download
        step(13, "Download a draft", "Every unapproved download carries a DRAFT watermark")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1200)
        download("#download", "ravi_draft.docx", "Draft download: watermark on every page")

        # 14 save and submit
        step(14, "Save a version and submit for review", "Only the associate can submit; editing is then locked")
        click(page, page.locator("#save"))
        say_flash(page, "Saved as version")
        page.wait_for_timeout(2000)
        click(page, page.locator("#submit"))
        say_flash(page, "Submitted")
        page.wait_for_timeout(3500)
        logout(page)

        # 15 lead reviews
        step(15, "The Competency Lead reviews", "She sees the changes, and anything the associate added himself")
        login_as(page, "Lakshmi Narayan")
        show_notifications(page)
        open_request(page)
        scroll_to(page, "#changes", 3000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1500)

        # 16 send back
        step(16, "Send it back, with a note", "A note is required so the associate knows what to change")
        click(page, page.locator("#send-back"))
        say_flash(page, "Please say what needs to change")
        page.wait_for_timeout(2500)
        type_into(page, page.locator("#decision-note"), "Please add more detail about the Kafka work in Payment Gateway.")
        click(page, page.locator("#send-back"))
        say_flash(page, "Sent back")
        page.wait_for_timeout(3000)
        logout(page)

        # 17 associate revises
        step(17, "The associate sees the note and revises", "Status: changes requested; the note is shown at the top")
        login_as(page, "Ravi Kumar")
        show_notifications(page)
        open_request(page)
        point(page, page.locator("#decision-note-shown"), 600)
        page.wait_for_timeout(3500)
        first_bullet = page.locator("#resume .rb-project .rb-bullet").first
        text = first_bullet.locator(".text").inner_text().strip().rstrip(".")
        click(page, first_bullet.locator(".edit"))
        type_into(page, page.get_by_label("New wording"), f"{text}, as the lead engineer.", replace=True)
        click(page, page.locator(".save-edit"))
        say_flash(page, "Done")
        page.wait_for_timeout(2000)
        click(page, page.locator("#save"))
        say_flash(page, "Saved as version")
        click(page, page.locator("#submit"))
        say_flash(page, "Submitted")
        page.wait_for_timeout(3000)
        logout(page)

        # 18 approve
        step(18, "The Competency Lead approves", "Approval creates the approved version")
        login_as(page, "Lakshmi Narayan")
        open_request(page)
        click(page, page.locator("#approve"))
        say_flash(page, "Approved")
        page.wait_for_timeout(3500)
        logout(page)

        # 19 RMG downloads final
        step(19, "RMG downloads the approved resume", "No watermark and no draft mark: only an approved resume is clean")
        login_as(page, "Sam Joseph")
        point(page, page.locator(".rb-table"), 600)
        page.wait_for_timeout(2500)
        open_request(page)
        download("#download", "ravi_final.docx", "Approved download: no watermark")
        logout(page)

        # 20 reopen
        step(20, "Reopen an approved resume", "Approval is cleared and the next save is a new version")
        login_as(page, "Ravi Kumar")
        open_request(page)
        scroll_to(page, "text=Versions", 2500)
        page.evaluate("window.scrollTo(0, 0)")
        click(page, page.locator("#reopen"))
        expect(page.locator(".rb-bar .badge")).to_have_text("In progress", timeout=30000)
        page.wait_for_timeout(3500)

        talk.wait()
        step(21, "That was the whole journey", "Never invents skills. Facts computed by code. Everyone sees only what is theirs.")
        page.wait_for_timeout(1000)
        talk.wait()
        page.wait_for_timeout(1500)
        print(f"walkthrough took {time.time() - started:.0f} s", flush=True)
    except Exception as exc:  # keep what was recorded, then report the failure
        failure = exc
        page.screenshot(path=str(work / "failure.png"))
    finally:
        ctx.close()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "resume_builder_walkthrough.webm"
    page.video.save_as(str(target))
    if failure:
        print(f"stopped early ({type(failure).__name__}: {str(failure)[:300]}); partial video saved to {target}; "
              f"screenshot in {work}")
        raise failure
    return target, talk.clips


def main() -> None:
    narrate = "--no-voice" not in sys.argv and narration_available()
    template = REAL_TEMPLATE
    if not template.exists() or "--demo-template" in sys.argv:
        from app.rmg.resume.demo_template import make_demo_template

        template = Path(tempfile.mkdtemp()) / "demo_template.docx"
        template.write_bytes(make_demo_template())
    print("template:", template.name, flush=True)
    if narrate:
        pregenerate()
    server, url = start_app()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            webm, clips = walkthrough(browser, url, narrate, template)
            browser.close()
    finally:
        server.should_exit = True
    files = [webm, to_mp4(webm)]
    if clips:
        narrated = webm.with_name(webm.stem + "_narrated.mp4")
        mux(webm, clips, narrated)
        files.append(narrated)
    for f in files:
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")
    print("saved to", OUT)


if __name__ == "__main__":
    main()
