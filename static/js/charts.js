/* =====================================================================
 PARABELLUM ISOS - Charts (Chart.js, brand-themed)
 Each chart only initializes if its <canvas> exists on the page.
 ===================================================================== */
document.addEventListener('DOMContentLoaded', () => {
  if (typeof Chart === 'undefined') return;

  const C = {
    primary:'#b11217', primarySoft:'rgba(177,18,23,.12)', primaryLine:'rgba(177,18,23,.85)',
    gold:'#e6a817', goldSoft:'rgba(230,168,23,.18)',
    success:'#1f9d55', info:'#2b6cb0', gray:'#cfd3da', grayText:'#6b7280', grid:'#eef0f3'
  };

  Chart.defaults.font.family = "'Poppins', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = C.grayText;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.padding = 16;

  const axis = (extra={}) => ({
    grid: { color: C.grid, drawBorder:false },
    ticks: { color: C.grayText },
    ...extra
  });
  const noGridX = { grid:{ display:false }, ticks:{ color:C.grayText } };

  const grad = (ctx, color) => {
    const g = ctx.createLinearGradient(0,0,0,260);
    g.addColorStop(0, color.replace('RGB','rgba').replace(')',',.28)').replace('rgb','rgba'));
    g.addColorStop(1, 'rgba(177,18,23,0)');
    return g;
  };

  const el = (id) => document.getElementById(id);

  // For charts whose categories run down the LEFT side (indexAxis:'y'): make sure
  // the FIRST category is at the top and the last at the bottom, whichever way
  // this Chart.js build orders a vertical category axis by default.
  const firstOnTop = (chart) => {
    const sy = chart.scales && chart.scales.y;
    const n = chart.data.labels.length;
    if (!sy || n < 2) return;
    if (sy.getPixelForValue(0) > sy.getPixelForValue(n - 1)) {
      chart.options.scales.y.reverse = !chart.options.scales.y.reverse;
      chart.update();
    }
  };

  /* ---------- Inventory Usage (bar) - dashboard, gold current period + daily/weekly/monthly toggle ----------
   Starts EMPTY. app.js fills each range from /api/dashboard (real
   stock_movements issuances) via window.setUsageData(range, labels, values).
   It used to be pre-loaded with made-up "tons" figures, and the Daily and
   Weekly buttons only ever showed sample arrays. The figures are total
   QUANTITY issued across all materials - materials are counted in mixed
   units (pcs, sheets, lengths...), so the honest label is "units", not tons. */
  if (el('chartMaterialUsage')) {
    const goldLast = (labels) => labels.map((_, i) => i === labels.length - 1 ? C.gold : C.primary);
    const NOTES = {
      daily:   'Total quantity issued per day (last 7 days, all materials).',
      weekly:  'Total quantity issued per week (last 6 weeks, all materials).',
      monthly: 'Total quantity issued per month (latest months with activity, all materials).',
    };
    const sets = { daily: null, weekly: null, monthly: null };
    let currentRange = 'monthly';
    const usageChart = new Chart(el('chartMaterialUsage'), {
      type:'bar',
      data:{ labels:[],
        datasets:[{ label:'Units issued', data:[],
          backgroundColor:[], borderRadius:6, barThickness:26, maxBarThickness:34 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
    const paint = () => {
      const d = sets[currentRange] || { labels: [], data: [] };
      usageChart.data.labels = d.labels.slice();
      usageChart.data.datasets[0].data = d.data.slice();
      usageChart.data.datasets[0].backgroundColor = goldLast(d.labels);
      usageChart.update();
    };
    // Daily / Weekly / Monthly toggle (wired in app.js). Returns the caption for the range.
    window.updateUsageChart = (range) => { currentRange = range; paint(); return NOTES[range] || ''; };
    window.setUsageData = (range, labels, values) => {
      sets[range] = { labels: labels || [], data: values || [] };
      if (range === currentRange) paint();
    };
    window.usageNote = (range) => NOTES[range] || '';
  }

  /* ---------- Forecasting page: Monthly Forecast Graph ---------- */
  let forecastChart;
  if (el('chartMonthlyForecast')) {
    forecastChart = new Chart(el('chartMonthlyForecast'), {
      type:'line',
      data:{ labels:[],
        datasets:[
          { label:'Historical demand', data:[],
            borderColor:C.primary, backgroundColor:C.primary, tension:.35, borderWidth:2.5, pointRadius:3 },
          { label:'Forecast', data:[],
            borderColor:C.gold, backgroundColor:C.goldSoft, borderDash:[6,5], tension:.35, borderWidth:2.5, pointRadius:4, fill:true }
        ]},
      // indexAxis:'y' swaps the axes: the months run down the LEFT side
      // (oldest at the top, forecast month at the bottom) and the units sit
      // along the BOTTOM.
      options:{ responsive:true, maintainAspectRatio:false, indexAxis:'y',
        plugins:{ legend:{ position:'top', align:'end' } },
        scales:{ x:axis({ beginAtZero:true }),
                 y:{ grid:{ display:false }, ticks:{ color:C.grayText } } } }
    });
    window.updateForecastChart = (historyPoints, forecastLabel, predicted) => {
      const labels = historyPoints.map(p => p.month).concat([forecastLabel]);
      const histSeries = historyPoints.map(p => p.demand).concat([null]);
      const fcSeries   = historyPoints.map(_ => null);
      if (histSeries.length >= 2) fcSeries[fcSeries.length - 1] = histSeries[histSeries.length - 2];
      fcSeries.push(predicted);
      forecastChart.data.labels = labels;
      forecastChart.data.datasets[0].data = histSeries;
      forecastChart.data.datasets[1].data = fcSeries;
      forecastChart.update();
      firstOnTop(forecastChart);          // oldest month at the top, forecast month at the bottom
    };
  }

  /* ---------- Forecasting page: Historical Demand (month picker) ----------
   Pick a month (#histMonthSelect, newest by default); the bars show how many
   units of each MATERIAL were consumed that month, most consumed at the top.
   Source: the per-material `history` the forecast returns (its last months).
   Materials are counted in their own units (pcs, sheets, kg ...), so the
   ranking compares raw numbers across different units - the tooltip shows
   each bar's unit. Materials with no consumption that month are left out. */
  let historicalChart;
  if (el('chartHistoricalDemand')) {
    let histForecasts = [];
    historicalChart = new Chart(el('chartHistoricalDemand'), {
      type:'bar',
      data:{ labels:[], datasets:[{ label:'Units consumed', data:[], units:[],
        backgroundColor:C.primary, borderRadius:4, maxBarThickness:26 }] },
      options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false },
          tooltip:{ callbacks:{ label:(c)=> ' ' + Number(c.raw).toLocaleString('en-PH') + ' ' + ((c.dataset.units || [])[c.dataIndex] || '') } } },
        scales:{ x:axis({ beginAtZero:true }), y:{ grid:{ display:false } } } }
    });
    const draw = () => {
      const sel = el('histMonthSelect');
      const month = sel ? sel.value : '';
      const rows = [];
      histForecasts.forEach(f => {
        const p = (f.history || []).find(h => h.month === month);
        const v = p ? Number(p.demand) || 0 : 0;
        if (v > 0) rows.push({ name: f.material_name, unit: f.unit, v });
      });
      rows.sort((a, b) => b.v - a.v);                      // most consumed first (top)
      const ds = historicalChart.data.datasets[0];
      historicalChart.data.labels = rows.map(r => r.name);
      ds.data = rows.map(r => r.v);
      ds.units = rows.map(r => r.unit);
      historicalChart.update();
    };
    el('histMonthSelect')?.addEventListener('change', draw);
    window.updateHistoricalChart = (forecasts) => {
      histForecasts = forecasts || [];
      const months = [];                                   // month labels, oldest first
      histForecasts.forEach(f => (f.history || []).forEach(p => { if (!months.includes(p.month)) months.push(p.month); }));
      const sel = el('histMonthSelect');
      if (sel) {
        const keep = sel.value;
        sel.innerHTML = months.slice().reverse().map(m => `<option value="${m}">${m}</option>`).join('');
        sel.value = months.includes(keep) ? keep : (months[months.length - 1] || '');
        sel.disabled = !months.length;
      }
      draw();
    };
  }

  /* ---------- Forecasting page: Inventory Trend (line) ---------- */
  let inventoryChart;
  if (el('chartInventoryTrend')) {
    const ctx = el('chartInventoryTrend').getContext('2d');
    inventoryChart = new Chart(ctx, {
      type:'line',
      data:{ labels:[],
        datasets:[{ label:'Stock level', data:[],
          borderColor:C.info, backgroundColor:'rgba(43,108,176,.12)', fill:true,
          tension:.38, borderWidth:2.5, pointRadius:3, pointBackgroundColor:C.info }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
    window.updateInventoryChart = (historyPoints) => {
      inventoryChart.data.labels          = historyPoints.map(p => p.month);
      inventoryChart.data.datasets[0].data = historyPoints.map(p => p.inventory);
      inventoryChart.update();
    };
  }

  /* ---------- Reports: monthly revenue (bar) ----------
   Starts empty; the Reports page fills it from /api/reports/overview via
   window.setRevenueChart(labels, pesos). (Was a fixed Jan-Jun series.) */
  if (el('chartRevenue')) {
    const revChart = new Chart(el('chartRevenue'), {
      type:'bar',
      data:{ labels:[],
        datasets:[{ label:'Revenue', data:[],
          backgroundColor:C.primary, borderRadius:6, barThickness:28 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false },
          tooltip:{ callbacks:{ label:(c)=>'\u20b1'+Number(c.raw).toLocaleString('en-PH',{minimumFractionDigits:2,maximumFractionDigits:2}) } } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true,
          ticks:{ color:C.grayText, callback:(v)=> v >= 1e6 ? '\u20b1'+(v/1e6)+'M' : (v >= 1e3 ? '\u20b1'+(v/1e3)+'K' : '\u20b1'+v) } }) } }
    });
    window.setRevenueChart = (labels, values) => {
      revChart.data.labels = labels.slice();
      revChart.data.datasets[0].data = values.slice();
      revChart.update();
    };
  }

  /* ---------- Reports: inventory value by category (pie) ----------
   Starts empty; filled from /api/reports/overview via
   window.setCategoryChart(labels, pesoValues). (Was a made-up distribution.) */
  if (el('chartCategory')) {
    const palette = [C.primary,'#c94a3f','#d97b34','#e6a817','#2b6cb0','#1f9d55','#9aa1ad','#7c3aed','#0f172a'];
    const catChart = new Chart(el('chartCategory'), {
      type:'pie',
      data:{ labels:[], datasets:[{ data:[], backgroundColor:palette, borderWidth:0 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ position:'right' },
          tooltip:{ callbacks:{ label:(c)=> c.label + ': \u20b1' + Number(c.raw).toLocaleString('en-PH',{minimumFractionDigits:2,maximumFractionDigits:2}) } } } }
    });
    window.setCategoryChart = (labels, values) => {
      catChart.data.labels = labels.slice();
      catChart.data.datasets[0].data = values.slice();
      catChart.update();
    };
  }

  /* ---------- Profile mini activity (line) ----------
   Starts empty; the Profile page fills it from /api/profile (the user's own
   audit-log entries per day, last 7 days) via window.setActivityChart. */
  if (el('chartActivity')) {
    const ctx = el('chartActivity').getContext('2d');
    const actChart = new Chart(ctx, {
      type:'line',
      data:{ labels:[],
        datasets:[{ label:'Actions', data:[],
          borderColor:C.primary, backgroundColor:grad(ctx,'rgb(177,18,23)'), fill:true,
          tension:.4, borderWidth:2.5, pointRadius:0 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true, ticks:{ color:C.grayText, precision:0 } }) } }
    });
    window.setActivityChart = (labels, values) => {
      actChart.data.labels = labels.slice();
      actChart.data.datasets[0].data = values.slice();
      actChart.update();
    };
  }

});
