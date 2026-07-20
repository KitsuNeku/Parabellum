/* =====================================================================
   PARABELLUM ISOS — Charts (Chart.js, brand-themed)
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

  /* ---------- Inventory Status (doughnut) ---------- */
  if (el('chartInventoryStatus')) {
    new Chart(el('chartInventoryStatus'), {
      type:'doughnut',
      data:{ labels:['In Stock','Low Stock','Out of Stock'],
        datasets:[{ data:[12,3,2], backgroundColor:[C.success, C.gold, C.primary], borderWidth:0, hoverOffset:6 }]},
      options:{ responsive:true, maintainAspectRatio:false, cutout:'68%',
        plugins:{ legend:{ position:'bottom' } } }
    });
  }

  /* ---------- Inventory Usage (bar) — dashboard, gold current period + daily/weekly/monthly toggle ---------- */
  if (el('chartMaterialUsage')) {
    const goldLast = (labels) => labels.map((_, i) => i === labels.length - 1 ? C.gold : C.primary);
    const fallback = { labels:['Jan','Feb','Mar','Apr','May','Jun'], data:[182,205,231,198,256,243], note:'' };
    const src = (typeof USAGE_MONTHLY !== 'undefined') ? USAGE_MONTHLY : fallback;
    const usageChart = new Chart(el('chartMaterialUsage'), {
      type:'bar',
      data:{ labels:src.labels.slice(),
        datasets:[{ label:'Tons used', data:src.data.slice(),
          backgroundColor:goldLast(src.labels), borderRadius:6, barThickness:26, maxBarThickness:34 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
    // Daily / Weekly / Monthly toggle wired from app.js — swaps the dataset client-side.
    window.updateUsageChart = (range) => {
      const map = {
        daily:   (typeof USAGE_DAILY  !== 'undefined') ? USAGE_DAILY  : src,
        weekly:  (typeof USAGE_WEEKLY !== 'undefined') ? USAGE_WEEKLY : src,
        monthly: src
      };
      const d = map[range] || src;
      usageChart.data.labels = d.labels.slice();
      usageChart.data.datasets[0].data = d.data.slice();
      usageChart.data.datasets[0].backgroundColor = goldLast(d.labels);
      usageChart.update();
      return d.note || '';
    };
    // Lets app.js push REAL monthly usage totals from /api/dashboard into the
    // chart (labels + values straight from the database).
    window.updateUsageData = (labels, values) => {
      if (!labels || !labels.length) return;
      usageChart.data.labels = labels.slice();
      usageChart.data.datasets[0].data = values.slice();
      usageChart.data.datasets[0].backgroundColor = goldLast(labels);
      usageChart.update();
    };
  }

  /* ---------- Transaction Trend (line) ---------- */
  if (el('chartTxnTrend')) {
    const ctx = el('chartTxnTrend').getContext('2d');
    new Chart(ctx, {
      type:'line',
      data:{ labels:['Jan','Feb','Mar','Apr','May','Jun'],
        datasets:[{ label:'Transactions', data:[42,55,49,63,58,71],
          borderColor:C.primary, backgroundColor:grad(ctx,'rgb(177,18,23)'),
          fill:true, tension:.38, pointRadius:3, pointBackgroundColor:C.primary, borderWidth:2.5 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
  }

  /* ---------- Commission Overview (bar) ---------- */
  if (el('chartCommission')) {
    new Chart(el('chartCommission'), {
      type:'bar',
      data:{ labels:['Dela Cruz','Santos','Mendoza','Lim','Reyes'],
        datasets:[{ label:'Commission (₱)', data:[48200,36800,29400,21600,42500],
          backgroundColor:[C.primary,C.primary,C.primary,C.primary,C.gold], borderRadius:6, barThickness:30 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true,
          ticks:{ color:C.grayText, callback:(v)=>'₱'+(v/1000)+'k' } }) } }
    });
  }

  /* ---------- Forecast Summary (line: actual vs predicted) ---------- */
  if (el('chartForecastSummary')) {
    new Chart(el('chartForecastSummary'), {
      type:'line',
      data:{ labels:['Jan','Feb','Mar','Apr','May','Jun','Jul*'],
        datasets:[
          { label:'Actual demand', data:[118,132,140,128,135,121,null],
            borderColor:C.primary, backgroundColor:C.primary, tension:.35, borderWidth:2.5, pointRadius:3 },
          { label:'Predicted', data:[120,128,140,124,140,128,150],
            borderColor:C.gold, backgroundColor:C.gold, borderDash:[6,5], tension:.35, borderWidth:2.5, pointRadius:3 }
        ]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ position:'top', align:'end' } },
        scales:{ x:noGridX, y:axis({ beginAtZero:false }) } }
    });
  }

  /* ---------- Forecasting page: Monthly Forecast Graph ---------- */
  let forecastChart;
  if (el('chartMonthlyForecast')) {
    forecastChart = new Chart(el('chartMonthlyForecast'), {
      type:'line',
      data:{ labels:['Feb','Mar','Apr','May','Jun','Jul*','Aug*'],
        datasets:[
          { label:'Historical demand', data:[132,140,128,135,121,null,null],
            borderColor:C.primary, backgroundColor:C.primary, tension:.35, borderWidth:2.5, pointRadius:3 },
          { label:'Forecast', data:[null,null,null,null,121,150,162],
            borderColor:C.gold, backgroundColor:C.goldSoft, borderDash:[6,5], tension:.35, borderWidth:2.5, pointRadius:4, fill:true }
        ]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ position:'top', align:'end' } },
        scales:{ x:noGridX, y:axis({ beginAtZero:false }) } }
    });
    // allow app.js to push a new predicted value
    window.updateForecastChart = (val) => {
      forecastChart.data.datasets[1].data = [null,null,null,null,121,val,Math.round(val*1.08)];
      forecastChart.update();
    };
  }

  /* ---------- Forecasting page: Historical Demand (bar) ---------- */
  if (el('chartHistoricalDemand')) {
    new Chart(el('chartHistoricalDemand'), {
      type:'bar',
      data:{ labels:['Jan','Feb','Mar','Apr','May','Jun'],
        datasets:[{ label:'Units', data:[118,132,140,128,135,121],
          backgroundColor:C.primary, borderRadius:6, barThickness:24 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
  }

  /* ---------- Forecasting page: Inventory Trend (line) ---------- */
  if (el('chartInventoryTrend')) {
    const ctx = el('chartInventoryTrend').getContext('2d');
    new Chart(ctx, {
      type:'line',
      data:{ labels:['Jan','Feb','Mar','Apr','May','Jun'],
        datasets:[{ label:'Stock level', data:[210,185,160,140,110,80],
          borderColor:C.info, backgroundColor:'rgba(43,108,176,.12)', fill:true,
          tension:.38, borderWidth:2.5, pointRadius:3, pointBackgroundColor:C.info }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
  }

  /* ---------- Reports: revenue (bar) ---------- */
  if (el('chartRevenue')) {
    new Chart(el('chartRevenue'), {
      type:'bar',
      data:{ labels:['Jan','Feb','Mar','Apr','May','Jun'],
        datasets:[{ label:'Revenue', data:[1.82,2.05,2.31,1.98,2.56,2.84],
          backgroundColor:C.primary, borderRadius:6, barThickness:28 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false }, tooltip:{ callbacks:{ label:(c)=>'₱'+c.raw+'M' } } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true, ticks:{ color:C.grayText, callback:(v)=>'₱'+v+'M' } }) } }
    });
  }

  /* ---------- Reports: category distribution (pie) ---------- */
  if (el('chartCategory')) {
    new Chart(el('chartCategory'), {
      type:'pie',
      data:{ labels:['Bars','Plates','Sheets','Beams','Tubes/Pipes','Fasteners','Consumables'],
        datasets:[{ data:[34,16,12,14,10,8,6],
          backgroundColor:[C.primary,'#c94a3f','#d97b34','#e6a817','#2b6cb0','#1f9d55','#9aa1ad'], borderWidth:0 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ position:'right' } } }
    });
  }

  /* ---------- Profile / settings mini activity (line) ---------- */
  if (el('chartActivity')) {
    const ctx = el('chartActivity').getContext('2d');
    new Chart(ctx, {
      type:'line',
      data:{ labels:['Mon','Tue','Wed','Thu','Fri','Sat'],
        datasets:[{ label:'Actions', data:[12,18,9,22,16,7],
          borderColor:C.primary, backgroundColor:grad(ctx,'rgb(177,18,23)'), fill:true,
          tension:.4, borderWidth:2.5, pointRadius:0 }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ x:noGridX, y:axis({ beginAtZero:true }) } }
    });
  }

});
