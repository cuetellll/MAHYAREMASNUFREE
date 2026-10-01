/* ═══════════════════════════════════════════════════════════════════════════
   graph.js — canvas sparklines and the live traffic chart.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const SAMPLES = 90;

  function fit(canvas) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(40, Math.round(rect.width));
    const height = Math.max(30, Math.round(rect.height || canvas.height));
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width, height };
  }

  /* ─────────────────────────────── sparkline ─────────────────────────────── */
  class Spark {
    constructor(canvas, color) {
      this.canvas = canvas;
      this.color = color;
      this.data = new Array(38).fill(0);
      this.draw();
    }

    push(value) {
      this.data.push(value);
      if (this.data.length > 38) this.data.shift();
      this.draw();
    }

    reset() {
      this.data = new Array(38).fill(0);
      this.draw();
    }

    draw() {
      const { ctx, width, height } = fit(this.canvas);
      ctx.clearRect(0, 0, width, height);

      const peak = Math.max(...this.data, 1);
      const step = width / (this.data.length - 1);

      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, `rgba(${this.color},0.42)`);
      gradient.addColorStop(1, `rgba(${this.color},0)`);

      ctx.beginPath();
      ctx.moveTo(0, height);
      this.data.forEach((value, index) => {
        const x = index * step;
        const y = height - (value / peak) * (height - 5) - 2;
        ctx.lineTo(x, y);
      });
      ctx.lineTo(width, height);
      ctx.closePath();
      ctx.fillStyle = gradient;
      ctx.fill();

      ctx.beginPath();
      this.data.forEach((value, index) => {
        const x = index * step;
        const y = height - (value / peak) * (height - 5) - 2;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = `rgba(${this.color},0.95)`;
      ctx.lineWidth = 1.7;
      ctx.shadowColor = `rgba(${this.color},0.85)`;
      ctx.shadowBlur = 9;
      ctx.stroke();
      ctx.shadowBlur = 0;

      const lastIndex = this.data.length - 1;
      const lastY = height - (this.data[lastIndex] / peak) * (height - 5) - 2;
      ctx.fillStyle = `rgba(${this.color},1)`;
      ctx.beginPath();
      ctx.arc(lastIndex * step, lastY, 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  /* ──────────────────────────── traffic chart ──────────────────────────── */
  class TrafficChart {
    constructor(canvas) {
      this.canvas = canvas;
      this.down = new Array(SAMPLES).fill(0);
      this.up = new Array(SAMPLES).fill(0);
      this.peak = 1024 * 512;
      this.draw();
    }

    push(down, up) {
      this.down.push(down);
      this.up.push(up);
      if (this.down.length > SAMPLES) this.down.shift();
      if (this.up.length > SAMPLES) this.up.shift();
      const localPeak = Math.max(...this.down, ...this.up, 1024 * 64);
      this.peak += (localPeak - this.peak) * 0.08;
      this.draw();
    }

    reset() {
      this.down.fill(0);
      this.up.fill(0);
      this.draw();
    }

    _series(values, color, ctx, width, height, fill) {
      const step = width / (values.length - 1);
      const toY = (value) => height - 8 - (value / this.peak) * (height - 26);

      if (fill) {
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, `rgba(${color},0.36)`);
        gradient.addColorStop(1, `rgba(${color},0)`);
        ctx.beginPath();
        ctx.moveTo(0, height);
        values.forEach((value, index) => ctx.lineTo(index * step, toY(value)));
        ctx.lineTo(width, height);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();
      }

      ctx.beginPath();
      values.forEach((value, index) => {
        const x = index * step;
        const y = toY(value);
        if (index === 0) ctx.moveTo(x, y);
        else {
          const prevX = (index - 1) * step;
          const prevY = toY(values[index - 1]);
          ctx.bezierCurveTo((prevX + x) / 2, prevY, (prevX + x) / 2, y, x, y);
        }
      });
      ctx.strokeStyle = `rgba(${color},0.95)`;
      ctx.lineWidth = 2;
      ctx.shadowColor = `rgba(${color},0.7)`;
      ctx.shadowBlur = 12;
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    draw() {
      const { ctx, width, height } = fit(this.canvas);
      ctx.clearRect(0, 0, width, height);

      ctx.strokeStyle = "rgba(120,170,255,0.09)";
      ctx.lineWidth = 1;
      for (let i = 1; i < 5; i += 1) {
        const y = (height / 5) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      this._series(this.down, "0,240,255", ctx, width, height, true);
      this._series(this.up, "255,47,214", ctx, width, height, false);

      ctx.fillStyle = "rgba(140,170,220,0.55)";
      ctx.font = '10px "Orbitron", sans-serif';
      ctx.textAlign = "left";
      ctx.fillText(formatRate(this.peak), 6, 13);
    }
  }

  /* ─────────────────────────────── helpers ─────────────────────────────── */
  function formatRate(bytesPerSecond) {
    const value = Number(bytesPerSecond) || 0;
    if (value >= 1024 * 1024 * 1024) return (value / (1024 ** 3)).toFixed(1) + " GB/s";
    if (value >= 1024 * 1024) return (value / (1024 ** 2)).toFixed(1) + " MB/s";
    if (value >= 1024) return (value / 1024).toFixed(1) + " KB/s";
    return Math.round(value) + " B/s";
  }

  function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value >= 1024 ** 4) return (value / (1024 ** 4)).toFixed(2) + " TB";
    if (value >= 1024 ** 3) return (value / (1024 ** 3)).toFixed(2) + " GB";
    if (value >= 1024 ** 2) return (value / (1024 ** 2)).toFixed(2) + " MB";
    if (value >= 1024) return (value / 1024).toFixed(1) + " KB";
    return Math.round(value) + " B";
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(seconds || 0));
    const h = String(Math.floor(total / 3600)).padStart(2, "0");
    const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
    const s = String(total % 60).padStart(2, "0");
    return `${h}:${m}:${s}`;
  }

  window.GraphFX = {
    Spark,
    TrafficChart,
    formatRate,
    formatBytes,
    formatDuration,
    redrawAll(charts) {
      charts.forEach((chart) => { try { chart.draw(); } catch (e) { /* ignore */ } });
    },
  };
})();
