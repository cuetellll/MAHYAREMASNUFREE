/* ═══════════════════════════════════════════════════════════════════════════
   app.js — MahyarFree interface controller.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const { Spark, TrafficChart, formatRate, formatBytes, formatDuration } = window.GraphFX;

  const State = {
    settings: {},
    nodes: [],
    status: { running: false, core: "", node_id: "", node_name: "", uptime: 0 },
    filter: "all",
    search: "",
    sort: "latency",
    pinging: false,
    connecting: false,
    peakDown: 0,
    startedAt: 0,
  };

  const $ = (id) => document.getElementById(id);
  const el = (selector) => document.querySelector(selector);
  const els = (selector) => Array.from(document.querySelectorAll(selector));

  let sparkDown;
  let sparkUp;
  let chart;
  let statsChart;

  /* ────────────────────────────── sound engine ────────────────────────────── */
  const Sound = (() => {
    let ctx = null;
    function ensure() {
      if (!ctx) {
        try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { ctx = null; }
      }
      return ctx;
    }
    return {
      play(type) {
        if (!State.settings.sound) return;
        const audio = ensure();
        if (!audio) return;
        const now = audio.currentTime;
        const osc = audio.createOscillator();
        const gain = audio.createGain();
        const map = {
          click: [520, 0.05, "triangle"],
          on: [420, 0.32, "sine"],
          off: [260, 0.22, "sine"],
          error: [150, 0.4, "sawtooth"],
        };
        const [freq, duration, wave] = map[type] || map.click;
        osc.type = wave;
        osc.frequency.setValueAtTime(freq, now);
        osc.frequency.exponentialRampToValueAtTime(type === "on" ? freq * 2.2 : freq * 0.7, now + duration);
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.055, now + 0.012);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
        osc.connect(gain).connect(audio.destination);
        osc.start(now);
        osc.stop(now + duration + 0.02);
      },
    };
  })();

  /* ─────────────────────────────── toasts ─────────────────────────────── */
  function toast(message, kind = "info", timeout = 3800) {
    const box = $("toasts");
    const node = document.createElement("div");
    node.className = `toast toast--${kind}`;
    node.textContent = message;
    box.appendChild(node);
    setTimeout(() => {
      node.classList.add("is-out");
      setTimeout(() => node.remove(), 320);
    }, timeout);
  }

  function overlay(show, text) {
    const box = $("overlay");
    if (text) $("overlay-text").textContent = text;
    box.hidden = !show;
  }

  /* ─────────────────────────────── navigation ─────────────────────────────── */
  function goTo(page) {
    els(".rail__btn[data-page]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.page === page);
    });
    els(".page").forEach((section) => {
      section.classList.toggle("is-active", section.dataset.page === page);
    });
    if (page === "stats") {
      chart && chart.draw();
      statsChart && statsChart.draw();
    }
    if (page === "servers") { renderServers(); }
  }

  /* ──────────────────────────────── servers ──────────────────────────────── */
  const QUALITY_ORDER = { excellent: 0, good: 1, fair: 2, poor: 3, offline: 4 };

  function qualityOf(ms) {
    if (ms === null || ms === undefined) return "offline";
    if (ms < 120) return "excellent";
    if (ms < 250) return "good";
    if (ms < 500) return "fair";
    return "poor";
  }

  function visibleNodes() {
    let list = State.nodes.slice();
    const query = State.search.trim().toLowerCase();

    if (State.filter === "fav") list = list.filter((n) => n.favourite);
    else if (State.filter !== "all") list = list.filter((n) => n.protocol === State.filter);

    if (query) {
      list = list.filter((n) =>
        (n.name || "").toLowerCase().includes(query) ||
        (n.server || "").toLowerCase().includes(query) ||
        (n.protocol || "").toLowerCase().includes(query) ||
        (n.group || "").toLowerCase().includes(query));
    }

    const byLatency = (a, b) => {
      const qa = QUALITY_ORDER[qualityOf(a.latency)];
      const qb = QUALITY_ORDER[qualityOf(b.latency)];
      if (qa !== qb) return qa - qb;
      return (a.latency || 9999) - (b.latency || 9999);
    };

    if (State.sort === "latency") list.sort(byLatency);
    else if (State.sort === "name") list.sort((a, b) => (a.name || "").localeCompare(b.name || "", "fa"));
    else if (State.sort === "group") list.sort((a, b) => (a.group || "").localeCompare(b.group || "", "fa") || byLatency(a, b));
    else if (State.sort === "fav") list.sort((a, b) => Number(b.favourite) - Number(a.favourite) || byLatency(a, b));

    return list;
  }

  function renderServers() {
    const list = $("serverlist");
    const nodes = visibleNodes();
    list.querySelectorAll(".scard, .empty").forEach((n) => n.remove());

    if (!nodes.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.innerHTML = `
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.4 3 14.6 0 18M12 3c-3 3.4-3 14.6 0 18"/></svg>
        <div>سروری پیدا نشد — لینک سابسکریپشن را بررسی کنید یا دکمهٔ «به‌روزرسانی» را بزنید.</div>`;
      list.appendChild(empty);
      return;
    }

    const fragment = document.createDocumentFragment();
    nodes.forEach((node, index) => {
      const quality = qualityOf(node.latency);
      const card = document.createElement("article");
      card.className = "scard" + (node.id === State.status.node_id && State.status.running ? " is-active" : "");
      card.dataset.id = node.id;
      card.style.animationDelay = `${Math.min(index * 22, 420)}ms`;
      card.innerHTML = `
        <div class="scard__top">
          <span class="scard__flag">${node.country || "🌐"}</span>
          <span class="scard__name" title="${escapeHtml(node.name)}">${escapeHtml(node.name)}</span>
          <button class="scard__star ${node.favourite ? "is-on" : ""}" data-star="${node.id}" title="علاقه‌مندی">★</button>
        </div>
        <div class="scard__tags">
          <span class="tag tag--${node.protocol}">${node.protocol}</span>
          <span class="tag tag--dim">${(node.transport || "tcp").toUpperCase()}</span>
          <span class="tag tag--dim">${node.core}</span>
          ${node.tls ? '<span class="tag tag--dim">TLS</span>' : ""}
          ${node.group ? `<span class="tag tag--dim">${escapeHtml(node.group)}</span>` : ""}
        </div>
        <div class="scard__bottom">
          <div class="bars" data-q="${quality}"><i></i><i></i><i></i><i></i><i></i></div>
          <span class="scard__latency" data-q="${quality}">${node.latency === null || node.latency === undefined ? "—" : node.latency + " ms"}</span>
        </div>
        <div class="scard__server">${escapeHtml(node.server)}:${node.port}</div>`;
      fragment.appendChild(card);
    });

    list.appendChild(fragment);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ──────────────────────────────── status ──────────────────────────────── */
  function setStatus(patch) {
    Object.assign(State.status, patch || {});
    const running = !!State.status.running;
    const pill = $("status-pill");
    const orb = $("btn-connect");

    if (State.connecting) {
      pill.dataset.state = "connecting";
      pill.querySelector(".statuspill__label").textContent = "در حال اتصال…";
      orb.dataset.state = "connecting";
      $("orb-label").textContent = "اتصال…";
    } else if (running) {
      pill.dataset.state = "on";
      pill.querySelector(".statuspill__label").textContent = "متصل";
      orb.dataset.state = "on";
      $("orb-label").textContent = "قطع";
    } else {
      pill.dataset.state = "off";
      pill.querySelector(".statuspill__label").textContent = "قطع";
      orb.dataset.state = "off";
      $("orb-label").textContent = "اتصال";
    }

    if (window.OrbFX) window.OrbFX.setMode(State.connecting ? "connecting" : running ? "on" : "off");

    $("core-chip-value").textContent = State.status.core || "—";
    $("meta-uptime").textContent = formatDuration(State.status.uptime || 0);
    $("s-uptime").textContent = formatDuration(State.status.uptime || 0);

    const chip = $("current-node");
    chip.classList.toggle("is-live", running);
    const node = State.nodes.find((n) => n.id === State.status.node_id) ||
      State.nodes.find((n) => n.id === State.settings.selected_node_id);
    if (node) {
      chip.querySelector(".nodechip__flag").textContent = node.country || "🌐";
      chip.querySelector(".nodechip__name").textContent = node.name;
      chip.querySelector(".nodechip__ping").textContent =
        node.latency === null || node.latency === undefined ? "—" : node.latency + "ms";
      $("meta-ping").textContent = node.latency === null || node.latency === undefined ? "—" : node.latency + "ms";
      $("current-ping").textContent = node.latency === null || node.latency === undefined ? "—" : node.latency + "ms";
    }
    renderServers();
  }

  /* ──────────────────────────────── actions ──────────────────────────────── */
  async function doConnect(nodeId) {
    if (State.connecting) return;
    if (State.status.running && (!nodeId || nodeId === State.status.node_id)) {
      State.connecting = true;
      setStatus({});
      overlay(true, "در حال قطع اتصال…");
      try {
        await Bridge.call("disconnect");
        toast("اتصال قطع شد", "warn");
        Sound.play("off");
      } finally {
        State.connecting = false;
        overlay(false);
        setStatus({ running: false, core: "", node_id: "", uptime: 0 });
      }
      return;
    }

    State.connecting = true;
    setStatus({});
    overlay(true, "در حال اتصال به سرور…");
    try {
      const result = await Bridge.call("connect", nodeId || "");
      if (result && result.ok) {
        State.startedAt = Date.now();
        setStatus({ ...result, running: true });
        toast(`متصل شد — ${result.node_name || "سرور"}`, "ok");
        Sound.play("on");
        sparkDown && sparkDown.reset();
        sparkUp && sparkUp.reset();
        chart && chart.reset();
        statsChart && statsChart.reset();
      } else {
        toast((result && result.error) || "اتصال ناموفق بود", "err", 5200);
        Sound.play("error");
        setStatus({ running: false });
      }
    } catch (error) {
      toast("خطای غیرمنتظره: " + error, "err");
    } finally {
      State.connecting = false;
      overlay(false);
      setStatus({});
    }
  }

  async function doBest() {
    if (State.connecting) return;
    State.connecting = true;
    setStatus({});
    overlay(true, "در حال یافتن بهترین سرور…");
    try {
      const result = await Bridge.call("connect_best");
      if (!result || !result.ok) {
        toast("هیچ سرور سالمی پیدا نشد", "err", 5200);
        Sound.play("error");
        setStatus({ running: false });
      } else {
        State.startedAt = Date.now();
        setStatus({ ...result, running: true });
        toast(`بهترین سرور پیدا شد — ${result.node_name || ""}`, "ok");
        Sound.play("on");
      }
    } catch (error) {
      toast("خطای غیرمنتظره: " + error, "err");
    } finally {
      State.connecting = false;
      overlay(false);
      setStatus({});
    }
  }

  async function doPingAll() {
    if (State.pinging) return;
    State.pinging = true;
    $("radar").classList.add("is-on");
    toast("آزمون واقعی عبور اینترنت از همهٔ سرورها آغاز شد", "info", 2600);
    await Bridge.call("ping_all");
  }

  /* ──────────────────────────────── render ──────────────────────────────── */
  function renderSubscriptions() {
    const list = $("sublist");
    const subs = State.settings.subscriptions || [];
    list.innerHTML = "";
    if (!subs.length) {
      list.innerHTML = '<div class="empty" style="padding:18px 6px">هیچ سابسکریپشنی ثبت نشده است.</div>';
      return;
    }
    subs.forEach((sub) => {
      const row = document.createElement("div");
      row.className = "subrow";
      row.innerHTML = `
        <span class="dot ${sub.enabled === false ? "dot--off" : "dot--on"}"></span>
        <div class="subrow__info">
          <div class="subrow__name">${escapeHtml(sub.name)}</div>
          <div class="subrow__url">${escapeHtml(sub.url)}</div>
        </div>
        <input type="checkbox" class="switch" data-sub-toggle="${sub.id}" ${sub.enabled === false ? "" : "checked"}>
        <button class="subrow__del" data-sub-del="${sub.id}" title="حذف">✕</button>`;
      list.appendChild(row);
    });
  }

  function renderCores() {
    const list = $("corelist");
    const cores = State.cores || {};
    list.innerHTML = "";
    Object.keys(cores).forEach((name) => {
      const info = cores[name] || {};
      const row = document.createElement("div");
      row.className = "corerow";
      row.innerHTML = `
        <span class="dot ${info.available ? "dot--on" : "dot--off"}"></span>
        <span class="corerow__name">${escapeHtml(name)}</span>
        <span class="corerow__ver">${escapeHtml(info.version || "نصب نشده")}</span>
        ${info.available ? "" : `<button class="qbtn qbtn--xs" data-core-dl="${name}">دانلود</button>`}`;
      list.appendChild(row);
    });
  }

  function applySettingsToForm() {
    const s = State.settings;
    const setCheck = (id, value) => { const node = $(id); if (node) node.checked = !!value; };
    setCheck("set-ads", s.block_ads);
    setCheck("set-lan", s.bypass_lan);
    setCheck("set-fragment", s.fragment);
    setCheck("set-mux", s.mux);
    setCheck("set-autostart", s.autostart);
    setCheck("set-best-start", s.auto_best_on_start);
    setCheck("set-autoupd", s.update_on_start);
    setCheck("set-anim", s.animations);
    setCheck("set-sound", s.sound);

    if ($("set-socks")) $("set-socks").value = s.socks_port;
    if ($("set-http")) $("set-http").value = s.http_port;
    if ($("set-core")) $("set-core").value = s.preferred_core || "auto";

    segSync("set-mode", s.mode);
    segSync("set-routing", s.routing);
    segSync("seg-mode", s.mode);
    segSync("seg-routing", s.routing);

    document.body.classList.toggle("no-anim", !s.animations);
    renderSubscriptions();
    renderCores();
  }

  function segSync(id, value) {
    const group = $(id);
    if (!group) return;
    group.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.value === value);
    });
  }

  async function save(patch, quiet) {
    Object.assign(State.settings, patch);
    const result = await Bridge.call("save_settings", patch);
    if (result && result.settings) State.settings = result.settings;
    applySettingsToForm();
    if (!quiet) toast("تنظیمات ذخیره شد", "ok", 1800);
  }

  /* ──────────────────────────────── wiring ──────────────────────────────── */
  function wire() {
    els(".rail__btn[data-page]").forEach((button) => {
      button.addEventListener("click", () => { Sound.play("click"); goTo(button.dataset.page); });
    });

    els("[data-win]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.win;
        if (action === "close") Bridge.call("quit");
        if (action === "min") Bridge.call("minimize");
        if (action === "max") Bridge.call("toggle_maximize");
      });
    });

    $("btn-connect").addEventListener("click", () => doConnect(""));
    $("btn-best").addEventListener("click", doBest);
    $("btn-quick-best").addEventListener("click", doBest);
    $("btn-ping").addEventListener("click", doPingAll);
    $("btn-ping-all").addEventListener("click", doPingAll);

    $("btn-refresh").addEventListener("click", async () => {
      overlay(true, "در حال دریافت سابسکریپشن…");
      try {
        const result = await Bridge.call("refresh");
        if (result && result.errors && Object.keys(result.errors).length) {
          Object.values(result.errors).forEach((message) => toast(message, "err", 5000));
        } else if (result && result.count !== undefined && !result.started) {
          toast(`${result.count} سرور بارگذاری شد`, "ok");
        }
      } finally {
        overlay(false);
      }
    });

    $("search").addEventListener("input", (event) => {
      State.search = event.target.value;
      renderServers();
    });
    $("sort").addEventListener("change", (event) => {
      State.sort = event.target.value;
      renderServers();
    });

    $("filters").addEventListener("click", (event) => {
      const button = event.target.closest(".chipf");
      if (!button) return;
      State.filter = button.dataset.filter;
      els(".chipf").forEach((chip) => chip.classList.toggle("is-active", chip === button));
      renderServers();
    });

    $("serverlist").addEventListener("click", async (event) => {
      const star = event.target.closest("[data-star]");
      if (star) {
        event.stopPropagation();
        const result = await Bridge.call("toggle_favourite", star.dataset.star);
        if (result && result.nodes) State.nodes = result.nodes;
        star.classList.toggle("is-on", result && result.favourite);
        return;
      }
      const card = event.target.closest(".scard");
      if (!card) return;
      const node = State.nodes.find((n) => n.id === card.dataset.id);
      if (!node) return;
      if (State.status.running && State.status.node_id === node.id) {
        doConnect(node.id);
      } else {
        toast(`اتصال به ${node.name}…`, "info", 2000);
        doConnect(node.id);
      }
    });

    els("#seg-mode button, #set-mode button").forEach((button) => {
      button.addEventListener("click", () => save({ mode: button.dataset.value }, true));
    });
    els("#seg-routing button, #set-routing button").forEach((button) => {
      button.addEventListener("click", () => save({ routing: button.dataset.value }, true));
    });

    const bindSwitch = (id, key) => {
      const node = $(id);
      if (node) node.addEventListener("change", () => save({ [key]: node.checked }, true));
    };
    bindSwitch("set-ads", "block_ads");
    bindSwitch("set-lan", "bypass_lan");
    bindSwitch("set-fragment", "fragment");
    bindSwitch("set-mux", "mux");
    bindSwitch("set-autostart", "autostart");
    bindSwitch("set-best-start", "auto_best_on_start");
    bindSwitch("set-autoupd", "update_on_start");
    bindSwitch("set-anim", "animations");
    bindSwitch("set-sound", "sound");

    $("set-core").addEventListener("change", (event) => save({ preferred_core: event.target.value }, true));
    $("set-socks").addEventListener("change", (event) => save({ socks_port: Number(event.target.value) || 20808 }, true));
    $("set-http").addEventListener("change", (event) => save({ http_port: Number(event.target.value) || 20809 }, true));

    $("btn-add-sub").addEventListener("click", () => { $("addsub").hidden = !$("addsub").hidden; });
    $("btn-save-sub").addEventListener("click", async () => {
      const name = $("sub-name").value.trim();
      const url = $("sub-url").value.trim();
      if (!url) { toast("لینک سابسکریپشن را وارد کنید", "warn"); return; }
      const result = await Bridge.call("add_subscription", name, url);
      if (result && result.subscriptions) {
        State.settings.subscriptions = result.subscriptions;
        $("sub-name").value = "";
        $("sub-url").value = "";
        $("addsub").hidden = true;
        renderSubscriptions();
        toast("سابسکریپشن افزوده شد", "ok");
      }
    });

    $("sublist").addEventListener("click", async (event) => {
      const del = event.target.closest("[data-sub-del]");
      if (del) {
        const result = await Bridge.call("remove_subscription", del.dataset.subDel);
        if (result && result.subscriptions) {
          State.settings.subscriptions = result.subscriptions;
          renderSubscriptions();
        }
      }
    });
    $("sublist").addEventListener("change", async (event) => {
      const toggle = event.target.closest("[data-sub-toggle]");
      if (toggle) {
        const result = await Bridge.call("toggle_subscription", toggle.dataset.subToggle);
        if (result && result.subscriptions) {
          State.settings.subscriptions = result.subscriptions;
          renderSubscriptions();
        }
      }
    });

    $("corelist").addEventListener("click", (event) => {
      const button = event.target.closest("[data-core-dl]");
      if (button) {
        toast(`دانلود ${button.dataset.coreDl} آغاز شد…`, "info");
        Bridge.call("download_core", button.dataset.coreDl);
      }
    });

    $("btn-open-dir").addEventListener("click", () => Bridge.call("open_data_dir"));
    $("btn-elevate").addEventListener("click", async () => {
      const result = await Bridge.call("request_elevation");
      if (result && result.already) toast("برنامه همین حالا با دسترسی ادمین اجرا می‌شود", "ok");
      else toast("درخواست دسترسی ادمین ارسال شد", "info");
    });
    $("btn-clear-log").addEventListener("click", () => { $("logbox").textContent = ""; });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") goTo("home");
      if (event.key === "F5") { event.preventDefault(); doPingAll(); }
      if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); doConnect(""); }
    });

    window.addEventListener("resize", () => {
      sparkDown && sparkDown.draw();
      sparkUp && sparkUp.draw();
      chart && chart.draw();
      statsChart && statsChart.draw();
    });

    setInterval(() => {
      const now = new Date();
      $("clock").textContent = now.toLocaleTimeString("fa-IR", { hour12: false });
      if (State.status.running && State.startedAt) {
        const uptime = Math.floor((Date.now() - State.startedAt) / 1000);
        State.status.uptime = uptime;
        $("meta-uptime").textContent = formatDuration(uptime);
        $("s-uptime").textContent = formatDuration(uptime);
      }
    }, 1000);
  }

  /* ──────────────────────────────── events ──────────────────────────────── */
  function bindEvents() {
    Bridge.on("traffic", (sample) => {
      const down = Number(sample.down) || 0;
      const up = Number(sample.up) || 0;
      $("spd-down").textContent = (down / (1024 * 1024)).toFixed(2);
      $("spd-up").textContent = (up / (1024 * 1024)).toFixed(2);
      $("tot-down").textContent = formatBytes(sample.total_down || 0);
      $("tot-up").textContent = formatBytes(sample.total_up || 0);
      $("s-total-down").textContent = formatBytes(sample.total_down || 0);
      $("s-total-up").textContent = formatBytes(sample.total_up || 0);
      State.peakDown = Math.max(State.peakDown, down);
      $("s-peak-down").textContent = formatRate(State.peakDown);
      sparkDown && sparkDown.push(down);
      sparkUp && sparkUp.push(up);
      chart && chart.push(down, up);
      statsChart && statsChart.push(down, up);
    });

    Bridge.on("status", (status) => setStatus(status));

    Bridge.on("connecting", (info) => {
      $("overlay-text").textContent = `در حال اتصال به ${info.node_name || "سرور"}…`;
    });

    Bridge.on("best-progress", (info) => {
      $("overlay-text").textContent =
        `بررسی سرور ${info.attempt}/${info.count} — ${info.name}`;
    });

    Bridge.on("ping-start", () => {
      State.pinging = true;
      $("radar").classList.add("is-on");
    });

    Bridge.on("ping-result", (info) => {
      const node = State.nodes.find((n) => n.id === info.id);
      if (node) node.latency = info.latency;
      const card = document.querySelector(`.scard[data-id="${info.id}"]`);
      if (card) {
        const quality = qualityOf(info.latency);
        const bars = card.querySelector(".bars");
        const label = card.querySelector(".scard__latency");
        if (bars) bars.dataset.q = quality;
        if (label) {
          label.dataset.q = quality;
          label.textContent = info.latency === null || info.latency === undefined ? "—" : info.latency + " ms";
          label.title = info.latency === null || info.latency === undefined
            ? "تست واقعی از این کانفیگ عبور نکرد"
            : "زمان پاسخ HTTP(S) واقعی از طریق تونل VPN";
        }
      }
    });

    Bridge.on("ping-done", (info) => {
      State.pinging = false;
      $("radar").classList.remove("is-on");
      if (State.sort === "latency") renderServers();
      const good = Number(info && info.success) || 0;
      const failed = Number(info && info.failed) || 0;
      const kind = failed && !good ? "err" : failed ? "warn" : "ok";
      toast(`آزمون واقعی تمام شد: ${good} سرور سالم، ${failed} ناموفق`, kind, 3600);
    });

    Bridge.on("nodes", (nodes) => {
      State.nodes = nodes || [];
      $("rail-count").textContent = State.nodes.length;
      renderServers();
    });

    Bridge.on("refresh-done", (info) => {
      if (info && info.count !== undefined) {
        toast(`${info.count} سرور بارگذاری شد`, "ok");
        $("rail-count").textContent = info.count;
      }
      if (info && info.errors) {
        Object.entries(info.errors).forEach(([name, message]) => toast(`${name}: ${message}`, "err", 5200));
      }
    });

    Bridge.on("refresh-progress", (info) => {
      if (info && info.message) $("overlay-text").textContent = info.message;
    });

    Bridge.on("core-log", (info) => {
      const box = $("logbox");
      if (!box || !info || !info.line) return;
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
      box.textContent += info.line + "\n";
      if (box.textContent.length > 40000) box.textContent = box.textContent.slice(-30000);
      if (atBottom) box.scrollTop = box.scrollHeight;
    });

    Bridge.on("error", (info) => {
      if (info && info.message) toast(info.message, "err", 6000);
      Sound.play("error");
    });

    Bridge.on("core-download-done", (info) => {
      if (info && info.ok) {
        toast(`هستهٔ ${info.core} آماده شد`, "ok");
        State.cores = info.cores || State.cores;
        renderCores();
      } else {
        toast("دانلود هسته ناموفق بود", "err");
      }
    });
  }

  /* ──────────────────────────────── bootstrap ──────────────────────────────── */
  async function boot() {
    await Bridge.waitReady();

    const info = await Bridge.call("bootstrap");
    State.settings = info.settings || {};
    State.nodes = info.nodes || [];
    State.cores = info.cores || {};
    State.status = Object.assign({ running: false, core: "", node_id: "", uptime: 0 }, info.status || {});

    $("about-version").textContent = info.version || "1.0.0";
    $("rail-count").textContent = State.nodes.length;

    sparkDown = new Spark($("spark-down"), "0,240,255");
    sparkUp = new Spark($("spark-up"), "255,47,214");
    chart = new TrafficChart($("traffic-graph"));
    statsChart = new TrafficChart($("stats-graph"));

    wire();
    bindEvents();
    applySettingsToForm();
    renderServers();
    setStatus({});
    ParticleFX.start();

    if (Bridge.mode === "mock") {
      toast("حالت پیش‌نمایش — داده‌های نمونه", "warn", 5000);
    }
    if (!info.is_windows) {
      toast("این نسخه برای ویندوز ساخته شده است", "warn", 5000);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
