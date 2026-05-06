'use strict';

// ------------------------------------------------------------------ tab state

// Tab: { id, sessionId, goal, state, turnsEl, scrollTop }
// state: 'active' | 'done' | 'halted' | 'readonly'
const tabs = [];
let activeTabId = null;
let waitingMsgEl = null;
let pendingCloseTabId = null;   // for confirm-close modal

// ------------------------------------------------------------------ DOM refs
const dialogue      = document.getElementById('dialogue');
const emptyState    = document.getElementById('empty-state');
const statusStrip   = document.getElementById('status-strip');
const userInput     = document.getElementById('user-input');
const btnSend       = document.getElementById('btn-send');
const btnStop       = document.getElementById('btn-stop');
const btnResume     = document.getElementById('btn-resume');
const inputTarget   = document.getElementById('input-target');
const tabBar        = document.getElementById('tab-bar');
const btnNewSession = document.getElementById('btn-new-session');
const historyPane   = document.getElementById('history-pane');
const historyList   = document.getElementById('history-list');

// ------------------------------------------------------------------ history pane collapse

const HISTORY_KEY = 'kollab_history_collapsed';

function applyHistoryCollapse(collapsed) {
  historyPane.style.width = collapsed ? '0px' : '240px';
  historyPane.style.overflow = 'hidden';
}

document.getElementById('btn-history-toggle').addEventListener('click', () => {
  const collapsed = historyPane.style.width === '0px';
  applyHistoryCollapse(!collapsed);
  localStorage.setItem(HISTORY_KEY, !collapsed ? 'true' : 'false');
});

applyHistoryCollapse(localStorage.getItem(HISTORY_KEY) === 'true');

// ------------------------------------------------------------------ tab management

function makeTabId() {
  return 'tab_' + Math.random().toString(36).slice(2, 10);
}

function getTab(tabId) {
  return tabs.find(t => t.id === tabId) || null;
}

function getTabBySessionId(sessionId) {
  return tabs.find(t => t.sessionId === sessionId) || null;
}

function createTab(goal, sessionId, state) {
  const tab = {
    id: makeTabId(),
    sessionId: sessionId || null,
    goal: goal || '',
    state: state || 'active',
    turnsEl: document.createDocumentFragment(),
    scrollTop: 0,
    _nodes: [],   // actual DOM nodes (fragment is consumed on first use)
  };
  tabs.push(tab);
  renderTabBar();
  return tab;
}

function closeTab(tabId) {
  const idx = tabs.findIndex(t => t.id === tabId);
  if (idx === -1) return;
  tabs.splice(idx, 1);
  if (activeTabId === tabId) {
    activeTabId = null;
    const next = tabs[Math.min(idx, tabs.length - 1)];
    if (next) switchTab(next.id);
    else showEmptyState();
  }
  renderTabBar();
}

function switchTab(tabId) {
  // save scroll of outgoing tab
  if (activeTabId) {
    const outgoing = getTab(activeTabId);
    if (outgoing) outgoing.scrollTop = dialogue.scrollTop;
  }

  activeTabId = tabId;
  const tab = getTab(tabId);
  if (!tab) return;

  // clear dialogue and repopulate with this tab's nodes
  dialogue.innerHTML = '';
  for (const node of tab._nodes) {
    dialogue.appendChild(node);
  }
  dialogue.scrollTop = tab.scrollTop;
  stickyBottom = true;

  renderTabBar();
  updateInputStrip(tab);
}

function showEmptyState() {
  activeTabId = null;
  dialogue.innerHTML = '';
  const p = document.createElement('p');
  p.id = 'empty-state';
  p.className = 'text-muted text-center mt-16';
  p.textContent = 'Start a new session to begin the dialogue.';
  dialogue.appendChild(p);
  updateInputStrip(null);
  renderTabBar();
}

function activeTab() {
  return activeTabId ? getTab(activeTabId) : null;
}

// ------------------------------------------------------------------ tab bar rendering

function renderTabBar() {
  // Remove all tab elements (keep the + New Session button)
  const oldTabs = tabBar.querySelectorAll('.kollab-tab');
  oldTabs.forEach(el => el.remove());

  for (const tab of tabs) {
    const label = (tab.state === 'readonly' ? '[readonly] ' : '')
      + (tab.goal ? tab.goal.slice(0, 40) + (tab.goal.length > 40 ? '…' : '') : 'New session');

    const el = document.createElement('div');
    el.className = 'kollab-tab flex items-center gap-1 px-3 py-2 text-xs cursor-pointer border-r border-white/10 whitespace-nowrap shrink-0 transition '
      + (tab.id === activeTabId
        ? 'text-user border-b-2 border-b-claude bg-claudeTint/20'
        : 'text-muted hover:text-user');
    el.dataset.tabId = tab.id;

    const labelSpan = document.createElement('span');
    labelSpan.textContent = label;
    labelSpan.addEventListener('click', () => switchTab(tab.id));

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.className = 'ml-1 opacity-50 hover:opacity-100 transition';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      handleTabClose(tab.id);
    });

    el.appendChild(labelSpan);
    el.appendChild(closeBtn);
    tabBar.appendChild(el);
  }
}

function handleTabClose(tabId) {
  const tab = getTab(tabId);
  if (!tab) return;
  if (tab.state === 'active') {
    pendingCloseTabId = tabId;
    document.getElementById('modal-confirm-close').classList.remove('hidden');
  } else {
    closeTab(tabId);
  }
}

document.getElementById('btn-confirm-close-no').addEventListener('click', () => {
  pendingCloseTabId = null;
  document.getElementById('modal-confirm-close').classList.add('hidden');
});

document.getElementById('btn-confirm-close-yes').addEventListener('click', async () => {
  document.getElementById('modal-confirm-close').classList.add('hidden');
  if (pendingCloseTabId) {
    await fetch('/api/session/stop', { method: 'POST' });
    closeTab(pendingCloseTabId);
    pendingCloseTabId = null;
  }
});

// ------------------------------------------------------------------ input strip

function updateInputStrip(tab) {
  const isHalted  = tab && tab.state === 'halted';
  const isReadonly = !tab || tab.state === 'readonly' || tab.state === 'done';

  // dropdown: only enabled when halted
  inputTarget.disabled = !isHalted;
  if (!isHalted) {
    inputTarget.value = '';
  }

  // input + send: only enabled when halted AND target selected
  const targetSelected = isHalted && inputTarget.value !== '';
  userInput.disabled = !targetSelected;
  btnSend.disabled = !targetSelected;
  userInput.placeholder = isHalted
    ? (targetSelected ? 'Type your instruction…' : 'Select a target first…')
    : 'Session not halted';

  if (isReadonly) {
    btnStop.classList.add('hidden');
    btnResume.classList.add('hidden');
  }
}

// enable input once target is selected
inputTarget.addEventListener('change', () => {
  const tab = activeTab();
  updateInputStrip(tab);
  if (inputTarget.value) userInput.focus();
});

// ------------------------------------------------------------------ append to active tab

function appendToActiveTab(node) {
  const tab = activeTab();
  if (!tab) return;
  tab._nodes.push(node);
  dialogue.appendChild(node);
  scrollIfSticky();
}

// ------------------------------------------------------------------ WebSocket

let ws = null;
let stickyBottom = true;

let wsReconnectAttempts = 0;

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = e => handleEvent(JSON.parse(e.data));
  ws.onopen = () => onServerOnline();
  ws.onclose = () => {
    if (wsReconnectAttempts === 0) onServerGone();
    wsReconnectAttempts++;
  };
}

function onServerOnline() {
  wsReconnectAttempts = 0;
  document.getElementById('btn-shutdown').disabled = false;
  document.getElementById('btn-shutdown').classList.remove('opacity-40');
}

function onServerGone() {
  document.getElementById('btn-shutdown').disabled = true;
  document.getElementById('btn-shutdown').classList.add('opacity-40');
  document.getElementById('modal-shutdown').classList.add('hidden');
  const msg = document.getElementById('shutdown-msg');
  msg.textContent = 'koll♠b has shut down.';
  const noBtn = document.getElementById('btn-shutdown-no');
  noBtn.classList.add('hidden');
  const yesBtn = document.getElementById('btn-shutdown-yes');
  yesBtn.textContent = 'Close tab';
  yesBtn.disabled = false;
  yesBtn.onclick = () => window.close();
  document.getElementById('modal-shutdown').classList.remove('hidden');
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

let currentTurnId = null;
let isStreaming = false;

function buildTurnCard(msg) {
  const isClaude = msg.actor === 'claude';
  const accentBg     = isClaude ? 'bg-claudeTint' : 'bg-codexTint';
  const accentBorder = isClaude ? 'border-claude'  : 'border-codex';
  const accentText   = isClaude ? 'text-claude'    : 'text-codex';

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
  return card;
}

function applyVerdict(turnId, verdict) {
  const verdictEl = document.getElementById(`verdict-${turnId}`);
  if (verdictEl && verdict) {
    const colors = {
      AGREE:    'text-verdictAgree bg-verdictAgree/20',
      DISAGREE: 'text-verdictDisagree bg-verdictDisagree/20',
      REVISED:  'text-verdictRevised bg-verdictRevised/20',
    };
    verdictEl.className = `text-xs px-1.5 py-0.5 rounded font-bold ${colors[verdict] || ''}`;
    verdictEl.textContent = verdict;
  }
}

function removeWaitingMsg() {
  if (waitingMsgEl) { waitingMsgEl.remove(); waitingMsgEl = null; }
}

function onTurnStart(msg) {
  removeWaitingMsg();
  currentTurnId = msg.turn_id;
  isStreaming = true;
  appendToActiveTab(buildTurnCard(msg));
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
  applyVerdict(msg.turn_id, msg.verdict);
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

  const sessionRunning = ['claude_turn', 'codex_turn', 'fanning_out'].includes(msg.state);
  btnStop.classList.toggle('hidden', !sessionRunning);
  if (sessionRunning) {
    btnStop.disabled = false;
    btnStop.textContent = 'Stop';
    btnStop.classList.remove('opacity-50');
  }
  btnResume.classList.toggle('hidden', msg.state !== 'halted');

  const tab = activeTab();
  if (tab) {
    if (msg.state === 'halted') tab.state = 'halted';
    else if (msg.state === 'done') tab.state = 'done';
    else if (sessionRunning) tab.state = 'active';
    updateInputStrip(tab);
  }
}

function onSessionDone(msg) {
  const reasons = {
    convergence: '✓ Both agents reached agreement.',
    round_limit: '⚠ Round limit reached.',
    token_limit: '⚠ Token budget exhausted.',
    halted:      '⏹ Session halted.',
  };
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted';
  banner.textContent = reasons[msg.reason] || `Session ended: ${msg.reason}`;
  appendToActiveTab(banner);

  const tab = activeTab();
  if (tab) tab.state = 'done';

  btnStop.classList.add('hidden');
  statusStrip.textContent = `done — ${msg.reason}`;
  updateInputStrip(tab);
  renderTabBar();
  scrollIfSticky();

  // refresh history pane
  loadHistory();
}

function onError(msg) {
  removeWaitingMsg();
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-verdictDisagree/50 bg-verdictDisagree/10 px-4 py-3 text-verdictDisagree';
  banner.textContent = `Error: ${msg.message}`;
  appendToActiveTab(banner);
  scrollIfSticky();
}

// ------------------------------------------------------------------ buttons

btnSend.addEventListener('click', sendInput);
userInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) sendInput(); });

btnStop.addEventListener('click', async () => {
  btnStop.disabled = true;
  btnStop.textContent = 'Stopping…';
  btnStop.classList.add('opacity-50');
  const res = await fetch('/api/session/stop', { method: 'POST' });
  if (!res.ok) {
    btnStop.disabled = false;
    btnStop.textContent = 'Stop';
    btnStop.classList.remove('opacity-50');
  }
});

btnResume.addEventListener('click', () => {
  // check for unsent instruction
  if (inputTarget.value && userInput.value.trim()) {
    showUnsentToast();
    return;
  }
  doResume();
});

function doResume() {
  fetch('/api/session/resume', { method: 'POST' });
  btnResume.classList.add('hidden');
  const tab = activeTab();
  if (tab) { tab.state = 'active'; updateInputStrip(tab); }
}

function showUnsentToast() {
  // remove existing toast if any
  document.getElementById('unsent-toast')?.remove();
  const toast = document.createElement('div');
  toast.id = 'unsent-toast';
  toast.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 bg-panel border border-white/20 rounded px-4 py-2 text-xs text-muted z-50 flex items-center gap-3';
  toast.innerHTML = `
    <span>Instruction not sent.</span>
    <button id="toast-send-resume" class="text-verdictAgree hover:underline">Send &amp; Resume</button>
    <button id="toast-resume-anyway" class="text-muted hover:underline">Resume anyway</button>
  `;
  document.body.appendChild(toast);
  toast.querySelector('#toast-send-resume').addEventListener('click', async () => {
    toast.remove();
    await sendInput();
    doResume();
  });
  toast.querySelector('#toast-resume-anyway').addEventListener('click', () => {
    toast.remove();
    userInput.value = '';
    doResume();
  });
  setTimeout(() => toast?.remove(), 8000);
}

async function sendInput() {
  const text = userInput.value.trim();
  if (!text) return;
  const target = inputTarget.value || 'both';
  const ref = text.match(/\b([CX]-\d+)\b/);
  if (ref) highlightCard(ref[1]);

  // render user instruction card
  const targetLabels = { claude: 'CLAUDE', codex: 'CODEX', both: 'CLAUDE, CODEX' };
  const card = document.createElement('div');
  card.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
  card.innerHTML = `
    <div class="text-xs text-muted uppercase">USER → ${targetLabels[target] || target.toUpperCase()}</div>
    <pre class="whitespace-pre-wrap text-user">${escHtml(text)}</pre>
  `;
  appendToActiveTab(card);

  await fetch('/api/session/input', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, target }),
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

// Model matrix — single source of truth for all model dropdowns.
// label: short display name shown in UI
// model: full model string passed to the CLI
// tier: fast | gp | high-end
const MODEL_MATRIX = {
  claude: [
    { label: 'haiku',  model: 'claude-haiku-4-5-20251001', tier: 'fast'     },
    { label: 'sonnet', model: 'claude-sonnet-4-6',          tier: 'gp'       },
    { label: 'opus',   model: 'claude-opus-4-7',            tier: 'high-end' },
  ],
  codex: [
    { label: 'mini',    model: 'gpt-5.4-mini', tier: 'fast' },
    { label: 'gpt-5.4', model: 'gpt-5.4',      tier: 'gp'   },
  ],
};

function populateSelect(selectEl, agentKey, currentValue) {
  selectEl.innerHTML = '';
  for (const m of MODEL_MATRIX[agentKey]) {
    const opt = document.createElement('option');
    opt.value = m.model;
    opt.textContent = `${m.label} (${m.model})`;
    if (m.model === currentValue) opt.selected = true;
    selectEl.appendChild(opt);
  }
}

btnNewSession.addEventListener('click', async () => {
  // block if a session is already active
  const runningTab = tabs.find(t => t.state === 'active');
  if (runningTab) {
    switchTab(runningTab.id);
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 bg-panel border border-white/20 rounded px-4 py-2 text-xs text-muted z-50';
    toast.textContent = 'A session is already running. Stop it or wait for it to finish.';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
    return;
  }

  // fetch config to pre-fill defaults
  let cfg = {};
  try {
    const res = await fetch('/api/config');
    if (res.ok) cfg = await res.json();
  } catch (_) {}

  populateSelect(document.getElementById('override-claude-model'), 'claude', cfg.claude_model || MODEL_MATRIX.claude[1].model);
  populateSelect(document.getElementById('override-codex-model'),  'codex',  cfg.codex_model  || MODEL_MATRIX.codex[1].model);

  const roundInput = document.getElementById('override-round-limit');
  roundInput.placeholder = `default (${cfg.round_limit ?? 8})`;
  roundInput.value = '';

  document.getElementById('override-tokens-turn').value = '';
  document.getElementById('override-tokens-session').value = '';

  document.getElementById('modal-new-session').classList.remove('hidden');
  document.getElementById('goal-input').focus();
});

document.getElementById('btn-modal-cancel').addEventListener('click', () => {
  document.getElementById('modal-new-session').classList.add('hidden');
});

document.getElementById('btn-modal-start').addEventListener('click', async () => {
  const goal = document.getElementById('goal-input').value.trim();
  if (!goal) return;

  // collect overrides — only send fields the user actually changed
  let cfg = {};
  try { const r = await fetch('/api/config'); if (r.ok) cfg = await r.json(); } catch (_) {}

  const body = { goal };

  const claudeModel = document.getElementById('override-claude-model').value;
  if (claudeModel && claudeModel !== cfg.claude_model) body.claude_model = claudeModel;

  const codexModel = document.getElementById('override-codex-model').value;
  if (codexModel && codexModel !== cfg.codex_model) body.codex_model = codexModel;

  const roundVal = parseInt(document.getElementById('override-round-limit').value, 10);
  if (!isNaN(roundVal) && roundVal > 0 && roundVal !== cfg.round_limit) body.round_limit = roundVal;

  const tokensTurn = parseInt(document.getElementById('override-tokens-turn').value, 10);
  if (!isNaN(tokensTurn) && tokensTurn > 0) body.max_tokens_per_turn = tokensTurn;

  const tokensSession = parseInt(document.getElementById('override-tokens-session').value, 10);
  if (!isNaN(tokensSession) && tokensSession > 0) body.max_tokens_per_session = tokensSession;

  document.getElementById('modal-new-session').classList.add('hidden');
  document.getElementById('goal-input').value = '';

  const tab = createTab(goal, null, 'active');
  switchTab(tab.id);

  // render goal card immediately
  const goalCard = document.createElement('div');
  goalCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
  goalCard.innerHTML = `
    <div class="text-xs text-muted uppercase">goal</div>
    <pre class="whitespace-pre-wrap text-user">${escHtml(goal)}</pre>
  `;
  appendToActiveTab(goalCard);

  waitingMsgEl = document.createElement('p');
  waitingMsgEl.className = 'text-muted text-center mt-16';
  waitingMsgEl.textContent = 'Waiting for Claude to respond…';
  appendToActiveTab(waitingMsgEl);

  const res = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const data = await res.json();
    tab.sessionId = data.session_id;
  } else if (res.status === 409) {
    removeWaitingMsg();
    closeTab(tab.id);
  } else {
    removeWaitingMsg();
    onError({ message: `Failed to start session (${res.status})` });
  }
});

document.getElementById('btn-shutdown').addEventListener('click', () => {
  const running = tabs.find(t => t.state === 'active');
  const msg = document.getElementById('shutdown-msg');
  msg.textContent = running
    ? 'A session is in progress. Quit anyway? It will be stopped.'
    : 'Quit koll\u2660b?';
  document.getElementById('modal-shutdown').classList.remove('hidden');
});

document.getElementById('btn-shutdown-no').addEventListener('click', () => {
  document.getElementById('modal-shutdown').classList.add('hidden');
});

document.getElementById('btn-shutdown-yes').addEventListener('click', async () => {
  document.getElementById('btn-shutdown-yes').disabled = true;
  document.getElementById('btn-shutdown-yes').textContent = 'Quitting…';
  await fetch('/api/shutdown', { method: 'POST' });
  document.body.innerHTML = '<p style="color:#888;font-family:monospace;padding:2rem">koll♠b has shut down. You can close this tab.</p>';
});

// ------------------------------------------------------------------ configure modal

const configFields = [
  { key: 'claude_binary', label: 'Claude binary path' },
  { key: 'claude_model',  label: 'Claude model', type: 'select', agentKey: 'claude' },
  { key: 'claude_workdir',label: 'Claude working dir' },
  { key: 'codex_binary',  label: 'Codex binary path' },
  { key: 'codex_model',   label: 'Codex model',  type: 'select', agentKey: 'codex' },
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
      for (const m of MODEL_MATRIX[f.agentKey]) {
        const o = document.createElement('option');
        o.value = m.model;
        o.textContent = `${m.label} (${m.model})`;
        if (cfg[f.key] === m.model) o.selected = true;
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

// ------------------------------------------------------------------ history pane

async function loadHistory() {
  let sessions;
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) throw new Error(res.status);
    sessions = await res.json();
  } catch (_) {
    historyList.innerHTML = '<p class="text-muted text-xs px-3 py-4">Could not load history.</p>';
    return;
  }

  historyList.innerHTML = '';
  historyList.scrollTop = 0;
  if (!sessions.length) {
    historyList.innerHTML = '<p id="history-empty" class="text-muted text-xs px-3 py-4">No sessions yet.</p>';
    return;
  }

  for (const s of sessions) {
    const row = document.createElement('button');
    row.className = 'text-left w-full px-3 py-2 border-b border-white/5 hover:bg-white/5 transition flex flex-col gap-0.5';
    row.dataset.sessionId = s.session_id;

    const goalEl = document.createElement('span');
    goalEl.className = 'text-xs text-user truncate';
    goalEl.textContent = (s.goal || '').slice(0, 40) + ((s.goal || '').length > 40 ? '…' : '');

    const metaEl = document.createElement('span');
    metaEl.className = 'text-xs text-muted flex items-center gap-1';

    const tsEl = document.createElement('span');
    tsEl.textContent = s.started_at ? relativeTime(s.started_at) : '';

    const pillEl = document.createElement('span');
    const pillStyles = {
      convergence: 'text-verdictAgree',
      round_limit: 'text-verdictRevised',
      halted:      'text-muted',
    };
    const pillLabels = {
      convergence: '✓ converged',
      round_limit: '⚠ round limit',
      halted:      '⏹ halted',
    };
    pillEl.className = `text-xs ${pillStyles[s.end_reason] || 'text-muted'}`;
    pillEl.textContent = pillLabels[s.end_reason] || (s.end_reason || '');

    metaEl.appendChild(tsEl);
    if (s.end_reason) { metaEl.appendChild(document.createTextNode(' · ')); metaEl.appendChild(pillEl); }

    row.appendChild(goalEl);
    row.appendChild(metaEl);
    row.addEventListener('click', () => openHistorySession(s.session_id, s.goal));
    historyList.appendChild(row);
  }
}

function relativeTime(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

async function openHistorySession(sessionId, goal) {
  const existing = getTabBySessionId(sessionId);
  if (existing) { switchTab(existing.id); return; }

  let data;
  try {
    const res = await fetch(`/api/sessions/${sessionId}`);
    if (!res.ok) throw new Error(res.status);
    data = await res.json();
  } catch (_) {
    onError({ message: `Could not load session ${sessionId}` });
    return;
  }

  const tab = createTab(goal || sessionId, sessionId, 'readonly');
  switchTab(tab.id);
  reconstructSession(tab, data.events);
  updateInputStrip(tab);
}

// ------------------------------------------------------------------ readonly reconstruction

function reconstructSession(tab, events) {
  // readonly banner
  const readonlyBanner = document.createElement('div');
  readonlyBanner.className = 'rounded border border-white/10 bg-userPanel px-4 py-2 text-center text-muted text-xs';
  readonlyBanner.textContent = 'This session is complete. Read-only view.';
  appendToActiveTab(readonlyBanner);

  for (const ev of events) {
    const kind = ev.kind;
    if (kind === 'session_start') {
      const goalCard = document.createElement('div');
      goalCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
      goalCard.innerHTML = `
        <div class="text-xs text-muted uppercase">goal</div>
        <pre class="whitespace-pre-wrap text-user">${escHtml(ev.payload?.goal || '')}</pre>
      `;
      appendToActiveTab(goalCard);
    } else if (kind === 'turn_start') {
      const card = buildTurnCard({
        turn_id: ev.turn_id,
        actor: ev.actor,
        role: ev.role,
      });
      // clear thinking placeholder — will be filled by turn_end
      appendToActiveTab(card);
    } else if (kind === 'turn_end') {
      const body = document.getElementById(`body-${ev.turn_id}`);
      if (body) {
        body.classList.remove('thinking');
        body.textContent = ev.payload?.text || '';
      }
      applyVerdict(ev.turn_id, ev.payload?.verdict);
      if (ev.payload?.reasoning) {
        const details = document.getElementById(`reasoning-${ev.turn_id}`);
        const pre = document.getElementById(`reasoning-body-${ev.turn_id}`);
        if (details && pre) {
          details.classList.remove('hidden');
          pre.textContent = ev.payload.reasoning;
        }
      }
    } else if (kind === 'user_input') {
      const targetLabels = { claude: 'CLAUDE', codex: 'CODEX', both: 'CLAUDE, CODEX' };
      const target = ev.payload?.target || 'both';
      const userCard = document.createElement('div');
      userCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
      userCard.innerHTML = `
        <div class="text-xs text-muted uppercase">USER → ${targetLabels[target] || target.toUpperCase()}</div>
        <pre class="whitespace-pre-wrap text-user">${escHtml(ev.payload?.text || '')}</pre>
      `;
      appendToActiveTab(userCard);
    } else if (kind === 'session_end') {
      const reasons = {
        convergence: '✓ Both agents reached agreement.',
        round_limit: '⚠ Round limit reached.',
        token_limit: '⚠ Token budget exhausted.',
        halted:      '⏹ Session halted.',
      };
      const reason = ev.payload?.reason || '';
      const banner = document.createElement('div');
      banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted';
      banner.textContent = reasons[reason] || `Session ended: ${reason}`;
      appendToActiveTab(banner);
    }
  }
}

function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

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
loadHistory();
