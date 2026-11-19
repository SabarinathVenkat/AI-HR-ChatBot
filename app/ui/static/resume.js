/* Resume builder screens.
 * Like the chat app, everything dynamic is built with DOM APIs and textContent, never innerHTML, so a resume, a job
 * description or a model reply can never inject markup. Pairs with the strict Content-Security-Policy. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "hr_token";
  const state = {
    token: sessionStorage.getItem(TOKEN_KEY), user: null, roles: [], tab: null, detail: null,
    editing: null, addingFact: null, addingSkill: null, scoreDelta: null, listedDelta: null, pendingTab: false, chat: [], busy: false,
  };
  if (!state.token) { location.replace("/"); return; }

  const STATUS = {
    requested: "Requested", in_progress: "In progress", submitted: "Waiting for review",
    changes_requested: "Changes requested", approved: "Approved", cancelled: "Cancelled",
  };
  const KIND = {
    reworded: "Reworded", emphasised: "Emphasised", condensed: "Condensed", dropped: "Dropped", reordered: "Reordered",
    rejected: "Rejected", added_by_you: "Added by you",
  };

  /* ---------- helpers ---------- */
  function h(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "on") for (const [ev, fn] of Object.entries(value)) node.addEventListener(ev, fn);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const kid of kids.flat()) if (kid) node.append(kid);
    return node;
  }
  const initials = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
  const isRmg = () => state.roles.includes("rmg_staff") || state.roles.includes("rmg_head");
  const badge = (text, cls) => h("span", { class: `badge ${cls || ""}`, text });
  const statusBadge = (status) => badge(STATUS[status] || status, `s-${status}`);
  const pct = (x) => (x === null || x === undefined ? "n/a" : `${Math.round(x * 100)}%`);

  function flash(text, kind = "") {
    const el = $("message");
    el.textContent = text || "";
    el.className = `rb-message ${kind}`;
    el.hidden = !text;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${state.token}` } });
    if (response.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
      location.replace("/");
      throw new Error("unauthorized");
    }
    return response;
  }
  async function call(path, options) {
    const response = await api(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error((body.error && body.error.message) || "Something went wrong. Please try again.");
    return body;
  }
  const post = (path, data) => call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}) });
  const upload = (path, file) => call(path, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });

  /* Run an action; show its error instead of failing silently. */
  async function attempt(fn, busyText) {
    if (state.busy) return;
    state.busy = true;
    if (busyText) flash(busyText);
    try {
      await fn();
    } catch (error) {
      if (error.message !== "unauthorized") flash(error.message, "error");
    } finally {
      state.busy = false;
      if (state.pendingTab) {  // a tab was clicked while something was loading: go there now
        state.pendingTab = false;
        attempt(renderTab);
      }
    }
  }

  /* Switching tab is navigation, not an action that could be repeated by mistake, so a click made while the screen is
     still loading is remembered and applied afterwards instead of being thrown away. */
  function goToTab(id) {
    state.tab = id;
    flash("");
    if (state.busy) state.pendingTab = true;
    else attempt(renderTab);
  }

  /* ---------- notifications ---------- */
  async function loadNotes() {
    try {
      const { notifications } = await call("/resume/notifications");
      const unread = notifications.filter((n) => !n.read_at).length;
      $("bell-count").textContent = String(unread);
      $("bell-count").hidden = unread === 0;
      $("notes-list").replaceChildren(...(notifications.length
        ? notifications.map((n) => h("li", { class: "rb-item" }, h("span", { class: n.read_at ? "muted" : "title", text: n.message })))
        : [h("li", { class: "rb-empty", text: "No notifications." })]));
    } catch (error) { /* not essential */ }
  }

  /* ---------- lists ---------- */
  function requestItem(r, extra) {
    return h("li", { class: "rb-item" },
      h("div", {},
        h("div", { class: "title", text: `${r.jd_title}` }),
        h("div", { class: "sub", text: `${r.associate} · Lead: ${r.lead}` + (r.coverage ? ` · Required skills covered: ${pct(r.coverage.required_after)}` : "") })),
      h("div", { class: "rb-row" }, statusBadge(r.status), extra,
        h("button", { class: "btn", type: "button", on: { click: () => openRequest(r.id) } }, "Open")));
  }

  /* ---------- the landing page: a dashboard for the person who signed in ---------- */
  const SVG_NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, ...kids) => {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) if (value !== null && value !== undefined) node.setAttribute(key, value);
    for (const kid of kids.flat()) if (kid) node.append(kid);
    return node;
  };
  const calm = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const DASH_SCOPE = {
    all: "Every resume request across RMG",
    lead: "Resume requests from the associates you are Competency Lead for",
    mine: "Your own resume requests",
  };

  /* Numbers count up to their value; with reduced motion they simply appear. */
  function countUp(el, target, decimals = 0, suffix = "") {
    const show = (v) => { el.textContent = v.toFixed(decimals) + suffix; };
    if (calm() || !target) { show(target || 0); return; }
    const began = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - began) / 900);
      show(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(tick); else show(target);
    };
    show(0);
    requestAnimationFrame(tick);
  }

  /* Run `grow` on the next frame, so a CSS transition has a starting point to move from. */
  const afterPaint = (grow) => (calm() ? grow() : requestAnimationFrame(() => requestAnimationFrame(grow)));

  function kpi(tone, label, value, sub, opts = {}) {
    const num = h("div", { class: "num" });
    countUp(num, value, opts.decimals || 0, opts.suffix || "");
    return h("div", { class: `rb-kpi k-${tone}` }, h("span", { class: "dot", "aria-hidden": "true" }), h("div", { class: "label", text: label }), num,
      sub ? h("div", { class: "sub", text: sub }) : null);
  }

  /* A ring of coloured arcs, one per status. */
  function donut(byStatus, total) {
    const R = 46, C = 2 * Math.PI * R;
    const arcs = [];
    let used = 0;
    for (const key of Object.keys(STATUS)) {
      const n = byStatus[key];
      if (!n) continue;
      const len = (n / total) * C;
      const arc = svg("circle", { class: `seg seg-${key}`, cx: 60, cy: 60, r: R, "stroke-dasharray": `0 ${C}`, "stroke-dashoffset": -used });
      const label = svg("title"); label.textContent = `${STATUS[key]}: ${n}`;
      arc.append(label);
      arcs.push(arc);
      afterPaint(() => arc.setAttribute("stroke-dasharray", `${Math.max(len - 1.5, 0.5)} ${C}`));
      used += len;
    }
    const centre = svg("text", { x: 60, y: 58, "text-anchor": "middle", class: "c-num" }); centre.textContent = String(total);
    const word = svg("text", { x: 60, y: 74, "text-anchor": "middle", class: "c-sub" }); word.textContent = total === 1 ? "request" : "requests";
    return svg("svg", { class: "donut", viewBox: "0 0 120 120", role: "img", "aria-label": `${total} requests by status` },
      svg("circle", { class: "ring-bg", cx: 60, cy: 60, r: R }), svg("g", { transform: "rotate(-90 60 60)" }, arcs), centre, word);
  }

  /* An area chart of requests made per day. */
  function trendChart(trend) {
    const W = 420, H = 150, L = 26, T = 14, B = 26, max = Math.max(3, ...trend.map((p) => p.count));
    const x = (i) => L + (i * (W - L - 8)) / (trend.length - 1);
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const pts = trend.map((p, i) => [x(i), y(p.count)]);
    const line = pts.map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)} ${b.toFixed(1)}`).join(" ");
    const area = `${line} L${x(trend.length - 1).toFixed(1)} ${y(0)} L${x(0).toFixed(1)} ${y(0)} Z`;
    const grid = [0, 0.5, 1].map((f) => {
      const gy = y(max * f), t = svg("text", { x: L - 6, y: gy + 3, "text-anchor": "end", class: "axis" }); t.textContent = String(Math.round(max * f));
      return [svg("line", { class: "grid", x1: L, x2: W - 8, y1: gy, y2: gy }), t];
    });
    const short = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
    const first = svg("text", { x: L, y: H - 6, class: "axis" }); first.textContent = short(trend[0].date);
    const last = svg("text", { x: W - 8, y: H - 6, "text-anchor": "end", class: "axis" }); last.textContent = short(trend[trend.length - 1].date);
    const stroke = svg("path", { class: "t-line", d: line, pathLength: 1 });
    const fill = svg("path", { class: "t-area", d: area });
    const dots = trend.map((p, i) => {
      const dot = svg("circle", { class: "t-dot", cx: pts[i][0], cy: pts[i][1], r: p.count ? 3.5 : 0 });
      const tip = svg("title"); tip.textContent = `${short(p.date)}: ${p.count}`;
      dot.append(tip);
      return dot;
    });
    afterPaint(() => { stroke.classList.add("drawn"); fill.classList.add("drawn"); });
    const defs = svg("defs", {}, svg("linearGradient", { id: "t-grad", x1: 0, y1: 0, x2: 0, y2: 1 },
      svg("stop", { offset: "0%", "stop-color": "#2563eb", "stop-opacity": 0.35 }), svg("stop", { offset: "100%", "stop-color": "#2563eb", "stop-opacity": 0 })));
    return svg("svg", { class: "trend", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Requests made per day, last 14 days" },
      defs, grid, fill, stroke, dots, first, last);
  }

  function ring(rate) {
    const R = 30, C = 2 * Math.PI * R;
    const arc = svg("circle", { class: "hero-arc", cx: 40, cy: 40, r: R, "stroke-dasharray": `0 ${C}` });
    afterPaint(() => arc.setAttribute("stroke-dasharray", `${(rate || 0) * C} ${C}`));
    const text = svg("text", { x: 40, y: 45, "text-anchor": "middle", class: "hero-pct" });
    text.textContent = rate === null ? "n/a" : `${Math.round(rate * 100)}%`;
    return svg("svg", { class: "hero-ring", viewBox: "0 0 80 80", role: "img", "aria-label": "Share of requests approved" },
      svg("circle", { class: "hero-bg", cx: 40, cy: 40, r: R }), svg("g", { transform: "rotate(-90 40 40)" }, arc), text);
  }

  function jdBars(top) {
    if (!top.length) return h("p", { class: "rb-empty", text: "Job descriptions will appear here once people are tagged." });
    const most = Math.max(...top.map((j) => j.total));
    return h("ul", { class: "rb-jdbars" }, top.map((j) => {
      const all = h("span", { class: "all" }), done = h("span", { class: "done" });
      afterPaint(() => { all.style.width = `${(j.total / most) * 100}%`; done.style.width = `${(j.approved / most) * 100}%`; });  // through the DOM: the CSP forbids style attributes
      return h("li", {}, h("div", { class: "top" }, h("span", { class: "nm", text: j.title }), h("span", { class: "ct", text: `${j.approved} of ${j.total} approved` })),
        h("div", { class: "track" }, all, done));
    }));
  }

  async function renderDashboard() {
    const d = await call("/resume/stats");
    const open = d.by_status.requested + d.by_status.in_progress + d.by_status.changes_requested;
    const hour = new Date().getHours();
    const hello = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    const first = (state.user.name || "").split(" ")[0];
    const chip = (text) => h("span", { class: "chip", text });
    const hero = h("section", { class: "rb-hero" },
      h("div", { class: "txt" }, h("p", { class: "eyebrow", text: DASH_SCOPE[d.scope] }), h("h2", { text: `${hello}, ${first}` }),
        h("p", { class: "lede", text: d.total ? `${d.by_status.submitted} waiting for review, ${open} still being worked on.` : "No resume requests yet. They will show up here as soon as RMG tags someone." }),
        h("div", { class: "chips" }, chip(d.avg_days_to_approve === null ? "No approvals yet" : `Approved in ${d.avg_days_to_approve} ${d.avg_days_to_approve === 1 ? "day" : "days"} on average`),
          d.scope === "all" ? chip(`${d.job_descriptions} job descriptions`) : null)),
      h("div", { class: "ring-wrap" }, ring(d.completion_rate), h("span", { class: "ring-label", text: "approved" })));
    const cards = [
      kpi("blue", "Requests", d.total, "all time"),
      kpi("slate", "In progress", open, "requested, being built or changes asked for"),
      kpi("amber", "Waiting for review", d.by_status.submitted, "with the Competency Lead or RMG"),
      kpi("green", "Approved", d.by_status.approved, d.completion_rate === null ? null : `${Math.round(d.completion_rate * 100)}% of requests`),
    ];
    if (d.scope === "all") cards.push(kpi("violet", "People without a Lead", d.without_lead, "RMG reviews their resumes"));
    const legend = h("ul", { class: "legend" }, Object.keys(STATUS).map((key) => h("li", {},
      h("span", { class: `sw seg-${key}` }), h("span", { class: "nm", text: STATUS[key] }), h("span", { class: "ct", text: String(d.by_status[key]) }))));
    const attention = d.attention.length
      ? h("ul", { class: "rb-list" }, d.attention.map((r) => h("li", { class: "rb-item" },
        h("div", {}, h("div", { class: "title", text: r.jd_title }), h("div", { class: "sub", text: `${r.associate} · waiting ${r.days_waiting} ${r.days_waiting === 1 ? "day" : "days"}` })),
        h("button", { class: "btn", type: "button", on: { click: () => openRequest(r.id) } }, "Open"))))
      : h("p", { class: "rb-empty", text: "Nothing is waiting for review." });
    const panel = (title, sub, body, extra = "") => h("section", { class: `rb-panel ${extra}` }, h("h3", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null, body);
    const layout = [hero, h("div", { class: "rb-kpis" }, cards),
      h("div", { class: "rb-dash" },
        panel("Requests by status", "Where every request stands right now",
          h("div", { class: "donut-wrap" }, donut(d.by_status, d.total), legend), "p-donut"),
        panel("Requests made", "Per day, over the last 14 days", trendChart(d.trend), "p-trend"),
        panel("Busiest job descriptions", "Requests, with how many are approved", jdBars(d.top_jds), "p-jds"),
        panel("Waiting the longest", "Submitted resumes, oldest first", attention, "p-wait"),
        panel("Recently updated", null, d.recent.length ? h("ul", { class: "rb-list" }, d.recent.map((r) => requestItem(r)))
          : h("p", { class: "rb-empty", text: "Nothing yet." }), "p-recent"))];
    $("view").replaceChildren(h("div", { class: "rb-dashboard" }, layout));
    $("view").querySelectorAll(".rb-hero, .rb-kpi, .rb-panel").forEach((el, i) => { el.style.animationDelay = `${i * 70}ms`; });
  }

  async function renderMine() {
    const { requests } = await call("/resume/requests?scope=mine");
    $("view").replaceChildren(h("h2", { text: "My resume requests" }),
      requests.length ? h("ul", { class: "rb-list" }, requests.map((r) => requestItem(r)))
        : h("p", { class: "rb-empty", text: "Nothing yet. When RMG needs a resume from you, the request will appear here." }));
  }

  async function renderReview() {
    const { requests } = await call("/resume/requests?scope=review");
    const waiting = requests.filter((r) => r.status === "submitted");
    $("view").replaceChildren(h("h2", { text: "Resumes to review" }),
      h("p", { class: "muted", text: `${waiting.length} waiting for your decision. The Competency Lead and RMG can both review.` }),
      requests.length ? h("ul", { class: "rb-list" }, requests.map((r) => requestItem(r)))
        : h("p", { class: "rb-empty", text: "Nothing is waiting for review." }));
  }

  /* ---------- RMG board ---------- */
  async function renderBoard() {
    const [{ jds }, { associates }, { requests }, tpl] = await Promise.all([
      call("/resume/jds"), call("/resume/associates"), call("/resume/requests?scope=board"), call("/resume/template"),
    ]);
    const jdSelect = h("select", { id: "tag-jd", "aria-label": "Job description" },
      jds.map((j) => h("option", { value: j.id, text: j.title })));
    const roleSelect = h("select", { id: "tag-role", "aria-label": "Role" });
    const roleField = h("div", { id: "tag-role-field", hidden: true },
      h("label", { class: "rb-field", for: "tag-role", text: "Role" }), roleSelect);
    const fillRoles = () => {
      const jd = jds.find((j) => String(j.id) === jdSelect.value);
      roleSelect.replaceChildren(...(jd ? jd.roles.map((r, i) => h("option", { value: i, text: r.title })) : []));
      roleField.hidden = !(jd && jd.roles.length > 1);  // one role is the normal case, so there is nothing to choose
    };
    jdSelect.addEventListener("change", fillRoles);
    fillRoles();
    const person = (a) => h("label", { class: "rb-check" },
      h("input", { type: "checkbox", value: a.id }),
      h("span", { class: "who-line" }, h("span", { class: "nm", text: a.name }),
        h("span", { class: "meta", text: a.lead ? `${a.department} · Lead: ${a.lead}` : `${a.department} · Reviewed by RMG` })));
    const taggable = associates;
    const jdFile = h("input", { id: "jd-file", type: "file", accept: ".docx,.pdf,.txt", "aria-label": "Job description file" });
    const jdTitle = h("input", { id: "jd-title", type: "text", placeholder: "Title (optional)" });
    const jdPaste = h("textarea", { id: "jd-paste", "aria-label": "Pasted job description", placeholder: "Paste the job description, or a list of skills such as: Java, Spring Boot, Kafka, SQL" });

    const form = h("div", { class: "rb-card" },
      h("h3", { text: "New request" }),
      !tpl.template ? h("p", { class: "rb-warn", text: "No resume template is set up yet. Ask the RMG Head to upload one." }) : null,
      h("label", { class: "rb-field", for: "tag-jd", text: "Job description" }),
      jds.length ? h("div", { class: "rb-selectrow" }, jdSelect,
        h("button", { id: "board-jd-preview", class: "btn", type: "button", on: { click: () => attempt(async () => showJdPreview(await call(`/resume/jds/${jdSelect.value}/preview`))) } }, "Preview"),
        h("button", { id: "board-jd-download", class: "btn", type: "button", on: { click: () => downloadJd(`/resume/jds/${jdSelect.value}/file`) } }, "Download"))
        : h("p", { class: "muted", text: "Add a job description first." }),
      roleField,
      h("label", { class: "rb-field", text: "Tag associates" }),
      h("div", { id: "tag-people", class: "rb-people" }, taggable.map(person)),
      h("div", { class: "rb-row" }, h("button", { id: "tag-go", class: "btn primary", type: "button", on: { click: () => attempt(async () => {
        const ids = [...document.querySelectorAll("#tag-people input:checked")].map((i) => Number(i.value));
        if (!jds.length || !ids.length) { flash("Choose a job description and at least one associate.", "error"); return; }
        const result = await post(`/resume/jds/${jdSelect.value}/tag`, { associate_ids: ids, role_index: Number(roleSelect.value) });
        const skipped = result.skipped.map((s) => s.message).join(" ");
        flash(`Tagged ${result.created.length}.${skipped ? " " + skipped : ""}`, result.skipped.length ? "error" : "ok");
        await renderTab();
      }) } }, "Tag selected")));

    const jdCardNode = h("div", { class: "rb-card" },
      h("h3", { text: "Add a job description" }),
      h("div", { class: "rb-inline" }, jdFile, jdTitle,
        h("button", { id: "jd-go", class: "btn", type: "button", on: { click: () => attempt(async () => {
          const file = jdFile.files[0];
          if (!file) { flash("Choose a file first.", "error"); return; }
          const title = jdTitle.value.trim();
          await upload(`/resume/jds?filename=${encodeURIComponent(file.name)}${title ? `&title=${encodeURIComponent(title)}` : ""}`, file);
          flash("Job description added.", "ok");
          await renderTab();
        }, "Reading the job description…") } }, "Upload")),
      h("p", { class: "muted", text: "A Word, PDF or text file. It is read once and stored, and can be used for many associates." }),
      h("label", { class: "rb-field", for: "jd-paste", text: "Or paste it here (it can be just a list of skills)" }),
      jdPaste,
      h("div", { class: "rb-row" }, h("button", { id: "jd-paste-go", class: "btn", type: "button", on: { click: () => attempt(async () => {
        const text = jdPaste.value.trim();
        if (!text) { flash("Paste the job description, or a list of skills, first.", "error"); return; }
        await post("/resume/jds/text", { text, title: jdTitle.value.trim() || null });
        flash("Job description added.", "ok");
        await renderTab();
      }, "Reading the job description…") } }, "Add pasted text")));

    const table = h("table", { class: "rb-table" },
      h("thead", {}, h("tr", {}, ["Job description", "Associate", "Lead", "Status", "Required covered", ""].map((t) => h("th", { text: t })))),
      h("tbody", {}, requests.map((r) => h("tr", {},
        h("td", { text: r.jd_title }), h("td", { text: r.associate }), h("td", { text: r.lead }),
        h("td", {}, statusBadge(r.status)), h("td", { text: r.coverage ? pct(r.coverage.required_after) : "-" }),
        h("td", {}, h("button", { class: "btn", type: "button", on: { click: () => openRequest(r.id) } }, "Open"))))));
    $("view").replaceChildren(h("h2", { text: "Resume requests" }), h("div", { class: "rb-grid rb-two" }, form,
      h("div", {}, jdCardNode, h("div", { class: "rb-card" }, h("h3", { text: "Requests" }),
        requests.length ? table : h("p", { class: "rb-empty", text: "No requests yet. Tag an associate to start one." })))));
  }

  /* ---------- RMG head setup ---------- */
  async function renderSetup() {
    const [tpl, leads] = await Promise.all([call("/resume/template"), call("/resume/leads")]);
    const file = h("input", { id: "tpl-file", type: "file", accept: ".docx", "aria-label": "Template file" });
    const associate = h("select", { id: "map-associate", "aria-label": "Associate" }, leads.employees.map((e) => h("option", { value: e.id, text: e.name })));
    const lead = h("select", { id: "map-lead", "aria-label": "Competency Lead" }, leads.leads.map((e) => h("option", { value: e.id, text: e.name })));
    $("view").replaceChildren(h("h2", { text: "Setup" }), h("div", { class: "rb-grid rb-two" },
      h("div", {}, h("div", { class: "rb-card" },
        h("h3", { text: "Resume template" }),
        h("p", { id: "tpl-current", class: "rb-current", text: tpl.template ? `Active: ${tpl.template.name}` : "No template yet." }),
        h("p", { class: "muted", text: "A Word (.docx) file. It is checked for the parts a resume needs before it becomes active. A new template replaces the active one for new drafts." }),
        h("label", { class: "rb-field", for: "tpl-file", text: "Template file" }), file,
        h("div", { class: "rb-row" }, h("button", { id: "tpl-go", class: "btn primary", type: "button", on: { click: () => attempt(async () => {
          if (!file.files[0]) { flash("Choose a file first.", "error"); return; }
          await upload(`/resume/template?filename=${encodeURIComponent(file.files[0].name)}`, file.files[0]);
          flash("Template uploaded and active.", "ok");
          await renderTab();
        }, "Checking the template…") } }, "Upload template")))),
      h("div", { class: "rb-card" },
        h("h3", { text: "Competency Lead for each associate" }),
        h("p", { class: "muted", text: "The Lead approves that associate's resumes. An associate with no Lead cannot be tagged." }),
        h("div", { class: "rb-map" }, associate, h("span", { class: "arrow", "aria-hidden": "true", text: "→" }), lead,
          h("button", { id: "map-go", class: "btn primary", type: "button", on: { click: () => attempt(async () => {
            await call("/resume/leads", { method: "PUT", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ associate_id: Number(associate.value), lead_id: Number(lead.value) }) });
            flash("Competency Lead saved.", "ok");
            await renderTab();
          }) } }, "Save")),
        h("table", { class: "rb-table", id: "map-table" },
          h("thead", {}, h("tr", {}, ["Associate", "Competency Lead"].map((t) => h("th", { text: t })))),
          h("tbody", {}, leads.assignments.map((a) => h("tr", {}, h("td", { text: a.associate }), h("td", { text: a.lead }))))))));
  }

  /* ---------- the workspace for one request ---------- */
  async function openRequest(id) {
    await attempt(async () => {
      state.detail = await call(`/resume/requests/${id}`);
      state.editing = null;
      state.addingFact = null;
      state.addingSkill = null;
      state.scoreDelta = null;
      state.listedDelta = null;
      state.chat = [];
      flash("");
      renderWorkspace();
    });
  }

  const requiredScore = (d) => (d && d.changelog ? d.changelog.coverage.required_after : null);

  const listedCount = (d) => (d && d.changelog ? d.changelog.coverage.listed_required.length : null);

  async function refreshDetail(detail) {
    const before = requiredScore(state.detail);
    const listedBefore = listedCount(state.detail);
    state.detail = detail || await call(`/resume/requests/${state.detail.id}`);
    const after = requiredScore(state.detail);
    // how far the score moved with this change, in points; null when there is nothing to compare yet
    state.scoreDelta = before !== null && after !== null ? Math.round((after - before) * 100) : null;
    const listedAfter = listedCount(state.detail);
    state.listedDelta = listedBefore !== null && listedAfter !== null ? listedAfter - listedBefore : null;
    renderWorkspace();
    loadNotes();
  }

  /* Fetch a file with the signed-in token and hand it to the browser as a download. */
  function downloadFile(path, fallbackName, doneMessage, busyText) {
    return attempt(async () => {
      const response = await api(path);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error((body.error && body.error.message) || "The download failed.");
      }
      const blob = await response.blob();
      const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "");
      const url = URL.createObjectURL(blob);
      const link = h("a", { href: url, download: match ? match[1] : fallbackName });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      flash(doneMessage(response), "ok");
    }, busyText);
  }

  /* What the layout check did to the downloaded file, said plainly. */
  const LAYOUT_NOTE = {
    fixed: " The layout was checked and adjusted for you.",
    unfixed: " The layout still has a problem that could not be fixed automatically: please look at the Word file before you send it.",
  };

  const download = (id) => downloadFile(`/resume/requests/${id}/download`, "resume.docx",
    (response) => (response.headers.get("X-Resume-Draft") === "true" ? "Downloaded a DRAFT copy (not approved yet)." : "Downloaded the approved resume.")
      + (response.headers.get("X-Resume-Check") === "pass" ? "" : " The template check has things to look at: see the Template check above.")
      + (LAYOUT_NOTE[response.headers.get("X-Resume-Layout")] || ""), "Preparing and checking the Word file…");
  const downloadJd = (path) => downloadFile(path, "job-description.docx", () => "Downloaded the job description.");

  function actionBar(d) {
    const can = d.can;
    const fileInput = h("input", { id: "resume-file", type: "file", accept: ".docx,.pdf,.txt", "aria-label": "Your resume file" });
    const buttons = [];
    const btn = (id, label, fn, cls = "btn", busy) => buttons.push(h("button", { id, class: cls, type: "button", on: { click: () => attempt(fn, busy) } }, label));
    if (can.upload) {
      buttons.push(h("label", { class: "rb-filepick", for: "resume-file" },
        h("span", { text: d.base_filename ? `Your resume: ${d.base_filename}` : "Your resume (max 10 pages)" }), fileInput));
      btn("upload-resume", "Upload", async () => {
        const file = fileInput.files[0];
        if (!file) { flash("Choose your resume file first.", "error"); return; }
        await upload(`/resume/requests/${d.id}/resume?filename=${encodeURIComponent(file.name)}`, file);
        flash("Resume uploaded. Now build the tailored draft.", "ok");
        await refreshDetail();
      });
    }
    if (can.build) btn("build", d.resume ? "Rebuild (discard my edits)" : "Build tailored resume", async () => {
      const rebuilt = await post(`/resume/requests/${d.id}/build`, { force: Boolean(d.resume) });
      flash("Your tailored draft is ready. Review the changes, edit anything, then save and submit.", "ok");
      await refreshDetail(rebuilt);
    }, "btn primary", "Building your tailored resume… this can take a minute.");
    if (can.save) btn("save", "Save version", async () => { const r = await post(`/resume/requests/${d.id}/save`); flash(`Saved as version ${r.version}.`, "ok"); await refreshDetail(); });
    if (can.submit) btn("submit", "Submit for review", async () => { await post(`/resume/requests/${d.id}/submit`); flash("Submitted. Your reviewers have been notified.", "ok"); await refreshDetail(); }, "btn primary");
    if (can.reopen) btn("reopen", "Reopen to edit", async () => { await post(`/resume/requests/${d.id}/reopen`); await refreshDetail(); });
    if (can.download) buttons.push(h("button", { id: "download", class: "btn", type: "button", on: { click: () => download(d.id) } }, d.status === "approved" ? "Download approved resume" : "Download draft"));
    if (can.cancel) btn("cancel", "Cancel request", async () => { await post(`/resume/requests/${d.id}/cancel`); flash("Request cancelled.", "ok"); await refreshDetail(); });
    return h("div", { class: "rb-toolbar" }, buttons);
  }

  function decisionCard(d) {
    if (!d.can.decide) return null;
    const note = h("textarea", { id: "decision-note", "aria-label": "Note to the associate", placeholder: "Note (required if you send it back)" });
    return h("div", { class: "rb-card" }, h("h3", { text: "Your decision" }), note,
      h("div", { class: "rb-row" },
        h("button", { id: "approve", class: "btn primary", type: "button", on: { click: () => attempt(async () => {
          await post(`/resume/requests/${d.id}/decide`, { decision: "approve", note: note.value });
          flash("Approved.", "ok");
          await refreshDetail();
        }) } }, "Approve"),
        h("button", { id: "send-back", class: "btn", type: "button", on: { click: () => attempt(async () => {
          await post(`/resume/requests/${d.id}/decide`, { decision: "send_back", note: note.value });
          flash("Sent back to the associate.", "ok");
          await refreshDetail();
        }) } }, "Send back")));
  }

  /* ---------- job description preview ---------- */
  function showJdPreview(preview) {
    const chips = (items, cls) => h("div", { class: "rb-chips" }, items.map((s) => h("span", { class: `chip ${cls}`, text: s })));
    $("jd-preview-title").textContent = preview.title;
    const parts = [
      preview.filename ? h("p", { class: "muted", text: `File: ${preview.filename}` }) : null,
      preview.flagged.length ? h("p", { class: "rb-warn", text: "This job description contains text that tries to instruct an assistant. It was ignored." }) : null,
      preview.roles.map((role) => h("section", { class: "rb-prev-role" },
        h("h3", { text: role.title }),
        role.min_years !== null && role.min_years !== undefined || role.domain
          ? h("p", { class: "muted", text: [role.min_years !== null && role.min_years !== undefined ? `At least ${role.min_years} years` : "", role.domain || ""].filter(Boolean).join(" · ") }) : null,
        h("h4", { text: "Must have" }), chips(role.must_have, ""),
        role.nice_to_have.length ? [h("h4", { text: "Nice to have" }), chips(role.nice_to_have, "nice")] : null)),
      h("h3", { text: "Text of the job description" }),
      preview.text
        ? [h("pre", { class: "rb-pre", id: "jd-preview-text", text: preview.text }),
          preview.truncated ? h("p", { class: "muted", text: "Only the start is shown. Download the file to read all of it." }) : null]
        : h("p", { class: "muted", text: "There is no original text to show; the requirements above are what was kept." }),
    ];
    $("jd-preview-body").replaceChildren(...parts.flat().filter(Boolean));
    $("jd-preview").showModal();
  }

  function jdCard(d) {
    const role = d.jd.role;
    const cov = d.changelog && d.changelog.coverage;
    const chips = (items, cls) => h("div", { class: "rb-chips" }, items.map((s) => h("span", { class: `chip ${cls}`, text: s })));
    /* A skill the JD wants and the resume does not have is only a suggestion: one click adds it, as the person's own statement. */
    const suggestions = (items, cls) => (d.can.edit ? h("div", { class: "rb-chips" }, items.map((s) => h("button", {
      type: "button", class: `chip ${cls} suggest`, title: "Click to add this to the resume, if it is true", "aria-label": `Add ${s} to the skills`,
      on: { click: () => doEdit({ action: "add_skill", text: s, category: "Other relevant skills" }) } }, `+ ${s}`))) : chips(items, cls));
    return h("div", {},
      h("div", { class: "rb-card" },
        h("h3", { text: role.title }),
        role.min_years !== null && role.min_years !== undefined ? h("p", { class: "muted", text: `At least ${role.min_years} years` + (d.years_text ? ` (you have ${d.years_text})` : "") }) : null,
        d.jd.flagged.length ? h("p", { class: "rb-warn", text: "This job description contains text that tries to instruct an assistant. It was ignored." }) : null,
        h("h3", { text: "Must have" }), chips(role.must_have, ""),
        role.nice_to_have.length ? [h("h3", { text: "Nice to have" }), chips(role.nice_to_have, "nice")] : null,
        h("div", { class: "rb-row" },
          h("button", { id: "preview-jd", class: "btn", type: "button",
            on: { click: () => attempt(async () => showJdPreview(await call(`/resume/requests/${d.id}/jd/preview`))) } }, "Preview"),
          h("button", { id: "download-jd", class: "btn", type: "button",
            on: { click: () => downloadJd(`/resume/requests/${d.id}/jd`) } }, "Download job description"))),
      cov ? h("div", { class: "rb-card", id: "coverage" },
        h("h3", { text: `Required skills covered: ${pct(cov.required_after)}` }),
        cov.required_after !== null ? h("progress", { class: "rb-progress", max: "1", value: String(cov.required_after) }) : null,
        h("p", { class: "muted", text: "In your resume" }), chips(cov.covered, ""),
        cov.missing_required.length ? [h("p", { class: "muted", text: d.can.edit ? "Required, but not in your resume (not claimed). Click one that is true to add it:" : "Required, but not in the resume (not claimed)" }), suggestions(cov.missing_required, "missing")] : null,
        cov.missing_nice.length ? [h("p", { class: "muted", text: d.can.edit ? "Nice to have, not in your resume. Click to add if true:" : "Nice to have, not in the resume" }), suggestions(cov.missing_nice, "nice")] : null,
        d.can.edit ? h("p", { class: "muted", text: "Anything you add is marked as your own statement, so only add what is true." }) : null) : null,
      d.versions.length ? h("div", { class: "rb-card" }, h("h3", { text: "Versions" }),
        h("ul", { class: "rb-list" }, d.versions.map((v) => h("li", { class: "sub", text: `v${v.version}: ${v.kind}` })))) : null);
  }

  /* One editable line of the resume: text, where it came from, and tools if the associate may edit. */
  /* Who added a line, as the person looking should read it: "you" only for the associate. */
  const addedBy = (d, item) => (item.by ? `added by ${item.by}` : d.relations.includes("associate") ? "added by you" : "added by the associate");

  function line(d, path, item, tools) {
    if (state.editing === path) {
      const box = h("textarea", { "aria-label": "New wording" });
      box.value = item.text;
      return h("li", { class: "rb-edit" }, box, h("div", { class: "rb-row" },
        h("button", { class: "btn primary save-edit", type: "button", on: { click: () => doEdit({ action: "set_text", path, text: box.value }) } }, "Save"),
        h("button", { class: "btn", type: "button", on: { click: () => { state.editing = null; renderWorkspace(); } } }, "Cancel")));
    }
    const can = d.can.edit;
    return h("li", { class: "rb-bullet", "data-path": path },
      h("span", { class: "text" }, item.text, " ", item.origin !== "original" ? badge(item.origin === "user_added" ? addedBy(d, item) : "reworded", `o-${item.origin}`) : null),
      can ? h("span", { class: "rb-tools" },
        h("button", { type: "button", class: "edit", "aria-label": `Edit: ${item.text}`, on: { click: () => { state.editing = path; renderWorkspace(); } } }, "Edit"),
        h("button", { type: "button", class: "remove", "aria-label": `Remove: ${item.text}`, on: { click: () => doEdit({ action: "remove", path }) } }, "Remove"),
        tools) : null);
  }

  function doEdit(command) {
    return attempt(async () => {
      const result = await post(`/resume/requests/${state.detail.id}/edit`, command);
      state.editing = null;
      state.addingFact = null;
      state.addingSkill = null;
      flash(result.message, "ok");
      await refreshDetail(result.detail);
    });
  }

  function mover(label, command) {
    return h("button", { type: "button", "aria-label": label, on: { click: () => doEdit(command) } }, label.startsWith("Move up") ? "Up" : "Down");
  }

  /* A project whose resume gave no dates can be given them: they are the associate's own statement. */
  function datesBox(d, project) {
    if (!d.can.edit) return null;
    const key = `dates-${project}`;
    if (state.addingFact !== key) {
      return h("button", { type: "button", class: "rb-linkbtn add-dates", on: { click: () => { state.addingFact = key; renderWorkspace(); } } }, "Add dates");
    }
    const box = h("input", { type: "text", "aria-label": "Project dates", placeholder: "For example: Jan 2022 \u2013 Mar 2023", maxlength: "60" });
    return h("div", { class: "rb-edit" }, box, h("div", { class: "rb-row" },
      h("button", { class: "btn primary save-dates", type: "button", on: { click: () => doEdit({ action: "add_dates", project, text: box.value }) } }, "Add as my own statement"),
      h("button", { class: "btn", type: "button", on: { click: () => { state.addingFact = null; renderWorkspace(); } } }, "Cancel")));
  }

  /* A certification is the associate's own statement, so it is added here and marked as theirs. */
  function certBox(d) {
    if (!d.can.edit) return null;
    if (state.addingFact !== "certification") {
      return h("button", { type: "button", class: "rb-linkbtn add-certification", on: { click: () => { state.addingFact = "certification"; renderWorkspace(); } } }, "Add a certification");
    }
    const box = h("input", { type: "text", "aria-label": "Certification", placeholder: "For example: AWS Certified Developer", maxlength: "200" });
    return h("div", { class: "rb-edit" }, box, h("div", { class: "rb-row" },
      h("button", { class: "btn primary save-certification", type: "button", on: { click: () => doEdit({ action: "add_certification", text: box.value }) } }, "Add as my own statement"),
      h("button", { class: "btn", type: "button", on: { click: () => { state.addingFact = null; renderWorkspace(); } } }, "Cancel")));
  }

  function factBox(d, project) {
    if (!d.can.edit) return null;
    if (state.addingFact !== project) {
      return h("button", { type: "button", class: "rb-linkbtn add-fact", on: { click: () => { state.addingFact = project; renderWorkspace(); } } }, "Add a fact");
    }
    const box = h("textarea", { "aria-label": "A fact about you", placeholder: "Something true about your work that is not in your resume" });
    return h("div", { class: "rb-edit" }, box, h("div", { class: "rb-row" },
      h("button", { class: "btn primary save-fact", type: "button", on: { click: () => doEdit({ action: "add_fact", project: project === "highlights" ? null : project, text: box.value }) } }, "Add as my own statement"),
      h("button", { class: "btn", type: "button", on: { click: () => { state.addingFact = null; renderWorkspace(); } } }, "Cancel")));
  }

  /* Skills are short, so each is a chip: click to edit, x to remove. A skill the associate adds is marked as theirs. */
  function skillChip(d, gi, i, item) {
    const path = `skill_groups.${gi}.items.${i}`;
    if (state.editing === path) {
      const input = h("input", { type: "text", class: "rb-skill-input", "aria-label": "Skill", value: item.text, maxlength: "100" });
      const save = () => doEdit({ action: "set_text", path, text: input.value });
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); save(); }
        if (e.key === "Escape") { state.editing = null; renderWorkspace(); }
      });
      setTimeout(() => input.focus(), 0);
      return h("span", { class: "rb-skill-edit" }, input,
        h("button", { type: "button", class: "rb-linkbtn skill-save", on: { click: save } }, "Save"),
        h("button", { type: "button", class: "rb-linkbtn", on: { click: () => { state.editing = null; renderWorkspace(); } } }, "Cancel"));
    }
    const mine = item.origin === "user_added";
    return h("span", { class: `chip skill-chip${mine ? " mine" : ""}`, "data-path": path },
      d.can.edit
        ? h("button", { type: "button", class: "skill-edit", "aria-label": `Edit skill ${item.text}`, title: "Click to edit", on: { click: () => { state.editing = path; renderWorkspace(); } } }, item.text)
        : item.text,
      mine ? h("span", { class: "skill-mine", text: addedBy(d, item) }) : null,
      d.can.edit ? h("button", { type: "button", class: "skill-remove", "aria-label": `Remove skill ${item.text}`, title: "Remove", on: { click: () => doEdit({ action: "remove", path }) } }, "×") : null);
  }

  function skillAdder(d, key, command) {
    if (!d.can.edit) return null;
    if (state.addingSkill !== key) {
      return h("button", { type: "button", class: "rb-linkbtn skill-add", on: { click: () => { state.addingSkill = key; renderWorkspace(); } } }, "+ Add a skill");
    }
    const input = h("input", { type: "text", class: "rb-skill-input", "aria-label": "New skill", placeholder: "For example: Terraform", maxlength: "100" });
    const save = () => doEdit({ ...command, text: input.value });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); save(); }
      if (e.key === "Escape") { state.addingSkill = null; renderWorkspace(); }
    });
    setTimeout(() => input.focus(), 0);
    return h("span", { class: "rb-skill-edit" }, input,
      h("button", { type: "button", class: "rb-linkbtn skill-save", on: { click: save } }, "Add"),
      h("button", { type: "button", class: "rb-linkbtn", on: { click: () => { state.addingSkill = null; renderWorkspace(); } } }, "Cancel"));
  }

  function skillGroup(d, g, gi) {
    return h("div", { class: "rb-skillgroup" },
      h("strong", { class: "rb-skillcat", text: `${g.category}:` }),
      h("span", { class: "rb-skillchips" }, g.items.map((item, i) => skillChip(d, gi, i, item)), skillAdder(d, gi, { action: "add_skill", group: gi })));
  }

  function newGroupControl(d) {
    if (state.addingSkill !== "group") {
      return h("button", { type: "button", class: "rb-linkbtn skill-new-group", on: { click: () => { state.addingSkill = "group"; renderWorkspace(); } } }, "+ Add a skill group");
    }
    const category = h("input", { type: "text", class: "rb-skill-input", "aria-label": "Group name", placeholder: "Group name, for example Infrastructure", maxlength: "100" });
    const skill = h("input", { type: "text", class: "rb-skill-input", "aria-label": "First skill", placeholder: "First skill", maxlength: "100" });
    const save = () => doEdit({ action: "add_skill", category: category.value, text: skill.value });
    for (const input of [category, skill]) input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
    setTimeout(() => category.focus(), 0);
    return h("div", { class: "rb-skill-edit new-group" }, category, skill,
      h("button", { type: "button", class: "rb-linkbtn skill-save", on: { click: save } }, "Add"),
      h("button", { type: "button", class: "rb-linkbtn", on: { click: () => { state.addingSkill = null; renderWorkspace(); } } }, "Cancel"));
  }

  function resumeCard(d) {
    const r = d.resume;
    if (!r) {
      return h("div", { class: "rb-card" }, h("h3", { text: "Your resume" }),
        h("p", { class: "rb-empty", text: d.can.upload ? "Upload your resume, then build the tailored draft." : "Nothing has been built yet." }));
    }
    const sections = [];
    if (r.summary) sections.push(h("div", { class: "section" }, h("h4", { text: "Summary" }), h("ul", { class: "rb-bullets" }, line(d, "summary", r.summary))));
    if (r.skill_groups.length || d.can.edit) {
      sections.push(h("div", { class: "section", id: "skills-section" }, h("h4", { text: "Skills" }),
        r.skill_groups.map((g, gi) => skillGroup(d, g, gi)), d.can.edit ? newGroupControl(d) : null));
    }
    if (r.education.length) sections.push(h("div", { class: "section" }, h("h4", { text: "Education" }),
      r.education.map((e) => h("p", { text: [e.degree, e.institution].filter(Boolean).join(", ") + (e.year ? ` ${e.year}` : "") }))));
    if (r.certifications.length || d.can.edit) {
      sections.push(h("div", { class: "section", id: "certifications-section" }, h("h4", { text: "Certifications" }),
        r.certifications.length ? h("ul", { class: "rb-bullets" }, r.certifications.map((c, i) => line(d, `certifications.${i}`, c)))
          : h("p", { class: "muted", text: "None listed. The Word file has no certifications section unless you add one." }),
        certBox(d)));
    }
    sections.push(h("div", { class: "section" }, h("h4", { text: "Key highlights" }),
      h("ul", { class: "rb-bullets" }, r.highlights.map((item, i) => line(d, `highlights.${i}`, item))), factBox(d, "highlights")));
    sections.push(h("div", { class: "section" }, h("h4", { text: "Projects" }), r.projects.map((p, pi) => h("div", { class: "rb-project", "data-path": `projects.${pi}` },
      h("div", { class: "pname" }, h("span", { text: p.name }), d.can.edit ? h("span", { class: "rb-tools" },
        mover("Move up project", { action: "move_project", index: pi, to: pi - 1 }), mover("Move down project", { action: "move_project", index: pi, to: pi + 1 })) : null),
      p.dates ? h("ul", { class: "rb-bullets rb-dates" }, line(d, `projects.${pi}.dates`, p.dates)) : datesBox(d, pi),
      p.description ? h("ul", { class: "rb-bullets" }, line(d, `projects.${pi}.description`, p.description)) : null,
      h("ul", { class: "rb-bullets" }, p.bullets.map((b, bi) => line(d, `projects.${pi}.bullets.${bi}`, b, [
        mover("Move up", { action: "move_bullet", project: pi, index: bi, to: bi - 1 }), mover("Move down", { action: "move_bullet", project: pi, index: bi, to: bi + 1 })]))),
      factBox(d, pi)))));
    return h("div", { class: "rb-card rb-resume", id: "resume" },
      h("h3", { class: "name", text: r.name }),
      h("div", { class: "role" }, r.role_title ? line(d, "role_title", r.role_title) : null, d.years_text ? `Experience: ${d.years_text}` : null),
      sections);
  }

  function changesCard(d) {
    const log = d.changelog;
    const entries = log ? log.entries : [];
    const input = h("textarea", { id: "chat-input", "aria-label": "Tell the assistant what to change", placeholder: "For example: make the first Payments bullet shorter" });
    const send = () => attempt(async () => {
      const message = input.value.trim();
      if (!message) return;
      input.value = "";
      state.chat.push({ me: true, text: message });
      const result = await post(`/resume/requests/${d.id}/chat`, { message });
      state.chat.push({ me: false, text: result.reply });
      await refreshDetail(result.detail);
    }, "Thinking…");
    return h("div", {},
      d.warnings && d.warnings.length ? h("div", { class: "rb-warn", text: d.warnings.join(" ") }) : null,
      h("div", { class: "rb-card", id: "changes" }, h("h3", { text: "What changed" }),
        log ? h("p", { id: "change-summary", text: log.summary }) : h("p", { class: "rb-empty", text: "Nothing yet." }),
        entries.length ? h("p", { class: "muted", text: "Use Show in resume to see which line a change is about." }) : null,
        h("div", { class: "rb-log" }, entries.map((e) => h("div", { class: `entry${e.path ? " linked" : ""}`, "data-path": e.path || null },
          badge(KIND[e.kind] || e.kind, `k-${e.kind}`), h("div", { class: "where", text: e.where }),
          e.before ? h("div", { class: "before", text: e.before }) : null, e.after ? h("div", { class: "after", text: e.after }) : null,
          h("div", { class: "reason", text: e.reason }),
          e.path ? h("button", { type: "button", class: "rb-linkbtn show-in-resume", on: { click: () => showInResume(e.path) } }, "Show in resume")
            : h("span", { class: "muted gone", text: "No longer in the resume" }))))),
      d.can.chat ? h("div", { class: "rb-card", id: "chat" }, h("h3", { text: "Ask for a change" }),
        h("div", { class: "rb-chat-log", "aria-live": "polite" }, state.chat.map((m) => h("div", { class: m.me ? "me" : "bot", text: m.text }))),
        h("div", { class: "rb-chat-form" }, input, h("div", { class: "rb-row" }, h("button", { id: "chat-send", class: "btn primary", type: "button", on: { click: send } }, "Send")))) : null);
  }

  /* Match a change to its line: a button scrolls to it and flashes it, and hovering either one highlights the other. */
  const lineFor = (path) => document.querySelector(`#resume [data-path="${CSS.escape(path)}"]`);
  const entriesFor = (path) => [...document.querySelectorAll("#changes .entry[data-path]")].filter((e) => e.dataset.path === path);

  function showInResume(path) {
    const target = lineFor(path);
    if (!target) { flash("That line is no longer in the resume.", "error"); return; }
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.add("rb-flash");
    setTimeout(() => target.classList.remove("rb-flash"), 2600);
  }

  function wireLinks() {
    for (const entry of document.querySelectorAll("#changes .entry.linked")) {
      entry.addEventListener("mouseenter", () => lineFor(entry.dataset.path)?.classList.add("rb-linked"));
      entry.addEventListener("mouseleave", () => lineFor(entry.dataset.path)?.classList.remove("rb-linked"));
    }
    for (const line of document.querySelectorAll("#resume [data-path]")) {
      line.addEventListener("mouseenter", () => entriesFor(line.dataset.path).forEach((e) => e.classList.add("rb-linked")));
      line.addEventListener("mouseleave", () => entriesFor(line.dataset.path).forEach((e) => e.classList.remove("rb-linked")));
    }
  }

  /* One prominent score that follows every change: the share of required skills the resume shows. */
  function scoreBlock(d) {
    const cov = d.changelog && d.changelog.coverage;
    if (!cov || cov.required_after === null) return null;
    const total = d.jd.role.must_have.length;
    const delta = state.scoreDelta;
    const listed = cov.listed_required.length, moved = state.listedDelta;
    return h("div", { class: "rb-score", id: "score", role: "status", "aria-live": "polite" },
      h("span", { class: "num", text: pct(cov.required_after) }),
      h("span", { class: "lab" }, h("strong", { text: "Match with the job" }),
        h("span", { text: `${total - cov.missing_required.length} of ${total} required skills shown in the resume` }),
        h("span", { id: "score-listed", class: "listed", title: "Required skills that are listed in the Skills section itself" },
          `${listed} of ${total} listed in Skills`, moved ? h("b", { class: moved > 0 ? "up" : "down", text: ` ${moved > 0 ? "+" : "-"}${Math.abs(moved)}` }) : null)),
      delta === null ? null : h("span", { class: `delta ${delta > 0 ? "up" : delta < 0 ? "down" : "same"}`,
        text: delta === 0 ? "no change" : `${delta > 0 ? "+" : "-"}${Math.abs(delta)} pts` }));
  }

  /* ---------- template check: does the Word file match the setup template? ---------- */
  const CHECK_TITLE = { pass: "Matches the template", warn: "Matches the template, with things to look at", fail: "Does not match the template" };
  const CHECK_MARK = { pass: "OK", warn: "Look", fail: "Fix" };

  function checkCard() {
    return h("div", { class: "rb-check", id: "template-check", hidden: true });
  }

  async function loadCheck(id) {
    try {
      const response = await api(`/resume/requests/${id}/conformance`);
      const box = $("template-check");
      if (!response.ok || !box) return;
      const report = await response.json();
      const problems = report.checks.filter((c) => c.status !== "pass");
      box.className = `rb-check ${report.status}`;
      box.replaceChildren(
        h("strong", { text: "Template check" }),
        h("span", { class: `rb-check-status ${report.status}`, id: "template-check-status", text: CHECK_TITLE[report.status] }),
        problems.map((c) => h("div", { class: "rb-check-problem", text: c.message })),
        h("details", {},
          h("summary", { text: "All checks" }),
          report.checks.map((c) => h("div", { class: `rb-check-row ${c.status}` },
            h("span", { class: "rb-check-mark", text: CHECK_MARK[c.status] }), h("span", { text: c.message })))));
      box.hidden = false;
    } catch (e) {
      /* the check is a courtesy: if it cannot be shown, the page is still fine */
    }
  }

  function renderWorkspace() {
    const d = state.detail;
    $("view").replaceChildren(...[
      h("div", { class: "rb-bar" },
        h("button", { class: "btn", type: "button", id: "back", on: { click: () => attempt(renderTab) } }, "Back"),
        h("div", { class: "rb-titleblock" },
          h("h2", { text: `${d.jd.title}: ${d.associate.name}` }),
          h("span", { class: "muted", text: d.review_by === "RMG" ? "Reviewed by the RMG team (no Competency Lead)" : `Competency Lead: ${d.lead.name} (RMG can review too)` })),
        scoreBlock(d), statusBadge(d.status)),
      d.decision_note ? h("p", { class: "rb-note", id: "decision-note-shown", text: `Reviewer note: ${d.decision_note}` }) : null,
      h("div", { class: "rb-strip" },
        d.render_notes && d.render_notes.length ? h("div", { class: "rb-info", id: "render-notes" },
          h("strong", { text: "About the Word file" }), d.render_notes.map((n) => h("div", { text: n }))) : null,
        d.can && d.can.download ? checkCard() : null),
      actionBar(d), decisionCard(d),
      h("div", { class: "rb-grid rb-work" }, jdCard(d), resumeCard(d), changesCard(d)),
    ].filter(Boolean));
    wireLinks();
    if (d.can && d.can.download) loadCheck(d.id);
  }

  /* ---------- tabs ---------- */
  const TABS = [
    { id: "dashboard", label: "Dashboard", show: () => true, render: renderDashboard },
    { id: "mine", label: "My requests", show: () => true, render: renderMine },
    { id: "review", label: "Review", show: () => state.roles.includes("competency_lead") || isRmg(), render: renderReview },
    { id: "board", label: "Requests", show: isRmg, render: renderBoard },
    { id: "setup", label: "Setup", show: () => state.roles.includes("rmg_head"), render: renderSetup },
  ];

  async function renderTab() {
    const tab = TABS.find((t) => t.id === state.tab) || TABS[0];
    $("tabs").replaceChildren(...TABS.filter((t) => t.show()).map((t) => h("button", {
      class: "rb-tab", type: "button", "aria-current": t.id === tab.id ? "page" : null,
      on: { click: () => goToTab(t.id) },
    }, t.label)));
    await tab.render();
    loadNotes();
  }

  async function start() {
    try {
      const [me, { roles, available }] = await Promise.all([call("/me"), call("/resume/me")]);
      if (!available) { location.replace("/"); return; }  // the RMG module is off (or not installed)
      state.user = me;
      state.roles = roles;
      if ((me.apps || []).length < 2) {  // nothing else to go back to: no "All apps" button, and the title is not a link
        document.querySelector(".rb-user a.btn").hidden = true;
        document.querySelector(".rb-brand-link").removeAttribute("href");
      }
      $("who").textContent = me.name;
    } catch (error) {
      if (error.message !== "unauthorized") flash("The resume builder is not available right now.", "error");
      return;
    }
    state.tab = "dashboard";  // the landing page for everyone
    $("sign-out").addEventListener("click", () => { sessionStorage.removeItem(TOKEN_KEY); location.replace("/"); });
    $("bell").addEventListener("click", () => {
      const open = $("notes").hidden;
      $("notes").hidden = !open;
      $("bell").setAttribute("aria-expanded", String(open));
    });
    $("notes-read").addEventListener("click", () => attempt(async () => { await post("/resume/notifications/read"); await loadNotes(); }));
    $("jd-preview-close").addEventListener("click", () => $("jd-preview").close());
    $("jd-preview").addEventListener("click", (event) => { if (event.target === $("jd-preview")) $("jd-preview").close(); });  // a click outside the box
    await attempt(renderTab);
  }

  start();
})();
