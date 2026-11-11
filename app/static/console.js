'use strict';

const TIER_LABEL = {
  tier1: 'Tier 1: automatic',
  tier2: 'Tier 2: human approval',
  blocked: 'Blocked',
};
const STATUS_LABEL = {
  paid: 'Paid (simulated)',
  awaiting_approval: 'Awaiting human approval',
  rejected: 'Rejected by the approver',
  blocked: 'Blocked',
  failed: 'Failed',
  ready_to_pay: 'Ready to pay',
};
const SCENARIO_COPY = {
  'FP-88213': {
    title: 'In-policy order',
    blurb: 'The supplier quotes the agreed price. Expect a Tier 1 payment with no person involved.',
  },
  'FP-88214': {
    title: 'Price drift',
    blurb: 'The supplier adds a surcharge after agreement. Expect Tier 2: a person must approve.',
  },
};

const state = { cfg: null, running: false, live: true, runId: null, lastSeq: 0 };
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function money(minor) {
  const currency = state.cfg ? state.cfg.currency : 'EUR';
  return new Intl.NumberFormat('en-IE', { style: 'currency', currency }).format(minor / 100);
}

function cap(text) {
  const s = String(text || '');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function shorten(text) {
  const s = String(text || '');
  return s.length > 12 ? s.slice(0, 10) + '…' : s;
}

function list(value) {
  return Array.isArray(value) ? value.map(String) : [];
}

function fact(dl, label, value) {
  dl.appendChild(el('dt', null, label));
  dl.appendChild(el('dd', null, value));
}

async function getJson(url) {
  const res = await fetch(url, { headers: { accept: 'application/json' } });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

function showBanner(text, tone) {
  const banner = $('banner');
  banner.className = 'banner tone-' + tone;
  banner.textContent = text;
  banner.hidden = false;
}

function hideBanner() {
  $('banner').hidden = true;
}

function refreshButtons() {
  for (const button of document.querySelectorAll('button[data-action]')) {
    button.disabled = state.running || !state.live;
  }
}

function setRunning(value) {
  state.running = value;
  refreshButtons();
}

function applyLiveState() {
  if (!state.live) {
    showBanner(
      'Corridor is paused to protect its spend cap. You can read this page, but runs are switched off until it resumes.',
      'warn'
    );
  }
  refreshButtons();
}

async function showHttpError(res) {
  let detail = 'The request failed (' + res.status + ').';
  try {
    const body = await res.json();
    if (typeof body.detail === 'string') detail = body.detail;
  } catch (err) {
    /* keep the generic message */
  }
  if (res.status === 503) {
    state.live = false;
    applyLiveState();
    return;
  }
  showBanner(detail, res.status === 429 ? 'warn' : 'stop');
}

function describe(e) {
  const d = e.data || {};
  switch (e.kind) {
    case 'run.started':
      return { title: 'Order received', tone: 'info', lines: ['Order ' + d.order_ref] };
    case 'negotiation.offer':
      return {
        title: 'Supplier quote received',
        tone: 'info',
        lines: [
          'Quoted total ' + money(d.claimed_total_minor),
          'Signed checkout ' + shorten(d.checkout_hash),
        ],
        note: d.note,
      };
    case 'interpreter.proposal':
      return {
        title: 'Supplier note reviewed',
        tone: d.action === 'accept' ? 'ok' : 'warn',
        lines: [(d.action === 'accept' ? 'Routine' : 'Flagged for a person') + ': ' + d.reason],
      };
    case 'gate.screening':
      return {
        title: 'Sanctions screening',
        tone: d.status === 'clear' ? 'ok' : d.status === 'review' ? 'warn' : 'stop',
        lines: [cap(d.status)].concat(list(d.reasons)),
      };
    case 'gate.mandate':
      return {
        title: d.fresh_mandate ? 'Mandate gate, fresh mandate' : 'Mandate Integrity Gate',
        tone: d.passed ? 'ok' : 'stop',
        lines: [d.passed ? 'Payment matches the signed mandate and checkout' : 'Rejected'].concat(
          list(d.reasons)
        ),
      };
    case 'tier.decision': {
      const lines = [];
      if (Number.isFinite(d.agreed_minor) && Number.isFinite(d.total_minor)) {
        let text = 'Agreed ' + money(d.agreed_minor) + ', quoted ' + money(d.total_minor);
        if (d.drift_bps > 0) text += ' (' + (d.drift_bps / 100).toFixed(2) + '% above)';
        lines.push(text);
      }
      return {
        title: 'Routing: ' + (TIER_LABEL[d.tier] || d.tier),
        tone: d.tier === 'tier1' ? 'ok' : d.tier === 'tier2' ? 'warn' : 'stop',
        lines: lines.concat(list(d.reasons)),
      };
    }
    case 'rail.selected':
      return {
        title: 'Rail selected',
        tone: d.rail ? 'ok' : 'stop',
        lines: [d.rail ? 'Rail ' + d.rail : 'No eligible rail'].concat(list(d.reasons)),
      };
    case 'approval.requested':
      return {
        title: 'Waiting for a person',
        tone: 'warn',
        lines: ['Amount ' + money(d.total_minor)].concat(list(d.reasons)),
      };
    case 'approval.granted':
      return {
        title: 'Approved by a person',
        tone: 'ok',
        lines: [
          'A fresh mandate capped at ' + money(d.total_minor) + ' is signed and checked again',
        ],
      };
    case 'payment.executed':
      return {
        title: 'Payment executed (simulated)',
        tone: 'ok',
        lines: [
          'Reference ' + d.reference,
          money(d.amount_minor) + ' via ' + d.rail + (d.duplicate ? ' (repeat, nothing spent again)' : ''),
        ],
      };
    case 'run.completed':
      return {
        title: 'Run completed',
        tone: d.status === 'paid' ? 'ok' : d.status === 'awaiting_approval' ? 'warn' : 'stop',
        lines: [STATUS_LABEL[d.status] || String(d.status)],
      };
    case 'run.failed':
      return { title: 'Run failed', tone: 'stop', lines: [String(d.reason || 'Unknown error')] };
    default:
      return { title: String(e.kind), tone: 'info', lines: [] };
  }
}

function addEvent(e) {
  state.runId = e.run_id;
  state.lastSeq = Math.max(state.lastSeq, e.seq);
  const info = describe(e);
  const item = el('li', 'event tone-' + info.tone);
  item.appendChild(el('span', 'dot'));
  const body = el('div', 'event-body');
  body.appendChild(el('strong', 'event-title', info.title));
  for (const line of info.lines) body.appendChild(el('p', 'event-line', line));
  if (info.note) {
    const quote = el('blockquote', 'note');
    quote.appendChild(el('span', 'note-label', 'Supplier note, untrusted text shown as plain text'));
    quote.appendChild(el('p', 'note-text', String(info.note)));
    body.appendChild(quote);
  }
  item.appendChild(body);
  $('timeline').appendChild(item);
  $('run-empty').hidden = true;
  item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function showResult(r) {
  const card = $('result');
  card.replaceChildren();
  card.hidden = false;
  card.appendChild(el('span', 'badge tier-' + r.tier, TIER_LABEL[r.tier] || String(r.tier)));
  card.appendChild(el('p', 'result-status', STATUS_LABEL[r.status] || String(r.status)));
  const dl = el('dl', 'facts');
  fact(dl, 'Order', String(r.order_ref));
  if (Number.isFinite(r.total_minor)) fact(dl, 'Total', money(r.total_minor));
  if (r.rail) fact(dl, 'Rail', String(r.rail));
  if (r.reference) fact(dl, 'Reference', String(r.reference));
  for (const reason of list(r.reasons)) fact(dl, 'Note', reason);
  card.appendChild(dl);

  const approval = $('approval');
  if (r.status === 'awaiting_approval') {
    $('approval-detail').textContent =
      'Approving signs a fresh mandate capped at ' +
      money(r.total_minor) +
      ' and runs it through the gate again. The original cap is not raised.';
    approval.hidden = false;
  } else {
    approval.hidden = true;
  }
}

function resetRunPanel(orderRef) {
  state.runId = null;
  state.lastSeq = 0;
  $('run-title').textContent = 'Run ' + orderRef;
  $('timeline').replaceChildren();
  $('result').hidden = true;
  $('approval').hidden = true;
  $('run-empty').hidden = true;
  hideBanner();
}

function parseBlock(block) {
  let kind = 'message';
  let data = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) kind = line.slice(7);
    else if (line.startsWith('data: ')) data += line.slice(6);
  }
  try {
    return { kind, data: JSON.parse(data) };
  } catch (err) {
    return null;
  }
}

function handleBlock(block) {
  const parsed = parseBlock(block);
  if (!parsed) return;
  if (parsed.kind === 'result') showResult(parsed.data);
  else if (parsed.kind === 'error') showBanner('The run failed unexpectedly.', 'stop');
  else addEvent(parsed.data);
}

async function readStream(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf('\n\n');
    while (index >= 0) {
      handleBlock(buffer.slice(0, index));
      buffer = buffer.slice(index + 2);
      index = buffer.indexOf('\n\n');
    }
  }
}

async function startRun(orderRef) {
  if (state.running) return;
  setRunning(true);
  resetRunPanel(orderRef);
  try {
    const res = await fetch('/runs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ order_ref: orderRef, demo_hostile: $('hostile').checked }),
    });
    if (!res.ok) {
      await showHttpError(res);
      return;
    }
    await readStream(res);
  } catch (err) {
    showBanner('The run was interrupted. Please try again.', 'stop');
  } finally {
    setRunning(false);
  }
}

async function appendNewEvents() {
  const res = await fetch(
    '/runs/' + encodeURIComponent(state.runId) + '/events?after=' + state.lastSeq
  );
  if (!res.ok) return;
  const body = await res.json();
  for (const e of body.events) addEvent(e);
}

async function decide(kind) {
  if (!state.runId || state.running) return;
  setRunning(true);
  try {
    const res = await fetch('/runs/' + encodeURIComponent(state.runId) + '/' + kind, {
      method: 'POST',
    });
    if (!res.ok) {
      await showHttpError(res);
      return;
    }
    const body = await res.json();
    await appendNewEvents();
    showResult(body.result);
  } catch (err) {
    showBanner('The decision could not be completed. Please try again.', 'stop');
  } finally {
    setRunning(false);
  }
}

async function resetDemo() {
  if (state.running) return;
  setRunning(true);
  try {
    const res = await fetch('/demo/reset', { method: 'POST' });
    if (!res.ok) {
      await showHttpError(res);
      return;
    }
    state.runId = null;
    state.lastSeq = 0;
    $('timeline').replaceChildren();
    $('result').hidden = true;
    $('approval').hidden = true;
    $('run-title').textContent = 'Run';
    $('run-empty').hidden = false;
    showBanner('Demo state cleared: spend history and pending approvals.', 'ok');
  } catch (err) {
    showBanner('The reset could not be completed.', 'stop');
  } finally {
    setRunning(false);
  }
}

function renderConfig() {
  const c = state.cfg;
  const m = c.mandate;
  const dl = $('mandate');
  dl.replaceChildren();
  fact(dl, 'Buyer', c.buyer);
  fact(dl, 'Supplier', c.supplier);
  fact(dl, 'Cap per payment', money(m.cap_minor));
  fact(dl, 'Budget', money(m.budget_minor));
  fact(dl, 'Payments', String(m.max_uses) + ' per period');
  fact(dl, 'Period', cap(String(m.frequency).toLowerCase()));
  fact(dl, 'Price tolerance', (c.price_tolerance_bps / 100).toFixed(2) + '% above agreed');
}

function renderOrders() {
  const box = $('orders');
  box.replaceChildren();
  for (const s of state.cfg.scenarios) {
    const copy = SCENARIO_COPY[s.order_ref] || { title: 'Order', blurb: '' };
    const card = el('div', 'order');
    card.appendChild(el('div', 'order-ref', s.order_ref));
    card.appendChild(el('div', 'order-title', copy.title));
    card.appendChild(el('div', 'order-amount', 'Agreed ' + money(s.agreed_minor)));
    card.appendChild(el('p', 'order-blurb', copy.blurb));
    const button = el('button', 'btn primary', 'Run ' + s.order_ref);
    button.type = 'button';
    button.setAttribute('data-action', '');
    button.addEventListener('click', () => startRun(s.order_ref));
    card.appendChild(button);
    box.appendChild(card);
  }
}

async function init() {
  $('approve').addEventListener('click', () => decide('approve'));
  $('reject').addEventListener('click', () => decide('reject'));
  $('reset').addEventListener('click', resetDemo);
  try {
    const [cfg, health] = await Promise.all([getJson('/config'), getJson('/health')]);
    state.cfg = cfg;
    state.live = health.live_enabled !== false;
  } catch (err) {
    showBanner('Corridor could not be reached. Please refresh in a moment.', 'stop');
    return;
  }
  renderConfig();
  renderOrders();
  applyLiveState();
}

init();
