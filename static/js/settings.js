/* Settings modal — scaffold + state plumbing.
 *
 * Chunk 3 of stage 2.2: opens, closes, switches tabs, fetches /api/settings,
 * shows placeholders. Functional tab bodies land in chunks 4-9.
 *
 * Public surface:
 *   Settings.open()        — fetch + show modal (used by gear icon)
 *   Settings.close()       — hide modal + drop focus trap
 *   Settings.refresh()     — re-fetch settings without closing
 *   Settings.activeTab     — current tab id (read-only-ish)
 *
 * Private state lives in module-level vars; nothing on window besides the
 * single Settings export.
 */

const Settings = (() => {
  // ---------------------------------------------------------------------------
  // Tab definitions. Body renderers are stubs in chunk 3; chunks 4-9 swap them
  // out for real implementations.
  // ---------------------------------------------------------------------------
  const TABS = [
    { id: "servers",       label: "Servers",       chunk: 4 },
    { id: "disks",         label: "Disks",         chunk: 5 },
    { id: "alerts",        label: "Alerts",        chunk: 6 },
    { id: "notifications", label: "Notifications", chunk: 7 },
    { id: "display",       label: "Display",       chunk: 8 },
    { id: "about",         label: "About",         chunk: 9 },
  ];

  let state = {
    settings: {},
    revision: 0,
    pendingRestart: [],
    secretSentinel: "***SET***",
    _runtime: {},  // populated from envelope.runtime — what's actually loaded
    activeTab: "servers",
    isOpen: false,
    fetchInFlight: false,
  };

  // ---------------------------------------------------------------------------
  // Network
  // ---------------------------------------------------------------------------
  function applyEnvelope(data) {
    if (!data || typeof data !== "object") return;
    state.settings = data.settings || {};
    state.revision = data.revision || 0;
    state.pendingRestart = data.pending_restart || [];
    state.secretSentinel = data.secret_sentinel || "***SET***";
    state._runtime = data.runtime || {};
  }

  async function fetchSettings() {
    state.fetchInFlight = true;
    try {
      const res = await fetch("/api/settings");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      applyEnvelope(data);
      return data;
    } finally {
      state.fetchInFlight = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------
  function renderSide() {
    const side = document.getElementById("st-side");
    if (!side) return;
    side.innerHTML = `
      <div class="st-side-head">Settings</div>
      ${TABS.map(t => `
        <button class="st-tab ${t.id === state.activeTab ? "active" : ""}"
                data-tab="${t.id}" type="button">
          ${t.label}
        </button>`).join("")}
      <div class="st-side-spacer"></div>
      <div class="st-side-foot">
        IPMI Dashboard · LAN-only.<br>
        Auth + remote access on the v3.x roadmap.
      </div>
    `;
    side.querySelectorAll(".st-tab").forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
  }

  function renderBody() {
    const body = document.getElementById("st-body");
    if (!body) return;
    const tab = TABS.find(t => t.id === state.activeTab) || TABS[0];
    const renderer = RENDERERS[tab.id] || renderPlaceholder;
    renderer(body, tab);
  }

  // ---------------------------------------------------------------------------
  // Generic placeholder for tabs not yet built (chunks 5-9 will swap these in)
  // ---------------------------------------------------------------------------
  function renderPlaceholder(body, tab) {
    body.innerHTML = `
      <div class="st-body-head">
        <h2>${tab.label}</h2>
        <p class="st-lead">Coming in chunk ${tab.chunk}.</p>
      </div>
      <div class="st-placeholder">
        <p>This tab will be wired up in a later chunk of the v2.2 settings UI.</p>
        <p>The REST API behind it
        (<code>GET /api/settings</code>, <code>PATCH /api/settings</code>)
        is already live — you can hit it directly with curl right now if you want.</p>
        <pre class="st-codeblock">curl -s http://localhost:8082/api/settings | jq .</pre>
      </div>
    `;
  }

  // ---------------------------------------------------------------------------
  // Servers tab — chunk 4
  //
  // Behaviours covered:
  //   - List currently configured servers in a table
  //   - Detect when servers are loaded from YAML or env (read-only banner)
  //   - Add a new server via inline form with Test Connection
  //   - Edit / Delete existing settings.json servers
  //   - Multi-vendor board dropdown (Redfish vendors visible but disabled)
  //   - Pending-restart pill lights up automatically (servers is RESTART_REQUIRED)
  // ---------------------------------------------------------------------------

  // Supermicro board families. Other vendors (Dell iDRAC, HPE iLO, ASRock
  // Rack via Redfish) are out of scope for ipmi-dashboard — see the sister
  // project brooksaw/ironboard for multi-vendor support.
  const BOARD_OPTIONS = [
    { value: "X11",        label: "Supermicro X11 (default)",    disabled: false },
    { value: "X10",        label: "Supermicro X10",              disabled: false },
    { value: "X10_LEGACY", label: "Supermicro X10 / X9 (legacy)", disabled: false },
  ];

  const serversUI = {
    // Local view-state, not persisted — drives which row is in edit mode and
    // what the inline add form is showing. Cleared on every renderServers().
    editingId: null,    // string | null — id of row currently being edited
    addOpen: false,     // bool — is the add form visible?
    testStatus: {},     // { id|"add": {ok, msg} } — last Test Connection result
  };

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function boardSelectHtml(selected, name = "board") {
    return `<select class="st-input" name="${name}">${
      BOARD_OPTIONS.map(o => `
        <option value="${o.value}"
                ${o.disabled ? "disabled" : ""}
                ${o.value === selected ? "selected" : ""}>
          ${o.label}
        </option>`).join("")
    }</select>`;
  }

  function renderServers(body) {
    const cfgServers = (state.settings.servers && typeof state.settings.servers === "object")
      ? state.settings.servers : {};
    const runtime = state._runtime || {};
    const source = runtime.servers_source || "none";

    // Banner if running from YAML or env — those rows are not editable here.
    let banner = "";
    if (source === "yaml") {
      banner = `<div class="st-info-banner">
        <strong>Servers are managed via <code>servers.yaml</code></strong> —
        edit that file (then restart the container) to change them.
        Adds made here will take precedence after restart but are normally a
        sign of conflicting configuration; pick one source.
      </div>`;
    } else if (source === "env") {
      banner = `<div class="st-info-banner">
        <strong>One server is configured via the <code>IPMI_HOST</code> environment variable.</strong>
        It's currently running but you can't edit it here — change the env vars on the container
        (or add servers below to take over).
      </div>`;
    } else if (source === "none" && Object.keys(cfgServers).length === 0) {
      banner = `<div class="st-info-banner">
        <strong>No servers configured yet.</strong> Add one below — IP, IPMI username, password, and board family.
      </div>`;
    }

    const rows = Object.entries(cfgServers).map(([sid, srv]) => {
      if (serversUI.editingId === sid) {
        return rowEdit(sid, srv);
      }
      return rowView(sid, srv);
    }).join("");

    body.innerHTML = `
      <div class="st-body-head">
        <h2>Servers</h2>
        <p class="st-lead">BMCs this dashboard polls. Changes need a container restart to take effect (a "Restart needed" pill will appear in the modal header).</p>
      </div>

      ${banner}

      <table class="st-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Host</th>
            <th>User</th>
            <th>Board</th>
            <th class="st-table-actions">Actions</th>
          </tr>
        </thead>
        <tbody id="st-srv-tbody">
          ${rows || `<tr><td colspan="5" class="st-empty">No servers in <code>settings.json</code> yet.</td></tr>`}
          ${serversUI.addOpen ? rowAdd() : ""}
        </tbody>
      </table>

      <div class="st-actions-row">
        ${serversUI.addOpen ? "" : `<button class="st-btn primary" id="st-add-server" type="button">＋ Add server</button>`}
      </div>
    `;

    wireServerHandlers(body);
  }

  function rowView(sid, srv) {
    const test = serversUI.testStatus[sid];
    const testBadge = test ? `<span class="st-test-${test.ok ? "ok" : "fail"}" title="${escapeHtml(test.msg)}">${test.ok ? "✓ reachable" : "✗ failed"}</span>` : "";
    return `
      <tr data-sid="${sid}">
        <td><strong>${escapeHtml(srv.name || sid)}</strong> <span class="st-id-chip">${sid}</span></td>
        <td><code>${escapeHtml(srv.host || "")}</code> ${testBadge}</td>
        <td>${escapeHtml(srv.user || "")}</td>
        <td>${escapeHtml(srv.board || "X11")}</td>
        <td class="st-table-actions">
          <button class="st-btn small" data-action="test"   data-sid="${sid}" type="button">Test</button>
          <button class="st-btn small" data-action="edit"   data-sid="${sid}" type="button">Edit</button>
          <button class="st-btn small danger" data-action="delete" data-sid="${sid}" type="button">Delete</button>
        </td>
      </tr>`;
  }

  function rowEdit(sid, srv) {
    const test = serversUI.testStatus[sid];
    const testBadge = test ? `<div class="st-test-line st-test-${test.ok ? "ok" : "fail"}">${test.ok ? "✓" : "✗"} ${escapeHtml(test.msg)}</div>` : "";
    return `
      <tr data-sid="${sid}" class="st-row-editing">
        <td colspan="5">
          <form class="st-form" data-form="edit" data-sid="${sid}">
            <div class="st-form-grid">
              <label>ID<input class="st-input" name="id" value="${escapeHtml(sid)}" disabled/></label>
              <label>Display name<input class="st-input" name="name" value="${escapeHtml(srv.name || "")}" required/></label>
              <label>Host / IP<input class="st-input" name="host" value="${escapeHtml(srv.host || "")}" required/></label>
              <label>User<input class="st-input" name="user" value="${escapeHtml(srv.user || "ADMIN")}" required/></label>
              <label>Password<input class="st-input" type="password" name="password" placeholder="${state.secretSentinel} (leave blank to keep)" autocomplete="off"/></label>
              <label>Board / vendor${boardSelectHtml(srv.board || "X11")}</label>
            </div>
            ${testBadge}
            <div class="st-form-actions">
              <button class="st-btn" data-action="test-form" type="button">Test Connection</button>
              <span class="grow"></span>
              <button class="st-btn" data-action="cancel-edit" type="button">Cancel</button>
              <button class="st-btn primary" type="submit">Save</button>
            </div>
          </form>
        </td>
      </tr>`;
  }

  function rowAdd() {
    const test = serversUI.testStatus["__add__"];
    const testBadge = test ? `<div class="st-test-line st-test-${test.ok ? "ok" : "fail"}">${test.ok ? "✓" : "✗"} ${escapeHtml(test.msg)}</div>` : "";
    return `
      <tr class="st-row-editing">
        <td colspan="5">
          <form class="st-form" data-form="add">
            <div class="st-form-grid">
              <label>ID <span class="st-hint">no spaces, used in URLs</span>
                <input class="st-input" name="id" required pattern="[a-z0-9_-]+" placeholder="e.g. cube"/></label>
              <label>Display name<input class="st-input" name="name" required placeholder="e.g. Joe's CUBE"/></label>
              <label>Host / IP<input class="st-input" name="host" required placeholder="192.168.1.x"/></label>
              <label>User<input class="st-input" name="user" required value="ADMIN"/></label>
              <label>Password<input class="st-input" type="password" name="password" required autocomplete="off"/></label>
              <label>Board / vendor${boardSelectHtml("X11")}</label>
            </div>
            ${testBadge}
            <div class="st-form-actions">
              <button class="st-btn" data-action="test-form" type="button">Test Connection</button>
              <span class="grow"></span>
              <button class="st-btn" data-action="cancel-add" type="button">Cancel</button>
              <button class="st-btn primary" type="submit">Add server</button>
            </div>
          </form>
        </td>
      </tr>`;
  }

  function wireServerHandlers(body) {
    body.querySelector("#st-add-server")?.addEventListener("click", () => {
      serversUI.addOpen = true;
      serversUI.editingId = null;
      renderServers(body);
    });

    body.querySelectorAll("button[data-action]").forEach(btn => {
      btn.addEventListener("click", (e) => handleServerAction(e.currentTarget, body));
    });

    body.querySelectorAll("form[data-form]").forEach(form => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        await handleServerSubmit(form, body);
      });
    });
  }

  async function handleServerAction(btn, body) {
    const action = btn.dataset.action;
    const sid = btn.dataset.sid;

    if (action === "edit") {
      serversUI.editingId = sid;
      serversUI.addOpen = false;
      delete serversUI.testStatus[sid];
      renderServers(body);
      return;
    }
    if (action === "cancel-edit") {
      serversUI.editingId = null;
      delete serversUI.testStatus[sid];
      renderServers(body);
      return;
    }
    if (action === "cancel-add") {
      serversUI.addOpen = false;
      delete serversUI.testStatus["__add__"];
      renderServers(body);
      return;
    }
    if (action === "test") {
      // Test using stored creds — call the API with current settings.json values
      const srv = state.settings.servers?.[sid];
      if (!srv) return;
      btn.disabled = true; btn.textContent = "Testing…";
      const res = await testServer({
        host: srv.host,
        user: srv.user,
        password: srv.password === state.secretSentinel ? null : (srv.password || null),
      });
      // If password was masked, we can't actually test without the real one;
      // tell the user to use Edit → Test Connection in that case.
      if (!srv.password || srv.password === state.secretSentinel) {
        serversUI.testStatus[sid] = { ok: false, msg: "Use Edit → Test Connection to test (password is masked here)" };
      } else {
        serversUI.testStatus[sid] = res;
      }
      btn.disabled = false; btn.textContent = "Test";
      renderServers(body);
      return;
    }
    if (action === "test-form") {
      const form = btn.closest("form");
      const fd = new FormData(form);
      const which = form.dataset.form === "edit" ? form.dataset.sid : "__add__";
      btn.disabled = true; btn.textContent = "Testing…";
      const res = await testServer({
        host: fd.get("host"),
        user: fd.get("user"),
        password: fd.get("password"),
      });
      serversUI.testStatus[which] = res;
      btn.disabled = false; btn.textContent = "Test Connection";
      renderServers(body);
      return;
    }
    if (action === "delete") {
      if (!confirm(`Delete server "${sid}"? This will be applied on the next container restart.`)) return;
      try {
        const res = await fetch(`/api/settings/servers.${encodeURIComponent(sid)}`, { method: "DELETE" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await Settings.refresh();
      } catch (err) {
        alert(`Delete failed: ${err.message}`);
      }
      return;
    }
  }

  async function handleServerSubmit(form, body) {
    const fd = new FormData(form);
    const sid = form.dataset.form === "edit" ? form.dataset.sid : (fd.get("id") || "").trim();
    if (!sid) { alert("ID is required"); return; }

    // Reject duplicate IDs on add
    if (form.dataset.form === "add" && state.settings.servers?.[sid]) {
      alert(`A server with id "${sid}" already exists.`);
      return;
    }

    const password = fd.get("password");
    const update = {
      name: fd.get("name"),
      host: fd.get("host"),
      user: fd.get("user"),
      board: fd.get("board"),
    };
    // Only include password if non-empty (lets edit form preserve existing)
    if (password) update.password = password;

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    submitBtn.textContent = form.dataset.form === "add" ? "Adding…" : "Saving…";
    try {
      const res = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ servers: { [sid]: update } }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      // Reset view-state and refresh from authoritative response
      serversUI.editingId = null;
      serversUI.addOpen = false;
      delete serversUI.testStatus[sid];
      delete serversUI.testStatus["__add__"];
      const data = await res.json();
      applyEnvelope(data);
      renderAll();
    } catch (err) {
      alert(`Save failed: ${err.message}`);
      submitBtn.disabled = false;
      submitBtn.textContent = form.dataset.form === "add" ? "Add server" : "Save";
    }
  }

  async function testServer({ host, user, password }) {
    if (!host || !user) return { ok: false, msg: "host and user are required" };
    try {
      const res = await fetch("/api/settings/test/server", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host, user, password: password || "", timeout: 5 }),
      });
      const data = await res.json();
      return { ok: !!data.ok, msg: data.ok ? data.summary : data.error };
    } catch (err) {
      return { ok: false, msg: err.message };
    }
  }

  // ---------------------------------------------------------------------------
  // Disks tab — chunk 5
  //
  // Coverage:
  //   - Master enable/disable toggle (disks.enabled)
  //   - Source picker: local | ssh
  //   - Local: path input
  //   - SSH: host, user, key (sensitive), timeout
  //   - Test Source button hits /api/settings/test/disks BEFORE save
  //   - Live preview pulls /api/disks if currently enabled+running
  //   - Pending-restart pill auto-lights (all disks.* paths are RESTART_REQUIRED)
  // ---------------------------------------------------------------------------

  const disksUI = {
    // Local form state. Initialised from settings on every render so the
    // user's in-progress edits survive re-renders triggered by Test.
    formInitialized: false,
    enabled: false,
    source: "local",
    localPath: "/host/disks.ini",
    sshHost: "",
    sshUser: "root",
    sshKey: "",        // empty = use SECRET_SENTINEL placeholder; stays as user types
    sshTimeout: 8,
    testStatus: null,  // {ok, msg}
    livePreview: null, // {enabled, as_of, disks:[...]}
  };

  function initDisksForm() {
    const d = state.settings.disks || {};
    disksUI.enabled    = !!d.enabled;
    disksUI.source     = (d.source || "local").toLowerCase();
    disksUI.localPath  = d.local_path || "/host/disks.ini";
    disksUI.sshHost    = d.ssh?.host || "";
    disksUI.sshUser    = d.ssh?.user || "root";
    disksUI.sshKey     = d.ssh?.key || "";
    disksUI.sshTimeout = Number.isFinite(d.ssh?.timeout) ? d.ssh.timeout : 8;
    disksUI.formInitialized = true;
  }

  async function fetchDisksLivePreview() {
    try {
      const r = await fetch("/api/disks");
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  }

  function renderDisks(body) {
    if (!disksUI.formInitialized) initDisksForm();

    const runtime = state._runtime || {};
    const isRunningEnabled = !!runtime.disks_enabled;
    const runtimeSource = runtime.disks_source || "local";

    // Live preview pane only makes sense if the runtime has it on; if user
    // is enabling it for the first time, restart-needed is the path forward.
    const previewBlock = isRunningEnabled
      ? `<div class="st-preview" id="st-disks-preview">
           <div class="st-preview-head">Live preview <span class="st-hint">/api/disks</span></div>
           <div id="st-disks-preview-body" class="st-preview-body">Loading…</div>
         </div>`
      : `<div class="st-info-banner st-info-muted">
           Disk monitoring is currently <strong>disabled</strong> in the running container.
           ${disksUI.enabled ? "After saving and restarting, the preview pane will appear here." : "Enable below and restart the container to start polling."}
         </div>`;

    const test = disksUI.testStatus;
    const testBadge = test
      ? `<div class="st-test-line st-test-${test.ok ? "ok" : "fail"}">${test.ok ? "✓" : "✗"} ${escapeHtml(test.msg)}</div>`
      : "";

    const sshKeyPlaceholder = disksUI.sshKey
      ? state.secretSentinel
      : "/ssh_key";

    body.innerHTML = `
      <div class="st-body-head">
        <h2>Disks</h2>
        <p class="st-lead">Reads <code>/var/local/emhttp/disks.ini</code> from an Unraid host to surface SMART health, temperature, capacity, and spin state. Optional — turn off if you don't want it.</p>
      </div>

      <form class="st-form" id="st-disks-form">
        <label class="st-toggle-row">
          <span>
            <strong>Enable disk monitoring</strong>
            <span class="st-hint">${isRunningEnabled ? "currently active in runtime" : "currently off in runtime"}</span>
          </span>
          <span class="st-toggle">
            <input type="checkbox" name="enabled" ${disksUI.enabled ? "checked" : ""}/>
            <span class="st-toggle-track"><span class="st-toggle-thumb"></span></span>
          </span>
        </label>

        <fieldset class="st-fieldset" ${disksUI.enabled ? "" : "disabled"}>
          <legend>Source</legend>

          <div class="st-radio-row">
            <label class="st-radio">
              <input type="radio" name="source" value="local" ${disksUI.source === "local" ? "checked" : ""}/>
              <span><strong>Local file mount</strong>
              <span class="st-hint">When this container runs ON the Unraid box. Mount <code>/var/local/emhttp/disks.ini</code> read-only into the container.</span></span>
            </label>
            <label class="st-radio">
              <input type="radio" name="source" value="ssh" ${disksUI.source === "ssh" ? "checked" : ""}/>
              <span><strong>SSH to remote Unraid</strong>
              <span class="st-hint">When the dashboard runs elsewhere and reads disks.ini over SSH. Requires an SSH key mounted into this container.</span></span>
            </label>
          </div>

          <div class="st-source-pane" data-source="local" ${disksUI.source === "local" ? "" : "hidden"}>
            <div class="st-form-grid">
              <label>Path inside the container
                <input class="st-input" name="local_path" value="${escapeHtml(disksUI.localPath)}" placeholder="/host/disks.ini"/>
                <span class="st-hint">Mount the host path here, e.g. <code>-v /var/local/emhttp/disks.ini:/host/disks.ini:ro</code></span>
              </label>
            </div>
          </div>

          <div class="st-source-pane" data-source="ssh" ${disksUI.source === "ssh" ? "" : "hidden"}>
            <div class="st-form-grid">
              <label>SSH host<input class="st-input" name="ssh_host" value="${escapeHtml(disksUI.sshHost)}" placeholder="192.168.1.5"/></label>
              <label>SSH user<input class="st-input" name="ssh_user" value="${escapeHtml(disksUI.sshUser)}" placeholder="root"/></label>
              <label>SSH key path
                <input class="st-input" type="${disksUI.sshKey === state.secretSentinel ? "password" : "text"}" name="ssh_key" placeholder="${escapeHtml(sshKeyPlaceholder)}" value="${disksUI.sshKey === state.secretSentinel ? state.secretSentinel : escapeHtml(disksUI.sshKey)}"/>
                <span class="st-hint">Path inside container. Mount your private key read-only, e.g. <code>-v ~/.ssh/disks-key:/ssh_key:ro</code></span>
              </label>
              <label>SSH timeout (s)
                <input class="st-input" type="number" name="ssh_timeout" min="1" max="60" value="${disksUI.sshTimeout}"/>
              </label>
            </div>
          </div>

          ${testBadge}

          <div class="st-form-actions">
            <button class="st-btn" id="st-disks-test" type="button">Test source</button>
            <span class="grow"></span>
            <button class="st-btn primary" type="submit">Save</button>
          </div>
        </fieldset>
      </form>

      ${previewBlock}
    `;

    wireDisksHandlers(body);

    if (isRunningEnabled) {
      // Async refresh of the live preview
      fetchDisksLivePreview().then(d => {
        const el = document.getElementById("st-disks-preview-body");
        if (!el) return;
        if (!d || !d.enabled || !d.disks?.length) {
          el.innerHTML = `<span class="st-muted">No disks reported yet. The poller updates every 30s; check back shortly.</span>`;
          return;
        }
        el.innerHTML = `
          <div class="st-preview-meta">As of ${escapeHtml(new Date(d.as_of).toLocaleString())} — ${d.disks.length} disk${d.disks.length === 1 ? "" : "s"}</div>
          <ul class="st-preview-list">
            ${d.disks.slice(0, 8).map(disk => `
              <li>
                <span class="st-disk-dot st-disk-${(disk.health || "UNKNOWN").toLowerCase()}"></span>
                <strong>${escapeHtml(disk.disk_name)}</strong>
                <span class="st-hint">${escapeHtml(disk.disk_type || "")}</span>
                <span class="grow"></span>
                <span class="st-mono">${disk.temp != null ? `${disk.temp}°C` : "—"}</span>
                <span class="st-mono">${(disk.capacity_pct ?? 0).toFixed(0)}%</span>
              </li>`).join("")}
          </ul>
          ${d.disks.length > 8 ? `<div class="st-hint" style="margin-top:6px">+${d.disks.length - 8} more — see Storage panel on the main dashboard</div>` : ""}
        `;
      });
    }
  }

  function wireDisksHandlers(body) {
    const form = document.getElementById("st-disks-form");
    if (!form) return;

    // Reflect live form-state into the disksUI struct so partial edits
    // survive a re-render (e.g. after Test runs).
    form.addEventListener("input", (e) => {
      const t = e.target;
      if (t.name === "enabled")     disksUI.enabled = t.checked;
      if (t.name === "source")      disksUI.source = t.value;
      if (t.name === "local_path")  disksUI.localPath = t.value;
      if (t.name === "ssh_host")    disksUI.sshHost = t.value;
      if (t.name === "ssh_user")    disksUI.sshUser = t.value;
      if (t.name === "ssh_key")     disksUI.sshKey = t.value;
      if (t.name === "ssh_timeout") disksUI.sshTimeout = parseInt(t.value, 10) || 8;

      if (t.name === "enabled") {
        // Toggle disabled state on the fieldset without full re-render
        form.querySelector(".st-fieldset").disabled = !t.checked;
      }
      if (t.name === "source") {
        body.querySelectorAll(".st-source-pane").forEach(p => {
          p.hidden = p.dataset.source !== t.value;
        });
      }
    });

    document.getElementById("st-disks-test")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true; btn.textContent = "Testing…";
      try {
        const payload = {
          source: disksUI.source,
          local_path: disksUI.localPath,
          ssh: {
            host: disksUI.sshHost,
            user: disksUI.sshUser,
            key: disksUI.sshKey,
            timeout: disksUI.sshTimeout,
          },
        };
        const r = await fetch("/api/settings/test/disks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        disksUI.testStatus = { ok: !!data.ok, msg: data.ok ? data.detail : data.error };
      } catch (err) {
        disksUI.testStatus = { ok: false, msg: err.message };
      }
      renderDisks(body);
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector("button[type=submit]");
      submitBtn.disabled = true; submitBtn.textContent = "Saving…";
      try {
        const sshKey = (disksUI.sshKey || "").trim();
        const patch = {
          disks: {
            enabled: !!disksUI.enabled,
            source: disksUI.source,
            local_path: disksUI.localPath,
            ssh: {
              host: disksUI.sshHost,
              user: disksUI.sshUser,
              // Send sentinel-as-typed; settings_store strips it server-side
              ...(sshKey ? { key: sshKey } : {}),
              timeout: disksUI.sshTimeout,
            },
          },
        };
        const r = await fetch("/api/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${r.status}`);
        }
        const data = await r.json();
        applyEnvelope(data);
        disksUI.formInitialized = false;  // re-init from new settings on next render
        disksUI.testStatus = { ok: true, msg: "Saved. Restart the container to apply." };
        renderAll();
      } catch (err) {
        alert(`Save failed: ${err.message}`);
        submitBtn.disabled = false;
        submitBtn.textContent = "Save";
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Alerts tab — chunk 6
  //
  // Eight thresholds across four sensor categories. All hot-reload via
  // alerts._live_thresholds() in the poller — NO restart pill required.
  // The poller picks up new values on the next cycle (~30s default).
  //
  // Empty input = "use env var or built-in default". The placeholder shows
  // the default so the user can see what's active without staring at empty
  // input boxes wondering what happens.
  // ---------------------------------------------------------------------------

  const ALERT_FIELDS = [
    {
      group: "CPU temperature",
      hint:  "Per-CPU sensors matching 'cpu' or 'processor'",
      rows: [
        { path: "alerts.cpu.warn", label: "Warn",     unit: "°C", default: 75, env: "CPU_WARN_C" },
        { path: "alerts.cpu.crit", label: "Critical", unit: "°C", default: 90, env: "CPU_CRIT_C" },
      ],
    },
    {
      group: "Inlet temperature",
      hint:  "Sensors matching 'inlet' (front-of-chassis intake)",
      rows: [
        { path: "alerts.inlet.warn", label: "Warn", unit: "°C", default: 45, env: "INLET_WARN_C" },
      ],
    },
    {
      group: "Fan speed",
      hint:  "Lowest acceptable fan RPM. Below = stuck/dead/fault.",
      rows: [
        { path: "alerts.fan.min", label: "Minimum", unit: "RPM", default: 500, env: "FAN_MIN_RPM" },
      ],
    },
    {
      group: "Disk temperature",
      hint:  "Applied to every disk reported by the disk plugin (parity, data, cache, etc.)",
      rows: [
        { path: "alerts.disk_temp.warn", label: "Warn",     unit: "°C", default: 40, env: "DISK_WARN_C" },
        { path: "alerts.disk_temp.crit", label: "Critical", unit: "°C", default: 50, env: "DISK_CRIT_C" },
      ],
    },
    {
      group: "Disk capacity",
      hint:  "Percentage full. Only fires for disks reporting fsSize/fsFree.",
      rows: [
        { path: "alerts.disk_capacity.warn", label: "Warn",     unit: "%", default: 85, env: "DISK_CAPACITY_WARN_PCT" },
        { path: "alerts.disk_capacity.crit", label: "Critical", unit: "%", default: 95, env: "DISK_CAPACITY_CRIT_PCT" },
      ],
    },
  ];

  function getCurrentAlertValue(path) {
    // Walk state.settings via dotted path, return undefined if not set
    const parts = path.split(".");
    let cur = state.settings;
    for (const p of parts) {
      if (cur == null || typeof cur !== "object" || !(p in cur)) return undefined;
      cur = cur[p];
    }
    return cur;
  }

  const alertsUI = {
    saveStatus: null,  // {ok, msg}
  };

  function renderAlerts(body) {
    const sections = ALERT_FIELDS.map(section => `
      <fieldset class="st-fieldset st-alert-group">
        <legend>${escapeHtml(section.group)}</legend>
        <p class="st-group-hint">${escapeHtml(section.hint)}</p>
        <div class="st-alert-rows">
          ${section.rows.map(r => {
            const cur = getCurrentAlertValue(r.path);
            const value = cur != null ? String(cur) : "";
            const isOverride = cur != null;
            return `
              <div class="st-alert-row">
                <label class="st-alert-label">${escapeHtml(r.label)}</label>
                <div class="st-alert-input-wrap">
                  <input class="st-input st-alert-input"
                         type="number"
                         step="any"
                         data-path="${r.path}"
                         value="${escapeHtml(value)}"
                         placeholder="${r.default}"/>
                  <span class="st-alert-unit">${r.unit}</span>
                </div>
                <div class="st-alert-meta">
                  <span class="st-alert-default ${isOverride ? "muted" : "active"}">
                    default: ${r.default} ${r.unit}
                  </span>
                  <span class="st-hint">env <code>${r.env}</code></span>
                </div>
              </div>`;
          }).join("")}
        </div>
      </fieldset>
    `).join("");

    const status = alertsUI.saveStatus;
    const statusBlock = status
      ? `<div class="st-test-line st-test-${status.ok ? "ok" : "fail"}">${status.ok ? "✓" : "✗"} ${escapeHtml(status.msg)}</div>`
      : "";

    body.innerHTML = `
      <div class="st-body-head">
        <h2>Alerts</h2>
        <p class="st-lead">Threshold values for opening/closing alerts. <strong>Changes hot-reload on the next poll cycle (~30s)</strong> — no container restart needed. Empty input means "use env var or built-in default".</p>
      </div>

      <form class="st-form" id="st-alerts-form">
        ${sections}
        ${statusBlock}
        <div class="st-form-actions">
          <button class="st-btn" id="st-alerts-reset" type="button">Reset all to defaults</button>
          <span class="grow"></span>
          <button class="st-btn primary" type="submit">Save thresholds</button>
        </div>
      </form>
    `;

    wireAlertsHandlers(body);
  }

  function wireAlertsHandlers(body) {
    const form = document.getElementById("st-alerts-form");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector("button[type=submit]");
      submitBtn.disabled = true; submitBtn.textContent = "Saving…";

      // Build a sparse patch: only include fields the user actually filled in.
      // Empty inputs cause a DELETE-equivalent — call settings_store.delete()
      // for each cleared key separately, since PATCH can't represent "remove".
      const inputs = form.querySelectorAll(".st-alert-input");
      const setKeys = {};
      const deleteKeys = [];
      inputs.forEach(inp => {
        const path = inp.dataset.path;
        const raw = inp.value.trim();
        if (raw === "") {
          // Was previously set, now empty → delete
          if (getCurrentAlertValue(path) !== undefined) deleteKeys.push(path);
          return;
        }
        const num = Number(raw);
        if (!Number.isFinite(num)) return;
        setKeys[path] = num;
      });

      try {
        // 1) DELETE cleared keys (one round-trip each — small N, fine)
        for (const path of deleteKeys) {
          const r = await fetch(`/api/settings/${encodeURIComponent(path)}`, { method: "DELETE" });
          if (!r.ok) throw new Error(`Delete ${path}: HTTP ${r.status}`);
        }

        // 2) PATCH set keys as a nested object
        let envelope;
        if (Object.keys(setKeys).length > 0) {
          const patch = {};
          for (const [path, val] of Object.entries(setKeys)) {
            const parts = path.split(".");
            let cur = patch;
            for (let i = 0; i < parts.length - 1; i++) {
              cur = cur[parts[i]] = cur[parts[i]] || {};
            }
            cur[parts[parts.length - 1]] = val;
          }
          const r = await fetch("/api/settings", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(patch),
          });
          if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${r.status}`);
          }
          envelope = await r.json();
        } else {
          // No PATCH needed; just refresh state from a GET
          const r = await fetch("/api/settings");
          envelope = await r.json();
        }

        applyEnvelope(envelope);
        const changed = Object.keys(setKeys).length + deleteKeys.length;
        alertsUI.saveStatus = {
          ok: true,
          msg: `Saved ${changed} threshold${changed === 1 ? "" : "s"}. Active on next poll cycle (~30s).`,
        };
        renderAll();
      } catch (err) {
        alertsUI.saveStatus = { ok: false, msg: err.message };
        submitBtn.disabled = false;
        submitBtn.textContent = "Save thresholds";
        renderAlerts(body);
      }
    });

    document.getElementById("st-alerts-reset")?.addEventListener("click", async () => {
      if (!confirm("Reset all alert thresholds to defaults? Any settings.json overrides under 'alerts' will be removed. Hot-reloads — no restart.")) return;
      try {
        const r = await fetch("/api/settings/alerts", { method: "DELETE" });
        if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
        // Refresh state
        const fresh = await fetch("/api/settings").then(x => x.json());
        applyEnvelope(fresh);
        alertsUI.saveStatus = { ok: true, msg: "Reset to defaults. Active on next poll cycle (~30s)." };
        renderAll();
      } catch (err) {
        alertsUI.saveStatus = { ok: false, msg: `Reset failed: ${err.message}` };
        renderAlerts(body);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Notifications tab — chunk 7
  //
  // Webhook URL + format + timeout, per-event mute toggles, Test button.
  // Hot-reload — no restart pill (notifications.py reads through settings_store
  // on every send_event() call).
  //
  // The webhook URL is masked on GET (notifications.webhook_url is in
  // SENSITIVE_PATHS). Sentinel round-trip preserves the saved URL when other
  // fields change.
  // ---------------------------------------------------------------------------

  const WEBHOOK_FORMATS = [
    { value: "generic", label: "Generic JSON",          hint: "Flat POST body — works for Mattermost custom webhooks, n8n, custom endpoints." },
    { value: "discord", label: "Discord webhook",       hint: "Posts as embeds. Drop in any Discord channel webhook URL." },
    { value: "slack",   label: "Slack incoming webhook",hint: "Posts as text with severity emoji (:rotating_light: / :warning: / :information_source:)." },
    { value: "ntfy",    label: "ntfy.sh",               hint: "Plain body + X-Title header. Works with self-hosted ntfy or ntfy.sh public." },
  ];

  // Events the dashboard fires. Order = display order in the toggle list.
  // Defaults are all-on (matches notifications._event_enabled() default).
  const NOTIF_EVENTS = [
    { name: "alert.opened",  label: "Alert opened",      hint: "Threshold breach starts. Highest signal-to-noise event." },
    { name: "alert.updated", label: "Alert level changed", hint: "Existing alert escalates warn↔crit. Mute if you don't care about transitions." },
    { name: "alert.cleared", label: "Alert cleared",     hint: "Returns to normal. Useful for noisy thresholds; mute if your channel doesn't care about resolutions." },
    { name: "power.action",  label: "Power action",      hint: "Someone clicked On/Off/Cycle/Reset on a server card." },
    { name: "power.failed",  label: "Power action failed", hint: "ipmitool power command returned an error. Strongly recommend keeping on." },
  ];

  const notifUI = {
    formInitialized: false,
    url: "",
    format: "generic",
    timeout: 5,
    events: {},      // { eventName: bool }
    testStatus: null,
  };

  function initNotifForm() {
    const n = state.settings.notifications || {};
    notifUI.url     = n.webhook_url ?? "";
    notifUI.format  = n.webhook_format || "generic";
    notifUI.timeout = Number.isFinite(n.webhook_timeout) ? n.webhook_timeout : 5;
    notifUI.events  = {};
    for (const ev of NOTIF_EVENTS) {
      // settings.notifications.events.<name> — undefined or true = enabled
      const v = n.events?.[ev.name];
      notifUI.events[ev.name] = v === false ? false : true;
    }
    notifUI.formInitialized = true;
  }

  function renderNotifications(body) {
    if (!notifUI.formInitialized) initNotifForm();

    const isUrlMasked = notifUI.url === state.secretSentinel;
    const hasUrl = !!notifUI.url && notifUI.url !== "";

    const formatOptions = WEBHOOK_FORMATS.map(f => `
      <option value="${f.value}" ${f.value === notifUI.format ? "selected" : ""}>${f.label}</option>
    `).join("");
    const formatHint = WEBHOOK_FORMATS.find(f => f.value === notifUI.format)?.hint || "";

    const eventToggles = NOTIF_EVENTS.map(ev => `
      <label class="st-toggle-row st-toggle-row-compact">
        <span>
          <strong>${escapeHtml(ev.label)}</strong>
          <span class="st-hint">${escapeHtml(ev.hint)}</span>
          <span class="st-event-name"><code>${ev.name}</code></span>
        </span>
        <span class="st-toggle">
          <input type="checkbox" data-event="${ev.name}" ${notifUI.events[ev.name] ? "checked" : ""}/>
          <span class="st-toggle-track"><span class="st-toggle-thumb"></span></span>
        </span>
      </label>
    `).join("");

    const test = notifUI.testStatus;
    const testBadge = test
      ? `<div class="st-test-line st-test-${test.ok ? "ok" : "fail"}">${test.ok ? "✓" : "✗"} ${escapeHtml(test.msg)}</div>`
      : "";

    body.innerHTML = `
      <div class="st-body-head">
        <h2>Notifications</h2>
        <p class="st-lead">POST events to Discord, Slack, ntfy, or any custom webhook. <strong>Hot-reloads on every send</strong> — no restart needed. Leave URL blank to silence everything.</p>
      </div>

      <form class="st-form" id="st-notif-form">
        <fieldset class="st-fieldset">
          <legend>Webhook</legend>

          <div class="st-form-grid">
            <label style="grid-column: 1 / -1">URL
              <input class="st-input" type="${isUrlMasked ? "password" : "text"}"
                     name="url"
                     value="${escapeHtml(notifUI.url)}"
                     placeholder="https://discord.com/api/webhooks/... or https://hooks.slack.com/... or https://ntfy.sh/topic"
                     autocomplete="off"/>
              <span class="st-hint">${hasUrl ? (isUrlMasked ? "Saved (masked). Type new value to replace." : "Will be sent as-is.") : "Empty = all webhooks disabled."}</span>
            </label>

            <label>Format
              <select class="st-input" name="format">${formatOptions}</select>
              <span class="st-hint">${escapeHtml(formatHint)}</span>
            </label>

            <label>Timeout (s)
              <input class="st-input" type="number" name="timeout" min="1" max="60" value="${notifUI.timeout}"/>
              <span class="st-hint">How long to wait for the webhook before giving up.</span>
            </label>
          </div>

          ${testBadge}

          <div class="st-form-actions">
            <button class="st-btn" id="st-notif-test" type="button" ${hasUrl || !isUrlMasked ? "" : "disabled"}>Test webhook</button>
            <span class="grow"></span>
            <button class="st-btn primary" type="submit">Save</button>
          </div>
        </fieldset>

        <fieldset class="st-fieldset st-events-fieldset">
          <legend>Events</legend>
          <p class="st-group-hint">Mute individual events without disabling the whole webhook. All on by default.</p>
          <div class="st-events-list">
            ${eventToggles}
          </div>
        </fieldset>
      </form>
    `;

    wireNotifHandlers(body);
  }

  function wireNotifHandlers(body) {
    const form = document.getElementById("st-notif-form");
    if (!form) return;

    // Live form-state mirror
    form.addEventListener("input", (e) => {
      const t = e.target;
      if (t.name === "url")     notifUI.url = t.value;
      if (t.name === "format")  {
        notifUI.format = t.value;
        // Re-render to update the format hint without losing other fields
        renderNotifications(body);
      }
      if (t.name === "timeout") notifUI.timeout = parseInt(t.value, 10) || 5;
      if (t.dataset.event)      notifUI.events[t.dataset.event] = t.checked;
    });

    document.getElementById("st-notif-test")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true; btn.textContent = "Testing…";
      try {
        // If URL is the masked sentinel, server-side test endpoint will see it
        // and reject — we need the user to type a real URL. Detect early.
        if (notifUI.url === state.secretSentinel) {
          notifUI.testStatus = { ok: false, msg: "Type a real URL to test (the saved one is masked here for security). Then save and the saved value will be used at runtime." };
        } else {
          const r = await fetch("/api/settings/test/webhook", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: notifUI.url, format: notifUI.format, timeout: notifUI.timeout }),
          });
          const data = await r.json();
          notifUI.testStatus = { ok: !!data.ok, msg: data.ok ? data.detail : data.error };
        }
      } catch (err) {
        notifUI.testStatus = { ok: false, msg: err.message };
      }
      renderNotifications(body);
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector("button[type=submit]");
      submitBtn.disabled = true; submitBtn.textContent = "Saving…";

      // Build the patch. URL is omitted when it's the sentinel (preserves saved
      // value via settings_store.unmask_into() server-side).
      const url = (notifUI.url || "").trim();
      const eventsPatch = {};
      for (const ev of NOTIF_EVENTS) {
        eventsPatch[ev.name] = !!notifUI.events[ev.name];
      }

      const patch = {
        notifications: {
          ...(url ? { webhook_url: url } : {}),  // empty URL = leave alone, use Reset to actually clear
          webhook_format: notifUI.format,
          webhook_timeout: notifUI.timeout,
          events: eventsPatch,
        },
      };

      try {
        const r = await fetch("/api/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${r.status}`);
        }
        const data = await r.json();
        applyEnvelope(data);
        notifUI.formInitialized = false;  // re-init from new state
        notifUI.testStatus = { ok: true, msg: "Saved. Hot-reloaded — next event uses the new config." };
        renderAll();
      } catch (err) {
        notifUI.testStatus = { ok: false, msg: `Save failed: ${err.message}` };
        submitBtn.disabled = false;
        submitBtn.textContent = "Save";
        renderNotifications(body);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Display tab — chunk 8
  //
  // Tunables that affect runtime cost / data retention. All three are
  // RESTART_REQUIRED (poll loop and prune loop are bound at startup; web port
  // is bound to the Flask app at boot).
  //
  // Web port is read-only here — changing it without simultaneously updating
  // the docker port mapping (or the macvlan rule) gives you an unreachable
  // dashboard. Show what's running, link out to docs for how to change it.
  // ---------------------------------------------------------------------------

  const displayUI = {
    formInitialized: false,
    pollInterval: 30,
    historyRetentionDays: 30,
    saveStatus: null,
  };

  function initDisplayForm() {
    displayUI.pollInterval = state.settings.poll_interval
      ?? state._runtime?.poll_interval
      ?? 30;
    displayUI.historyRetentionDays = state.settings.history_retention_days
      ?? state._runtime?.history_retention_days
      ?? 30;
    displayUI.formInitialized = true;
  }

  function renderDisplay(body) {
    if (!displayUI.formInitialized) initDisplayForm();

    const runtime = state._runtime || {};
    const runningPoll = runtime.poll_interval ?? "—";
    const runningRetention = runtime.history_retention_days ?? "—";
    const runningPort = runtime.web_port ?? "—";

    const status = displayUI.saveStatus;
    const statusBlock = status
      ? `<div class="st-test-line st-test-${status.ok ? "ok" : "fail"}">${status.ok ? "✓" : "✗"} ${escapeHtml(status.msg)}</div>`
      : "";

    body.innerHTML = `
      <div class="st-body-head">
        <h2>Display & runtime</h2>
        <p class="st-lead">Polling cadence, history retention, and web port. <strong>Restart required</strong> to apply — the poller and Flask app bind these at startup.</p>
      </div>

      <form class="st-form" id="st-display-form">
        <fieldset class="st-fieldset">
          <legend>Polling</legend>

          <div class="st-form-grid">
            <label>Poll interval (seconds)
              <input class="st-input" type="number" name="poll_interval"
                     min="5" max="3600" step="5"
                     value="${displayUI.pollInterval}"/>
              <span class="st-hint">How often the poller queries each BMC for sensors. Default 30s. Higher = lighter on the BMC; lower = quicker alert detection.</span>
            </label>

            <label>History retention (days)
              <input class="st-input" type="number" name="history_retention_days"
                     min="1" max="365" step="1"
                     value="${displayUI.historyRetentionDays}"/>
              <span class="st-hint">Old SensorReading / DiskReading / FanControlLog rows are pruned beyond this. Default 30. Lower = smaller SQLite DB.</span>
            </label>
          </div>

          <div class="st-runtime-meta">
            Running now: poll every <strong>${runningPoll}s</strong>, keep <strong>${runningRetention}</strong> days of history.
          </div>
        </fieldset>

        <fieldset class="st-fieldset">
          <legend>Web port (read-only)</legend>

          <div class="st-readonly-grid">
            <div>
              <span class="st-readonly-label">Container is listening on</span>
              <span class="st-readonly-value">${runningPort}</span>
            </div>
            <div class="st-hint" style="grid-column: 1/-1; margin-top: 6px">
              Changing the listen port also requires updating the Docker port mapping
              (<code>-p &lt;host&gt;:&lt;container&gt;</code>) or — on Atlas's services macvlan —
              picking a different free port on the macvlan IP. Edit
              <code>WEB_PORT</code> env or <code>web_port</code> in settings.json,
              then update the container deployment to match.
            </div>
          </div>
        </fieldset>

        ${statusBlock}

        <div class="st-form-actions">
          <button class="st-btn" id="st-display-reset" type="button">Reset to defaults</button>
          <span class="grow"></span>
          <button class="st-btn primary" type="submit">Save</button>
        </div>
      </form>
    `;

    wireDisplayHandlers(body);
  }

  function wireDisplayHandlers(body) {
    const form = document.getElementById("st-display-form");
    if (!form) return;

    form.addEventListener("input", (e) => {
      const t = e.target;
      if (t.name === "poll_interval")          displayUI.pollInterval = parseInt(t.value, 10) || 30;
      if (t.name === "history_retention_days") displayUI.historyRetentionDays = parseInt(t.value, 10) || 30;
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector("button[type=submit]");
      submitBtn.disabled = true; submitBtn.textContent = "Saving…";

      const patch = {
        poll_interval: displayUI.pollInterval,
        history_retention_days: displayUI.historyRetentionDays,
      };

      try {
        const r = await fetch("/api/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${r.status}`);
        }
        const data = await r.json();
        applyEnvelope(data);
        displayUI.formInitialized = false;
        displayUI.saveStatus = { ok: true, msg: "Saved. Restart the container to apply." };
        renderAll();
      } catch (err) {
        displayUI.saveStatus = { ok: false, msg: `Save failed: ${err.message}` };
        submitBtn.disabled = false;
        submitBtn.textContent = "Save";
        renderDisplay(body);
      }
    });

    document.getElementById("st-display-reset")?.addEventListener("click", async () => {
      if (!confirm("Clear poll_interval and history_retention_days from settings.json? Falls back to env vars or defaults (30/30). Restart needed to apply.")) return;
      try {
        // Two independent DELETEs — no atomic multi-delete in the API
        for (const key of ["poll_interval", "history_retention_days"]) {
          const r = await fetch(`/api/settings/${key}`, { method: "DELETE" });
          if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status} on DELETE ${key}`);
        }
        const fresh = await fetch("/api/settings").then(x => x.json());
        applyEnvelope(fresh);
        displayUI.formInitialized = false;
        displayUI.saveStatus = { ok: true, msg: "Reset. Restart the container to apply." };
        renderAll();
      } catch (err) {
        displayUI.saveStatus = { ok: false, msg: `Reset failed: ${err.message}` };
        renderDisplay(body);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // About tab — chunk 9
  //
  // Project metadata (read-only): version, revision, repo links, license,
  // active runtime snapshot, related project pointer (ironboard for
  // multi-vendor users).
  // ---------------------------------------------------------------------------

  function renderAbout(body) {
    const runtime = state._runtime || {};
    const version  = runtime.version  || "dev";
    const revision = runtime.revision || "unknown";
    const isDevBuild = version === "dev";

    // Show short SHA if revision is a 40-char git hash
    const shortRev = (revision && revision.length >= 8 && revision !== "unknown")
      ? revision.slice(0, 8)
      : revision;

    const buildBadge = isDevBuild
      ? `<span class="st-badge st-badge-dev">dev build</span>`
      : `<span class="st-badge st-badge-release">v${escapeHtml(version)}</span>`;

    body.innerHTML = `
      <div class="st-body-head">
        <h2>About IPMI Dashboard</h2>
        <p class="st-lead">Supermicro BMC + Unraid disk-health dashboard. Open source, MIT licensed, on the Unraid Community Apps store.</p>
      </div>

      <div class="st-about-card">
        <div class="st-about-row">
          <span class="st-about-label">Version</span>
          <span class="st-about-value">${buildBadge}</span>
        </div>
        <div class="st-about-row">
          <span class="st-about-label">Build SHA</span>
          <span class="st-about-value"><code>${escapeHtml(shortRev)}</code></span>
        </div>
        <div class="st-about-row">
          <span class="st-about-label">Source</span>
          <span class="st-about-value">
            <a href="https://github.com/brooksaw/ipmi-dashboard" target="_blank" rel="noopener">github.com/brooksaw/ipmi-dashboard</a>
          </span>
        </div>
        <div class="st-about-row">
          <span class="st-about-label">Image</span>
          <span class="st-about-value"><code>ghcr.io/brooksaw/ipmi-dashboard:${isDevBuild ? "dev" : escapeHtml(version)}</code></span>
        </div>
        <div class="st-about-row">
          <span class="st-about-label">License</span>
          <span class="st-about-value">MIT</span>
        </div>
      </div>

      <h3 class="st-about-section">Looking for multi-vendor?</h3>
      <ul class="st-about-related">
        <li>
          <strong>ironboard</strong> — sister project that adds Redfish backends (Dell iDRAC, HPE iLO, ASRock Rack) on top of the same UI. Use this if your fleet isn't Supermicro-only.<br>
          <a href="https://github.com/brooksaw/ironboard" target="_blank" rel="noopener">github.com/brooksaw/ironboard</a>
        </li>
      </ul>

      <h3 class="st-about-section">Roadmap</h3>
      <table class="st-table st-roadmap">
        <thead>
          <tr><th>Stage</th><th>Title</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr><td>2.0</td><td>Multi-server Flask web UI + history charts + alerts</td><td><span class="st-badge st-badge-release">shipped</span></td></tr>
          <tr><td>2.1</td><td>Unraid disk monitoring</td><td><span class="st-badge st-badge-release">shipped</span></td></tr>
          <tr><td>2.2</td><td>Settings UI (this modal — backend hot-reload + 6 config tabs)</td><td><span class="st-badge st-badge-release">shipped</span></td></tr>
          <tr><td>2.3</td><td>Sidebar + density modes (Focus / Grid / Compact)</td><td><span class="st-badge st-badge-planned">planned</span></td></tr>
          <tr><td>2.4</td><td>VNC console + websockify (browser KVM)</td><td><span class="st-badge st-badge-planned">planned</span></td></tr>
          <tr><td>2.5</td><td>GPU monitoring (NVIDIA)</td><td><span class="st-badge st-badge-planned">planned</span></td></tr>
        </tbody>
      </table>

      <h3 class="st-about-section">Active config snapshot</h3>
      <table class="st-table">
        <tbody>
          <tr><td>Servers configured</td><td>${Object.keys(state.settings.servers || {}).length} (source: ${escapeHtml(runtime.servers_source || "none")})</td></tr>
          <tr><td>Disk monitoring</td><td>${runtime.disks_enabled ? `enabled (source: ${escapeHtml(runtime.disks_source || "?")})` : "disabled"}</td></tr>
          <tr><td>Poll interval</td><td>${runtime.poll_interval ?? "?"}s</td></tr>
          <tr><td>History retention</td><td>${runtime.history_retention_days ?? "?"} days</td></tr>
          <tr><td>Web port</td><td>${runtime.web_port ?? "?"}</td></tr>
          <tr><td>Notifications</td><td>${state.settings.notifications?.webhook_url ? "configured" : "not set"}</td></tr>
          <tr><td>Settings revision</td><td><code>#${state.revision}</code></td></tr>
        </tbody>
      </table>

      <p class="st-about-foot">
        Released under MIT — see
        <a href="https://github.com/brooksaw/ipmi-dashboard/blob/main/LICENSE" target="_blank" rel="noopener">LICENSE</a>.
        Issues + feature requests welcome at
        <a href="https://github.com/brooksaw/ipmi-dashboard/issues" target="_blank" rel="noopener">github.com/brooksaw/ipmi-dashboard/issues</a>.
      </p>
    `;
  }

  // Renderer registry — each chunk 4-9 adds an entry here.
  const RENDERERS = {
    servers:       renderServers,
    disks:         renderDisks,
    alerts:        renderAlerts,
    notifications: renderNotifications,
    display:       renderDisplay,
    about:         renderAbout,
  };

  function renderHeader() {
    const restartChip = document.getElementById("st-restart-chip");
    if (!restartChip) return;
    if (state.pendingRestart.length > 0) {
      restartChip.style.display = "";
      restartChip.title = `Restart required: ${state.pendingRestart.join(", ")}`;
      restartChip.querySelector(".st-restart-count").textContent = state.pendingRestart.length;
    } else {
      restartChip.style.display = "none";
    }
  }

  function renderAll() {
    renderSide();
    renderBody();
    renderHeader();
  }

  // ---------------------------------------------------------------------------
  // Behavior
  // ---------------------------------------------------------------------------
  function switchTab(tabId) {
    if (!TABS.find(t => t.id === tabId)) return;
    if (state.activeTab === tabId) return;
    state.activeTab = tabId;
    renderSide();   // updates which tab is .active
    renderBody();
  }

  async function open() {
    if (state.isOpen) return;
    const scrim = document.getElementById("settings-scrim");
    if (!scrim) return;

    state.isOpen = true;
    scrim.classList.add("open");
    document.body.classList.add("settings-open");

    // Show whatever was last loaded immediately (cuts perceived latency).
    renderAll();

    try {
      await fetchSettings();
      renderAll();
    } catch (err) {
      const body = document.getElementById("st-body");
      if (body) {
        body.innerHTML = `<div class="st-error">Failed to load settings: ${err.message}</div>`;
      }
    }

    // Focus the first tab so keyboard users land somewhere predictable.
    const firstTab = document.querySelector(".st-tab.active") || document.querySelector(".st-tab");
    firstTab?.focus();
  }

  function close() {
    if (!state.isOpen) return;
    const scrim = document.getElementById("settings-scrim");
    if (!scrim) return;
    scrim.classList.remove("open");
    document.body.classList.remove("settings-open");
    state.isOpen = false;
    // Return focus to the gear so keyboard nav doesn't get lost
    document.getElementById("open-settings")?.focus();
  }

  async function refresh() {
    try {
      await fetchSettings();
      renderAll();
    } catch (err) {
      console.warn("[settings] refresh failed:", err);
    }
  }

  // ---------------------------------------------------------------------------
  // Wire-up — runs once on DOMContentLoaded
  // ---------------------------------------------------------------------------
  function init() {
    const gear = document.getElementById("open-settings");
    const scrim = document.getElementById("settings-scrim");
    const closeBtn = document.getElementById("st-close");

    gear?.addEventListener("click", () => open());
    closeBtn?.addEventListener("click", () => close());

    // Click-outside (on scrim background, not on the panel itself)
    scrim?.addEventListener("click", (e) => {
      if (e.target === scrim) close();
    });

    // ESC to close
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.isOpen) close();
    });

    // Render the initial scaffold so first open is instant (state will refresh).
    renderAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return {
    open,
    close,
    refresh,
    get activeTab() { return state.activeTab; },
    get state() { return state; },  // read-only snapshot for chunks 4-9 to consume
  };
})();

window.Settings = Settings;
