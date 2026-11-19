/* The platform admin page: tick the modules the platform offers (HR, RMG) and save. Built with the strict CSP in mind:
 * no inline script, and text is only ever set with textContent. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "hr_token";
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) { location.replace("/"); return; }

  function h(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    for (const kid of kids) node.append(kid);
    return node;
  }

  function signOut() {
    sessionStorage.removeItem(TOKEN_KEY);
    location.replace("/");
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } });
    if (response.status === 401) { signOut(); throw new Error("unauthorized"); }
    return response;
  }

  function say(text, error = false) {
    const el = $("admin-message");
    el.textContent = text || "";
    el.className = `admin-message${error ? " error" : ""}`;
    el.hidden = !text;
  }

  async function onSave(event) {
    event.preventDefault();
    say("");
    const wanted = {};
    for (const box of document.querySelectorAll("#module-list input")) wanted[box.dataset.app] = box.checked;
    if (!Object.values(wanted).some(Boolean)) { say("Tick at least one app.", true); return; }
    $("save").disabled = true;
    try {
      const response = await api("/admin/modules", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(wanted),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) say((body.error && body.error.message) || "Could not save. Please try again.", true);
      else say("Saved. People who sign in from now on see only the ticked apps.");
    } catch (error) {
      if (error.message !== "unauthorized") say("Could not reach the server. Please try again.", true);
    } finally {
      $("save").disabled = false;
    }
  }

  async function start() {
    $("sign-out").addEventListener("click", signOut);
    $("modules-form").addEventListener("submit", onSave);
    try {
      const me = await (await api("/me")).json();
      if (!me.is_admin) { location.replace("/"); return; }
      $("who").textContent = me.name;
      const response = await api("/admin/modules");
      if (!response.ok) throw new Error("not ok");
      const { apps, installed } = await response.json();
      $("module-list").replaceChildren(...apps.map((app) => {
        const box = h("input", { id: `module-${app.id}`, type: "checkbox", "data-app": app.id });
        box.checked = app.enabled;
        return h("label", { class: "module-row", for: `module-${app.id}` }, box,
          h("span", {}, h("strong", {}, app.name), `${app.description}${installed[app.id] === false ? " (not installed on this server)" : ""}`));
      }));
    } catch (error) {
      if (error.message !== "unauthorized") say("The settings could not be loaded.", true);
    }
  }

  start();
})();
