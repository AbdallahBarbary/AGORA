// AGORA dashboard. Look and structure follow the design mock-up; every number, threshold,
// name and rule comes from the server's state (config, environment, agent_config).
'use strict';
let state = null, view = 'farm', selected = null, flash = '', timer = null, busy = false, pending = Promise.resolve();
let speedIdx = 1, msgFilter = 'all';
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = n => Math.round(n).toLocaleString('en-US');
const L = n => num(n) + ' L';
const pct = n => Math.round(n) + '%';
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;
const list = xs => xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1];
const cfg = () => state.config;
const DAY = () => Math.round(24 * 60 / cfg().tick_minutes);
const clockAt = t => { const m = t * cfg().tick_minutes;
  return `Day ${1 + Math.floor(m / 1440)} · ${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; };
const duration = ticks => { const h = ticks * cfg().tick_minutes / 60; return h % 24 === 0 ? plural(h / 24, 'day') : plural(h, 'hour'); };
const left = ticks => { const h = Math.ceil(ticks * cfg().tick_minutes / 60), d = Math.floor(h / 24), r = h % 24; return `${d ? d + ' d ' : ''}${r || !d ? r + ' h' : ''} left`.trim(); };
const dailyUse = () => state.cells.length * state.environment.base_drying_rate * DAY() * cfg().litres_per_point;
const decisionFor = id => state.requests.find(r => r.cell === id);
const stateOf = m => m < cfg().critical ? 'crit' : m < cfg().trigger ? 'need' : 'ok';
const STATE_LABEL = {ok: 'Healthy', need: 'Needs water', crit: 'Critical'};
const ZONE_VAR = ['--z-north', '--z-east', '--z-west', '--z-south'];   // fixed order, never cycled
const zoneColor = z => `var(${ZONE_VAR[state.zone_names.indexOf(z)]})`;
const agentName = n => n === 'Manager' ? 'Manager' : n === 'all' ? 'All agents' : `${n} agent`;
const SPEEDS = [{label: 'Slow', hint: '1 cycle a second', ms: 1000, cycles: 1}, {label: 'Normal', hint: '4 cycles a second', ms: 250, cycles: 1},
                {label: 'Fast', hint: 'a day in about 4 seconds', ms: 250, cycles: 3}];

// ---------- soil colours: brown below critical, straw below the irrigation line, green above ----------
function soil(v) {
  const c = cfg().critical, t = cfg().trigger;
  const stops = [[0, [122, 82, 46]], [c - .01, [176, 128, 74]], [c, [201, 163, 104]], [t - .01, [222, 196, 130]], [t, [170, 190, 110]], [100, [52, 104, 50]]];
  v = Math.max(0, Math.min(100, v));
  for (let i = 1; i < stops.length; i++) {
    const [a, ca] = stops[i - 1], [b, cb] = stops[i];
    if (v <= b) { const k = b === a ? 1 : (v - a) / (b - a); return ca.map((x, j) => Math.round(x + (cb[j] - x) * k)); }
  }
  return stops[stops.length - 1][1];
}
function ink(rgb) {   // dark or light text, whichever has more contrast on this soil colour
  const l = rgb.map(x => { x /= 255; return x <= .03928 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); });
  const lum = .2126 * l[0] + .7152 * l[1] + .0722 * l[2];
  return 1.05 / (lum + .05) >= (lum + .05) / .0613 ? '#FFFFFF' : '#1D1B16';
}
const rgb = c => `rgb(${c.join(',')})`;

// ---------- server calls (queued so playback, buttons and the demo never overlap) ----------
function api(path, body) { pending = pending.then(() => call(path, body)); return pending; }
async function call(path, body) {
  busy = true;
  try {
    const r = await fetch('/api/' + path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await r.json();
    if (!r.ok) throw Error(data.error);
    state = data; $('error').hidden = true; render();
  } catch (e) {
    pause(); $('error').textContent = `Connection problem: ${e.message}. Check that the Python server is running.`; $('error').hidden = false;
  } finally { busy = false; }
}

// ---------- playback ----------
const PLAY_ICON = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M4.5 3l8 5-8 5z"/></svg>Play';
const PAUSE_ICON = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M5.5 3.5v9M10.5 3.5v9"/></svg>Pause';
function showPlay() { $('run').innerHTML = timer ? PAUSE_ICON : PLAY_ICON; $('run').setAttribute('aria-label', timer ? 'Pause' : 'Play'); }
function pause() { clearInterval(timer); timer = null; showPlay(); }
function play() {
  if (timer) return pause();
  const s = SPEEDS[speedIdx];
  timer = setInterval(() => { if (!busy) api('step', {cycles: s.cycles}); }, s.ms);
  showPlay();
}

// ---------- render ----------
function render() {
  if (!$('scenario').options.length) {                          // first load: lists come from the server
    $('scenario').innerHTML = Object.entries(state.scenarios).map(([k, n]) => `<option value="${esc(k)}">${esc(n)}</option>`).join('');
    $('zone-filter').innerHTML = '<option value="all">All zones</option>' + state.zone_names.map(z => `<option>${esc(z)}</option>`).join('');
  }
  $('scenario').value = state.scenario;
  renderControls();
  if (view === 'farm') { renderField(); renderManager(); renderTank(); renderPlot(); drawChart(); }
  else { renderMessages(); renderRows(); }
}

function renderControls() {
  const e = state.environment, w = state.weather;
  $('speeds').innerHTML = SPEEDS.map((s, i) => `<button data-speed="${i}" aria-pressed="${i === speedIdx}" title="${s.hint}">${s.label}</button>`).join('');
  $('clock').textContent = clockAt(state.tick);
  $('temp').textContent = `${Math.round(w.temperature)} °C${w.heatwave_left ? ' (heatwave)' : ''}`;
  $('ex-heatwave').textContent = `+${e.heatwave_extra_temp} °C for ${duration(e.heatwave_ticks)}, soil dries faster`;
  $('ex-drought').textContent = `No rain, ${e.drought_drying_factor}× faster drying for ${duration(e.drought_ticks)}`;
  $('ex-refill').textContent = `Adds ${L(e.refill_litres)} to the tank (up to its capacity)`;
  $('ex-pump').textContent = `No supply into the tank for ${duration(e.pump_failure_ticks)}`;
  const chips = [];
  if (w.heatwave_left) chips.push(`<span class="ev-chip"><span class="dot" style="background:var(--heat-icon)"></span>Heatwave · ${left(w.heatwave_left)}</span>`);
  if (w.drought_left) chips.push(`<span class="ev-chip"><span class="dot" style="background:var(--drought-icon)"></span>Drought · ${left(w.drought_left)}</span>`);
  if (state.pump_off_left) chips.push(`<span class="ev-chip"><span class="dot" style="background:var(--pump-icon)"></span>Pump failure · ${left(state.pump_off_left)}</span>`);
  if (w.raining) chips.push(`<span class="ev-chip"><span class="dot" style="background:var(--water)"></span>Raining</span>`);
  $('active-events').innerHTML = chips.join('') || '<span class="small muted">None</span>';
  showPlay();
}

// ---------- the field ----------
const ICON_CRIT = bg => `<svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12"><path d="M6 1l5.2 9.5H.8z" fill="currentColor"/><path d="M6 4.5v3M6 9v.2" stroke="${bg}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
const ICON_NEED = '<svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="3.6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
const DROP_BADGE = '<svg class="drop" aria-hidden="true" width="20" height="20" viewBox="0 0 18 18"><circle cx="9" cy="9" r="8.3" fill="var(--water)" stroke="#FFFFFF" stroke-width="1.4"/><path d="M9 4.2c-1.8 2.4-2.8 3.9-2.8 5.2a2.8 2.8 0 005.6 0c0-1.3-1-2.8-2.8-5.2z" fill="#FFFFFF"/></svg>';
const SMALL_DROP = '<svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12"><path d="M6 1c-1.9 2.5-2.9 4-2.9 5.4a2.9 2.9 0 005.8 0C8.9 5 7.9 3.5 6 1z" fill="var(--water)"/></svg>';

function renderField() {
  const c = cfg(), side = Math.round(Math.sqrt(state.cells.length));
  $('field-sub').textContent = `${side} × ${side} plots seen from above · soil moisture, % of available water`;
  $('field-note').textContent = `Brown plots are below the ${c.critical}% critical line, straw plots are below the ${c.trigger}% irrigation line, green plots are healthy. ` +
    `Numbers are each plot's real moisture; select a plot to see what its sensor read, what its agent asked for and what the Manager decided.`;
  const ramp = (a, b) => `linear-gradient(90deg,${rgb(soil(a))},${rgb(soil(b))})`;
  $('legend').innerHTML = `<span><span class="mono small muted">0%</span><span class="ramp">
      <span style="flex:${c.critical};background:${ramp(0, c.critical - .01)}"></span><span style="flex:${c.trigger - c.critical};background:${ramp(c.critical, c.trigger - .01)}"></span>
      <span style="flex:${100 - c.trigger};background:${ramp(c.trigger, 100)}"></span></span><span class="mono small muted">100%</span></span>
    <span><span class="pipe-key"></span>Pipe from the tank</span><span>${DROP_BADGE.replace('class="drop" ', '').replace('width="20" height="20"', 'width="16" height="16"')}Watered this cycle</span>`;
  const full = state.capacity, share = Math.max(0, Math.min(1, state.tank / full));
  $('field').className = 'field' + (state.tank <= 0 ? ' dry' : '');
  $('field').innerHTML = `<div class="pipe v" aria-hidden="true"></div><div class="pipe h" aria-hidden="true"></div>` +
    state.zone_names.map(zoneBlock).join('') +
    `<div class="tank-dial" role="img" aria-label="Shared tank in the middle of the field, ${Math.round(share * 100)} percent of a full tank">
      <svg aria-hidden="true" width="72" height="72" viewBox="0 0 72 72"><circle cx="36" cy="36" r="30" fill="none" stroke="var(--hair)" stroke-width="5"/>
      <circle cx="36" cy="36" r="30" fill="none" stroke="var(--water)" stroke-width="5" stroke-linecap="round" stroke-dasharray="${(share * 188.5).toFixed(1)} 200" transform="rotate(-90 36 36)"/></svg>
      <b>${Math.round(share * 100)}%</b><span>tank</span></div>`;
}
function zoneBlock(z, zi) {
  const cells = state.cells.filter(c => c.zone === z), info = state.zones.find(x => x.name === z), c = cfg();
  const avg = cells.reduce((a, x) => a + x.moisture, 0) / cells.length, need = cells.filter(x => x.moisture < c.trigger).length;
  const flowing = cells.some(x => decisionFor(x.id)?.allocated > 0);
  const share = state.agent_config.stressed_share, limit = Math.floor(cells.length * share);
  const stripes = (zi === 0 || zi === 3) ? 90 : 0;                 // crop rows: alternate direction by zone
  return `<section class="zone" aria-label="${esc(z)} zone">
    <div class="zone-head"><h3><span class="zone-key" style="background:${zoneColor(z)}" aria-hidden="true"></span>${esc(z)}</h3>
      <span class="soft">Average ${pct(avg)}</span>
      <span class="need">${need === 0 ? 'No plots need water' : plural(need, 'plot') + (need === 1 ? ' needs' : ' need') + ' water'}</span>
      ${info.stressed ? `<span class="badge crit" title="The ${esc(z)} agent estimates more than ${limit} of its ${cells.length} plots below ${c.trigger}%">Stressed</span>` : ''}
      ${flowing ? `<span class="receiving">${SMALL_DROP}Receiving water</span>` : ''}</div>
    <div class="plots">${cells.map(x => plotButton(x, stripes)).join('')}</div></section>`;
}
function plotButton(c, deg) {
  const v = c.moisture, st = stateOf(v), col = soil(v), fg = ink(col), r = decisionFor(c.id), watered = r?.allocated > 0;
  const tex = `repeating-linear-gradient(${deg}deg, ${v >= cfg().trigger ? 'rgba(255,255,255,0.10)' : 'rgba(60,40,20,0.07)'} 0 2px, transparent 2px 9px)`;
  return `<button class="plot${watered ? ' watered' : ''}${c.id === selected ? ' sel' : ''}" data-cell="${esc(c.id)}" aria-pressed="${c.id === selected}"
      aria-label="${esc(c.id)}, ${Math.round(v)} percent, ${STATE_LABEL[st].toLowerCase()}${watered ? ', watered this cycle' : ''}"
      style="color:${fg};background-color:${rgb(col)};background-image:${tex}">
    <span class="pid">${st === 'crit' ? ICON_CRIT(rgb(col)) : st === 'need' ? ICON_NEED : ''}${esc(c.id)}</span>
    <span class="pct">${Math.round(v)}%</span>${watered ? DROP_BADGE : ''}</button>`;
}

// ---------- what the Manager is doing ----------
function renderManager() {
  const s = state, c = cfg(), a = s.assessment, d = s.requests, ac = s.agent_config;
  const zoneSize = s.cells.length / s.zone_names.length, limit = Math.floor(zoneSize * ac.stressed_share);
  $('cycle-label').textContent = s.tick ? `Latest cycle: ${clockAt(s.tick - 1)}` : 'Waiting to start';
  let box;
  if (!a) box = ['ok', 'Not assessed yet', 'The Manager assesses the farm every cycle once the simulation runs.'];
  else if (a.level === 'normal') box = ['ok', 'Normal', `No zone is stressed. A zone is stressed when more than ${limit} of its ${zoneSize} plots are estimated below ${c.trigger}%.`];
  else if (a.level === 'local') box = ['need', 'Local problem', `${plural(a.stressed.length, 'zone')} ${a.stressed.length === 1 ? 'is' : 'are'} stressed: ${list(a.stressed)}. The rest of the farm is fine.`];
  else box = ['crit', 'Farm-wide problem', `${a.stressed.length} of ${s.zone_names.length} zones are stressed: ${list(a.stressed)}.`];
  let html = `<div class="assess ${box[0]}"><div class="k">Farm assessment</div><div class="t">${box[1]}</div><div class="x">${esc(box[2])}</div></div>`;
  if (!s.tick) {
    html += `<p class="soft">No cycles have run yet. Press Play or Step one cycle to start. Each cycle is ${c.tick_minutes} simulated minutes.</p>`;
    $('manager').innerHTML = html; return;
  }
  const ok = d.filter(x => x.status === 'approved').length, cut = d.filter(x => x.status === 'adjusted').length, no = d.filter(x => x.status === 'rejected').length;
  const asked = d.reduce((t, x) => t + x.amount, 0), given = d.reduce((t, x) => t + x.allocated, 0), lines = [];
  if (!d.length) {
    const below = s.cells.filter(x => x.moisture < c.trigger).length;
    lines.push('No plot asked for water this cycle.');
    if (below) lines.push(`<span class="minor">${plural(below, 'plot')} ${below === 1 ? 'is' : 'are'} below ${c.trigger}%, but ${below === 1 ? 'its agent' : 'their agents'} chose to wait (still collecting readings, or water is being rationed).</span>`);
  } else {
    lines.push(`${plural(d.length, 'plot')} asked for water, ${L(asked)} in total.`);
    lines.push(`${ok} approved in full, ${cut} reduced and ${no} rejected${given ? `, ${L(given)} sent out` : ''}.`);
    if (!given && s.tank <= 0) lines.push('The tank was empty, so every request was rejected.');
    else if (a?.shortage) lines.push(`There was not enough water for everyone. Plots below ${c.critical}% were served first; the other requests shared what was left in proportion to what each asked for.`);
    else lines.push('There was enough water, so every request was approved in full.');
  }
  const scarcity = Math.max(0, 1 - s.tank / ac.comfortable_tank);
  if (scarcity > 0) lines.push(`<span class="minor">The tank is below ${L(ac.comfortable_tank)}, so the Manager has raised the water price to ×${(1 + ac.scarcity_price * scarcity).toFixed(1)}: agents now wait longer and may ask for half a refill.</span>`);
  html += `<div class="lines">${lines.map(t => `<p>${t}</p>`).join('')}</div>
    <div class="stats"><div class="stat"><div class="k">Asked</div><div class="v">${d.length}</div></div>
      <div class="stat"><div class="k"><span class="dot" style="background:#3F7A3A"></span>Approved</div><div class="v">${ok}</div></div>
      <div class="stat"><div class="k"><span class="dot" style="background:#C99A2E"></span>Reduced</div><div class="v">${cut}</div></div>
      <div class="stat"><div class="k"><span class="dot" style="background:#C8664A"></span>Rejected</div><div class="v">${no}</div></div></div>`;
  const sh = a?.shortage;
  if (sh && sh.available > 0) {
    const tags = (label, zones) => zones.length ? `<div><span class="label">${label}</span><div class="zone-tags">${zones.map(z => `<span>${esc(z)}</span>`).join('')}</div></div>` : '';
    html += `<div class="short"><div class="t">Water is short</div>
      <div class="pair"><div><div class="label">Asked for</div><div class="v">${L(sh.requested)}</div></div><div><div class="label">Available in the tank</div><div class="v">${L(sh.available)}</div></div></div>
      ${tags(`Critical plots served first in`, sh.prioritised)}${tags('Normal requests reduced in', sh.reduced)}${tags('Normal requests got nothing in', sh.delayed)}</div>`;
  }
  $('manager').innerHTML = html;
}

// ---------- water tank ----------
function renderTank() {
  const s = state, full = s.capacity, share = s.tank / full, use = dailyUse();
  $('tank-ref').innerHTML = `Capacity <b style="color:var(--text)">${L(full)}</b>`;
  $('tank').innerHTML = `<div class="tank-level"><b>${L(s.tank)}</b><span class="soft">${share > 1 ? 'more than a full tank' : `of ${L(full)} · ${Math.round(share * 100)}% full`}</span></div>
    <div class="meter${share < .1 ? ' low' : ''}" role="meter" aria-label="Tank level" aria-valuemin="0" aria-valuemax="${full}" aria-valuenow="${Math.round(Math.min(s.tank, full))}"><span style="width:${Math.min(100, share * 100).toFixed(1)}%"></span></div>
    <div class="scale"><span>0 L</span><span>${L(full)} (full)</span></div>
    <div class="pair-loose"><div><div class="label">Covers about</div><div class="v">${s.tank > 0 ? `${(s.tank / use).toFixed(1)} days of average use` : 'Nothing'}</div><div class="label">The farm uses about ${L(Math.round(use / 1000) * 1000)} a day on average</div></div>
      <div><div class="label">Supply into the tank</div><div class="v">${s.pump_off_left ? 'Stopped' : `${L(s.supply_per_day)} a day`}</div>
        <div class="label">${s.pump_off_left ? `Pump failure, ${left(s.pump_off_left)}` : `The farm's daily water quota`}</div></div></div>
    <div class="label">Used so far ${L(s.used)} · supplied ${L(s.supplied)}${s.added ? ` · topped up ${L(s.added)}` : ''}${s.spilled ? ` · overflowed ${L(s.spilled)} while full` : ''}</div>
    ${s.tank <= 0 ? `<div class="empty-tank"><span class="strong">The tank is empty. Requests are rejected until the supply or a top-up refills it.</span><button class="btn water" data-action="refill">Top up ${L(s.environment.refill_litres)}</button></div>` : ''}`;
}

// ---------- selected plot ----------
function renderPlot() {
  const s = state, c = cfg();
  const cell = selected && s.cells.find(x => x.id === selected);
  if (!cell) {
    $('plot').innerHTML = `<h2 id="plot-title">Selected plot</h2><p class="muted">Select a plot in the field to see its history, what its zone agent asked for and what the Manager decided.</p>`;
    return;
  }
  const p = cell.plan, r = decisionFor(cell.id), st = stateOf(cell.moisture), zone = esc(cell.zone);
  const watered = r?.allocated > 0;                                  // the reading and estimate were taken before the water arrived
  const readouts = [['Soil moisture', pct(cell.moisture), 'big']];
  if (p) readouts.push([watered ? 'Sensor, start of cycle' : 'Sensor reading', pct(p.reading)], [watered ? 'Estimate, start of cycle' : "Agent's estimate", pct(p.level)]);
  if (p && !watered) readouts.push(['In about 1 hour', pct(p.forecast)]);
  // history of the plot's real moisture, plus the agent's forecast as a dashed line
  const h = cell.history, n = Math.max(1, h.length - 1), x = i => i * 220 / n, y = v => (100 - v) * .72;
  const path = h.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const fore = p && !watered ? `<path d="M220 ${y(h[h.length - 1]).toFixed(1)} L260 ${y(p.forecast).toFixed(1)}" fill="none" stroke="var(--water)" stroke-width="1.75" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"/>` : '';
  const hours = (h.length - 1) * c.tick_minutes / 60;
  const est = p && `estimated it at ${pct(p.level)} and expected about ${pct(p.forecast)} in an hour`;
  let agent, mgr = 'Nothing to decide for this plot this cycle.';
  if (!p) agent = `No cycles have run yet, so the ${zone} agent has not looked at this plot.`;
  else if (p.warming_up) agent = `The ${zone} agent has ${plural(p.readings, 'reading')} of this plot so far and waits for ${s.agent_config.min_readings} before acting, because one reading can be off by ±${c.sensor_noise.toFixed(1)} points.`;
  else if (p.option === 'wait') agent = Object.keys(p.options).length === 1 ? `The ${zone} agent ${est}, at field capacity, so it did not ask for water.`
    : p.forecast >= c.trigger ? `The ${zone} agent ${est}, above the ${c.trigger}% line, so it did not ask for water.`
    : `The ${zone} agent ${est}. That is below the line, but at the current water price waiting still scored better than watering.`;
  else agent = `The ${zone} agent ${est}, so it asked for ${L(p.amount)}: ` + (p.option === 'full' ? `enough to refill it to field capacity (${c.target}%)` : 'half of a full refill, to save water') +
    (p.priority === 'critical' ? `. Below ${c.critical}%, so it marked the request critical.` : '.');
  if (r) mgr = r.status === 'approved' ? (s.assessment?.shortage ? 'Approved in full. Critical plots are served first, and there was enough left for this one.' : 'Approved in full. There was enough water for every request.')
    : r.status === 'adjusted' ? `Reduced to ${L(r.allocated)}. Water was short, so ${r.priority === 'critical' ? 'the critical plots shared what was in the tank' : 'critical plots were served first and the rest shared what was left'}.`
    : /empty/.test(r.reason) ? 'Rejected. The tank was empty.' : `Rejected. Water was short, and plots below ${c.critical}% needed all of it.`;
  $('plot').innerHTML = `<div class="plot-head"><h2 id="plot-title"><span class="swatch" style="background:${rgb(soil(cell.moisture))}" aria-hidden="true"></span>
      <span class="mono">${esc(cell.id)}</span> <span class="sub">${zone} zone</span></h2><span class="badge ${st}">${STATE_LABEL[st]}</span></div>
    <div class="readouts">${readouts.map(([k, v, cls]) => `<div><div class="label">${k}</div><div class="v ${cls || ''}">${v}</div></div>`).join('')}</div>
    <div><svg class="spark" role="img" viewBox="0 0 260 72" preserveAspectRatio="none" aria-label="${esc(cell.id)} over the last ${hours} hours, now ${pct(cell.moisture)}">
      <rect x="0" y="${y(c.trigger)}" width="260" height="0.8" fill="var(--line-trigger)"/><rect x="0" y="${y(c.critical)}" width="260" height="0.8" fill="var(--line-critical)"/>
      <path d="${path}" fill="none" stroke="var(--text)" stroke-width="1.75" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>${fore}</svg>
      <div class="spark-cap"><span>${h.length > 1 ? `Last ${hours} h: ${pct(h[0])} → ${pct(cell.moisture)}` : 'No history yet'}</span><span>${fore ? "Dashed: the agent's forecast · " : ''}lines at ${c.trigger}% and ${c.critical}%</span></div></div>
    ${watered ? `<p class="small soft">Watered this cycle: the sensor reading and the agent's estimate are from before the water arrived.</p>` : ''}
    <div><div class="who">Zone agent</div><p class="said">${agent}</p></div>
    <div><div class="who">Manager</div><p class="said">${mgr}</p></div>
    <div class="hand"><button class="btn" data-event="water"><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--water)" stroke-width="1.5"><path d="M8 2c-2.4 3.2-3.8 5.2-3.8 7a3.8 3.8 0 007.6 0c0-1.8-1.4-3.8-3.8-7z"/></svg>Water by hand, +${L(s.environment.manual_water_litres)}</button>
      <span class="small muted">Does not use the tank</span></div>
    ${flash ? `<p class="flash">${esc(flash)}</p>` : ''}
    <p class="footnote">Sensor readings are noisy (±${c.sensor_noise.toFixed(1)} points). Agents act on a smoothed estimate, so the plot's real moisture, its sensor reading and the agent's estimate can differ by a few points.</p>`;
}

// ---------- moisture over time ----------
function drawChart() {
  const box = $('chart'), tip = $('chart-tip'), hist = state.zone_history, c = cfg(), zones = state.zone_names, last = hist[hist.length - 1];
  $('chart-legend').innerHTML = zones.map((z, i) => `<span><span style="width:16px;height:2px;border-radius:1px;background:${zoneColor(z)}"></span>${esc(z)} <b>${pct(last[i + 1])}</b></span>`).join('') +
    `<span><span class="band" style="background:var(--heat-band)"></span>Heatwave</span><span><span class="band" style="background:var(--drought-band)"></span>Drought</span>
     <span><span class="band" style="background:var(--pump-band)"></span>Pump failure</span><span><span style="width:2px;height:12px;background:var(--water)"></span>Tank topped up</span>`;
  box.querySelector('svg')?.remove(); box.querySelector('.chart-empty')?.remove();
  const W = box.clientWidth, H = box.clientHeight;
  if (!W) return;
  const m = {l: 44, r: 14, t: 8, b: 24}, t0 = hist[0][0], t1 = Math.max(last[0], t0 + DAY());
  const X = t => m.l + (t - t0) * (W - m.l - m.r) / (t1 - t0), Y = v => m.t + (100 - v) * (H - m.t - m.b) / 100;
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const HALO = 'stroke="var(--chart)" stroke-width="4" paint-order="stroke" stroke-linejoin="round"';
  let labels = '';
  let g = `<rect x="${m.l}" y="${m.t}" width="${pw}" height="${ph}" rx="8" fill="var(--chart)" stroke="var(--hair)"/>`;
  for (const e of [...state.events].reverse()) {                           // heatwaves and droughts as shaded bands
    if (e.until == null) continue;
    const a = Math.max(t0, e.tick), b = Math.min(t1, e.until, last[0]);
    const band = {heatwave: ['heat', 'Heatwave'], drought: ['drought', 'Drought'], pump: ['pump', 'Pump failure']}[e.kind];
    if (b > a) { const row = {heatwave: 0, drought: 1, pump: 2}[e.kind];        // overlapping events get their own label row
      g += `<rect x="${X(a)}" y="${m.t}" width="${X(b) - X(a)}" height="${ph}" fill="var(--${band[0]}-band)" fill-opacity="${e.kind === 'drought' ? .7 : 1}"/>`;
      const edge = X(a) > W - m.r - 90;                                     // near the right edge: keep the label inside
      labels += `<text x="${edge ? W - m.r - 6 : X(a) + 8}" y="${m.t + 16 + row * 14}" text-anchor="${edge ? 'end' : 'start'}" font-size="11" fill="#D9B58A" ${HALO}>${band[1]}</text>`; }
  }
  for (const v of [c.target, c.trigger, c.critical, 0]) g += `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" class="mono" fill="var(--muted)">${v}%</text>`;
  for (const [v, col, label, txt] of [[c.trigger, 'var(--line-trigger)', `Irrigation line ${c.trigger}%`, 'var(--soft)'], [c.critical, 'var(--line-critical)', `Critical line ${c.critical}%`, '#E09A82']])
    { g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="${col}" stroke-dasharray="4 4"/>`;
      labels += `<text x="${W - m.r - 8}" y="${Y(v) - 6}" text-anchor="end" font-size="11" fill="${txt}" ${HALO}>${label}</text>`; }
  for (let t = Math.ceil(t0 / DAY()) * DAY(); t <= t1; t += DAY())
    g += `<text x="${X(t)}" y="${H - 6}" text-anchor="${t === t0 ? 'start' : 'middle'}" font-size="11" class="mono" fill="var(--muted)">Day ${t / DAY() + 1}</text>`;
  for (const e of state.events) {                                           // refills as hairline markers
    if (e.kind !== 'refill' || e.tick < t0) continue;
    const label = '+' + (e.text.match(/([\d,]+) L/) || [, ''])[1] + ' L';
    const right = X(e.tick) > W - m.r - 70;                                 // near the right edge: label on the left
    g += `<line x1="${X(e.tick)}" x2="${X(e.tick)}" y1="${m.t}" y2="${m.t + ph}" stroke="var(--water)" stroke-width="2"/>`;
    labels += `<text x="${X(e.tick) + (right ? -5 : 5)}" y="${m.t + ph - 6}" text-anchor="${right ? 'end' : 'start'}" font-size="11" fill="var(--water-text)" ${HALO}>${label}</text>`;
  }
  if (hist.length > 1) zones.forEach((z, i) => {
    g += `<polyline points="${hist.map(row => `${X(row[0]).toFixed(1)},${Y(row[i + 1]).toFixed(1)}`).join(' ')}" fill="none" stroke="${zoneColor(z)}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${X(last[0])}" cy="${Y(last[i + 1])}" r="4" fill="${zoneColor(z)}" stroke="var(--chart)" stroke-width="2"/>`;
  });
  g += labels;                                                              // labels on top of lines and markers
  g += `<line id="cross" y1="${m.t}" y2="${m.t + ph}" stroke="var(--muted)" visibility="hidden"/>`;
  box.insertAdjacentHTML('afterbegin', `<svg viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="Average moisture of each zone over time, with heatwaves, droughts and water added marked">${g}
    <rect x="${m.l}" y="${m.t}" width="${pw}" height="${ph}" fill="transparent"/></svg>`);
  if (hist.length <= 1) {
    box.insertAdjacentHTML('beforeend', '<div class="chart-empty"><b>Nothing to show yet</b><span>Start the simulation to draw one line per zone. Events you trigger appear here as shaded bands.</span></div>');
    return;
  }
  const svg = box.querySelector('svg'), cross = svg.querySelector('#cross');
  let idx = hist.length - 1;
  const show = i => {                                                       // crosshair snaps to the nearest cycle
    idx = Math.max(0, Math.min(hist.length - 1, i)); const row = hist[idx], x = X(row[0]);
    cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
    tip.replaceChildren();
    const when = document.createElement('div'); when.className = 'when'; when.textContent = clockAt(row[0]); tip.append(when);
    zones.forEach((z, i) => { const r = document.createElement('div'); r.className = 'row';
      const k = document.createElement('span'); k.style.cssText = `width:12px;height:2px;background:${zoneColor(z)}`;
      const v = document.createElement('b'); v.textContent = pct(row[i + 1]); const n = document.createElement('span'); n.textContent = z;
      r.append(k, v, n); tip.append(r); });
    state.events.filter(e => e.until != null ? e.tick <= row[0] && row[0] < e.until : e.kind === 'refill' && Math.abs(e.tick - row[0]) < 1)
      .forEach(e => { const d = document.createElement('div'); d.className = 'ev'; d.textContent = e.text; tip.append(d); });
    tip.hidden = false; tip.style.left = Math.min(x + 12, W - tip.offsetWidth - 4) + 'px'; tip.style.top = m.t + 8 + 'px';
  };
  const nearest = px => { let b = 0; hist.forEach((row, i) => { if (Math.abs(X(row[0]) - px) < Math.abs(X(hist[b][0]) - px)) b = i; }); return b; };
  const hide = () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); };
  svg.addEventListener('pointermove', e => show(nearest(e.clientX - svg.getBoundingClientRect().left)));
  svg.addEventListener('pointerleave', hide); svg.addEventListener('blur', hide);
  svg.addEventListener('focus', () => show(hist.length - 1));
  svg.addEventListener('keydown', e => { if (e.key === 'ArrowLeft') show(idx - 1); if (e.key === 'ArrowRight') show(idx + 1); });
}

// ---------- details: messages and decisions ----------
const KINDS = [['all', 'All'], ['recommendation', 'Recommendations'], ['decision', 'Manager decisions'], ['zone-status', 'Zone status'], ['tank-status', 'Tank broadcasts']];
const KIND_DOT = {recommendation: '#8D99A5', decision: '#5FA37E', 'zone-status': '#B5AC98', 'tank-status': 'var(--water)'};
const KIND_ONE = {recommendation: 'Recommendation', decision: 'Manager decision', 'zone-status': 'Zone status', 'tank-status': 'Tank broadcast'};
function renderMessages() {
  $('msg-filters').innerHTML = KINDS.map(([k, label]) => `<button data-filter="${k}" aria-pressed="${k === msgFilter}">${label}</button>`).join('');
  const ms = state.messages.filter(m => msgFilter === 'all' || m.kind === msgFilter);
  $('messages').innerHTML = ms.length ? ms.map(m => `<li class="msg"><div class="msg-meta">
      <span class="msg-tag"><span class="dot" style="background:${KIND_DOT[m.kind]}" aria-hidden="true"></span>${KIND_ONE[m.kind]}</span>
      <span class="msg-route">${esc(agentName(m.sender))} → ${esc(agentName(m.recipient))}</span>
      <span class="msg-when">${m.repeats > 1 ? `Cycles ${m.first_cycle}–${m.cycle}` : `Cycle ${m.cycle}`}</span>
      ${m.repeats > 1 ? `<span class="msg-rep">Repeated ${m.repeats} times</span>` : ''}</div><p>${esc(m.text)}</p></li>`).join('')
    : `<li class="empty">${state.tick ? 'No messages of this kind yet.' : 'Start the simulation to see the agents talk.'}</li>`;
}
function decisionText(r) {
  return r.status === 'approved' ? ['ok', `Approved, ${L(r.allocated)}`] : r.status === 'adjusted' ? ['need', `Reduced to ${L(r.allocated)}`]
    : ['crit', /empty/.test(r.reason) ? 'Rejected, tank empty' : 'Rejected'];
}
function filteredRows() {
  const q = $('search').value.trim().toUpperCase(), pr = $('priority').value, zone = $('zone-filter').value;
  return state.logs.filter(r => (!q || r.cell.includes(q)) && (pr === 'all' || r.priority === pr) && (zone === 'all' || r.zone === zone));
}
function renderRows() {
  const rows = filteredRows();
  $('row-count').textContent = `${rows.length} of ${state.logs.length} rows`;
  $('no-rows').hidden = rows.length > 0;
  $('rows').innerHTML = rows.map(r => { const [cls, dec] = decisionText(r);
    return `<tr><td>${r.tick}</td><td class="time">${clockAt(r.tick - 1)}</td><td class="cell-id">${esc(r.cell)}</td><td>${esc(r.zone)}</td>
      <td class="num">${pct(r.level)}</td><td class="num">${pct(r.forecast)}</td>
      <td>${r.priority === 'critical' ? '<span class="pill crit">Critical</span>' : '<span class="soft">Normal</span>'}</td>
      <td>${r.option === 'full' ? 'Full refill' : 'Half refill'}, ${L(r.amount)}</td><td><span class="pill ${cls}">${dec}</span></td></tr>`; }).join('');
}
function exportCsv() {
  const q = v => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [['cycle', 'time', 'cell', 'zone', 'estimate_pct', 'forecast_pct', 'priority', 'recommended', 'litres_asked', 'decision', 'litres_given', 'manager_reason'].join(',')]
    .concat(filteredRows().map(r => [r.tick, clockAt(r.tick - 1), r.cell, r.zone, r.level.toFixed(1), r.forecast.toFixed(1), r.priority, r.option, Math.round(r.amount), r.status, Math.round(r.allocated), r.reason].map(q).join(',')));
  const url = URL.createObjectURL(new Blob([lines.join('\n')], {type: 'text/csv'})), a = document.createElement('a');
  a.href = url; a.download = 'agora-decisions.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- views ----------
function showView(v) {
  view = v;
  $('farm-view').hidden = v !== 'farm'; $('details-view').hidden = v !== 'details';
  $('view-farm').toggleAttribute('aria-current', v === 'farm'); $('view-details').toggleAttribute('aria-current', v === 'details');
  if (v === 'farm') $('view-farm').setAttribute('aria-current', 'page'); else $('view-details').setAttribute('aria-current', 'page');
  if (state) render();
}

// ---------- guided demo: the project's four scripted steps, captions built from the run ----------
const below = s => s.cells.filter(c => c.moisture < s.config.trigger).length;
const lastDay = s => s.logs.filter(r => r.tick > s.tick - DAY());
const counts = rs => ({ok: rs.filter(r => r.status === 'approved').length, cut: rs.filter(r => r.status === 'adjusted').length, no: rs.filter(r => r.status === 'rejected').length});
let evapBefore = 0;                                       // soil evaporation total at the start of the last simulated day
const DEMO = [
  {title: 'A healthy farm', run: async () => { await api('reset', {scenario: 'healthy'}); await api('step', {cycles: DAY() / 2}); },
   caption: (a, b) => { const c = counts(b.logs);
     return `${L(b.supply_per_day)} flows into the tank every day, about what the farm uses. A few plots start just under the ${b.config.trigger}% line, so their agents ask for water within minutes and the Manager approves: ${c.ok} refills in 12 hours. ` +
       `The ${L(b.capacity)} tank is a buffer: it dips as refills go out and the supply tops it back up. It holds ${L(b.tank)} now.`; }},
  {title: 'One zone dries out', run: async () => { await api('reset', {scenario: 'one-zone'}); await api('step', {cycles: 12}); },
   figures: (a, b) => [['Given to North, last 6 h', b.logs.filter(r => r.zone === 'North').reduce((t, r) => t + r.allocated, 0), 'water'],
     ['North still needs, to reach field capacity', b.cells.filter(c => c.zone === 'North').reduce((t, c) => t + (b.config.target - c.moisture) * b.config.litres_per_point, 0), '']],
   caption: (a, b) => { const c = counts(b.logs.filter(r => r.zone !== 'North'));
     return `North starts parched, with plots below ${b.config.critical}%, while the rest of the farm is fine: a local problem. North's agent asks for far more than the tank holds, so the Manager serves North's critical plots first and shares each cycle's water between them` +
       `${c.no + c.cut ? `; ${c.no + c.cut} requests from other zones were cut back or waited` : ''}. Supply is 1.5 times the quota here, and North recovers over the next day.`; }},
  {title: 'A heatwave causes a shortage', run: async () => { await api('reset', {scenario: 'heatwave'});
     for (let d = 0; d < 6; d++) { evapBefore = state.evaporated; await api('step', {cycles: DAY()}); if (lastDay(state).some(r => r.status !== 'approved')) break; } },
   figures: (a, b) => [['Lost to evaporation, last day', b.evaporated - evapBefore, ''], ['Supplied to the tank, last day', b.supply_per_day, 'water']],
   caption: (a, b) => { const c = counts(lastDay(b));
     return `From day 2 the farm is hot and dry (+${b.environment.heatwave_extra_temp} °C and no rain, shaded on the chart), so plots dry much faster than the supply refills the tank. ` +
       `By ${clockAt(b.tick - 1).split(' · ')[0]} the tank can't cover every request: that day the Manager approved ${c.ok} and cut back ${c.cut}${c.no ? `, rejected ${c.no}` : ''}, serving the driest plots first.`; }},
  {title: 'Recovery', run: async () => { const hw = state.events.find(e => e.kind === 'heatwave'); const goal = (hw ? hw.until : state.tick) + 2 * DAY();
     while (state.tick < goal) await api('step', {cycles: Math.min(DAY(), goal - state.tick)}); },
   caption: (a, b) => { const c = counts(lastDay(b)), hw = b.events.find(e => e.kind === 'heatwave');
     return `The heat breaks ${hw ? `at ${clockAt(hw.until)}` : ''}. Demand falls back to about the supply, the tank recovers to ${L(b.tank)}, and in the last day the Manager approved ${c.ok} of ${c.ok + c.cut + c.no} requests` +
       `${c.cut + c.no ? '' : ' in full'}. The agents are back to routine top-ups.`; }},
];
let demoStep = -1;
async function demoGo(i) {
  if (i >= DEMO.length) return demoExit();
  pause(); if (view !== 'farm') showView('farm');
  demoStep = i; const d = DEMO[i]; $('demo').hidden = false;
  $('demo-step').textContent = `Guided demo · step ${i + 1} of ${DEMO.length}`;
  $('demo-bars').innerHTML = DEMO.map((_, k) => `<i class="${k <= i ? 'on' : ''}"></i>`).join('');
  $('demo-title').textContent = d.title; $('demo-caption').textContent = 'Running…'; $('demo-figures').replaceChildren(); $('demo-next').disabled = true;
  const before = state; await d.run();
  $('demo-caption').textContent = d.caption(before, state);
  for (const [label, v, cls] of d.figures ? d.figures(before, state) : []) {
    const t = document.createElement('div'), k = document.createElement('div'), n = document.createElement('div');
    t.className = 'tile'; k.className = 'label'; k.textContent = label; n.className = 'v ' + cls; n.textContent = L(v); t.append(k, n); $('demo-figures').append(t);
  }
  $('demo-next').disabled = false; $('demo-next').textContent = i === DEMO.length - 1 ? 'Finish' : 'Next';
}
function demoExit() { demoStep = -1; $('demo').hidden = true; }

// ---------- wiring ----------
document.addEventListener('click', e => {
  const t = e.target.closest('[data-event],[data-cell],[data-speed],[data-filter],[data-action]');
  if (!t) return;
  if (t.dataset.event) {
    const kind = t.dataset.event;
    return api('event', {type: kind, cell: selected}).then(() => { if (kind === 'water' && state.events[0]?.kind === 'water') { flash = state.events[0].text; renderPlot(); } });
  }
  if (t.dataset.cell) { selected = t.dataset.cell; flash = ''; render(); }
  if (t.dataset.speed) { speedIdx = +t.dataset.speed; if (timer) { pause(); play(); } else renderControls(); }
  if (t.dataset.filter) { msgFilter = t.dataset.filter; renderMessages(); }
  if (t.dataset.action === 'refill') api('refill', {});
});
const reset = () => { pause(); selected = null; flash = ''; api('reset', {scenario: $('scenario').value}); };
$('run').onclick = play;
$('step').onclick = () => { pause(); api('step', {cycles: 1}); };
$('skip').onclick = () => { pause(); api('step', {cycles: DAY()}); };
$('reset').onclick = reset; $('scenario').onchange = reset;
$('refill').onclick = () => api('refill', {});
$('demo-start').onclick = () => demoGo(0); $('demo-next').onclick = () => demoGo(demoStep + 1); $('demo-exit').onclick = demoExit;
$('view-farm').onclick = () => showView('farm'); $('view-details').onclick = () => showView('details');
for (const id of ['search', 'priority', 'zone-filter']) $(id).addEventListener('input', renderRows);
$('export').onclick = exportCsv;
let resizeTimer; window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (state && view === 'farm') drawChart(); }, 100); });
showPlay(); api('state');
