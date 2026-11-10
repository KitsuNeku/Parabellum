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

  const firstOnTop = (chart) => {
    const sy = chart.scales && chart.scales.y;
    const n = chart.data.labels.length;
    if (!sy || n < 2) return;
    if (sy.getPixelForValue(0) > sy.getPixelForValue(n - 1)) {
      chart.options.scales.y.reverse = !chart.options.scales.y.reverse;
      chart.update();
    }
  };

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
    window.updateUsageChart = (range) => { currentRange = range; paint(); return NOTES[range] || ''; };
    window.setUsageData = (range, labels, values) => {
      sets[range] = { labels: labels || [], data: values || [] };
      if (range === currentRange) paint();
    };
    window.usageNote = (range) => NOTES[range] || '';
  }

  /* Forecasting page: Monthly Forecast Graph */
  let forecastChart;
  if (el('chartMonthlyForecast')) {
    forecastChart = new Chart(el('chartMonthlyForecast'), {
      type:'bar',
      data:{ labels:[],
        datasets:[
          { label:'Historical demand', data:[],
            backgroundColor:C.primary, borderRadius:4, maxBarThickness:46 },
          { label:'Forecast', data:[],
            backgroundColor:C.gold, borderRadius:4, maxBarThickness:46 },
        ]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ position:'top', align:'end' } },
        scales:{ x:Object.assign({ stacked:true }, noGridX),
                 y:axis({ beginAtZero:true, stacked:true }) } }
    });
    window.updateForecastChart = (historyPoints, forecastLabel, predicted) => {
      const labels = historyPoints.map(p => p.month).concat([forecastLabel]);
      const histSeries = historyPoints.map(p => p.demand).concat([null]);
      const fcSeries   = historyPoints.map(_ => null).concat([predicted]);
      forecastChart.data.labels = labels;
      forecastChart.data.datasets[0].data = histSeries;
      forecastChart.data.datasets[1].data = fcSeries;
      forecastChart.update();
    };
    window.updateForecastChartSeasonal = (seasons) => {
      forecastChart.data.labels = seasons.map(s => s.label);
      forecastChart.data.datasets[0].data = seasons.map(s => s.historical > 0 ? s.historical : null);
      forecastChart.data.datasets[1].data = seasons.map(s => s.forecast > 0 ? s.forecast : null);
      forecastChart.update();
    };
  }

  let historicalChart;
  if (el('chartHistoricalDemand')) {
    const matPalette = [C.primary, C.gold, C.info, C.success, '#7c3aed', '#d97b34', '#0f766e', '#9aa1ad', '#c94a3f', '#0f172a'];
    historicalChart = new Chart(el('chartHistoricalDemand'), {
      type:'bar',
      data:{ labels:[], datasets:[] },
      options:{ responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'nearest', intersect:true },
        plugins:{
          legend:{ display:false },
          tooltip:{ callbacks:{ label:(c)=> ' ' + c.dataset.label + ': ' + Number(c.raw).toLocaleString('en-PH') + ' ' + (c.dataset.unit || '') } } },
        scales:{ x:Object.assign({ stacked:true }, noGridX),
                 y:axis({ beginAtZero:true, stacked:true }) } }
    });
    window.updateHistoricalChart = (forecasts) => {
      const fcs = forecasts || [];
      const months = [];
      fcs.forEach(f => (f.history || []).forEach(p => { if (!months.includes(p.month)) months.push(p.month); }));
      historicalChart.data.labels = months;
      historicalChart.data.datasets = fcs.map((f, i) => {
        const byMonth = {};
        (f.history || []).forEach(p => { byMonth[p.month] = Number(p.demand) || 0; });
        return { label: f.material_name, unit: f.unit,
                 data: months.map(m => byMonth[m] || 0),
                 backgroundColor: matPalette[i % matPalette.length], borderWidth:0, maxBarThickness:46 };
      });
      historicalChart.update();
      renderHistLegend();
    };
    const renderHistLegend = () => {
      const box = el('histLegend');
      if (!box) return;
      box.innerHTML = historicalChart.data.datasets.map((d, i) => {
        const hidden = !historicalChart.isDatasetVisible(i);
        return `<li><button type="button" class="legend-item${hidden ? ' is-off' : ''}" data-ds="${i}" aria-pressed="${!hidden}">
          <span class="legend-swatch" style="background:${d.backgroundColor}"></span>
          <span class="legend-name">${escapeHTML(d.label)}</span></button></li>`;
      }).join('');
    };
    el('histLegend')?.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-ds]'); if (!btn) return;
      const i = Number(btn.dataset.ds);
      historicalChart.setDatasetVisibility(i, !historicalChart.isDatasetVisible(i));
      historicalChart.update();
      renderHistLegend();
    });
  }

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
