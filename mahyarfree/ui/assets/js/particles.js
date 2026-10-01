/* ═══════════════════════════════════════════════════════════════════════════
   particles.js — animated backdrop network + the energy field around the orb.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const COLORS = ["0,240,255", "255,47,214", "139,92,255", "125,255,90"];
  let enabled = true;

  /* ───────────────────────────── backdrop network ───────────────────────────── */
  function initBackground() {
    const canvas = document.getElementById("bg-particles");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let width = 0;
    let height = 0;
    let dpr = 1;
    let particles = [];
    const pointer = { x: -9999, y: -9999 };

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    }

    function seed() {
      const count = Math.round(Math.min(120, Math.max(45, (width * height) / 18000)));
      particles = [];
      for (let i = 0; i < count; i += 1) {
        particles.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.34,
          vy: (Math.random() - 0.5) * 0.34,
          r: Math.random() * 1.7 + 0.6,
          c: COLORS[Math.floor(Math.random() * COLORS.length)],
          pulse: Math.random() * Math.PI * 2,
        });
      }
    }

    function step() {
      ctx.clearRect(0, 0, width, height);

      for (let i = 0; i < particles.length; i += 1) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.pulse += 0.02;

        const dx = p.x - pointer.x;
        const dy = p.y - pointer.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 130 && dist > 0.1) {
          p.x += (dx / dist) * 0.55;
          p.y += (dy / dist) * 0.55;
        }

        if (p.x < -20) p.x = width + 20;
        if (p.x > width + 20) p.x = -20;
        if (p.y < -20) p.y = height + 20;
        if (p.y > height + 20) p.y = -20;

        for (let j = i + 1; j < particles.length; j += 1) {
          const q = particles[j];
          const lx = p.x - q.x;
          const ly = p.y - q.y;
          const d2 = lx * lx + ly * ly;
          if (d2 < 16000) {
            const alpha = (1 - d2 / 16000) * 0.19;
            ctx.strokeStyle = `rgba(${p.c},${alpha})`;
            ctx.lineWidth = 0.7;
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(q.x, q.y);
            ctx.stroke();
          }
        }

        const glow = 0.55 + Math.sin(p.pulse) * 0.3;
        ctx.fillStyle = `rgba(${p.c},${glow})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
      requestAnimationFrame(step);
    }

    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", (event) => {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
    });
    window.addEventListener("mouseleave", () => {
      pointer.x = -9999;
      pointer.y = -9999;
    });

    resize();
    requestAnimationFrame(step);
  }

  /* ──────────────────────────────── orb field ──────────────────────────────── */
  function initOrb() {
    const canvas = document.getElementById("orb-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const size = 420;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const center = size / 2;
    const state = { mode: "off", burst: 0, angle: 0 };
    let motes = [];

    function makeMotes(count, speed) {
      motes = [];
      for (let i = 0; i < count; i += 1) {
        const angle = Math.random() * Math.PI * 2;
        const radius = 96 + Math.random() * 76;
        motes.push({
          angle,
          radius,
          speed: speed * (0.5 + Math.random()),
          size: Math.random() * 2.1 + 0.7,
          alpha: 0.3 + Math.random() * 0.6,
          color: Math.random() > 0.72 ? "255,47,214" : "0,240,255",
        });
      }
    }

    function burst(count) {
      for (let i = 0; i < count; i += 1) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 1.4 + Math.random() * 3.4;
        motes.push({
          angle,
          radius: 84,
          speed: 0,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          life: 1,
          size: Math.random() * 2.4 + 1,
          alpha: 1,
          color: Math.random() > 0.5 ? "125,255,90" : "0,240,255",
          free: true,
        });
      }
    }

    makeMotes(56, 0.0016);

    function frame() {
      ctx.clearRect(0, 0, size, size);

      const accent = state.mode === "on" ? "125,255,90" : state.mode === "connecting" ? "255,176,32" : "0,240,255";

      const halo = ctx.createRadialGradient(center, center, 60, center, center, 190);
      halo.addColorStop(0, `rgba(${accent},0.14)`);
      halo.addColorStop(1, `rgba(${accent},0)`);
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(center, center, 190, 0, Math.PI * 2);
      ctx.fill();

      state.angle += state.mode === "connecting" ? 0.03 : 0.006;

      for (let i = motes.length - 1; i >= 0; i -= 1) {
        const m = motes[i];
        if (m.free) {
          m.x = center + Math.cos(m.angle) * 84 + m.vx * (1 - m.life) * 60;
          m.y = center + Math.sin(m.angle) * 84 + m.vy * (1 - m.life) * 60;
          m.life -= 0.017;
          if (m.life <= 0) { motes.splice(i, 1); continue; }
          ctx.fillStyle = `rgba(${m.color},${m.life})`;
          ctx.beginPath();
          ctx.arc(m.x, m.y, m.size * m.life, 0, Math.PI * 2);
          ctx.fill();
          continue;
        }
        m.angle += m.speed * (state.mode === "connecting" ? 3.4 : 1);
        const wobble = Math.sin(state.angle * 2 + m.angle * 3) * 5;
        const x = center + Math.cos(m.angle) * (m.radius + wobble);
        const y = center + Math.sin(m.angle) * (m.radius + wobble);
        ctx.fillStyle = `rgba(${m.color},${m.alpha * 0.85})`;
        ctx.beginPath();
        ctx.arc(x, y, m.size, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = `rgba(${m.color},${m.alpha * 0.09})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        ctx.moveTo(center + Math.cos(m.angle) * 86, center + Math.sin(m.angle) * 86);
        ctx.lineTo(x, y);
        ctx.stroke();
      }

      if (state.burst > 0) {
        state.burst -= 1;
        if (state.burst % 3 === 0) burst(9);
      }
      requestAnimationFrame(frame);
    }

    requestAnimationFrame(frame);

    window.OrbFX = {
      setMode(mode) {
        if (state.mode === mode) return;
        state.mode = mode;
        if (mode === "on") { state.burst = 22; makeMotes(70, 0.0022); }
        else if (mode === "off") { makeMotes(56, 0.0016); }
      },
      burst(count) { burst(count || 30); },
    };
  }

  window.ParticleFX = {
    setEnabled(value) {
      enabled = !!value;
      document.body.classList.toggle("no-anim", !enabled);
    },
    start() {
      if (!enabled) return;
      initBackground();
      initOrb();
    },
  };
})();
