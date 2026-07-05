/**
 * BBT Fertility Tracker — Chart initialisation helpers
 *
 * Requires Chart.js 4.x + chartjs-plugin-annotation 3.x to be loaded first.
 *
 * Public API:
 *   initBBTChart(canvasId, data)   — full annotated cycle chart
 *   initMiniChart(canvasId, data)  — compact dashboard preview
 */

/* ── Shared colour palette (matches app.css custom properties) ─────────── */
const COLORS = {
  primary:    '#9c27b0',
  primaryFill:'rgba(156,39,176,0.12)',
  discarded:  '#bdbdbd',
  coverline:  '#e53935',
  fertile:    'rgba(102,187,106,0.18)',
  fertileLine:'rgba(102,187,106,0.6)',
  ovulation:  '#ff9800',
};

/* ── Mucus label → colour ────────────────────────────────────────────────── */
const MUCUS_COLORS = {
  dry:       '#ff8a65',
  sticky:    '#ffa726',
  creamy:    '#ffee58',
  watery:    '#42a5f5',
  egg_white: '#26c6da',
};

/* ── Helper: build Chart.js annotation objects ──────────────────────────── */
function _buildAnnotations(data, labels) {
  const ann = {};

  // Coverline
  if (data.coverline != null) {
    ann.coverline = {
      type: 'line',
      yMin: data.coverline,
      yMax: data.coverline,
      borderColor: COLORS.coverline,
      borderWidth: 1.5,
      borderDash: [5, 4],
      label: {
        content: `Coverline ${data.coverline}`,
        enabled: true,
        position: 'end',
        backgroundColor: COLORS.coverline,
        color: '#fff',
        font: { size: 10 },
        padding: { x: 5, y: 2 },
      },
    };
  }

  // Fertile window box
  if (data.fertile_start_day != null && data.fertile_end_day != null) {
    const fs = `Day ${data.fertile_start_day}`;
    const fe = `Day ${data.fertile_end_day}`;
    if (labels.includes(fs) && labels.includes(fe)) {
      ann.fertileBox = {
        type: 'box',
        xMin: fs,
        xMax: fe,
        backgroundColor: COLORS.fertile,
        borderColor: COLORS.fertileLine,
        borderWidth: 1,
        label: {
          content: 'Fertile',
          enabled: true,
          position: { x: 'center', y: 'start' },
          font: { size: 9 },
          color: '#388e3c',
        },
      };
    }
  }

  // Ovulation vertical line
  if (data.ovulation_day != null) {
    const ov = `Day ${data.ovulation_day}`;
    if (labels.includes(ov)) {
      ann.ovulation = {
        type: 'line',
        xMin: ov,
        xMax: ov,
        borderColor: COLORS.ovulation,
        borderWidth: 2,
        label: {
          content: 'OV',
          enabled: true,
          position: 'start',
          backgroundColor: COLORS.ovulation,
          color: '#fff',
          font: { size: 10 },
          padding: { x: 4, y: 2 },
        },
      };
    }
  }

  return ann;
}

/* ── Helper: mucus & OPK dot plugin ────────────────────────────────────── */
function _mucusPlugin(data) {
  return {
    id: 'mucus',
    afterDatasetsDraw(chart) {
      const { ctx, scales } = chart;
      if (!scales.x || !scales.y) return;

      scales.x.ticks.forEach((tick, i) => {
        const label = scales.x.getLabelForValue(i);
        const dayNum = label ? label.replace('Day ', '') : null;
        if (!dayNum) return;

        const x = scales.x.getPixelForValue(i);
        const yBottom = scales.y.bottom + 6;

        // Mucus dot
        const mucus = data.mucus && data.mucus[dayNum];
        if (mucus) {
          ctx.beginPath();
          ctx.arc(x, yBottom + 6, 4, 0, Math.PI * 2);
          ctx.fillStyle = MUCUS_COLORS[mucus] || '#9c27b0';
          ctx.fill();
        }

        // OPK indicator
        const opk = data.opk && data.opk[dayNum];
        if (opk && opk !== 'not_tested' && opk !== 'negative') {
          ctx.beginPath();
          ctx.moveTo(x, yBottom + 14);
          ctx.lineTo(x - 4, yBottom + 22);
          ctx.lineTo(x + 4, yBottom + 22);
          ctx.closePath();
          ctx.fillStyle = opk === 'peak' ? '#e53935' : '#ff9800';
          ctx.fill();
        }
      });
    },
  };
}

/* ── Public: full BBT chart ─────────────────────────────────────────────── */
function initBBTChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const labels = data.labels || [];
  const temps  = data.temperatures || [];
  const discardedPoints = data.discarded || [];

  const annotations = _buildAnnotations(data, labels);

  const existingChart = Chart.getChart(canvas);
  if (existingChart) existingChart.destroy();

  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: `BBT (°${data.unit || 'F'})`,
          data: temps,
          borderColor: COLORS.primary,
          backgroundColor: COLORS.primaryFill,
          pointBackgroundColor: COLORS.primary,
          pointRadius: 4,
          pointHoverRadius: 6,
          borderWidth: 2,
          tension: 0.2,
          spanGaps: false,
        },
        {
          label: 'Discarded',
          data: discardedPoints,
          borderColor: 'transparent',
          backgroundColor: COLORS.discarded,
          pointBackgroundColor: COLORS.discarded,
          pointStyle: 'circle',
          pointRadius: 4,
          showLine: false,
          parsing: { xAxisKey: 'x', yAxisKey: 'y' },
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top', labels: { font: { size: 11 }, boxWidth: 12 } },
        annotation: { annotations },
        tooltip: {
          callbacks: {
            label(ctx) {
              const v = ctx.parsed.y;
              return v != null ? `${ctx.dataset.label}: ${v}°${data.unit || 'F'}` : '';
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { font: { size: 11 }, maxRotation: 0 },
          grid: { display: false },
        },
        y: {
          ticks: {
            font: { size: 11 },
            callback: v => `${v}°`,
          },
          grid: { color: 'rgba(0,0,0,0.05)' },
        },
      },
      layout: { padding: { bottom: 28 } },
    },
    plugins: [_mucusPlugin(data)],
  });
}

/* ── Public: mini dashboard chart ──────────────────────────────────────── */
function initMiniChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const labels = data.labels || [];
  const temps  = data.temperatures || [];

  const annotations = {};
  if (data.coverline != null) {
    annotations.coverline = {
      type: 'line',
      yMin: data.coverline,
      yMax: data.coverline,
      borderColor: COLORS.coverline,
      borderWidth: 1,
      borderDash: [4, 3],
    };
  }

  const existingChart = Chart.getChart(canvas);
  if (existingChart) existingChart.destroy();

  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          data: temps,
          borderColor: COLORS.primary,
          backgroundColor: COLORS.primaryFill,
          pointRadius: 2,
          borderWidth: 2,
          tension: 0.25,
          spanGaps: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        annotation: { annotations },
        tooltip: { enabled: false },
      },
      scales: {
        x: { display: false },
        y: {
          ticks: { font: { size: 9 }, maxTicksLimit: 4, callback: v => `${v}°` },
          grid: { color: 'rgba(0,0,0,0.04)' },
        },
      },
      interaction: { mode: 'nearest', intersect: false },
    },
  });
}
