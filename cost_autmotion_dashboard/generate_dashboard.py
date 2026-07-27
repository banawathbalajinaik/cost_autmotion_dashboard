"""
Builds a single self-contained dashboard.html from the data collected by
the AWS/Azure/GCP collectors. No external services are called here --
this just renders whatever JSON it's handed (or reads data/*.json if run
standalone).
"""
import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(HERE, "assets", "akashx-logo.png")

CLOUD_META = {
    "aws":   {"label": "AWS",   "accent": "#F0A202"},
    "azure": {"label": "Azure", "accent": "#4C8DFF"},
    "gcp":   {"label": "GCP",   "accent": "#34D399"},
}

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Cloud Fleet &amp; Spend</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500&display=swap');

  :root {
    --bg:        #14161A;
    --panel:     #1C1F26;
    --panel-2:   #21252E;
    --line:      #2A2E38;
    --text:      #E8EAED;
    --muted:     #8B92A3;
    --signature: #5EEAD4;
    --aws:       #F0A202;
    --azure:     #4C8DFF;
    --gcp:       #34D399;
    --radius:    10px;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  .display   { font-family: 'Space Grotesk', system-ui, sans-serif; }
  .mono      { font-family: 'IBM Plex Mono', 'SFMono-Regular', monospace; }

  .wrap { max-width: 1240px; margin: 0 auto; padding: 40px 28px 80px; }

  .eyebrow {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    letter-spacing: 0.16em;
    color: var(--muted);
    text-transform: uppercase;
    margin: 0 0 10px;
  }

  header.hero {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 32px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--line);
    padding-bottom: 28px;
    margin-bottom: 36px;
  }

  .hero-left {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .brand-logo {
    height: 52px;
    width: auto;
    display: block;
  }

  h1.display {
    font-size: 34px;
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.01em;
  }

  .total-figure {
    text-align: right;
  }
  .total-figure .amount {
    font-size: 40px;
    font-weight: 700;
    color: var(--signature);
  }
  .total-figure .label {
    font-size: 12px;
    color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
  }

  /* Signature element: the stacked spend meter -- segment width == share of
     total combined spend, so the bar itself is a live proportional readout,
     not decoration. */
  .spend-meter {
    display: flex;
    height: 14px;
    border-radius: 999px;
    overflow: hidden;
    background: var(--panel-2);
    margin-top: 18px;
    border: 1px solid var(--line);
  }
  .spend-meter .segment { height: 100%; }
  .spend-meter-legend {
    display: flex;
    gap: 22px;
    margin-top: 10px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    flex-wrap: wrap;
  }
  .spend-meter-legend .dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 6px;
  }

  .clouds-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 22px;
  }

  .clouds-stack {
    display: flex;
    flex-direction: column;
    gap: 22px;
  }

  .filter-bar {
    display: flex;
    gap: 10px;
    margin: 14px 0 18px;
    flex-wrap: wrap;
  }
  .filter-bar input[type="text"] {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 6px;
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12.5px;
    padding: 7px 10px;
    flex: 1;
    min-width: 160px;
  }
  .filter-bar input[type="text"]::placeholder { color: var(--muted); }
  .filter-bar select {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 6px;
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12.5px;
    padding: 7px 10px;
  }

  .action-btn {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px;
    padding: 3px 9px;
    border-radius: 5px;
    border: 1px solid var(--line);
    background: var(--panel-2);
    color: var(--text);
    cursor: pointer;
    white-space: nowrap;
  }
  .action-btn:hover { border-color: var(--signature); color: var(--signature); }
  .action-btn.copied { border-color: var(--signature); color: var(--signature); }
  .ip-cell { color: var(--muted); font-size: 11.5px; }
  .no-rows-note { color: var(--muted); font-size: 13px; padding: 14px 0; }

  .cloud-panel {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 22px;
  }

  .cloud-panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }
  .cloud-name {
    font-size: 18px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .cloud-name .swatch {
    width: 10px; height: 10px; border-radius: 3px;
  }
  .cloud-total {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 15px;
    color: var(--muted);
  }

  .stat-row {
    display: flex;
    gap: 18px;
    margin: 14px 0 18px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
  }
  .stat-row b { color: var(--text); font-size: 14px; }

  .section-label {
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 18px 0 8px;
  }

  .cost-bar-row {
    display: grid;
    grid-template-columns: 90px 1fr 60px;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    margin-bottom: 6px;
  }
  .cost-bar-row .svc {
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cost-bar-track {
    background: var(--panel-2);
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
  }
  .cost-bar-fill { height: 100%; border-radius: 4px; }
  .cost-bar-row .amt {
    font-family: 'IBM Plex Mono', monospace;
    text-align: right;
    color: var(--text);
  }

  table.instances {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
    margin-top: 4px;
  }
  table.instances th {
    text-align: left;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 400;
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid var(--line);
    padding: 6px 8px 6px 0;
  }
  table.instances td {
    padding: 7px 8px 7px 0;
    border-bottom: 1px solid var(--line);
    font-family: 'IBM Plex Mono', monospace;
  }
  table.instances tr:last-child td { border-bottom: none; }

  .state-pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10.5px;
    font-family: 'IBM Plex Mono', monospace;
  }
  .state-running { background: rgba(52,211,153,0.15); color: #34D399; }
  .state-stopped { background: rgba(139,146,163,0.15); color: var(--muted); }
  .state-other   { background: rgba(240,162,2,0.15); color: var(--aws); }

  .empty-note {
    color: var(--muted);
    font-size: 13px;
    padding: 18px 0;
  }

  .scroll-table { max-height: 460px; overflow-y: auto; overflow-x: auto; }
  table.instances { min-width: 900px; }

  .account-row {
    display: grid;
    grid-template-columns: 1fr 70px 90px;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    padding: 5px 0;
    border-bottom: 1px solid var(--line);
  }
  .account-row:last-child { border-bottom: none; }
  .account-row .acct-name { color: var(--text); }
  .account-row .acct-count { color: var(--muted); font-family: 'IBM Plex Mono', monospace; }
  .account-row .acct-cost { font-family: 'IBM Plex Mono', monospace; text-align: right; }

  .tab-bar {
    display: flex;
    gap: 4px;
    margin-bottom: 28px;
    border-bottom: 1px solid var(--line);
  }
  .tab-btn {
    appearance: none;
    background: none;
    border: none;
    color: var(--muted);
    font-family: 'Space Grotesk', system-ui, sans-serif;
    font-weight: 500;
    font-size: 14px;
    padding: 10px 18px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transform: translateY(1px);
  }
  .tab-btn:hover { color: var(--text); }
  .tab-btn.active {
    color: var(--text);
    border-bottom-color: var(--signature);
  }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  table.resource-cost {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
  }
  table.resource-cost th {
    text-align: left;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 400;
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid var(--line);
    padding: 8px 10px 8px 0;
    position: sticky;
    top: 0;
    background: var(--panel);
  }
  table.resource-cost td {
    padding: 8px 10px 8px 0;
    border-bottom: 1px solid var(--line);
    font-family: 'IBM Plex Mono', monospace;
  }
  table.resource-cost td.cost-cell { text-align: right; color: var(--text); }
  table.resource-cost td.cost-cell.no-data { color: var(--muted); }
  table.resource-cost tr:last-child td { border-bottom: none; }
  .cloud-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .cloud-tag .swatch { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }

  .resource-cost-wrap {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 22px;
  }
  .resource-cost-scroll { max-height: 620px; overflow-y: auto; }
  .coverage-note {
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 14px;
    font-family: 'IBM Plex Mono', monospace;
  }

  .overview-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin-bottom: 28px;
  }
  .overview-card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 16px 18px;
  }
  .overview-card .oc-label {
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }
  .overview-card .oc-amount {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 22px;
    font-weight: 500;
  }
  .overview-card.grand .oc-amount { color: var(--signature); font-size: 26px; }

  .daily-cost-wrap {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 22px;
    margin-bottom: 22px;
  }
  table.daily-cost {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
  }
  table.daily-cost th {
    text-align: right;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 400;
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid var(--line);
    padding: 8px 10px;
    position: sticky;
    top: 0;
    background: var(--panel);
  }
  table.daily-cost th:first-child, table.daily-cost td:first-child { text-align: left; }
  table.daily-cost td {
    padding: 7px 10px;
    border-bottom: 1px solid var(--line);
    font-family: 'IBM Plex Mono', monospace;
    text-align: right;
  }
  table.daily-cost td.total-cell { color: var(--signature); font-weight: 500; }
  table.daily-cost tr:last-child td { border-bottom: none; }
  .daily-cost-scroll { max-height: 360px; overflow-y: auto; }

  .suggestions-wrap {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 22px;
    margin-bottom: 28px;
  }
  .suggestion-row {
    display: grid;
    grid-template-columns: 74px 1fr;
    gap: 14px;
    padding: 12px 0;
    border-bottom: 1px solid var(--line);
    font-size: 13px;
  }
  .suggestion-row:last-child { border-bottom: none; }
  .sug-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 999px;
    height: fit-content;
    text-align: center;
  }
  .sug-high { background: rgba(240,162,2,0.15); color: var(--aws); }
  .sug-medium { background: rgba(76,141,255,0.15); color: var(--azure); }
  .sug-info { background: rgba(139,146,163,0.15); color: var(--muted); }
  .sug-text b { color: var(--text); }

  footer {
    margin-top: 40px;
    color: var(--muted);
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    text-align: center;
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-left">
      <img class="brand-logo" src="data:image/png;base64,__LOGO_B64__" alt="AkashX">
      <div>
        <p class="eyebrow">MULTI-CLOUD OPERATIONS</p>
        <h1 class="display">Cloud Fleet &amp; Spend</h1>
      </div>
    </div>
    <div class="total-figure">
      <div class="amount mono" id="totalAmount">$0</div>
      <div class="label">COMBINED SPEND &middot; <span id="periodLabel"></span></div>
    </div>
  </header>

  <div id="spendMeterWrap">
    <div class="spend-meter" id="spendMeter"></div>
    <div class="spend-meter-legend" id="spendMeterLegend"></div>
  </div>

  <div class="tab-bar" style="margin-top:32px;">
    <button class="tab-btn active" data-tab="cost">Cost</button>
    <button class="tab-btn" data-tab="infra">Infrastructure</button>
    <button class="tab-btn" data-tab="resource">Resource Cost</button>
  </div>

  <div class="tab-panel active" id="tab-cost">
    <div class="overview-strip" id="overviewStrip"></div>

    <div class="daily-cost-wrap">
      <div class="section-label" style="margin-top:0">Daily spend (all clouds)</div>
      <div class="daily-cost-scroll">
        <table class="daily-cost">
          <thead><tr id="dailyCostHead"></tr></thead>
          <tbody id="dailyCostBody"></tbody>
        </table>
      </div>
    </div>

    <div class="suggestions-wrap">
      <div class="section-label" style="margin-top:0">Suggestions to reduce cost</div>
      <div id="suggestionsList"></div>
    </div>

    <div class="clouds-grid" id="costGrid"></div>
  </div>

  <div class="tab-panel" id="tab-infra">
    <div class="clouds-stack" id="infraGrid"></div>
  </div>

  <div class="tab-panel" id="tab-resource">
    <div class="resource-cost-wrap">
      <div class="coverage-note" id="resourceCoverageNote"></div>
      <div class="resource-cost-scroll">
        <table class="resource-cost">
          <thead><tr>
            <th>Resource</th><th>Cloud</th><th>Account</th><th>Type</th><th>Location</th><th>State</th><th style="text-align:right">Cost</th>
          </tr></thead>
          <tbody id="resourceCostBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <footer>GENERATED LOCALLY &middot; DATA FROM YOUR OWN CLOUD CREDENTIALS &middot; NO EXTERNAL TRANSMISSION</footer>
</div>

<script>
const DATA = __DATA_JSON__;
const META = __META_JSON__;

function fmtMoney(n) {
  if (n === null || n === undefined) return '—';
  return '$' + n.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function stateClass(state) {
  const s = (state || '').toLowerCase();
  if (s.includes('running') || s === 'vm running') return 'state-running';
  if (s.includes('stop') || s.includes('deallocat') || s.includes('terminated')) return 'state-stopped';
  return 'state-other';
}

function fmtDuration(sinceIso) {
  if (!sinceIso) return '—';
  const since = new Date(sinceIso);
  if (isNaN(since.getTime())) return '—';
  let ms = Date.now() - since.getTime();
  if (ms < 0) ms = 0;
  const mins = Math.floor(ms / 60000);
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  const minutes = mins % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function fmtSince(sinceIso) {
  if (!sinceIso) return '—';
  const d = new Date(sinceIso);
  if (isNaN(d.getTime())) return '—';
  return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
}

function aggregateCloud(providerData) {
  const accounts = (providerData && providerData.accounts) || [];
  let total = 0;
  const serviceTotals = {};
  const dayTotals = {};
  const instances = [];
  const accountSummaries = [];

  accounts.forEach(acct => {
    const acctCost = (acct.cost && acct.cost.total) || 0;
    total += acctCost;
    accountSummaries.push({
      account: acct.account,
      total: acctCost,
      instanceCount: (acct.instances || []).length,
    });
    if (acct.cost && acct.cost.by_service) {
      acct.cost.by_service.forEach(s => {
        serviceTotals[s.service] = (serviceTotals[s.service] || 0) + s.cost;
      });
    }
    if (acct.cost && acct.cost.by_day) {
      acct.cost.by_day.forEach(d => {
        dayTotals[d.date] = (dayTotals[d.date] || 0) + d.cost;
      });
    }
    (acct.instances || []).forEach(i => {
      instances.push(Object.assign({}, i, { account: i.account || acct.account }));
    });
  });

  const by_service = Object.entries(serviceTotals)
    .map(([service, cost]) => ({ service, cost }))
    .sort((a, b) => b.cost - a.cost);

  const by_day = Object.entries(dayTotals)
    .map(([date, cost]) => ({ date, cost: Math.round(cost * 100) / 100 }))
    .sort((a, b) => a.date.localeCompare(b.date));

  let periodStr = '';
  for (const acct of accounts) {
    if (acct.cost && acct.cost.period_start) {
      periodStr = acct.cost.period_start + ' \u2192 ' + acct.cost.period_end;
      break;
    }
  }

  return { total, by_service, by_day, instances, accountSummaries, periodStr };
}

function buildSpendMeter() {
  const totals = Object.entries(DATA).map(([key, d]) => ({
    key, total: aggregateCloud(d).total
  }));
  const grand = totals.reduce((s, t) => s + t.total, 0);
  document.getElementById('totalAmount').textContent = fmtMoney(grand);

  let periodStr = '';
  for (const [key, d] of Object.entries(DATA)) {
    const p = aggregateCloud(d).periodStr;
    if (p) { periodStr = p; break; }
  }
  document.getElementById('periodLabel').textContent = periodStr || 'no cost data available';

  const meter = document.getElementById('spendMeter');
  const legend = document.getElementById('spendMeterLegend');
  meter.innerHTML = '';
  legend.innerHTML = '';

  if (grand === 0) {
    meter.style.display = 'none';
    legend.innerHTML = '<span>No cost data collected yet -- see README for enabling billing export per provider.</span>';
    return;
  }

  totals.forEach(t => {
    if (t.total <= 0) return;
    const pct = (t.total / grand) * 100;
    const seg = document.createElement('div');
    seg.className = 'segment';
    seg.style.width = pct + '%';
    seg.style.background = META[t.key].accent;
    meter.appendChild(seg);

    const item = document.createElement('span');
    item.innerHTML = `<span class="dot" style="background:${META[t.key].accent}"></span>${META[t.key].label}: ${fmtMoney(t.total)} (${pct.toFixed(1)}%)`;
    legend.appendChild(item);
  });
}

function buildCostPanel(key, d) {
  const meta = META[key];
  const panel = document.createElement('div');
  panel.className = 'cloud-panel';

  const agg = aggregateCloud(d);
  const accountErrors = ((d && d.accounts) || []).filter(a => a.error);

  let html = `
    <div class="cloud-panel-head">
      <div class="cloud-name"><span class="swatch" style="background:${meta.accent}"></span>${meta.label}</div>
      <div class="cloud-total">${fmtMoney(agg.total)}</div>
    </div>
    <div class="stat-row">
      <div><b>${agg.accountSummaries.length}</b> account(s)</div>
      <div><b>${agg.instances.length}</b> instances</div>
    </div>
  `;

  if (d && d.error) {
    html += `<div class="empty-note">Collection error: ${d.error}</div>`;
  }
  accountErrors.forEach(a => {
    html += `<div class="empty-note">Collection error (${a.account}): ${a.error}</div>`;
  });

  if (agg.accountSummaries.length > 1) {
    html += `<div class="section-label">By account</div>`;
    agg.accountSummaries
      .sort((a, b) => b.total - a.total)
      .forEach(a => {
        html += `
          <div class="account-row">
            <div class="acct-name">${a.account}</div>
            <div class="acct-count">${a.instanceCount} inst.</div>
            <div class="acct-cost">${fmtMoney(a.total)}</div>
          </div>`;
      });
  }

  html += `<div class="section-label">Spend by service</div>`;
  if (agg.by_service.length) {
    const maxCost = Math.max(...agg.by_service.map(s => s.cost));
    agg.by_service.slice(0, 10).forEach(s => {
      const pct = maxCost > 0 ? (s.cost / maxCost) * 100 : 0;
      html += `
        <div class="cost-bar-row">
          <div class="svc" title="${s.service}">${s.service}</div>
          <div class="cost-bar-track"><div class="cost-bar-fill" style="width:${pct}%;background:${meta.accent}"></div></div>
          <div class="amt">${fmtMoney(s.cost)}</div>
        </div>`;
    });
  } else {
    html += `<div class="empty-note">No cost data (billing export not enabled, or provider disabled).</div>`;
  }

  panel.innerHTML = html;
  return panel;
}

function cliCommandFor(cloud, instance, action) {
  // action is 'start' or 'stop'. These are copy-to-clipboard commands the
  // person runs themselves with their own authenticated CLI session --
  // this static dashboard never holds live cloud credentials, so it can't
  // (and shouldn't) call these APIs directly from the browser.
  if (cloud === 'aws') {
    const verb = action === 'start' ? 'start-instances' : 'stop-instances';
    const region = instance.region ? ` --region ${instance.region}` : '';
    return `aws ec2 ${verb} --instance-ids ${instance.id}${region}`;
  }
  if (cloud === 'azure') {
    const verb = action === 'start' ? 'start' : 'deallocate';
    return `az vm ${verb} --ids "${instance.id}"`;
  }
  if (cloud === 'gcp') {
    const verb = action === 'start' ? 'start' : 'stop';
    const project = instance.project_id ? ` --project=${instance.project_id}` : '';
    const zone = instance.zone ? ` --zone=${instance.zone}` : '';
    return `gcloud compute instances ${verb} ${instance.name}${zone}${project}`;
  }
  return '';
}

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const original = btn.textContent;
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = original; btn.classList.remove('copied'); }, 1500);
  }).catch(() => {
    alert(text); // fallback if clipboard API is blocked
  });
}
window.__copyToClipboard = copyToClipboard;

function buildInfraPanel(key, d) {
  const meta = META[key];
  const panel = document.createElement('div');
  panel.className = 'cloud-panel';

  const agg = aggregateCloud(d);
  const instances = agg.instances;
  const running = instances.filter(i => (i.state || '').toLowerCase().includes('run')).length;
  const total = instances.length;
  const uid = 'infra_' + key;

  let html = `
    <div class="cloud-panel-head">
      <div class="cloud-name"><span class="swatch" style="background:${meta.accent}"></span>${meta.label}</div>
      <div class="cloud-total">${total} instances</div>
    </div>
    <div class="stat-row">
      <div><b>${running}</b> running</div>
      <div><b>${total - running}</b> stopped/other</div>
      <div><b>${agg.accountSummaries.length}</b> account(s)</div>
    </div>
  `;

  html += `<div class="section-label">Instances</div>`;

  if (instances.length) {
    const states = Array.from(new Set(instances.map(i => i.state || 'unknown'))).sort();
    html += `
      <div class="filter-bar">
        <input type="text" id="${uid}_search" placeholder="Filter by name, owner, account, IP...">
        <select id="${uid}_state">
          <option value="">All states</option>
          ${states.map(s => `<option value="${s}">${s}</option>`).join('')}
        </select>
      </div>
    `;

    html += `<div class="scroll-table"><table class="instances" id="${uid}_table"><thead><tr>
        <th>Name</th><th>Owner</th><th>Account</th><th>Type</th><th>Location</th>
        <th>Internal IP</th><th>External IP</th><th>State</th><th>Since</th><th>Duration</th><th>Action</th>
      </tr></thead><tbody>`;
    instances.forEach((i, idx) => {
      const name = i.name || i.id || '—';
      const type = i.type || '—';
      const location = i.region || i.zone || i.resource_group || '—';
      const isRunning = (i.state || '').toLowerCase().includes('run');
      const action = isRunning ? 'stop' : 'start';
      const cmd = cliCommandFor(key, i, action).replace(/"/g, '&quot;');
      const searchBlob = [name, i.owner, i.account, i.internal_ip, i.external_ip, type, location]
        .filter(Boolean).join(' ').toLowerCase();
      html += `<tr data-state="${i.state || 'unknown'}" data-search="${searchBlob}">
          <td>${name}</td>
          <td>${i.owner || '—'}</td>
          <td>${i.account || '—'}</td>
          <td>${type}</td>
          <td>${location}</td>
          <td class="ip-cell">${i.internal_ip || '—'}</td>
          <td class="ip-cell">${i.external_ip || '—'}</td>
          <td><span class="state-pill ${stateClass(i.state)}">${i.state || 'unknown'}</span></td>
          <td>${fmtSince(i.state_since)}</td>
          <td>${fmtDuration(i.state_since)}</td>
          <td><button class="action-btn" title="Copy ${action} command" data-cmd="${cmd}">${action === 'start' ? '▶ start' : '■ stop'}</button></td>
        </tr>`;
    });
    html += `</tbody></table></div>`;
    html += `<div class="no-rows-note" id="${uid}_empty" style="display:none">No instances match this filter.</div>`;
  } else {
    html += `<div class="empty-note">No instances found (or provider disabled/not scanned).</div>`;
  }

  panel.innerHTML = html;

  if (instances.length) {
    const searchInput = panel.querySelector(`#${uid}_search`);
    const stateSelect = panel.querySelector(`#${uid}_state`);
    const rows = panel.querySelectorAll(`#${uid}_table tbody tr`);
    const emptyNote = panel.querySelector(`#${uid}_empty`);

    function applyFilter() {
      const q = searchInput.value.trim().toLowerCase();
      const s = stateSelect.value;
      let visible = 0;
      rows.forEach(row => {
        const matchesSearch = !q || row.dataset.search.includes(q);
        const matchesState = !s || row.dataset.state === s;
        const show = matchesSearch && matchesState;
        row.style.display = show ? '' : 'none';
        if (show) visible++;
      });
      emptyNote.style.display = visible === 0 ? 'block' : 'none';
    }

    searchInput.addEventListener('input', applyFilter);
    stateSelect.addEventListener('change', applyFilter);

    panel.querySelectorAll('.action-btn').forEach(btn => {
      btn.addEventListener('click', () => copyToClipboard(btn.dataset.cmd, btn));
    });
  }

  return panel;
}

function buildResourceCostTable() {
  const rows = [];
  Object.entries(DATA).forEach(([key, d]) => {
    const agg = aggregateCloud(d);
    agg.instances.forEach(i => rows.push({ cloud: key, ...i }));
  });

  const withCost = rows.filter(r => typeof r.cost === 'number');
  const withoutCost = rows.filter(r => typeof r.cost !== 'number');
  withCost.sort((a, b) => b.cost - a.cost);

  const note = document.getElementById('resourceCoverageNote');
  if (rows.length === 0) {
    note.textContent = 'No instances collected yet.';
  } else if (withCost.length === 0) {
    note.textContent = `0 of ${rows.length} resources have per-resource cost data. `
      + `Per-resource cost needs extra setup per provider (AWS resource-level Cost Explorer data, `
      + `Azure Cost Management by ResourceId, GCP BigQuery billing export) -- see README.`;
  } else {
    note.textContent = `${withCost.length} of ${rows.length} resources have per-resource cost data `
      + `(${((withCost.length / rows.length) * 100).toFixed(0)}% coverage).`;
  }

  const body = document.getElementById('resourceCostBody');
  body.innerHTML = '';
  [...withCost, ...withoutCost].forEach(r => {
    const meta = META[r.cloud];
    const name = r.name || r.id || '—';
    const location = r.region || r.zone || r.resource_group || '—';
    const costCell = typeof r.cost === 'number'
      ? `<td class="cost-cell">${fmtMoney(r.cost)}</td>`
      : `<td class="cost-cell no-data">—</td>`;
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${name}</td>
      <td><span class="cloud-tag"><span class="swatch" style="background:${meta.accent}"></span>${meta.label}</span></td>
      <td>${r.account || '—'}</td>
      <td>${r.type || '—'}</td>
      <td>${location}</td>
      <td><span class="state-pill ${stateClass(r.state)}">${r.state || 'unknown'}</span></td>
      ${costCell}
    `;
    body.appendChild(row);
  });
}

function buildOverviewStrip() {
  const strip = document.getElementById('overviewStrip');
  strip.innerHTML = '';

  const clouds = ['aws', 'azure', 'gcp'].filter(k => DATA[k]);
  const grand = clouds.reduce((s, k) => s + aggregateCloud(DATA[k]).total, 0);

  const grandCard = document.createElement('div');
  grandCard.className = 'overview-card grand';
  grandCard.innerHTML = `<div class="oc-label">Overall cost (all clouds)</div><div class="oc-amount">${fmtMoney(grand)}</div>`;
  strip.appendChild(grandCard);

  clouds.forEach(k => {
    const agg = aggregateCloud(DATA[k]);
    const meta = META[k];
    const card = document.createElement('div');
    card.className = 'overview-card';
    card.innerHTML = `<div class="oc-label"><span class="dot" style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${meta.accent}"></span>${meta.label} (period)</div><div class="oc-amount">${fmtMoney(agg.total)}</div>`;
    strip.appendChild(card);
  });
}

function buildDailyCostTable() {
  const clouds = ['aws', 'azure', 'gcp'].filter(k => DATA[k]);
  const perCloudDays = {};
  const allDates = new Set();

  clouds.forEach(k => {
    const agg = aggregateCloud(DATA[k]);
    const map = {};
    agg.by_day.forEach(d => { map[d.date] = d.cost; allDates.add(d.date); });
    perCloudDays[k] = map;
  });

  const dates = Array.from(allDates).sort().reverse(); // most recent first

  const head = document.getElementById('dailyCostHead');
  const body = document.getElementById('dailyCostBody');

  if (dates.length === 0) {
    head.innerHTML = '<th>Date</th>';
    body.innerHTML = `<tr><td colspan="1" style="text-align:left;color:var(--muted)">No daily cost data available yet -- see README for enabling billing export per provider.</td></tr>`;
    return;
  }

  head.innerHTML = '<th>Date</th>' + clouds.map(k => `<th>${META[k].label}</th>`).join('') + '<th>Total</th>';

  body.innerHTML = '';
  dates.forEach(date => {
    let rowTotal = 0;
    const cells = clouds.map(k => {
      const v = perCloudDays[k][date];
      if (typeof v === 'number') { rowTotal += v; return `<td>${fmtMoney(v)}</td>`; }
      return `<td style="color:var(--muted)">—</td>`;
    }).join('');
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${date}</td>${cells}<td class="total-cell">${fmtMoney(rowTotal)}</td>`;
    body.appendChild(tr);
  });
}

function getLookbackDays() {
  for (const key of ['aws', 'azure', 'gcp']) {
    const d = DATA[key];
    if (!d || !d.accounts) continue;
    for (const acct of d.accounts) {
      if (acct.cost && acct.cost.period_start && acct.cost.period_end) {
        const days = (new Date(acct.cost.period_end) - new Date(acct.cost.period_start)) / (24 * 60 * 60 * 1000);
        if (days > 0) return days;
      }
    }
  }
  return 30;
}

function monthlyEstimate(periodCost, lookbackDays) {
  return (periodCost / lookbackDays) * 30;
}

function buildSuggestions() {
  const list = document.getElementById('suggestionsList');
  const suggestions = [];
  const clouds = ['aws', 'azure', 'gcp'].filter(k => DATA[k]);
  const lookbackDays = getLookbackDays();

  let allInstances = [];
  clouds.forEach(k => {
    aggregateCloud(DATA[k]).instances.forEach(i => allInstances.push({ cloud: k, ...i }));
  });

  const DAY_MS = 24 * 60 * 60 * 1000;
  const nonProdPattern = /dev|test|staging|stage|sandbox|qa|demo/i;

  function resourceList(instances, limit) {
    return instances.slice(0, limit || 5).map(i => {
      const label = `${i.name || i.id} (${META[i.cloud].label}${i.account ? ', ' + i.account : ''})`;
      return typeof i.cost === 'number'
        ? `${label} &mdash; ${fmtMoney(monthlyEstimate(i.cost, lookbackDays))}/mo est.`
        : label;
    }).join('<br>');
  }

  // 1. Long-running non-prod instances -- the single most common source of
  //    avoidable spend: dev/test boxes left running around the clock.
  const longRunningNonProd = allInstances.filter(i => {
    if (!(i.state || '').toLowerCase().includes('run')) return false;
    if (!i.state_since) return false;
    const isNonProd = nonProdPattern.test(i.account || '') || nonProdPattern.test(i.name || '');
    if (!isNonProd) return false;
    const ms = Date.now() - new Date(i.state_since).getTime();
    return ms > 3 * DAY_MS;
  });
  if (longRunningNonProd.length > 0) {
    const withCost = longRunningNonProd.filter(i => typeof i.cost === 'number');
    const estTotal = withCost.reduce((s, i) => s + monthlyEstimate(i.cost, lookbackDays), 0);
    const savingsLine = withCost.length > 0
      ? ` Stopping or scheduling these off nights/weekends could save roughly ${fmtMoney(estTotal)}/mo.`
      : ` Enable per-resource cost to see an estimated savings figure for these.`;
    suggestions.push({
      level: 'high',
      text: `<b>Action: schedule or stop these ${longRunningNonProd.length} dev/test/staging instance(s)</b> `
        + `-- running continuously for 3+ days:<br>${resourceList(longRunningNonProd)}${savingsLine}`
    });
  }

  // 2. Stopped instances that still have per-resource cost attached --
  //    usually means attached storage/EIPs/disks are still billing even
  //    though the compute itself is off.
  const stoppedWithCost = allInstances.filter(i =>
    (i.state || '').toLowerCase().includes('stop') && typeof i.cost === 'number' && i.cost > 0
  );
  if (stoppedWithCost.length > 0) {
    const total = stoppedWithCost.reduce((s, i) => s + i.cost, 0);
    suggestions.push({
      level: 'high',
      text: `<b>Action: review or delete leftover storage/IPs on these ${stoppedWithCost.length} stopped instance(s)</b> `
        + `-- still generating ${fmtMoney(total)} this period even though compute is off:<br>${resourceList(stoppedWithCost)}`
    });
  }

  // 3. Any single service dominating a cloud's spend -- flag for
  //    reserved-instance / savings-plan / committed-use review.
  clouds.forEach(k => {
    const agg = aggregateCloud(DATA[k]);
    if (agg.total <= 0 || agg.by_service.length === 0) return;
    const top = agg.by_service[0];
    const share = top.cost / agg.total;
    if (share > 0.5) {
      const label = k === 'aws' ? 'Reserved Instances or a Savings Plan'
        : k === 'azure' ? 'Reserved VM Instances or an Azure Savings Plan'
        : 'Committed Use Discounts';
      suggestions.push({
        level: 'medium',
        text: `<b>Action: evaluate ${label} on ${META[k].label}</b> -- <b>${top.service}</b> alone accounts for `
          + `${(share * 100).toFixed(0)}% of that cloud's spend (${fmtMoney(top.cost)}). If usage is steady, `
          + `committing to a discount plan could meaningfully cut this.`
      });
    }
  });

  // 4. Long-running instances in general (any environment) past 30 days --
  //    worth a right-sizing look since we can't see CPU/memory utilization
  //    from inventory + billing data alone.
  const veryLongRunning = allInstances.filter(i => {
    if (!(i.state || '').toLowerCase().includes('run') || !i.state_since) return false;
    const ms = Date.now() - new Date(i.state_since).getTime();
    return ms > 30 * DAY_MS;
  });
  if (veryLongRunning.length > 0) {
    suggestions.push({
      level: 'medium',
      text: `<b>Action: check actual utilization on these ${veryLongRunning.length} instance(s)</b> `
        + `-- running for 30+ days straight:<br>${resourceList(veryLongRunning)}<br>`
        + `This dashboard has no CPU/memory data, so check the provider console to see if a smaller instance type would do.`
    });
  }

  // 5. Coverage gap -- encourage enabling per-resource cost so future
  //    suggestions (and the Resource Cost tab) get sharper.
  const withCost = allInstances.filter(i => typeof i.cost === 'number').length;
  if (allInstances.length > 0 && withCost < allInstances.length) {
    const pct = ((withCost / allInstances.length) * 100).toFixed(0);
    suggestions.push({
      level: 'info',
      text: `Only ${pct}% of instances have per-resource cost data. Enabling it (see README) would let these `
        + `suggestions point at specific expensive resources instead of just services.`
    });
  }

  // 6. Name the single most expensive individual resources, when we have
  //    per-resource cost -- a concrete "look at these first" list rather
  //    than just aggregate percentages.
  const rankedByCost = allInstances
    .filter(i => typeof i.cost === 'number' && i.cost > 0)
    .sort((a, b) => b.cost - a.cost)
    .slice(0, 5);
  if (rankedByCost.length > 0) {
    suggestions.push({
      level: 'high',
      text: `<b>Action: review these highest-cost resources first</b>:<br>${resourceList(rankedByCost)}`
    });
  }

  // 7. Resources with no Owner tag/label -- not a cost issue directly, but
  //    untagged resources are the ones most likely to be forgotten and
  //    left running indefinitely, and the hardest to chase down later.
  const untagged = allInstances.filter(i => !i.owner);
  if (untagged.length > 0 && allInstances.length > 0) {
    const pct = ((untagged.length / allInstances.length) * 100).toFixed(0);
    const sortedUntagged = [...untagged].sort((a, b) => (b.cost || 0) - (a.cost || 0));
    suggestions.push({
      level: 'medium',
      text: `<b>Action: add an Owner tag to these resources</b> -- ${untagged.length} of ${allInstances.length} `
        + `instances (${pct}%) have none, making them the ones most likely to be forgotten and left running:<br>${resourceList(sortedUntagged)}`
    });
  }

  // 8. Old-generation instance families -- newer generations are almost
  //    always better price-for-performance on all three clouds. This is a
  //    pattern match on type name, not a performance benchmark.
  const OLD_GEN_PATTERNS = {
    aws: /^(t2|m4|m3|c4|c3|r4|r3|i2|d2)\./i,
    azure: /^(standard_a|standard_d[0-9]+(_v1)?$|standard_d[0-9]+_v2|standard_g)/i,
    gcp: /^n1-/i,
  };
  const oldGen = allInstances.filter(i => {
    const pattern = OLD_GEN_PATTERNS[i.cloud];
    return pattern && i.type && pattern.test(i.type);
  });
  if (oldGen.length > 0) {
    suggestions.push({
      level: 'medium',
      text: `<b>Action: migrate these ${oldGen.length} instance(s) to a newer generation</b> `
        + `(older families are almost always cheaper-and-faster to replace in the same size class):<br>${resourceList(oldGen)}`
    });
  }

  // 9. Large instance types sitting in non-prod-looking accounts/names --
  //    a mismatch worth a second look, though this is a naming heuristic,
  //    not a utilization measurement.
  const oversizedNonProd = allInstances.filter(i => {
    const isNonProd = nonProdPattern.test(i.account || '') || nonProdPattern.test(i.name || '');
    if (!isNonProd || !i.type) return false;
    return /(4|8|16|24|32|48|64|96)xlarge/i.test(i.type) || /_v[3-9]\b.*[0-9]{2,}/i.test(i.type);
  });
  if (oversizedNonProd.length > 0) {
    suggestions.push({
      level: 'medium',
      text: `<b>Action: confirm these ${oversizedNonProd.length} large instance(s) actually need that size</b> `
        + `-- sitting in accounts/names that look like dev/test/staging:<br>${resourceList(oversizedNonProd)}`
    });
  }

  // 10. A high proportion of stopped instances overall -- even without
  //     per-resource cost, a large stopped fleet is worth a cleanup pass
  //     (attached disks/IPs/snapshots often keep billing after stop).
  const stoppedInstances = allInstances.filter(i => (i.state || '').toLowerCase().includes('stop') || (i.state || '').toLowerCase().includes('deallocat'));
  const stoppedCount = stoppedInstances.length;
  if (allInstances.length >= 5 && stoppedCount / allInstances.length > 0.5) {
    const pct = ((stoppedCount / allInstances.length) * 100).toFixed(0);
    const sortedStopped = [...stoppedInstances].sort((a, b) => (b.cost || 0) - (a.cost || 0));
    suggestions.push({
      level: 'medium',
      text: `<b>Action: run a cleanup pass on these stopped instances</b> -- ${stoppedCount} of ${allInstances.length} `
        + `(${pct}%) are currently stopped/deallocated, and attached disks/IPs/snapshots often keep billing regardless:`
        + `<br>${resourceList(sortedStopped, 8)}`
    });
  }

  // 11. One account/tenant dominating a cloud's spend when multiple
  //     accounts are configured -- useful for spotting where to focus
  //     cost-review effort first.
  clouds.forEach(k => {
    const agg = aggregateCloud(DATA[k]);
    if (agg.accountSummaries.length < 2 || agg.total <= 0) return;
    const sorted = [...agg.accountSummaries].sort((a, b) => b.total - a.total);
    const top = sorted[0];
    const share = top.total / agg.total;
    if (share > 0.6) {
      suggestions.push({
        level: 'info',
        text: `On <b>${META[k].label}</b>, account <b>${top.account}</b> accounts for ${(share * 100).toFixed(0)}% `
          + `of that cloud's total spend (${fmtMoney(top.total)} of ${fmtMoney(agg.total)}) across `
          + `${agg.accountSummaries.length} accounts -- the natural place to focus a closer cost review first.`
      });
    }
  });

  if (suggestions.length === 0) {
    list.innerHTML = `<div class="empty-note">No obvious savings opportunities found from the current inventory and cost data.</div>`;
    return;
  }

  list.innerHTML = '';
  suggestions.forEach(s => {
    const row = document.createElement('div');
    row.className = 'suggestion-row';
    row.innerHTML = `<span class="sug-badge sug-${s.level}">${s.level}</span><div class="sug-text">${s.text}</div>`;
    list.appendChild(row);
  });
}

function setupTabs() {
  const buttons = document.querySelectorAll('.tab-btn');
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
  });
}

function build() {
  buildSpendMeter();
  setupTabs();

  buildOverviewStrip();
  buildDailyCostTable();
  buildSuggestions();

  const costGrid = document.getElementById('costGrid');
  const infraGrid = document.getElementById('infraGrid');
  ['aws', 'azure', 'gcp'].forEach(key => {
    if (DATA[key]) {
      costGrid.appendChild(buildCostPanel(key, DATA[key]));
      infraGrid.appendChild(buildInfraPanel(key, DATA[key]));
    }
  });

  buildResourceCostTable();
}

build();
</script>
</body>
</html>
"""


def _logo_base64():
    try:
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""  # missing logo shouldn't break the whole dashboard build


def generate(results, output_path):
    """results: dict like {"aws": {...}, "azure": {...}, "gcp": {...}}
    (same shape written by each collector's collect())."""
    html = TEMPLATE.replace("__DATA_JSON__", json.dumps(results)) \
                    .replace("__META_JSON__", json.dumps(CLOUD_META)) \
                    .replace("__LOGO_B64__", _logo_base64())
    with open(output_path, "w") as f:
        f.write(html)
    return output_path


def _load_from_data_dir():
    data_dir = os.path.join(HERE, "data")
    results = {}
    for provider in ("aws", "azure", "gcp"):
        path = os.path.join(data_dir, f"{provider}.json")
        if os.path.exists(path):
            with open(path) as f:
                results[provider] = json.load(f)
    return results


if __name__ == "__main__":
    results = _load_from_data_dir()
    if not results:
        print("No data/*.json found -- run `python run_all.py` first "
              "(or run this after collectors have written their output).")
    else:
        out = generate(results, os.path.join(HERE, "dashboard.html"))
        print(f"Dashboard written to {out}")
