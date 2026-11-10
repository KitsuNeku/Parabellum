/* Forecasting page */
document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  const html = (id, v) => { const e = $(id); if (e) e.innerHTML = v; };
  const fmt = (n) => Number(n).toLocaleString('en-PH', { maximumFractionDigits: 2 });
  const select = $('fcMaterialSelect');
  const runBtn = $('fcRunBtn');
  let RESULT = null;
  let onlyRunout = false;
  let viewMode = 'monthly';

  const trendOf = (f) => (f.prev_demand ? ((f.predicted_demand - f.prev_demand) / f.prev_demand) * 100 : null);
  const trendHTML = (t) => t === null ? '<span class="text-muted-2">—</span>'
    : t >= 0 ? `<span class="text-danger"><i class="bi bi-arrow-up"></i> ${t.toFixed(1)}%</span>`
             : `<span class="text-success"><i class="bi bi-arrow-down"></i> ${Math.abs(t).toFixed(1)}%</span>`;
  const riskBadge = (f) => {
    const cls = f.risk === 'Will run out' ? 'b-danger' : f.risk === 'Low' ? 'b-warning' : 'b-success';
    return `<span class="badge ${cls}">${escapeHTML(f.risk)}</span>`;
  };
  const coverText = (f) => f.days_of_cover === null ? '—' : f.days_of_cover >= 90 ? '3+ months' : `${Math.round(f.days_of_cover)} days`;

  function renderKpis(){
    const s = RESULT.summary, ev = RESULT.evaluation;
    set('fcKpiMonth', RESULT.forecast_month);
    set('fcKpiMaterials', `${s.materials} materials forecast`);
    set('fcKpiRunout', s.will_run_out);
    if (ev) {
      const m = ev.models[0];
      set('fcKpiMape', m.mape === null ? `MAE ${fmt(m.mae)}` : `${m.mape}%`);
      set('fcKpiMapeDesc', `Tested on ${ev.test_period}`);
      if (ev.weather_helps) {
        set('fcKpiWeather', `Helps (${ev.weather_improvement_pct}%)`);
        set('fcKpiWeatherDesc', 'Lower error when weather is included');
      } else {
        set('fcKpiWeather', 'No clear effect');
        set('fcKpiWeatherDesc', 'Error is about the same with or without weather');
      }
    } else {
      set('fcKpiMape', '—'); set('fcKpiMapeDesc', 'Not enough history to test yet');
      set('fcKpiWeather', '—'); set('fcKpiWeatherDesc', 'Needs more history');
    }
    if (RESULT.run_at) set('fcUpdated', new Date(RESULT.run_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }));
  }

  function renderTable(){
    set('fcTableMonth', RESULT.forecast_month);
    const list = RESULT.forecasts.filter(f => !onlyRunout || f.risk === 'Will run out');
    $('forecastAllBody').innerHTML = list.length ? list.map(f => `
      <tr class="fc-row${f.material_name === select.value ? ' is-active' : ''}" data-mat="${escapeHTML(f.material_name)}">
        <td class="fw-medium">${escapeHTML(f.material_name)}${f.model_type === 'pooled' ? ' <span class="badge b-neutral" title="Uses the combined model (not enough history for its own)">combined</span>' : ''}</td>
        <td class="text-end">${fmt(f.current_stock)} <span class="text-muted-2">${escapeHTML(f.unit)}</span></td>
        <td class="text-end fw-semibold">${fmt(f.predicted_demand)} <span class="text-muted-2">${escapeHTML(f.unit)}</span></td>
        <td class="text-end">${trendHTML(trendOf(f))}</td>
        <td class="text-end">${f.reorder_qty > 0 ? `<span class="fw-semibold" style="color:var(--primary)">${fmt(f.reorder_qty)} ${escapeHTML(f.unit)}</span>` : '<span class="text-muted-2">—</span>'}</td>
        <td>${riskBadge(f)}</td>
      </tr>`).join('')
      : '<tr><td colspan="6" class="text-center text-muted-2 py-4">No materials will run out next month.</td></tr>';
  }

  function renderDetail(name){
    const f = RESULT.forecasts.find(x => x.material_name === name) || RESULT.forecasts[0];
    if (!f) return;
    select.value = f.material_name;
    document.querySelectorAll('.fc-row').forEach(r => r.classList.toggle('is-active', r.dataset.mat === f.material_name));
    const useSeasonal = (viewMode === 'seasonal') && (f.seasonal_naive_demand != null);
    const shownPredicted = useSeasonal ? f.seasonal_naive_demand : f.predicted_demand;
    const shownReorder = Math.max(0, (shownPredicted || 0) - (f.current_stock || 0));
    set('fcResPredicted', `${fmt(shownPredicted ?? 0)} ${f.unit}`);
    set('fcResStock', `${fmt(f.current_stock)} ${f.unit}`);
    html('fcResTrend', trendHTML(f.prev_demand ? ((shownPredicted - f.prev_demand) / f.prev_demand) * 100 : null));
    set('fcResCover', shownPredicted > 0
      ? (() => { const d = Math.round(f.current_stock / (shownPredicted / 30.0)); return d >= 90 ? '3+ months' : `${d} days`; })()
      : '—');
    html('fcResReorder', shownReorder > 0
      ? `Order about <strong>${fmt(shownReorder)} ${escapeHTML(f.unit)}</strong> before ${escapeHTML(RESULT.forecast_month)} to cover the predicted demand.`
      : `Current stock should be enough for ${escapeHTML(RESULT.forecast_month)}. No restock needed yet.`);
    let insight = escapeHTML(f.weather_insight || '—');
    if (f.sample_size_warning) insight += ` <span class="text-muted-2">(Based on only ${f.training_rows} months of history.)</span>`;
    html('fcWxInsight', `<i class="bi bi-info-circle me-1"></i>${insight}`);
    // Seasonal mode uses the demand from the same calendar month one year ago
    // as the forecast value (seasonal naive). Monthly mode uses the MLR output.
    const forecastValue = useSeasonal ? f.seasonal_naive_demand : f.predicted_demand;
    if (viewMode === 'seasonal') {
      set('fcDetailChartTitle', 'Seasonal Demand & Forecast');
      if (f.seasonal_naive_demand == null) {
        set('fcDetailChartSub', `No data from ${RESULT.forecast_month} of last year yet, so no seasonal forecast for this material.`);
      } else {
        set('fcDetailChartSub', `Forecast for ${RESULT.forecast_month} uses the actual demand from the same month last year.`);
      }
    } else {
      set('fcDetailChartTitle', 'Monthly Demand & Forecast');
      set('fcDetailChartSub', "Last 6 months of actual demand and next month's forecast.");
    }
    window.updateForecastChart?.(f.history || [], f.forecast_label || RESULT.forecast_month, forecastValue);
    window.updateInventoryChart?.(f.history || []);
  }

  function renderWeather(){
    const wx = RESULT.weather || {};
    set('fcWxMonth', RESULT.forecast_month);
    if (wx.available === false) {
      set('fcWxSource', 'no weather data yet, it is downloaded automatically when the weather service is reachable');
      ['fcWxTemp', 'fcWxRain', 'fcWxDays'].forEach(id => set(id, '—'));
      return;
    }
    set('fcWxSource', wx.source || '—');
    set('fcWxTemp', wx.avg_temp_c != null ? `${wx.avg_temp_c}°C` : '—');
    set('fcWxRain', wx.total_rainfall_mm != null ? `${fmt(wx.total_rainfall_mm)} mm` : '—');
    set('fcWxDays', wx.rainy_days != null ? `${wx.rainy_days}` : '—');
  }

  function renderEvaluation(){
    const ev = RESULT.evaluation;
    if (!ev) {
      set('fcEvalPeriod', '—');
      set('fcEvalSub', 'There is not enough history yet to test the model on months it has not seen (needs at least 12 months).');
      html('fcEvalBody', '<tr><td colspan="5" class="text-center text-muted-2 py-3">Not enough history to evaluate.</td></tr>');
      html('fcEvalNotes', '');
      return;
    }
    set('fcEvalPeriod', `Test months: ${ev.test_period}`);
    set('fcEvalSub', `Trained on older months, then tested on the last ${ev.holdout_months} months (${ev.test_rows} material-months) it never saw.`);
    const best = Math.min(...ev.models.map(m => m.mae));
    html('fcEvalBody', ev.models.map((m, i) => `<tr${i === 0 ? ' class="fw-semibold"' : ''}>
      <td>${escapeHTML(m.name)}${m.mae === best ? ' <span class="badge b-success">lowest error</span>' : ''}</td>
      <td class="text-end">${fmt(m.mae)}</td><td class="text-end">${fmt(m.rmse)}</td>
      <td class="text-end">${m.mape === null ? 'n/a' : m.mape + '%'}</td>
      <td class="text-end">${m.r2 === null ? 'n/a' : m.r2}</td></tr>`).join(''));
    const note = (ok, text) => `<div class="col-md-6"><div class="alert ${ok ? 'alert-soft-success' : 'alert-soft-warning'} small mb-0"><i class="bi ${ok ? 'bi-check-circle' : 'bi-info-circle'} me-1"></i>${text}</div></div>`;
    html('fcEvalNotes',
      note(ev.beats_naive, ev.beats_naive
        ? 'The model is more accurate than simply repeating last month.'
        : 'Simply repeating last month was as accurate or more accurate on this data. More real history should help the model.') +
      note(ev.weather_helps, ev.weather_helps
        ? `Including weather lowered the error by ${ev.weather_improvement_pct}%.`
        : 'Weather did not noticeably change the error for monthly demand on this data.'));
  }

  function renderAll(){
    renderKpis(); renderTable(); renderWeather(); renderEvaluation();
    const keep = select.value;
    select.innerHTML = RESULT.forecasts.map(f => `<option>${escapeHTML(f.material_name)}</option>`).join('');
    renderDetail(RESULT.forecasts.some(f => f.material_name === keep) ? keep : (RESULT.forecasts.find(f => f.risk === 'Will run out') || RESULT.forecasts[0]).material_name);
    window.updateHistoricalChart?.(RESULT.forecasts);
  }

  function showError(msg){
    html('forecastAllBody', `<tr><td colspan="6" class="text-center text-danger py-4">${escapeHTML(msg)}</td></tr>`);
    select.innerHTML = '<option value="">Unavailable</option>';
  }

  async function runForecast(){
    runBtn.disabled = true;
    const label = runBtn.innerHTML;
    runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running…';
    try {
      const res = await fetch('/api/forecast', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || 'Forecast failed.');
      RESULT = { ...json.data, run_at: new Date().toISOString() };
      renderAll();
      reloadHistory();
      showToast('Forecast updated', 'success');
    } catch (err) {
      if (!RESULT) showError(err.message);
      showToast(err.message, 'error', 'bi-exclamation-triangle');
    } finally {
      runBtn.disabled = false;
      runBtn.innerHTML = label;
    }
  }

  async function loadLatest(){
    try {
      const res = await fetch('/api/forecast/latest');
      const json = await res.json();
      if (json.ok && json.data && json.data.forecasts) { RESULT = json.data; renderAll(); return; }
    } catch (_) {}
    runForecast();
  }

  async function reloadHistory(){
    const tb = $('fcHistBody');
    try {
      const json = await (await fetch('/api/forecast_history')).json();
      if (!json.ok || !json.data?.length) {
        tb.innerHTML = '<tr><td colspan="5" class="text-center text-muted-2 py-3">No past forecasts yet.</td></tr>';
        return;
      }
      tb.innerHTML = json.data.map(f => `<tr>
        <td class="fw-medium">${escapeHTML(f.material)}</td><td>${escapeHTML(f.month)}</td>
        <td class="text-end">${fmt(f.predicted)}</td>
        <td class="text-end">${f.actual == null ? '<span class="text-muted-2">—</span>' : fmt(f.actual)}</td>
        <td class="text-center">${f.accuracy == null ? '<span class="text-muted-2" title="Shown once the month is over">waiting</span>'
          : `<span class="badge ${f.accuracy >= 80 ? 'b-success' : f.accuracy >= 60 ? 'b-warning' : 'b-danger'}">${f.accuracy}%</span>`}</td></tr>`).join('');
    } catch (_) {
      tb.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-3">Could not load prediction history.</td></tr>';
    }
  }

  async function reloadScheduler(){
    try {
      const json = await (await fetch('/api/scheduler/status')).json();
      if (!json.ok || !json.data.enabled) { set('fcSchedNext', 'off'); return; }
      set('fcSchedNext', json.data.next_run_at
        ? new Date(json.data.next_run_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
        : 'pending');
      if (json.data.last_status === 'failed') {
        $('fcSchedBadge').classList.add('b-warning');
        $('fcSchedBadge').title = 'Last automatic run failed: ' + (json.data.last_message || '');
      }
    } catch (_) { set('fcSchedNext', 'unavailable'); }
  }

  $('forecastAllBody').addEventListener('click', (e) => {
    const row = e.target.closest('.fc-row'); if (!row) return;
    renderDetail(row.dataset.mat);
  });
  select.addEventListener('change', () => renderDetail(select.value));
  runBtn.addEventListener('click', runForecast);
  document.querySelectorAll('input[name="fcViewMode"]').forEach(r => {
    r.addEventListener('change', () => {
      viewMode = document.querySelector('input[name="fcViewMode"]:checked')?.value || 'monthly';
      if (RESULT) renderDetail(select.value);
    });
  });
  window.onKpiFilter = (key) => {
    onlyRunout = key === 'runout';
    if (RESULT) renderTable();
  };

  loadLatest();
  reloadHistory();
  reloadScheduler();
});
