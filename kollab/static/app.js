'use strict';

// ------------------------------------------------------------------ state
let ws = null;
let currentTurnId = null;
let isStreaming = false;
let stickyBottom = true;
let sessionActive = false;

// ------------------------------------------------------------------ DOM refs
const dialogue    = document.getElementById('dialogue');
const emptyState  = document.getElementById('empty-state');
const statusStrip = document.getElementById('status-strip');
const userInput   = document.getElementById('user-input');
const btnSend     = document.getElementById('btn-send');
const btnStop     = document.getElementById('btn-stop');
const btnResume   = document.getElementById('btn-resume');

// ------------------------------------------------------------------ WebSocket
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = e => handleEvent(JSON.parse(e.data));
  ws.onclose   = () => setTimeout(connectWS, 2000);
}

// ------------------------------------------------------------------ event dispatch
function handleEvent(msg) {
  switch (msg.type) {
    case 'turn_start':    onTurnStart(msg);   break;
    case 'turn_chunk':    onTurnChunk(msg);   break;
    case 'turn_end':      onTurnEnd(msg);     break;
    case 'state':         onState(msg);       break;
    case 'session_done':  onSessionDone(msg); break;
    case 'error':         onError(msg);       break;
  }
}

// ------------------------------------------------------------------ turn rendering
function onTurnStart(msg) {
  emptyState && emptyState.remove();
  currentTurnId = msg.turn_id;
  isStreaming = true;

  const isClaude = msg.actor === 'claude';
  const accentBg   = isClaude ? 'bg-claudeTint' : 'bg-codexTint';
  const accentBorder = isClaude ? 'border-claude' : 'border-codex';
  const accentText   = isClaude ? 'text-claude'   : 'text-codex';

  const card = document.createElement('div');
  card.id = `turn-${msg.turn_id}`;
  card.className = `rounded-lg border ${accentBorder} ${accentBg} p-3 flex flex-col gap-2`;
  card.innerHTML = `
    <div class="flex items-center gap-2 text-xs">
      <span class="font-bold ${accentText} uppercase">${msg.actor}</span>
      <span class="text-muted">${msg.role}</span>
      <span id="badge-${msg.turn_id}" class="ml-auto font-mono text-muted">${msg.turn_id}</span>
      <span id="verdict-${msg.turn_id}"></span>
    </div>
    <details id="reasoning-${msg.turn_id}" class="text-muted text-xs hidden">
      <summary class="cursor-pointer hover:text-user">Reasoning</summary>
      <pre id="reasoning-body-${msg.turn_id}" class="whitespace-pre-wrap mt-1 pl-2"></pre>
    </details>
    <pre id="body-${msg.turn_id}" class="whitespace-pre-wrap text-user thinking">…</pre>
  `;
  dialogue.appendChild(card);
  scrollIfSticky();
}

function onTurnChunk(msg) {
  if (msg.turn_id !== currentTurnId) return;
  if (msg.kind === 'text') {
    const body = document.getElementById(`body-${msg.turn_id}`);
    if (body) {
      if (body.classList.contains('thinking')) {
        body.classList.remove('thinking');
        body.textContent = '';
      }
      body.textContent += msg.content;
    }
  } else if (msg.kind === 'reasoning') {
    const details = document.getElementById(`reasoning-${msg.turn_id}`);
    const pre = document.getElementById(`reasoning-body-${msg.turn_id}`);
    if (details && pre) {
      details.classList.remove('hidden');
      pre.textContent += msg.content;
    }
  }
  scrollIfSticky();
}

function onTurnEnd(msg) {
  const verdictEl = document.getElementById(`verdict-${msg.turn_id}`);
  if (verdictEl && msg.verdict) {
    const colors = {
      AGREE:    'text-verdictAgree bg-verdictAgree/20',
      DISAGREE: 'text-verdictDisagree bg-verdictDisagree/20',
      REVISED:  'text-verdictRevised bg-verdictRevised/20',
    };
    verdictEl.className = `text-xs px-1.5 py-0.5 rounded font-bold ${colors[msg.verdict] || ''}`;
    verdictEl.textContent = msg.verdict;
  }
  // clear thinking animation on the body if still set
  const body = document.getElementById(`body-${msg.turn_id}`);
  if (body) body.classList.remove('thinking');
  isStreaming = false;
  currentTurnId = null;
  scrollIfSticky();
}

// ------------------------------------------------------------------ state
function onState(msg) {
  const stateLabels = {
    idle:          'idle',
    fanning_out:   'sending goal to both agents…',
    claude_turn:   `claude thinking… · round ${msg.round}`,
    codex_turn:    `codex thinking… · round ${msg.round}`,
    awaiting_user: 'awaiting input',
    halted:        'halted — click Resume to continue',
    done:          'session complete',
  };
  statusStrip.textContent = stateLabels[msg.state] || msg.state;
  sessionActive = ['claude_turn', 'codex_turn', 'fanning_out'].includes(msg.state);
  btnStop.classList.toggle('hidden', !sessionActive);
  btnResume.classList.toggle('hidden', msg.state !== 'halted');
}

function onSessionDone(msg) {
  const reasons = {
    convergence:  '✓ Both agents reached agreement.',
    round_limit:  '⚠ Round limit reached.',
    halted:       '⏹ Session halted.',
  };
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted';
  banner.textContent = reasons[msg.reason] || `Session ended: ${msg.reason}`;
  dialogue.appendChild(banner);
  sessionActive = false;
  btnStop.classList.add('hidden');
  statusStrip.textContent = `done — ${msg.reason}`;
  scrollIfSticky();
}

function onError(msg) {
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-verdictDisagree/50 bg-verdictDisagree/10 px-4 py-3 text-verdictDisagree';
  banner.textContent = `Error: ${msg.message}`;
  dialogue.appendChild(banner);
  scrollIfSticky();
}

// ------------------------------------------------------------------ buttons
btnSend.addEventListener('click', sendInput);
userInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) sendInput(); });

btnStop.addEventListener('click', () => {
  fetch('/api/session/stop', { method: 'POST' });
});

btnResume.addEventListener('click', () => {
  fetch('/api/session/resume', { method: 'POST' });
  btnResume.classList.add('hidden');
});

function sendInput() {
  const text = userInput.value.trim();
  if (!text) return;
  // highlight referenced turn card briefly
  const ref = text.match(/\b([CX]-\d+)\b/);
  if (ref) highlightCard(ref[1]);
  fetch('/api/session/input', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  userInput.value = '';
}

function highlightCard(turnId) {
  const card = document.getElementById(`turn-${turnId}`);
  if (!card) return;
  card.style.transition = 'box-shadow 0.2s';
  card.style.boxShadow = '0 0 0 2px #cc6600';
  setTimeout(() => { card.style.boxShadow = ''; }, 1200);
}

// ------------------------------------------------------------------ new session modal
document.getElementById('btn-new-session').addEventListener('click', () => {
  document.getElementById('modal-new-session').classList.remove('hidden');
  document.getElementById('goal-input').focus();
});
document.getElementById('btn-modal-cancel').addEventListener('click', () => {
  document.getElementById('modal-new-session').classList.add('hidden');
});
document.getElementById('btn-modal-start').addEventListener('click', async () => {
  const goal = document.getElementById('goal-input').value.trim();
  if (!goal) return;
  document.getElementById('modal-new-session').classList.add('hidden');
  document.getElementById('goal-input').value = '';
  await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal }),
  });
});

// ------------------------------------------------------------------ configure modal
const configFields = [
  { key: 'claude_binary', label: 'Claude binary path' },
  { key: 'claude_model',  label: 'Claude model', type: 'select', options: ['opus','sonnet','haiku'] },
  { key: 'claude_workdir',label: 'Claude working dir' },
  { key: 'codex_binary',  label: 'Codex binary path' },
  { key: 'codex_model',   label: 'Codex model' },
  { key: 'codex_workdir', label: 'Codex working dir' },
  { key: 'round_limit',   label: 'Round limit', type: 'number' },
  { key: 'port',          label: 'Port', type: 'number' },
  { key: 'sessions_dir',  label: 'Sessions dir' },
];

document.getElementById('btn-configure').addEventListener('click', async () => {
  const res = await fetch('/api/config');
  const cfg = await res.json();
  const form = document.getElementById('config-form');
  form.innerHTML = '';
  for (const f of configFields) {
    const label = document.createElement('label');
    label.className = 'flex flex-col gap-1 text-xs text-muted';
    label.textContent = f.label;
    let input;
    if (f.type === 'select') {
      input = document.createElement('select');
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none';
      for (const opt of f.options) {
        const o = document.createElement('option');
        o.value = opt; o.textContent = opt;
        if (cfg[f.key] === opt) o.selected = true;
        input.appendChild(o);
      }
    } else {
      input = document.createElement('input');
      input.type = f.type || 'text';
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none';
      input.value = cfg[f.key] ?? '';
    }
    input.name = f.key;
    label.appendChild(input);
    form.appendChild(label);
  }
  document.getElementById('modal-configure').classList.remove('hidden');
});

document.getElementById('btn-config-cancel').addEventListener('click', () => {
  document.getElementById('modal-configure').classList.add('hidden');
});

document.getElementById('btn-config-save').addEventListener('click', async () => {
  const form = document.getElementById('config-form');
  const data = {};
  for (const el of form.elements) {
    if (el.name) data[el.name] = el.type === 'number' ? Number(el.value) : el.value;
  }
  const res = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const result = await res.json();
  const errEl = document.getElementById('config-errors');
  if (result.ok) {
    document.getElementById('modal-configure').classList.add('hidden');
    errEl.classList.add('hidden');
  } else {
    errEl.textContent = result.errors.join(' · ');
    errEl.classList.remove('hidden');
  }
});

// ------------------------------------------------------------------ scroll
dialogue.addEventListener('scroll', () => {
  const atBottom = dialogue.scrollHeight - dialogue.scrollTop - dialogue.clientHeight < 40;
  stickyBottom = atBottom;
});

function scrollIfSticky() {
  if (stickyBottom) dialogue.scrollTop = dialogue.scrollHeight;
}

// ------------------------------------------------------------------ init
connectWS();
