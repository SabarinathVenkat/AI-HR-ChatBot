/* HR Assistant web client.
 * All dynamic content is built with DOM APIs (textContent), never innerHTML, so model output or
 * data can never inject markup. Pairs with the strict Content-Security-Policy set by the server. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "hr_token";
  const THREAD_KEY = "hr_thread";

  const state = {
    token: sessionStorage.getItem(TOKEN_KEY),
    threadId: sessionStorage.getItem(THREAD_KEY),
    user: null,
    busy: false,
  };

  const ROLE_LABELS = { employee: "Employee", manager: "Manager", hr_admin: "HR admin" };
  const LEAVE_NAMES = {
    AL: "Annual leave", CL: "Casual leave", SL: "Sick leave", ML: "Maternity leave",
    PL: "Paternity leave", BL: "Bereavement leave", MRL: "Marriage leave", CO: "Compensatory off",
  };
  const INTENT_LABELS = {
    policy_question: "Policy question", data_question: "Your leave data", policy_and_data: "Policy and your data",
    calculation: "Day calculation", leave_request: "Leave request", manager_action: "Manager question",
    complex_plan: "Planning", sensitive: "Sensitive topic", chitchat: "Chat", out_of_scope: "Outside HR",
    confirmation: "Confirmation",
  };
  const STARTERS = {
    employee: [
      "How many annual leave days do I have left?",
      "What is the notice period after confirmation?",
      "Can I take leave from 2 November to 6 November?",
      "Which holidays are in October?",
      "Can I carry forward my unused leave?",
    ],
    manager: [
      "Which requests are waiting for my approval?",
      "Who in my team is on leave next week?",
    ],
  };

  /* ---------- small DOM helpers ---------- */
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

  function showScreen(name) {
    $("login-screen").hidden = name !== "login";
    $("chat-screen").hidden = name !== "chat";
  }

  const initials = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("");
  const fmtDays = (n) => (Number.isInteger(n) ? String(n) : String(n));
  const fmtDate = (iso) => {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  };
  const fmtRange = (start, end) => (start === end ? fmtDate(start) : `${fmtDate(start)} to ${fmtDate(end)}`);

  /* ---------- API ---------- */
  function authHeaders(extra = {}) {
    return { ...extra, Authorization: `Bearer ${state.token}` };
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: authHeaders(options.headers || {}),
    });
    if (response.status === 401) {
      signOut("Your session has ended. Please sign in again.");
      throw new Error("unauthorized");
    }
    return response;
  }

  /* ---------- rich text: paragraphs, lists, bold, citation chips ---------- */
  const CITATION_GROUP = /(\[[^\]]*POL-\d{2}[^\]]*\])/;
  const CITATION_REF = /(POL-\d{2}\s§\d+(?:\.\d+)*)|§(\d+(?:\.\d+)*)/g;

  function appendBold(parent, text) {
    text.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) parent.append(h("strong", { text: part.slice(2, -2) }));
      else if (part) parent.append(part);
    });
  }

  function appendInline(parent, text) {
    text.split(CITATION_GROUP).forEach((segment) => {
      if (!CITATION_GROUP.test(segment)) {
        appendBold(parent, segment);
        return;
      }
      let policy = null;
      for (const match of segment.matchAll(CITATION_REF)) {
        let id;
        if (match[1]) {
          id = match[1];
          policy = id.split(" ")[0];
        } else if (policy) {
          id = `${policy} §${match[2]}`;
        } else continue;
        parent.append(
          h("button", {
            class: "chip", type: "button", title: "Show the policy text",
            text: match[1] ? id : `§${match[2]}`,
            on: { click: () => openPolicy(id) },
          }),
        );
      }
    });
  }

  function renderRich(target, text) {
    target.replaceChildren();
    const lines = text.split("\n");
    let paragraph = [];
    let list = null;
    const flushParagraph = () => {
      if (paragraph.length) {
        const p = h("p");
        appendInline(p, paragraph.join(" "));
        target.append(p);
        paragraph = [];
      }
    };
    const flushList = () => {
      list = null;
    };
    for (const line of lines) {
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (bullet || numbered) {
        flushParagraph();
        const kind = bullet ? "ul" : "ol";
        if (!list || list.kind !== kind) {
          list = { kind, node: h(kind) };
          target.append(list.node);
        }
        const li = h("li");
        appendInline(li, (bullet || numbered)[1]);
        list.node.append(li);
      } else if (line.trim() === "") {
        flushParagraph();
        flushList();
      } else {
        flushList();
        paragraph.push(line.trim());
      }
    }
    flushParagraph();
  }

  async function openPolicy(id) {
    const dialog = $("policy-dialog");
    $("policy-title").textContent = id;
    $("policy-meta").textContent = "Loading…";
    $("policy-text").textContent = "";
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    try {
      const response = await api(`/policy/section?id=${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error("not found");
      const section = await response.json();
      $("policy-title").textContent = `${section.section_id}: ${section.title}`;
      $("policy-meta").textContent = `${section.policy_title}, version ${section.version}, effective ${section.effective_date}. Sample policy for demonstration.`;
      $("policy-text").textContent = section.text;
    } catch (error) {
      if (error.message !== "unauthorized") {
        $("policy-meta").textContent = "I could not load that section.";
      }
    }
  }

  /* ---------- messages ---------- */
  const messagesEl = () => $("messages");

  function scrollDown() {
    const el = messagesEl();
    el.scrollTop = el.scrollHeight;
  }

  function addUser(text) {
    messagesEl().append(h("div", { class: "msg user" }, h("div", { class: "bubble", text })));
    scrollDown();
  }

  function addAssistant(text) {
    const bubble = h("div", { class: "bubble" });
    const meta = h("div", { class: "meta" });
    const root = h("div", { class: "msg assistant" }, bubble, meta);
    messagesEl().append(root);
    if (text) renderRich(bubble, text);
    scrollDown();
    return { root, bubble, meta, answer: "", steps: [], stepsEl: null, thinking: null };
  }

  function showThinking(m, label) {
    if (!m.thinking) {
      m.thinking = h("span", { class: "thinking" }, h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")), h("span", { class: "thinking-label" }));
      m.bubble.replaceChildren(m.thinking);
    }
    m.thinking.querySelector(".thinking-label").textContent = label;
  }

  function showError(m, message) {
    m.bubble.className = "bubble error";
    m.bubble.setAttribute("role", "alert");
    m.bubble.textContent = message;
    m.thinking = null;
  }

  function addStep(m, step) {
    m.steps.push(step);
    if (!m.stepsEl) {
      m.stepsEl = h("details", { class: "steps" }, h("summary"), h("ol"));
      m.root.insertBefore(m.stepsEl, m.meta);
    }
    const args = JSON.stringify(step.arguments);
    m.stepsEl.querySelector("ol").append(
      h("li", {}, h("code", { text: step.tool }), ` ${args.length > 90 ? args.slice(0, 87) + "..." : args}`, step.ok ? "" : " (failed)"),
    );
    m.stepsEl.querySelector("summary").textContent = `How I got this (${m.steps.length} ${m.steps.length === 1 ? "step" : "steps"})`;
  }

  function addMeta(m, done, seconds) {
    m.meta.replaceChildren();
    if (INTENT_LABELS[done.intent]) m.meta.append(h("span", { class: "tag", text: INTENT_LABELS[done.intent] }));
    if (done.used_fallback) m.meta.append(h("span", { class: "tag warn", text: "Plain answer from your data" }));
    else if (done.rewrites > 0) m.meta.append(h("span", { class: "tag", text: "Corrected after checking" }));
    m.meta.append(h("span", { text: `${seconds.toFixed(1)}s` }));
  }

  /* ---------- leave confirmation card ---------- */
  function addConfirmCard(m, draft) {
    const status = h("p", { class: "confirm-status", role: "status" });
    const confirmBtn = h("button", { class: "btn primary", type: "button", text: "Confirm and submit" });
    const cancelBtn = h("button", { class: "btn", type: "button", text: "Cancel" });
    const actions = h("div", { class: "confirm-actions" }, confirmBtn, cancelBtn);
    const card = h(
      "div", { class: "confirm-card", role: "group", "aria-label": "Confirm leave request" },
      h("h3", { text: "Ready to submit?" }),
      h("dl", {},
        h("dt", { text: "Leave" }), h("dd", { text: LEAVE_NAMES[draft.leave_type] || draft.leave_type }),
        h("dt", { text: "Dates" }), h("dd", { text: fmtRange(draft.start_date, draft.end_date) }),
        h("dt", { text: "Working days" }), h("dd", { text: fmtDays(draft.days) }),
        draft.lop_days > 0 ? h("dt", { text: "Unpaid days" }) : null,
        draft.lop_days > 0 ? h("dd", { text: fmtDays(draft.lop_days) }) : null,
      ),
      actions,
      status,
    );
    m.root.insertBefore(card, m.meta);

    const finish = (text, kind) => {
      actions.hidden = true;
      status.textContent = text;
      status.className = `confirm-status ${kind}`;
    };
    const lock = (locked) => { confirmBtn.disabled = locked; cancelBtn.disabled = locked; };

    confirmBtn.addEventListener("click", async () => {
      lock(true);
      try {
        const response = await api(`/leave/drafts/${draft.draft_id}/confirm`, { method: "POST" });
        const body = await response.json().catch(() => ({}));
        if (response.ok) {
          finish(body.status === "already_submitted" ? "Already submitted." : "Submitted. Your manager has been asked to approve it.", "ok");
        } else if (response.status === 410) {
          finish("This request expired. Ask me to prepare it again.", "bad");
        } else if (response.status === 409) {
          finish("This request is no longer allowed.", "bad");
          const blocking = (body.rules || []).filter((r) => !r.passed && r.blocking);
          if (blocking.length) status.after(h("ul", { class: "rule-list" }, blocking.map((r) => h("li", { text: r.message }))));
        } else {
          finish("I could not submit that. Please try again.", "bad");
          lock(false);
          actions.hidden = false;
        }
      } catch (error) {
        if (error.message !== "unauthorized") lock(false);
      }
      refreshPanel();
    });

    cancelBtn.addEventListener("click", async () => {
      lock(true);
      try {
        await api(`/leave/drafts/${draft.draft_id}/cancel`, { method: "POST" });
        finish("Cancelled. Nothing was submitted.", "bad");
      } catch (error) {
        if (error.message !== "unauthorized") lock(false);
      }
    });
    scrollDown();
  }

  /* ---------- streaming ---------- */
  async function* readEvents(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) yield { event, data: JSON.parse(data) };
      }
    }
  }

  function stepLabel(tool) {
    if (tool.startsWith("delegate_to_")) return `Asking the ${tool.slice(12).replaceAll("_", " ")}…`;
    return `Checking ${tool.replaceAll("_", " ")}…`;
  }

  function handleEvent(m, event, data, startedAt) {
    if (event === "route") {
      showThinking(m, `${INTENT_LABELS[data.intent] || "Working on it"}…`);
    } else if (event === "step") {
      addStep(m, data);
      showThinking(m, stepLabel(data.tool));
    } else if (event === "token") {
      m.thinking = null;
      m.answer += data.text;
      renderRich(m.bubble, m.answer);
      scrollDown();
    } else if (event === "confirm_required") {
      addConfirmCard(m, data);
    } else if (event === "done") {
      if (data.thread_id) {
        state.threadId = data.thread_id;
        sessionStorage.setItem(THREAD_KEY, state.threadId);
      }
      addMeta(m, data, (performance.now() - startedAt) / 1000);
      scrollDown();
    } else if (event === "error") {
      showError(m, data.message || "Something went wrong. Please try again.");
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    $("send").disabled = busy;
    $("composer-input").disabled = busy;
    if (!busy) $("composer-input").focus();
  }

  async function send(text) {
    text = text.trim();
    if (!text || state.busy) return;
    setBusy(true);
    $("starters").hidden = true;
    addUser(text);
    const m = addAssistant();
    showThinking(m, "Thinking…");
    const startedAt = performance.now();
    try {
      const response = await api("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, thread_id: state.threadId || undefined }),
      });
      if (response.status === 429) {
        const wait = response.headers.get("Retry-After") || "a few";
        showError(m, `You are sending messages quickly. Please wait ${wait} seconds.`);
      } else if (!response.ok) {
        showError(m, "Something went wrong. Please try again.");
      } else {
        for await (const { event, data } of readEvents(response)) handleEvent(m, event, data, startedAt);
        if (m.thinking) showError(m, "I did not get an answer. Please try again.");
      }
    } catch (error) {
      if (error.message !== "unauthorized") showError(m, "I could not reach the server. Check your connection and try again.");
    } finally {
      if (state.token) {
        setBusy(false);
        refreshPanel();
      }
    }
  }

  /* ---------- side panel ---------- */
  function renderBalances(balances) {
    const wanted = [["AL", "Annual"], ["CL", "Casual"], ["SL", "Sick"]];
    const byType = Object.fromEntries(balances.map((b) => [b.leave_type, b]));
    $("balances").replaceChildren(
      ...wanted.filter(([code]) => byType[code]).map(([code, label]) => h("div", { class: "balance" },
        h("span", { class: "num", text: fmtDays(byType[code].available) }),
        h("span", { class: "label", text: `${label} days` }),
        byType[code].pending > 0 ? h("span", { class: "sub", text: `${fmtDays(byType[code].pending)} pending` }) : null,
      )),
    );
  }

  function requestItem(r, actions) {
    return h("li", { class: "request" },
      h("div", { class: "top" },
        h("span", { class: "what", text: `${r.employee ? r.employee + ": " : ""}${LEAVE_NAMES[r.leave_type] || r.leave_type}, ${fmtDays(r.days)} ${r.days === 1 ? "day" : "days"}` }),
        h("span", { class: `pill ${r.status || "pending"}`, text: r.status || "pending" }),
      ),
      h("div", { class: "when", text: fmtRange(r.start_date, r.end_date) }),
      actions && actions.length ? h("div", { class: "actions" }, actions) : null,
    );
  }

  async function refreshPanel() {
    if (!state.token) return;
    try {
      const [balances, requests] = await Promise.all([
        api("/leave/balance").then((r) => r.json()),
        api("/leave/requests").then((r) => r.json()),
      ]);
      renderBalances(balances.balances || []);
      const mine = requests.requests || [];
      $("requests").replaceChildren(
        ...(mine.length ? mine.map((r) => requestItem(r, r.can_cancel ? [
          h("button", { class: "btn small danger", type: "button", text: "Cancel request", on: { click: () => cancelRequest(r.id) } }),
        ] : [])) : [h("li", { class: "muted", text: "No requests yet." })]),
      );
      if (state.user && state.user.role === "manager") {
        const team = await api("/leave/requests?scope=team").then((r) => r.json());
        const pending = (team.requests || []).filter((r) => r.status === "pending");
        $("approvals-section").hidden = false;
        $("approvals").replaceChildren(
          ...(pending.length ? pending.map((r) => requestItem(r, [
            h("button", { class: "btn small primary", type: "button", text: "Approve", on: { click: () => decide(r.id, "approve") } }),
            h("button", { class: "btn small danger", type: "button", text: "Reject", on: { click: () => decide(r.id, "reject") } }),
          ])) : [h("li", { class: "muted", text: "Nothing waiting." })]),
        );
      }
    } catch (error) {
      /* the panel is a convenience; a failed refresh must not break chat */
    }
  }

  async function cancelRequest(id) {
    if (!window.confirm("Cancel this leave request?")) return;
    await api(`/leave/requests/${id}/cancel`, { method: "POST" }).catch(() => {});
    refreshPanel();
  }

  async function decide(id, decision) {
    const note = decision === "reject" ? window.prompt("Reason for rejecting (optional)") : null;
    if (decision === "reject" && note === null) return;
    await api(`/leave/requests/${id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note: note || undefined }),
    }).catch(() => {});
    refreshPanel();
  }

  /* ---------- screens ---------- */
  function renderStarters() {
    const role = state.user.role;
    const list = [...STARTERS.employee, ...(role === "manager" ? STARTERS.manager : [])];
    $("starters").replaceChildren(...list.map((text) => h("button", { type: "button", text, on: { click: () => send(text) } })));
    $("starters").hidden = false;
  }

  function greet() {
    const first = state.user.name.split(" ")[0];
    messagesEl().replaceChildren();
    addAssistant(`Hi ${first}! I can check your leave balance, tell you whether dates work, apply for leave, and answer questions about HR policies. What would you like to do?`);
    renderStarters();
  }

  function newChat() {
    state.threadId = null;
    sessionStorage.removeItem(THREAD_KEY);
    greet();
  }

  async function enterChat() {
    const response = await api("/me");
    if (!response.ok) throw new Error("not ok");
    state.user = await response.json();
    $("who").textContent = `${state.user.name} · ${ROLE_LABELS[state.user.role] || state.user.role}`;
    $("avatar").textContent = initials(state.user.name);
    $("approvals-section").hidden = state.user.role !== "manager";
    showScreen("chat");
    greet();
    refreshPanel();
    $("composer-input").focus();
  }

  function signOut(message) {
    state.token = null;
    state.user = null;
    state.threadId = null;
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(THREAD_KEY);
    showScreen("login");
    setLoginError(message || "");
    loadDemoAccounts();
  }

  function setLoginError(message) {
    const el = $("login-error");
    el.textContent = message;
    el.hidden = !message;
  }

  async function loadDemoAccounts() {
    try {
      const response = await fetch("/demo/accounts");
      if (!response.ok) return;
      const { accounts, password } = await response.json();
      $("demo-password").textContent = password;
      $("demo-list").replaceChildren(...accounts.map((a) => h("li", {},
        h("button", { type: "button", on: { click: () => {
          $("login-email").value = a.email;
          $("login-password").value = password;
          $("login-submit").focus();
        } } },
          h("span", { class: "avatar", "aria-hidden": "true", text: initials(a.name) }),
          h("span", { class: "who-text" },
            h("span", { class: "nm", text: a.name }),
            h("span", { class: "role", text: `${ROLE_LABELS[a.role] || a.role}, ${a.department}` })),
        ),
      )));
      $("demo-box").hidden = false;
    } catch (error) { /* demo accounts are optional */ }
  }

  async function onLogin(event) {
    event.preventDefault();
    setLoginError("");
    $("login-submit").disabled = true;
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: $("login-email").value.trim(), password: $("login-password").value }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.status === 429) {
        const minutes = Math.ceil((Number(response.headers.get("Retry-After")) || 60) / 60);
        setLoginError(`Too many failed attempts. Try again in about ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`);
      } else if (!response.ok) {
        setLoginError((body.error && body.error.message) || "Sign-in failed. Please try again.");
      } else {
        state.token = body.access_token;
        sessionStorage.setItem(TOKEN_KEY, state.token);
        $("login-password").value = "";
        await enterChat();
      }
    } catch (error) {
      if (error.message !== "unauthorized") setLoginError("I could not reach the server. Please try again.");
    } finally {
      $("login-submit").disabled = false;
    }
  }

  function autosize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }

  function init() {
    $("login-form").addEventListener("submit", onLogin);
    $("sign-out").addEventListener("click", () => signOut(""));
    $("new-chat").addEventListener("click", newChat);
    $("composer").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = $("composer-input");
      const text = input.value;
      input.value = "";
      autosize(input);
      send(text);
    });
    $("composer-input").addEventListener("input", (event) => autosize(event.target));
    $("composer-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        $("composer").requestSubmit();
      }
    });

    if (state.token) {
      enterChat().catch(() => signOut(""));
    } else {
      showScreen("login");
      loadDemoAccounts();
    }
  }

  init();
})();
