/* ═══════════════════════════════════════════════════════════════════════════
   bridge.js — talks to the Python engine through pywebview, with a fully
   functional mock so the interface can also be reviewed in a plain browser.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const listeners = new Map();

  const Bridge = {
    ready: false,
    mode: "mock",

    on(name, handler) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(handler);
    },

    emit(name, payload) {
      const handlers = listeners.get(name) || [];
      handlers.forEach((fn) => {
        try { fn(payload); } catch (error) { console.error(name, error); }
      });
    },

    async waitReady() {
      if (window.pywebview && window.pywebview.api) {
        this.mode = "native";
        this.ready = true;
        return true;
      }
      for (let i = 0; i < 24; i += 1) {
        await new Promise((r) => setTimeout(r, 55));
        if (window.pywebview && window.pywebview.api) {
          this.mode = "native";
          this.ready = true;
          return true;
        }
      }
      // no pywebview: are we being served by the app's own HTTP bridge?
      try {
        const response = await fetch("/health", { cache: "no-store" });
        if (response.ok) {
          const info = await response.json();
          if (info && info.app === "MahyarFree") {
            this.mode = "http";
            this.ready = true;
            this.openEventStream();
            return true;
          }
        }
      } catch (error) { /* plain file:// or a static preview server */ }
      this.mode = "mock";
      this.ready = true;
      return false;
    },

    openEventStream() {
      try {
        const stream = new EventSource("/events");
        stream.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            Bridge.emit(message.name, message.payload);
          } catch (error) { /* ignore malformed frame */ }
        };
        stream.onerror = () => { /* the browser reconnects on its own */ };
        this.stream = stream;
      } catch (error) { /* EventSource unsupported */ }
    },

    call(method, ...args) {
      if (this.mode === "native" && window.pywebview && window.pywebview.api && window.pywebview.api[method]) {
        return window.pywebview.api[method](...args);
      }
      if (this.mode === "http") {
        return fetch(`/api/${method}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(args),
        })
          .then((response) => response.json())
          .catch((error) => ({ ok: false, error: String(error) }));
      }
      return Mock.call(method, ...args);
    },
  };

  /* ─────────────────────────────── mock engine ─────────────────────────────── */
  const Mock = (() => {
    const PROTOCOLS = ["vless", "vmess", "trojan", "hysteria2", "shadowsocks"];
    const COUNTRIES = ["🇩🇪", "🇳🇱", "🇫🇮", "🇫🇷", "🇬🇧", "🇺🇸", "🇹🇷", "🇦🇪", "🇸🇪", "🇵🇱", "🇦🇹", "🇯🇵"];
    const NAMES = ["Falcon", "Phantom", "Arvin", "Mahyar", "Storm", "Nova", "Vortex", "Blaze",
      "Onyx", "Titan", "Cipher", "Nebula", "Raptor", "Zenith", "Echo", "Pulse"];
    const TRANSPORTS = ["ws", "tcp", "grpc", "xhttp"];

    let nodes = [];
    for (let i = 0; i < 22; i += 1) {
      const country = COUNTRIES[i % COUNTRIES.length];
      nodes.push({
        id: `mock${String(i).padStart(3, "0")}`,
        name: `${NAMES[i % NAMES.length]} ${country}`,
        server: `node${i}.mahyarfree.net`,
        port: 443 + i,
        protocol: PROTOCOLS[i % PROTOCOLS.length],
        group: i % 3 ? "MahyarVPN" : "Sub Backup",
        country,
        core: i % 7 === 3 ? "xray" : "sing-box",
        latency: i % 9 === 4 ? null : [48, 62, 87, 110, 138, 175, 220, 310, 480][i % 9],
        favourite: i === 2 || i === 5,
        transport: TRANSPORTS[i % TRANSPORTS.length],
        tls: i % 3 !== 1,
      });
    }

    const state = {
      version: "1.0.0",
      platform: "win32",
      is_windows: true,
      elevated: true,
      settings: {
        mode: "system-proxy", routing: "rule", animations: true, sound: false,
        auto_best_on_start: false, block_ads: true, bypass_lan: true, dns_hijack: true,
        fragment: false, mux: false, autostart: false, update_on_start: true,
        socks_port: 20808, http_port: 20809, clash_port: 20810,
        subscriptions: [{ id: "default", name: "MahyarVPN", url: "https://raw.githubusercontent.com/cuetellll/mahyarvpn-sub/main/sub.txt", enabled: true }],
        selected_node_id: "mock002",
      },
      cores: {
        "sing-box": { available: true, version: "sing-box version 1.14.2", path: "…/core/sing-box.exe" },
        xray: { available: true, version: "Xray 25.9.11 (Xray, Penetrating Everything.)", path: "…/core/xray.exe" },
      },
      status: { running: false, core: "", node_id: "", node_name: "", uptime: 0, error: "" },
      nodes,
      last_update: Date.now() / 1000,
      errors: {},
      data_dir: "C:\\Users\\user\\AppData\\Roaming\\MahyarFree",
    };

    let running = false;
    let started = 0;
    let timer = null;

    function traffic() {
      if (!running) return;
      const up = Math.random() * 900000;
      const down = Math.random() * 5400000;
      Bridge.emit("traffic", { up, down, total_up: 0, total_down: 0 });
    }

    return {
      async call(method, ...args) {
        await new Promise((r) => setTimeout(r, 90));
        switch (method) {
          case "bootstrap":
            return JSON.parse(JSON.stringify(state));
          case "get_nodes":
            return JSON.parse(JSON.stringify(nodes));
          case "ping_all":
            setTimeout(() => {
              Bridge.emit("ping-start", { count: nodes.length });
              nodes.forEach((n, i) => setTimeout(() => {
                n.latency = [42, 58, 74, 96, 130, 168, 215, 290, 430, null][Math.floor(Math.random() * 10)];
                Bridge.emit("ping-result", { id: n.id, latency: n.latency, quality: "" });
              }, i * 55));
              setTimeout(() => Bridge.emit("ping-done", {}), nodes.length * 55 + 200);
            }, 120);
            return { ok: true, started: true };
          case "ping_node":
            return { ok: true, latency: 40 + Math.floor(Math.random() * 200) };
          case "connect":
          case "connect_best":
          case "switch_node": {
            const target = args[0] || state.settings.selected_node_id;
            const node = nodes.find((n) => n.id === target) || nodes[0];
            Bridge.emit("connecting", { node_id: node.id, node_name: node.name });
            await new Promise((r) => setTimeout(r, 1400));
            running = true;
            started = Date.now();
            state.status = { running: true, core: node.core, node_id: node.id, node_name: node.name, uptime: 0, error: "" };
            if (timer) clearInterval(timer);
            timer = setInterval(traffic, 900);
            setTimeout(() => Bridge.emit("status", { ...state.status, system_proxy: true }), 60);
            return { ok: true, ...state.status };
          }
          case "disconnect":
            running = false;
            if (timer) clearInterval(timer);
            state.status = { running: false, core: "", node_id: "", node_name: "", uptime: 0, error: "" };
            Bridge.emit("traffic", { up: 0, down: 0, total_up: 0, total_down: 0 });
            setTimeout(() => Bridge.emit("status", { ...state.status, system_proxy: false }), 60);
            return { ok: true };
          case "status":
            return { ...state.status, system_proxy: running };
          case "select_node":
            state.settings.selected_node_id = args[0];
            return { ok: true };
          case "toggle_favourite": {
            const node = nodes.find((n) => n.id === args[0]);
            if (node) node.favourite = !node.favourite;
            return { ok: true, favourite: node && node.favourite, nodes };
          }
          case "save_settings":
            Object.assign(state.settings, args[0] || {});
            return { ok: true, settings: state.settings };
          case "refresh":
            Bridge.emit("refresh-start", {});
            setTimeout(() => Bridge.emit("refresh-done", { count: nodes.length, errors: {} }), 900);
            return { ok: true, started: true };
          case "real_delay":
            return { ok: true, latency: 60 + Math.floor(Math.random() * 120) };
          case "core_info":
            return state.cores;
          case "add_subscription":
          case "remove_subscription":
          case "toggle_subscription":
          case "download_core":
          case "open_data_dir":
          case "request_elevation":
            return { ok: true };
          default:
            return { ok: true };
        }
      },
    };
  })();

  window.Bridge = Bridge;
  window.MF = {
    emit: (name, payload) => Bridge.emit(name, payload),
    on: (name, handler) => Bridge.on(name, handler),
  };
})();
