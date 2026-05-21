'use strict';

(function injectGoalCardStyle() {
  const s = document.createElement('style');
  s.textContent = `
    .kollab-goal-card {
      position: sticky;
      top: 0;
      z-index: 10;
    }
    [data-theme="dark"]  .kollab-goal-card { background: #17171a; }
    [data-theme="light"] .kollab-goal-card { background: #ffffff; }
  `;
  document.head.appendChild(s);
})();

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

// ------------------------------------------------------------------ timing helpers

function fmtTime(date) {
  if (!date) return '';
  return date.toTimeString().slice(0, 8); // HH:MM:SS
}

function fmtElapsed(ms) {
  if (ms < 0) ms = 0;
  const totalSecs = Math.floor(ms / 1000);
  const m = Math.floor(totalSecs / 60);
  const s = totalSecs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// ------------------------------------------------------------------ theme

const THEME_KEY = 'kollab_theme';

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('btn-theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '\uD83C\uDF19' : '\u2600';

  const isLight = theme === 'light';
  const styles = isLight ? {
    bg:        '#f4f4f6',
    panel:     '#ffffff',
    userPanel: '#ebebee',
    text:      '#1a1a1e',
    muted:     '#606060',
    border:    'rgba(0,0,0,0.10)',
    claudeTint:'#fff3e8',
    codexTint: '#e8f0fb',
  } : {
    bg:        '#0e0e10',
    panel:     '#17171a',
    userPanel: '#202024',
    text:      '#e5e5e5',
    muted:     '#888888',
    border:    'rgba(255,255,255,0.10)',
    claudeTint:'#3a2310',
    codexTint: '#162536',
  };

  document.body.style.backgroundColor = styles.bg;
  document.body.style.color = styles.text;

  const overrides = [
    ['.bg-bg',        'backgroundColor', styles.bg],
    ['.bg-panel',     'backgroundColor', styles.panel],
    ['.bg-userPanel', 'backgroundColor', styles.userPanel],
    ['.bg-claudeTint','backgroundColor', styles.claudeTint],
    ['.bg-codexTint', 'backgroundColor', styles.codexTint],
    ['.text-user',    'color',           styles.text],
    ['.text-muted',   'color',           styles.muted],
  ];
  for (const [sel, prop, val] of overrides) {
    document.querySelectorAll(sel).forEach(el => { el.style[prop] = val; });
  }
  document.querySelectorAll('.border-white\\/10, .border-white\\/20').forEach(el => {
    el.style.borderColor = styles.border;
  });

  window.__kollabThemeStyles = styles;
}

function applyThemeToEl(el) {
  const styles = window.__kollabThemeStyles;
  if (!styles) return;
  const overrides = [
    ['.bg-bg',        'backgroundColor', styles.bg],
    ['.bg-panel',     'backgroundColor', styles.panel],
    ['.bg-userPanel', 'backgroundColor', styles.userPanel],
    ['.bg-claudeTint','backgroundColor', styles.claudeTint],
    ['.bg-codexTint', 'backgroundColor', styles.codexTint],
    ['.text-user',    'color',           styles.text],
    ['.text-muted',   'color',           styles.muted],
  ];
  for (const [sel, prop, val] of overrides) {
    el.querySelectorAll(sel).forEach(e => { e.style[prop] = val; });
    if (el.matches && el.matches(sel)) el.style[prop] = val;
  }
  el.querySelectorAll('.border-white\\/10, .border-white\\/20').forEach(e => {
    e.style.borderColor = styles.border;
  });
  if (el.matches && (el.matches('.border-white\\/10') || el.matches('.border-white\\/20'))) {
    el.style.borderColor = styles.border;
  }
}

document.getElementById('btn-about').addEventListener('click', () => {
  window.open('/about', 'kollab-about');
});

document.getElementById('btn-theme-toggle').addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  localStorage.setItem(THEME_KEY, next);
  fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ theme: next }) });
});

(async () => {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored) {
    applyTheme(stored);
  } else {
    try {
      const r = await fetch('/api/config');
      if (r.ok) { const c = await r.json(); applyTheme(c.theme || 'dark'); }
    } catch (_) { applyTheme('dark'); }
  }
})();

// ------------------------------------------------------------------ history pane collapse

const HISTORY_KEY = 'kollab_history_collapsed';

function applyHistoryCollapse(collapsed) {
  historyPane.style.width = collapsed ? '0px' : '240px';
  historyPane.style.overflow = 'hidden';
}

function scrollHistoryToActive() {
  const sessionId = activeTab()?.sessionId || null;
  if (!sessionId) return;
  const row = historyList.querySelector(`[data-session-id="${sessionId}"]`);
  if (row) row.scrollIntoView({ block: 'nearest' });
}

document.getElementById('btn-history-toggle').addEventListener('click', () => {
  const collapsed = historyPane.style.width === '0px';
  applyHistoryCollapse(!collapsed);
  localStorage.setItem(HISTORY_KEY, (!collapsed).toString());
  if (collapsed) scrollHistoryToActive();
});

const _historySaved = localStorage.getItem(HISTORY_KEY);
applyHistoryCollapse(_historySaved === null ? true : _historySaved === 'true');

(function initHistoryResize() {
  const handle = document.getElementById('history-resize-handle');
  const pane   = document.getElementById('history-pane');
  if (!handle || !pane) return;
  const MIN_WIDTH = 240;
  let dragging = false;
  let startX = 0;
  let startW = 0;
  handle.addEventListener('mousedown', e => {
    dragging = true;
    startX = e.clientX;
    startW = pane.offsetWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const delta = e.clientX - startX;
    const newW  = Math.max(MIN_WIDTH, startW + delta);
    pane.style.width = newW + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
})();

// ------------------------------------------------------------------ tab persistence

const TABS_KEY = 'kollab_open_tabs';

function saveOpenTabs() {
  const persistable = tabs
    .filter(t => t.sessionId && t.state !== 'active')
    .map(t => ({ sessionId: t.sessionId, goal: t.goal, state: t.state, sessionNumber: t.sessionNumber || 0 }));
  localStorage.setItem(TABS_KEY, JSON.stringify(persistable));
}

async function restoreOpenTabs() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem(TABS_KEY) || '[]'); } catch (_) { return; }
  if (!saved.length) return;
  for (const entry of saved) {
    try {
      const res = await fetch(`/api/sessions/${entry.sessionId}`);
      if (!res.ok) continue;
      const data = await res.json();
      const tab = createTab(entry.goal || entry.sessionId, entry.sessionId, 'readonly', entry.sessionNumber || 0);
      // Write directly into tab._nodes — do NOT touch the live dialogue DOM.
      // appendToActiveTab() would clobber whatever is currently displayed.
      reconstructSessionIntoTab(tab, data.events);
      tab.scrollTop = 0;
    } catch (_) { /* skip broken entries */ }
  }
  if (tabs.length > 0 && !activeTabId) {
    switchTab(tabs[tabs.length - 1].id);
  }
  renderTabBar();
}

function makeTabId() {
  return 'tab_' + Math.random().toString(36).slice(2, 10);
}

function getTab(tabId) {
  return tabs.find(t => t.id === tabId) || null;
}

function getTabBySessionId(sessionId) {
  return tabs.find(t => t.sessionId === sessionId) || null;
}

function createTab(goal, sessionId, state, sessionNumber) {
  const tab = {
    id: makeTabId(),
    sessionId: sessionId || null,
    sessionNumber: sessionNumber || 0,
    goal: goal || '',
    state: state || 'active',
    claudeModel: null,
    codexModel: null,
    roundLimit: null,
    startedAt: null,
    endedAt: null,
    _timerInterval: null,
    turnsEl: document.createDocumentFragment(),
    scrollTop: 0,
    _nodes: [],
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
  saveOpenTabs();
}

function scrollTabIntoView(tabId) {
  const tabEl = tabBar.querySelector(`[data-tab-id="${tabId}"]`);
  if (tabEl) tabEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
}

function switchTab(tabId) {
  if (activeTabId) {
    const outgoing = getTab(activeTabId);
    if (outgoing) outgoing.scrollTop = dialogue.scrollTop;
  }

  activeTabId = tabId;
  const tab = getTab(tabId);
  if (!tab) return;

  dialogue.innerHTML = '';
  for (const node of tab._nodes) {
    dialogue.appendChild(node);
  }
  dialogue.scrollTop = tab.scrollTop;
  stickyBottom = true;

  // Re-run goal expand overflow check for reconstructed tabs now that nodes are in DOM
  const goalTextEl = dialogue.querySelector('[id^="goal-text-recon-"]');
  const goalExpandBtn = dialogue.querySelector('[id^="goal-expand-recon-"]');
  if (goalTextEl && goalExpandBtn && goalExpandBtn.classList.contains('hidden')) {
    if (goalTextEl.scrollHeight > goalTextEl.clientHeight + 2) {
      goalExpandBtn.classList.remove('hidden');
      if (!goalTextEl.dataset.expandWired) {
        goalTextEl.dataset.expandWired = '1';
        let expanded = false;
        goalExpandBtn.addEventListener('click', () => {
          expanded = !expanded;
          if (expanded) {
            goalTextEl.style.webkitLineClamp = 'unset';
            goalTextEl.style.display = 'block';
            goalExpandBtn.textContent = '↑';
          } else {
            goalTextEl.style.display = '-webkit-box';
            goalTextEl.style.webkitLineClamp = '1';
            goalExpandBtn.textContent = '↓';
          }
        });
      }
    }
  }

  renderTabBar();
  renderHistoryList(_allSessions);
  if (historyPane.style.width !== '0px') scrollHistoryToActive();
  updateInputStrip(tab);
  scrollTabIntoView(tabId);
}

function showEmptyState() {
  activeTabId = null;
  dialogue.innerHTML = '';
  const p = document.createElement('p');
  p.id = 'empty-state';
  p.className = 'text-muted text-center mt-16';
  p.textContent = 'Start a new session to begin the dialogue.';
  dialogue.appendChild(p);
  statusStrip.textContent = 'idle';
  updateInputStrip(null);
  renderTabBar();
}

function activeTab() {
  return activeTabId ? getTab(activeTabId) : null;
}

// ------------------------------------------------------------------ tab bar rendering

function renderTabBar() {
  const oldTabs = tabBar.querySelectorAll('.kollab-tab');
  oldTabs.forEach(el => el.remove());

  const countEl = document.getElementById('tab-count');
  if (countEl) countEl.textContent = tabs.length > 0 ? `${tabs.length}` : '';

  for (const tab of tabs) {
    const numPrefix = tab.sessionNumber ? `#${tab.sessionNumber} · ` : '';
    const label = numPrefix
      + (tab.goal ? tab.goal.slice(0, 35) + (tab.goal.length > 35 ? '\u2026' : '') : 'New session');

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
    closeBtn.textContent = '\u00d7';
    closeBtn.className = 'ml-1 text-base leading-none opacity-50 hover:opacity-100 transition px-0.5';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      handleTabClose(tab.id);
    });

    el.appendChild(labelSpan);
    el.appendChild(closeBtn);
    tabBar.appendChild(el);
  }
  if (activeTabId) scrollTabIntoView(activeTabId);
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
    const closingTab = pendingCloseTabId ? getTab(pendingCloseTabId) : null;
    const closingSid = closingTab?.sessionId || '';
    await fetch(`/api/session/stop?session_id=${encodeURIComponent(closingSid)}`, { method: 'POST' });
    closeTab(pendingCloseTabId);
    pendingCloseTabId = null;
  }
});

// ------------------------------------------------------------------ input strip

function updateInputStrip(tab) {
  const isHalted   = tab && tab.state === 'halted';
  const isReadonly = !tab || tab.state === 'readonly' || tab.state === 'done';

  inputTarget.disabled = !isHalted;
  if (!isHalted) inputTarget.value = '';

  const targetSelected = isHalted && inputTarget.value !== '';
  userInput.disabled = !targetSelected;
  btnSend.disabled = !targetSelected;
  userInput.placeholder = isHalted
    ? (targetSelected ? 'Type your instruction\u2026' : 'Select a target first\u2026')
    : 'Session not halted';

  if (isReadonly) {
    btnStop.classList.add('hidden');
    btnResume.classList.add('hidden');
  }
}

inputTarget.addEventListener('change', () => {
  const tab = activeTab();
  updateInputStrip(tab);
  if (inputTarget.value) userInput.focus();
});

// ------------------------------------------------------------------ append helpers

function appendToActiveTab(node) {
  const tab = activeTab();
  if (!tab) return;
  applyThemeToEl(node);
  tab._nodes.push(node);
  dialogue.appendChild(node);
  scrollIfSticky();
}

// Append directly into tab._nodes without touching live DOM.
// Used when reconstructing a non-active tab (e.g. restoreOpenTabs).
function appendNodeToTab(tab, node) {
  applyThemeToEl(node);
  tab._nodes.push(node);
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
  msg.textContent = 'koll\u2660b has shut down.';
  const noBtn = document.getElementById('btn-shutdown-no');
  noBtn.classList.add('hidden');
  const yesBtn = document.getElementById('btn-shutdown-yes');
  yesBtn.textContent = 'Close tab';
  yesBtn.disabled = false;
  yesBtn.onclick = () => window.close();
  document.getElementById('modal-shutdown').classList.remove('hidden');
}

// ------------------------------------------------------------------ event dispatch

function getTabForEvent(msg) {
  if (msg.session_id) {
    const t = getTabBySessionId(msg.session_id);
    if (t) return t;
  }
  return activeTab(); // fallback for events without session_id
}

function handleEvent(msg) {
  switch (msg.type) {
    case 'turn_start':   onTurnStart(msg);   break;
    case 'turn_chunk':   onTurnChunk(msg);   break;
    case 'turn_end':     onTurnEnd(msg);     break;
    case 'turn_cancel':  onTurnCancel(msg);  break;
    case 'state':        onState(msg);       break;
    case 'session_done': onSessionDone(msg); break;
    case 'error':        onError(msg);       break;
  }
}

// ------------------------------------------------------------------ turn card

let currentTurnId = null;
let isStreaming = false;


function buildTurnCard(msg) {
  const isClaude     = msg.actor === 'claude';
  const accentBg     = isClaude ? 'bg-claudeTint' : 'bg-codexTint';
  const accentBorder = isClaude ? 'border-claude'  : 'border-codex';
  const accentText   = isClaude ? 'text-claude'    : 'text-codex';
  const roleLabel    = msg.role;

  const card = document.createElement('div');
  card.id = `turn-${msg.turn_id}`;
  card.className = `rounded-lg border ${accentBorder} ${accentBg} p-3 flex flex-col gap-2`;

  const reasoningBlock = isClaude
    ? `<details id="reasoning-${msg.turn_id}" class="text-muted text-xs hidden">
        <summary class="cursor-pointer hover:text-user select-none">Reasoning</summary>
        <pre id="reasoning-body-${msg.turn_id}" class="whitespace-pre-wrap mt-1 pl-2"></pre>
      </details>`
    : `<div id="reasoning-${msg.turn_id}" class="text-muted text-xs">
        <span class="select-none">Reasoning</span>
        <pre id="reasoning-body-${msg.turn_id}" class="whitespace-pre-wrap mt-1 pl-2 opacity-40 italic">Reasoning streaming not supported by Codex CLI</pre>
      </div>`;

  card.innerHTML = `
    <div class="flex items-center gap-2 text-xs min-w-0">
      <button id="collapse-${msg.turn_id}" class="text-muted text-base opacity-30 cursor-not-allowed transition-transform select-none shrink-0" title="Collapse" disabled>&#8250;</button>
      <span class="font-bold ${accentText} uppercase shrink-0">${msg.actor}</span>
      <span class="text-muted shrink-0">${roleLabel}</span>
      <span id="badge-${msg.turn_id}" class="ml-auto font-mono text-muted shrink-0">${msg.turn_id}</span>
      <span id="verdict-${msg.turn_id}" ${msg.turn_id === 'C-1' ? 'class="text-xs px-1.5 py-0.5 rounded font-bold text-muted bg-white/10"' : ''}>${msg.turn_id === 'C-1' ? 'PROPOSAL' : ''}</span>
    </div>
    <div id="summary-${msg.turn_id}" class="text-xs text-muted italic hidden"></div>
    <div id="collapsible-body-${msg.turn_id}" class="flex flex-col gap-2">
      ${reasoningBlock}
      <details id="result-${msg.turn_id}" open>
        <summary class="cursor-pointer hover:text-user text-xs text-muted select-none">Result</summary>
        <pre id="body-${msg.turn_id}" class="whitespace-pre-wrap text-user thinking mt-1">\u2026</pre>
      </details>
    </div>
  `;
  return card;
}

function applyVerdict(turnId, verdict, root) {
  if (turnId === 'C-1') return;  // C-1 is always PROPOSAL, never a verdict
  const el = root ? root.querySelector(`#verdict-${turnId}`) : document.getElementById(`verdict-${turnId}`);
  if (el && verdict) {
    const colors = {
      AGREE:    'text-verdictAgree bg-verdictAgree/20',
      DISAGREE: 'text-verdictDisagree bg-verdictDisagree/20',
      REVISED:  'text-verdictRevised bg-verdictRevised/20',
    };
    el.className = `text-xs px-1.5 py-0.5 rounded font-bold ${colors[verdict] || ''}`;
    el.textContent = verdict;
  }
}

function removeWaitingMsg() {
  if (waitingMsgEl) { waitingMsgEl.remove(); waitingMsgEl = null; }
}

function enableCollapseChevron(turnId, root) {
  const btn = root ? root.querySelector(`#collapse-${turnId}`) : document.getElementById(`collapse-${turnId}`);
  if (!btn || !btn.disabled) return;  // already enabled
  btn.disabled = false;
  btn.classList.remove('opacity-30', 'cursor-not-allowed');
  btn.classList.add('opacity-60', 'hover:opacity-100', 'cursor-pointer');
  btn.style.transition = 'transform 0.2s';
  let collapsed = false;
  btn.addEventListener('click', () => {
    collapsed = !collapsed;
    const body = document.getElementById(`collapsible-body-${turnId}`);
    if (body) body.style.display = collapsed ? 'none' : '';
    btn.style.transform = collapsed ? 'rotate(90deg)' : '';
    btn.title = collapsed ? 'Expand' : 'Collapse';
  });
}

function onTurnCancel(msg) {
  // Mid-stream halt: leave the card as a permanent observable artifact.
  // Per spec, the agent will NOT pick up where it left off — the next turn
  // (e.g. C-2 after an interrupted C-1) is a fresh response with the
  // directive applied. The partial reasoning/output here is for the
  // viewer's benefit only.
  const targetTab = getTabForEvent(msg);
  const isActiveTab = !targetTab || targetTab.id === activeTabId;

  let body, card;
  if (isActiveTab) {
    body = document.getElementById(`body-${msg.turn_id}`);
    card = document.getElementById(`turn-${msg.turn_id}`);
  } else {
    card = targetTab._nodes.find(n => n.id === 'turn-' + msg.turn_id) || null;
    body = card ? card.querySelector(`#body-${msg.turn_id}`) : null;
  }

  if (body) body.classList.remove('thinking');
  if (card) {
    const note = document.createElement('div');
    note.className = 'text-xs text-muted border-t border-white/10 pt-2 mt-1';
    note.textContent = '\u23f8 interrupted';
    card.appendChild(note);
  }
  isStreaming = false;
  currentTurnId = null;
}

function onTurnStart(msg) {
  currentTurnId = msg.turn_id;
  isStreaming = true;
  const targetTab = getTabForEvent(msg);
  if (targetTab && targetTab.id !== activeTabId) {
    appendNodeToTab(targetTab, buildTurnCard(msg));
  } else {
    removeWaitingMsg();
    appendToActiveTab(buildTurnCard(msg));
  }
}

function onTurnChunk(msg) {
  const targetTab = getTabForEvent(msg);
  const isActiveTab = !targetTab || targetTab.id === activeTabId;

  if (!isActiveTab) {
    const card = targetTab._nodes.find(n => n.id === 'turn-' + msg.turn_id);
    if (!card) return;
    if (msg.kind === 'text') {
      const body = card.querySelector(`#body-${msg.turn_id}`);
      if (body) {
        if (body.classList.contains('thinking')) {
          body.classList.remove('thinking');
          body.textContent = '';
        }
        body.textContent += msg.content;
      }
    } else if (msg.kind === 'reasoning') {
      const reasoningEl = card.querySelector(`#reasoning-${msg.turn_id}`);
      const pre = card.querySelector(`#reasoning-body-${msg.turn_id}`);
      if (reasoningEl && pre) {
        reasoningEl.classList.remove('hidden');
        if (reasoningEl.tagName === 'DETAILS') reasoningEl.open = true;
        pre.textContent += msg.content;
      }
    }
    return;
  }

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
    const reasoningEl = document.getElementById(`reasoning-${msg.turn_id}`);
    const pre = document.getElementById(`reasoning-body-${msg.turn_id}`);
    if (reasoningEl && pre) {
      reasoningEl.classList.remove('hidden');
      if (reasoningEl.tagName === 'DETAILS') reasoningEl.open = true;
      pre.textContent += msg.content;
    }
  }
  scrollIfSticky();
}

function onTurnEnd(msg) {
  const targetTab = getTabForEvent(msg);
  const isActiveTab = !targetTab || targetTab.id === activeTabId;
  const card = !isActiveTab && targetTab
    ? targetTab._nodes.find(n => n.id === 'turn-' + msg.turn_id) || null
    : null;

  applyVerdict(msg.turn_id, msg.verdict, card || undefined);

  if (msg.session_id) {
    const badge = card
      ? card.querySelector(`#badge-${msg.turn_id}`)
      : document.getElementById(`badge-${msg.turn_id}`);
    if (badge) {
      const short = msg.session_id.length > 14 ? msg.session_id.slice(0, 14) + '\u2026' : msg.session_id;
      badge.textContent = `${msg.turn_id} \u00b7 ${short}`;
      badge.title = msg.session_id;
    }
  }
  const body = card
    ? card.querySelector(`#body-${msg.turn_id}`)
    : document.getElementById(`body-${msg.turn_id}`);
  if (body) {
    body.classList.remove('thinking');
    if (msg.text !== undefined) body.textContent = msg.text;
  }
  const summaryEl = card
    ? card.querySelector(`#summary-${msg.turn_id}`)
    : document.getElementById(`summary-${msg.turn_id}`);
  if (summaryEl && msg.summary) {
    summaryEl.textContent = msg.summary;
    summaryEl.classList.remove('hidden');
  }
  enableCollapseChevron(msg.turn_id, card || undefined);
  isStreaming = false;
  currentTurnId = null;
  if (isActiveTab) scrollIfSticky();
}

// ------------------------------------------------------------------ state

function onState(msg) {
  const targetTab = getTabForEvent(msg);
  const isActiveTab = !targetTab || targetTab.id === activeTabId;

  const stateLabels = {
    idle:          'idle',
    fanning_out:   'sending goal to both agents\u2026',
    claude_turn:   `claude thinking\u2026 \u00b7 round ${msg.round}`,
    codex_turn:    `codex thinking\u2026 \u00b7 round ${msg.round}`,
    awaiting_user: 'awaiting input',
    halted:        'halted \u2014 click Resume to continue',
    done:          'session complete',
  };

  const sessionRunning = ['claude_turn', 'codex_turn', 'fanning_out'].includes(msg.state);

  if (isActiveTab) {
    statusStrip.textContent = stateLabels[msg.state] || msg.state;
    btnStop.classList.toggle('hidden', !sessionRunning);
    if (sessionRunning) {
      btnStop.disabled = false;
      btnStop.textContent = 'Stop';
      btnStop.classList.remove('opacity-50');
    }
    btnResume.classList.toggle('hidden', msg.state !== 'halted');
  }

  const tab = targetTab || activeTab();
  if (tab) {
    // Capture session_number from fanning_out broadcast (first state event for a new session)
    if (msg.state === 'fanning_out' && msg.session_number) {
      tab.sessionNumber = msg.session_number;
      tab.sessionId = tab.sessionId || msg.session_id || null;
      if (msg.claude_model) tab.claudeModel = msg.claude_model;
      if (msg.codex_model)  tab.codexModel  = msg.codex_model;
      if (msg.round_limit)  tab.roundLimit  = msg.round_limit;
      if (isActiveTab) {
        // Update goal card number label now that we have it
        const goalNumEl = document.getElementById('goal-session-num');
        if (goalNumEl) goalNumEl.textContent = `Session #${msg.session_number}`;
        const goalMetaEl = document.getElementById('goal-meta-models');
        if (goalMetaEl && msg.claude_model && msg.codex_model) {
          goalMetaEl.textContent = `Claude: ${msg.claude_model} · Codex: ${msg.codex_model} · rounds: ${msg.round_limit ?? '?'}`;
        }
      }
      renderTabBar();
    }
    if (msg.state === 'halted') tab.state = 'halted';
    else if (msg.state === 'done') tab.state = 'done';
    else if (sessionRunning) tab.state = 'active';
    if (tab.id === activeTabId) updateInputStrip(tab);
  }
}

function buildExportButton(sessionId, sessionNumber) {
  const numStr = sessionNumber ? String(sessionNumber).padStart(3, '0') : '000';
  const today = new Date().toISOString().slice(0, 10);
  const btn = document.createElement('a');
  btn.href = `/api/sessions/${sessionId}/export${sessionNumber ? `?session_number=${sessionNumber}` : ''}`;
  btn.download = `kollab-${numStr}-${today}.md`;
  btn.className = 'text-xs text-muted hover:text-user border border-white/20 rounded px-2 py-1 transition';
  btn.textContent = '\u2193 Export .md';
  return btn;
}

function onSessionDone(msg) {
  const reasonsFull = {
    convergence: '\u2713 Both agents reached agreement.',
    round_limit: `\u26a0 Round limit reached${msg.round_limit ? ' (' + msg.round_limit + ' rounds)' : ''}.`,
    token_limit: '\u26a0 Token budget exhausted.',
    halted:      '\u23f9 Session halted.',
    expired:     '\u23f3 Stopped / expired.',
  };
  const reasonsShort = {
    convergence: '\u2713 Converged',
    round_limit: `\u26a0 Round limit${msg.round_limit ? ' (' + msg.round_limit + ')' : ''}`,
    token_limit: '\u26a0 Token limit',
    halted:      '\u23f9 Halted',
    expired:     '\u23f3 Expired',
  };
  const verdictColors = {
    convergence: 'text-verdictAgree',
    round_limit: 'text-verdictRevised',
    token_limit: 'text-verdictRevised',
    halted: 'text-muted',
    expired: 'text-muted',
  };
  const targetTab = getTabForEvent(msg);
  const isActiveTab = !targetTab || targetTab.id === activeTabId;
  const tab = targetTab || activeTab();

  // Defense in depth: if onState/fanning_out or the POST /api/session
  // response did not populate these (race conditions on fast sessions),
  // trust the session_done payload — backend always has both fields.
  if (tab) {
    if (msg.session_id && !tab.sessionId) tab.sessionId = msg.session_id;
    if (msg.session_number && !tab.sessionNumber) tab.sessionNumber = msg.session_number;
    tab.endedAt = new Date();
    if (tab._timerInterval) { clearInterval(tab._timerInterval); tab._timerInterval = null; }
  }

  if (!isActiveTab) {
    // Background session done: update state but skip all live DOM mutations
    if (tab) tab.state = 'done';
    renderTabBar();
    saveOpenTabs();
    loadHistory();
    return;
  }

  // Update live goal card: inject verdict pill + read-only label + export
  const goalNumEl = document.getElementById('goal-session-num');
  if (goalNumEl) {
    const parent = goalNumEl.parentElement;
    // Replace the plain session-num span with a flex row of chips
    const metaRow = document.createElement('div');
    metaRow.className = 'flex items-center gap-2';
    goalNumEl.className = 'text-xs text-muted opacity-50';
    metaRow.appendChild(goalNumEl.cloneNode(true));
    const pill = document.createElement('span');
    pill.className = `text-xs px-1.5 py-0.5 rounded font-bold ${verdictColors[msg.reason] || 'text-muted'} bg-white/10`;
    pill.textContent = reasonsShort[msg.reason] || msg.reason;
    metaRow.appendChild(pill);
    const roLabel = document.createElement('span');
    roLabel.className = 'text-xs text-muted opacity-50';
    roLabel.textContent = 'read-only';
    metaRow.appendChild(roLabel);
    if (tab && tab.sessionId) metaRow.appendChild(buildExportButton(tab.sessionId, tab.sessionNumber));
    parent.replaceChild(metaRow, goalNumEl);
  }

  if (tab && tab.startedAt && tab.endedAt && isActiveTab) {
    const endedEl   = document.getElementById(`goal-ended-${tab.id}`);
    const elapsedEl = document.getElementById(`goal-elapsed-${tab.id}`);
    if (endedEl)   { endedEl.textContent = 'ended ' + fmtTime(tab.endedAt); endedEl.classList.remove('hidden'); }
    if (elapsedEl) elapsedEl.textContent = fmtElapsed(tab.endedAt - tab.startedAt);
  }

  // Bottom banner: reason text + export button
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted flex items-center justify-center gap-3';
  const bannerText = document.createElement('span');
  bannerText.textContent = reasonsFull[msg.reason] || `Session ended: ${msg.reason}`;
  banner.appendChild(bannerText);
  if (tab && tab.sessionId) banner.appendChild(buildExportButton(tab.sessionId, tab.sessionNumber));
  if (tab && tab.startedAt && tab.endedAt) {
    const timingSpan = document.createElement('span');
    timingSpan.className = 'font-mono text-xs text-muted opacity-40 ml-auto';
    timingSpan.textContent = `started ${fmtTime(tab.startedAt)} · ended ${fmtTime(tab.endedAt)} · ${fmtElapsed(tab.endedAt - tab.startedAt)}`;
    banner.appendChild(timingSpan);
  }
  appendToActiveTab(banner);

  if (tab) tab.state = 'done';

  btnStop.classList.add('hidden');
  statusStrip.textContent = `done \u2014 ${msg.reason}`;
  updateInputStrip(tab);
  renderTabBar();
  scrollIfSticky();
  saveOpenTabs();
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
  btnStop.textContent = 'Stopping\u2026';
  btnStop.classList.add('opacity-50');
  const tab = activeTab();
  const sid = tab?.sessionId || '';
  const res = await fetch(`/api/session/stop?session_id=${encodeURIComponent(sid)}`, { method: 'POST' });
  if (!res.ok) {
    btnStop.disabled = false;
    btnStop.textContent = 'Stop';
    btnStop.classList.remove('opacity-50');
  }
});

btnResume.addEventListener('click', () => {
  if (inputTarget.value && userInput.value.trim()) {
    showUnsentToast();
    return;
  }
  doResume();
});

function doResume() {
  const tab = activeTab();
  const sid = tab?.sessionId || '';
  fetch(`/api/session/resume?session_id=${encodeURIComponent(sid)}`, { method: 'POST' });
  btnResume.classList.add('hidden');
  if (tab) { tab.state = 'active'; updateInputStrip(tab); }
}

function showUnsentToast() {
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

  const targetLabels = { claude: 'CLAUDE', codex: 'CODEX', both: 'CLAUDE, CODEX' };
  const card = document.createElement('div');
  card.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
  card.innerHTML = `
    <div class="text-xs text-muted uppercase">DIRECTIVE \u2192 ${targetLabels[target] || target.toUpperCase()}</div>
    <pre class="whitespace-pre-wrap text-user">${escHtml(text)}</pre>
  `;
  appendToActiveTab(card);

  const inputTab = activeTab();
  const inputSid = inputTab?.sessionId || '';
  await fetch(`/api/session/input?session_id=${encodeURIComponent(inputSid)}`, {
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

// ------------------------------------------------------------------ Esc to close modals

const MODAL_ESC_MAP = [
  { modalId: 'modal-new-session',    cancelId: 'btn-modal-cancel' },
  { modalId: 'modal-configure',      cancelId: 'btn-config-cancel' },
  { modalId: 'modal-shutdown',       cancelId: 'btn-shutdown-no' },
  { modalId: 'modal-confirm-close',  cancelId: 'btn-confirm-close-no' },
  { modalId: 'modal-confirm-delete', cancelId: 'btn-confirm-delete-no' },
];

document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  for (const { modalId, cancelId } of MODAL_ESC_MAP) {
    const modal = document.getElementById(modalId);
    if (modal && !modal.classList.contains('hidden')) {
      document.getElementById(cancelId)?.click();
      break;
    }
  }
});

// ------------------------------------------------------------------ new session modal

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

document.getElementById('btn-close-all-tabs').addEventListener('click', () => {
  const toClose = tabs.filter(t => t.state !== 'active').map(t => t.id);
  for (const id of toClose) closeTab(id);
});

btnNewSession.addEventListener('click', async () => {
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

  const goalCard = document.createElement('div');
  goalCard.className = 'kollab-goal-card rounded-lg border border-white/10 bg-panel p-3 flex flex-col gap-1.5';
  goalCard.innerHTML = `
    <div class="flex items-center gap-2 min-w-0">
      <span class="text-xs text-muted uppercase shrink-0">goal</span>
      <span id="goal-text-${tab.id}" class="text-xs text-user flex-1 overflow-hidden" style="display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;">${escHtml(goal)}</span>
      <button id="goal-expand-${tab.id}" class="text-xs text-muted opacity-40 hover:opacity-80 shrink-0 hidden">↓</button>
      <span id="goal-session-num" class="text-xs text-muted opacity-50 shrink-0"></span>
    </div>
    <div class="flex items-center justify-between gap-2 min-w-0">
      <div class="flex items-center gap-3 min-w-0">
        <button id="collapse-toggle-${tab.id}" class="text-xs text-muted opacity-40 hover:opacity-80 transition shrink-0">− collapse all</button>
        <span id="goal-meta-models" class="text-xs text-muted opacity-40 truncate"></span>
      </div>
      <div id="goal-timing-${tab.id}" class="flex items-center gap-2 font-mono text-xs text-muted opacity-40 shrink-0">
        <span id="goal-started-${tab.id}"></span>
        <span id="goal-ended-${tab.id}" class="hidden"></span>
        <span id="goal-elapsed-${tab.id}"></span>
      </div>
    </div>
  `;
  appendToActiveTab(goalCard);

  tab.startedAt = new Date();
  const startedSpan = document.getElementById(`goal-started-${tab.id}`);
  if (startedSpan) startedSpan.textContent = 'started ' + fmtTime(tab.startedAt);
  tab._timerInterval = setInterval(() => {
    const el = document.getElementById(`goal-elapsed-${tab.id}`);
    if (el) el.textContent = '⏱ ' + fmtElapsed(Date.now() - tab.startedAt.getTime());
  }, 1000);

  (function wireCollapseToggle(tabId) {
    let allCollapsed = false;
    const btn = document.getElementById(`collapse-toggle-${tabId}`);
    if (!btn) return;
    btn.addEventListener('click', () => {
      allCollapsed = !allCollapsed;
      btn.textContent = allCollapsed ? '+ expand all' : '− collapse all';
      dialogue.querySelectorAll('[id^="collapsible-body-"]').forEach(body => {
        body.style.display = allCollapsed ? 'none' : '';
      });
      dialogue.querySelectorAll('[id^="collapse-"]:not([id^="collapse-toggle"])').forEach(chevron => {
        if (!chevron.disabled) {
          chevron.style.transform = allCollapsed ? 'rotate(90deg)' : '';
          chevron.title = allCollapsed ? 'Expand' : 'Collapse';
        }
      });
    });
  })(tab.id);

  requestAnimationFrame(() => {
    const textEl = document.getElementById(`goal-text-${tab.id}`);
    const expandBtn = document.getElementById(`goal-expand-${tab.id}`);
    if (!textEl || !expandBtn) return;
    if (textEl.scrollHeight > textEl.clientHeight + 2) {
      expandBtn.classList.remove('hidden');
      let expanded = false;
      expandBtn.addEventListener('click', () => {
        expanded = !expanded;
        if (expanded) {
          textEl.style.webkitLineClamp = 'unset';
          textEl.style.display = 'block';
          expandBtn.textContent = '↑';
        } else {
          textEl.style.display = '-webkit-box';
          textEl.style.webkitLineClamp = '1';
          expandBtn.textContent = '↓';
        }
      });
    }
  });

  waitingMsgEl = document.createElement('p');
  waitingMsgEl.className = 'text-muted text-center mt-16';
  waitingMsgEl.textContent = 'Waiting for Claude to respond\u2026';
  appendToActiveTab(waitingMsgEl);

  const res = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const data = await res.json();
    tab.sessionId = data.session_id;
    // session_number is set from the fanning_out WS broadcast
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
  document.getElementById('btn-shutdown-yes').textContent = 'Quitting\u2026';
  await fetch('/api/shutdown', { method: 'POST' });
  document.body.innerHTML = '<p style="color:#888;font-family:monospace;padding:2rem">koll\u2660b has shut down. You can close this tab.</p>';
});

// ------------------------------------------------------------------ configure modal

document.getElementById('btn-configure').addEventListener('click', async () => {
  const res = await fetch('/api/config');
  const cfg = await res.json();
  const form = document.getElementById('config-form');
  form.innerHTML = '';
  form.className = 'flex flex-col gap-4';

  // ---- helper: build a single label+input field ----
  function makeField(f, targetEl) {
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
    } else if (f.type === 'logging_level') {
      input = document.createElement('select');
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none disabled:opacity-40';
      for (const [val, lbl] of [['info', 'info'], ['debug', 'debug']]) {
        const o = document.createElement('option');
        o.value = val; o.textContent = lbl;
        if ((cfg.logging_level || 'info') === val) o.selected = true;
        input.appendChild(o);
      }
      input.id = 'cfg-logging-level';
    } else {
      input = document.createElement('input');
      input.type = f.type || 'text';
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none';
      input.value = cfg[f.key] ?? '';
    }
    input.name = f.key;
    label.appendChild(input);
    targetEl.appendChild(label);
  }

  // ---- agent columns ----
  const agentRow = document.createElement('div');
  agentRow.className = 'flex gap-4';

  const claudeCol = document.createElement('div');
  claudeCol.className = 'flex-1 flex flex-col gap-3';
  const claudeHeader = document.createElement('p');
  claudeHeader.className = 'text-xs text-claude uppercase tracking-wider font-bold';
  claudeHeader.textContent = 'Claude';
  claudeCol.appendChild(claudeHeader);
  for (const f of [
    { key: 'claude_binary', label: 'Binary path' },
    { key: 'claude_model',  label: 'Model', type: 'select', agentKey: 'claude' },
    { key: 'claude_workdir',label: 'Working dir' },
  ]) makeField(f, claudeCol);

  const codexCol = document.createElement('div');
  codexCol.className = 'flex-1 flex flex-col gap-3';
  const codexHeader = document.createElement('p');
  codexHeader.className = 'text-xs text-codex uppercase tracking-wider font-bold';
  codexHeader.textContent = 'Codex';
  codexCol.appendChild(codexHeader);
  for (const f of [
    { key: 'codex_binary', label: 'Binary path' },
    { key: 'codex_model',  label: 'Model', type: 'select', agentKey: 'codex' },
    { key: 'codex_workdir',label: 'Working dir' },
  ]) makeField(f, codexCol);

  agentRow.appendChild(claudeCol);
  agentRow.appendChild(codexCol);
  form.appendChild(agentRow);

  // ---- session settings grid ----
  const sessionSep = document.createElement('div');
  sessionSep.className = 'border-t border-white/10 pt-3';
  sessionSep.innerHTML = '<p class="text-xs text-muted uppercase tracking-wider">Session</p>';
  form.appendChild(sessionSep);

  const sessionGrid = document.createElement('div');
  sessionGrid.className = 'grid grid-cols-2 gap-x-4 gap-y-3';
  for (const f of [
    { key: 'round_limit',       label: 'Round limit',                      type: 'number' },
    { key: 'halt_timeout_secs', label: 'Halt timeout (seconds, 0 = never)', type: 'number' },
    { key: 'port',              label: 'Port',                              type: 'number' },
    { key: 'sessions_dir',      label: 'Sessions dir' },
  ]) makeField(f, sessionGrid);
  form.appendChild(sessionGrid);

  // ---- MCP section ----
  const mcpSep = document.createElement('div');
  mcpSep.className = 'border-t border-white/10 pt-3';
  mcpSep.innerHTML = '<p class="text-xs text-muted uppercase tracking-wider">MCP Tools</p>';
  form.appendChild(mcpSep);

  const mcpRow = document.createElement('div');
  mcpRow.className = 'flex gap-4';

  const mcpLeft = document.createElement('div');
  mcpLeft.className = 'flex-1 flex flex-col gap-3';
  const fsLabel = document.createElement('label');
  fsLabel.className = 'flex flex-col gap-1 text-xs text-muted';
  fsLabel.textContent = 'Filesystem MCP enabled';
  const fsWrapper = document.createElement('div');
  fsWrapper.className = 'flex items-center gap-2 mt-1';
  const fsCheck = document.createElement('input');
  fsCheck.type = 'checkbox'; fsCheck.name = 'mcp_filesystem_enabled';
  fsCheck.className = 'w-4 h-4 accent-claude';
  fsCheck.checked = !!cfg.mcp_filesystem_enabled;
  fsWrapper.appendChild(fsCheck);
  fsLabel.appendChild(fsWrapper);
  mcpLeft.appendChild(fsLabel);

  const mcpRight = document.createElement('div');
  mcpRight.className = 'flex-1 flex flex-col gap-3';
  const fsPathsLabel = document.createElement('label');
  fsPathsLabel.className = 'flex flex-col gap-1 text-xs text-muted';
  fsPathsLabel.textContent = 'Filesystem allowed paths (one per line)';
  const fsPathsInput = document.createElement('textarea');
  fsPathsInput.rows = 3; fsPathsInput.name = 'mcp_filesystem_paths';
  fsPathsInput.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none font-mono text-xs';
  fsPathsInput.value = Array.isArray(cfg.mcp_filesystem_paths) ? cfg.mcp_filesystem_paths.join('\n') : '';
  fsPathsInput.placeholder = 'Leave empty to use agent workdir';
  fsPathsLabel.appendChild(fsPathsInput);
  mcpRight.appendChild(fsPathsLabel);

  mcpRow.appendChild(mcpLeft);
  mcpRow.appendChild(mcpRight);
  form.appendChild(mcpRow);

  const githubSep = document.createElement('div');
  githubSep.className = 'border-t border-white/10 pt-3';
  githubSep.innerHTML = '<p class="text-xs text-muted uppercase tracking-wider">GitHub MCP — coming soon</p>';
  form.appendChild(githubSep);

  // ---- logging section ----
  const logSep = document.createElement('div');
  logSep.className = 'border-t border-white/10 pt-3';
  logSep.innerHTML = '<p class="text-xs text-muted uppercase tracking-wider">Logging</p>';
  form.appendChild(logSep);

  const logRow = document.createElement('div');
  logRow.className = 'flex items-end gap-4';

  const logToggleLabel = document.createElement('label');
  logToggleLabel.className = 'flex flex-col gap-1 text-xs text-muted';
  logToggleLabel.textContent = 'Enable logging to ~/.kollab/kollab.log';
  const logToggleWrapper = document.createElement('div');
  logToggleWrapper.className = 'flex items-center gap-2 mt-1';
  const logToggle = document.createElement('input');
  logToggle.type = 'checkbox'; logToggle.name = 'logging_enabled';
  logToggle.className = 'w-4 h-4 accent-claude';
  logToggle.checked = !!cfg.logging_enabled;
  logToggleWrapper.appendChild(logToggle);
  logToggleLabel.appendChild(logToggleWrapper);
  logRow.appendChild(logToggleLabel);

  const logLevelLabel = document.createElement('label');
  logLevelLabel.className = 'flex flex-col gap-1 text-xs text-muted';
  logLevelLabel.textContent = 'Log level';
  const logLevelSelect = document.createElement('select');
  logLevelSelect.name = 'logging_level'; logLevelSelect.id = 'cfg-logging-level';
  logLevelSelect.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none disabled:opacity-40';
  for (const [val, lbl] of [['info', 'info'], ['debug', 'debug']]) {
    const o = document.createElement('option');
    o.value = val; o.textContent = lbl;
    if ((cfg.logging_level || 'info') === val) o.selected = true;
    logLevelSelect.appendChild(o);
  }
  logLevelLabel.appendChild(logLevelSelect);
  logRow.appendChild(logLevelLabel);
  form.appendChild(logRow);

  // ---- webhooks section ----
  const whSep = document.createElement('div');
  whSep.className = 'border-t border-white/10 pt-3';
  whSep.innerHTML = '<p class="text-xs text-muted uppercase tracking-wider">Webhooks</p>';
  form.appendChild(whSep);

  const whRow = document.createElement('div');
  whRow.className = 'flex items-end gap-4';

  const whToggleLabel = document.createElement('label');
  whToggleLabel.className = 'flex flex-col gap-1 text-xs text-muted';
  whToggleLabel.textContent = 'Enable webhook emission';
  const whToggleWrapper = document.createElement('div');
  whToggleWrapper.className = 'flex items-center gap-2 mt-1';
  const whToggle = document.createElement('input');
  whToggle.type = 'checkbox'; whToggle.id = 'cfg-webhooks-enabled';
  whToggle.className = 'w-4 h-4 accent-claude';
  whToggle.checked = !!(cfg.webhooks && cfg.webhooks.enabled);
  whToggleWrapper.appendChild(whToggle);
  whToggleLabel.appendChild(whToggleWrapper);
  whRow.appendChild(whToggleLabel);

  const whTimeoutLabel = document.createElement('label');
  whTimeoutLabel.className = 'flex flex-col gap-1 text-xs text-muted';
  whTimeoutLabel.textContent = 'Timeout (seconds)';
  const whTimeoutInput = document.createElement('input');
  whTimeoutInput.type = 'number'; whTimeoutInput.id = 'cfg-webhooks-timeout';
  whTimeoutInput.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none w-20';
  whTimeoutInput.value = (cfg.webhooks && cfg.webhooks.timeout_secs != null) ? cfg.webhooks.timeout_secs : 5;
  whTimeoutLabel.appendChild(whTimeoutInput);
  whRow.appendChild(whTimeoutLabel);
  form.appendChild(whRow);

  const whUrlsRow = document.createElement('div');
  whUrlsRow.className = 'flex gap-4 mt-2';

  const whTargetsLabel = document.createElement('label');
  whTargetsLabel.className = 'flex-1 flex flex-col gap-1 text-xs text-muted';
  whTargetsLabel.textContent = 'Webhook targets (one URL per line)';
  const whTargetsInput = document.createElement('textarea');
  whTargetsInput.rows = 3; whTargetsInput.id = 'cfg-webhooks-targets';
  whTargetsInput.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none font-mono text-xs';
  whTargetsInput.value = Array.isArray(cfg.webhooks && cfg.webhooks.targets) ? cfg.webhooks.targets.join('\n') : '';
  whTargetsInput.placeholder = 'https://your-app.com/hooks/kollab';
  whTargetsLabel.appendChild(whTargetsInput);
  whUrlsRow.appendChild(whTargetsLabel);

  const whSlackLabel = document.createElement('label');
  whSlackLabel.className = 'flex-1 flex flex-col gap-1 text-xs text-muted';
  whSlackLabel.textContent = 'Slack webhook URLs (one per line)';
  const whSlackInput = document.createElement('textarea');
  whSlackInput.rows = 3; whSlackInput.id = 'cfg-webhooks-slack';
  whSlackInput.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none font-mono text-xs';
  whSlackInput.value = Array.isArray(cfg.webhooks && cfg.webhooks.slack_targets) ? cfg.webhooks.slack_targets.join('\n') : '';
  whSlackInput.placeholder = 'https://hooks.slack.com/services/…';
  whSlackLabel.appendChild(whSlackInput);
  whUrlsRow.appendChild(whSlackLabel);
  form.appendChild(whUrlsRow);

  const _allEvents = ['session_start','turn_end','disagreement','convergence','round_limit','halt','directive','session_end'];
  const _enabledEvents = new Set((cfg.webhooks && Array.isArray(cfg.webhooks.events)) ? cfg.webhooks.events : _allEvents);

  const whEventsSep = document.createElement('div');
  whEventsSep.className = 'mt-2';
  whEventsSep.innerHTML = '<p class="text-xs text-muted mb-1">Events to emit</p>';
  form.appendChild(whEventsSep);

  const whEventsGrid = document.createElement('div');
  whEventsGrid.className = 'grid grid-cols-2 gap-x-4 gap-y-1';
  for (const evt of _allEvents) {
    const evLabel = document.createElement('label');
    evLabel.className = 'flex items-center gap-2 text-xs text-muted';
    const evCheck = document.createElement('input');
    evCheck.type = 'checkbox'; evCheck.dataset.whEvent = evt;
    evCheck.className = 'w-3.5 h-3.5 accent-claude';
    evCheck.checked = _enabledEvents.has(evt);
    evLabel.appendChild(evCheck);
    evLabel.appendChild(document.createTextNode(evt));
    whEventsGrid.appendChild(evLabel);
  }
  form.appendChild(whEventsGrid);

  document.getElementById('modal-configure').classList.remove('hidden');

  // Logging toggle/dropdown interlock
  const syncLevel = () => { logLevelSelect.disabled = !logToggle.checked; };
  syncLevel();
  logToggle.addEventListener('change', syncLevel);
});

document.getElementById('btn-config-cancel').addEventListener('click', () => {
  document.getElementById('modal-configure').classList.add('hidden');
});

document.getElementById('btn-config-save').addEventListener('click', async () => {
  const form = document.getElementById('config-form');
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') {
      data[el.name] = el.checked;
    } else if (el.tagName === 'TEXTAREA' && el.name === 'mcp_filesystem_paths') {
      data[el.name] = el.value.split('\n').map(s => s.trim()).filter(Boolean);
    } else if (el.type === 'number') {
      data[el.name] = Number(el.value);
    } else {
      data[el.name] = el.value;
    }
  }

  // Collect webhook fields (by ID, not name, to avoid the generic loop above)
  const whEnabledEl   = document.getElementById('cfg-webhooks-enabled');
  const whTimeoutEl   = document.getElementById('cfg-webhooks-timeout');
  const whTargetsEl   = document.getElementById('cfg-webhooks-targets');
  const whSlackEl     = document.getElementById('cfg-webhooks-slack');
  if (whEnabledEl) {
    const checkedEvents = Array.from(form.querySelectorAll('[data-wh-event]'))
      .filter(cb => cb.checked)
      .map(cb => cb.dataset.whEvent);
    data['webhooks'] = {
      enabled:       whEnabledEl.checked,
      targets:       whTargetsEl ? whTargetsEl.value.split('\n').map(s => s.trim()).filter(Boolean) : [],
      slack_targets: whSlackEl   ? whSlackEl.value.split('\n').map(s => s.trim()).filter(Boolean)   : [],
      events:        checkedEvents,
      timeout_secs:  whTimeoutEl ? (Number(whTimeoutEl.value) || 5) : 5,
    };
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
    errEl.textContent = result.errors.join(' \u00b7 ');
    errEl.classList.remove('hidden');
  }
});

// ------------------------------------------------------------------ history pane

let _historyFilter = null;
let _pendingDeleteId = null;
let _allSessions = [];

document.querySelectorAll('.history-filter').forEach(btn => {
  btn.addEventListener('click', () => {
    const f = btn.dataset.filter;
    _historyFilter = _historyFilter === f ? null : f;
    document.querySelectorAll('.history-filter').forEach(b => {
      const active = b.dataset.filter === _historyFilter;
      b.style.opacity = active ? '1' : '0.30';
      b.style.outline = active ? '1.5px solid rgba(255,255,255,0.4)' : 'none';
    });
    renderHistoryList(_allSessions);
  });
});

document.getElementById('btn-confirm-delete-no').addEventListener('click', () => {
  _pendingDeleteId = null;
  document.getElementById('modal-confirm-delete').classList.add('hidden');
});

document.getElementById('btn-confirm-delete-yes').addEventListener('click', async () => {
  document.getElementById('modal-confirm-delete').classList.add('hidden');
  if (!_pendingDeleteId) return;
  const sid = _pendingDeleteId;
  _pendingDeleteId = null;
  await fetch(`/api/sessions/${sid}`, { method: 'DELETE' });
  const openTab = getTabBySessionId(sid);
  if (openTab) closeTab(openTab.id);
  _allSessions = _allSessions.filter(s => s.session_id !== sid);
  renderHistoryList(_allSessions);
  const hCount = document.getElementById('history-count');
  if (hCount) hCount.textContent = _allSessions.length > 0 ? `${_allSessions.length}` : '';
});

function renderHistoryList(sessions) {
  const filtered = _historyFilter
    ? sessions.filter(s => s.end_reason === _historyFilter ||
        (_historyFilter === 'halted' && s.end_reason === 'expired'))
    : sessions;

  historyList.innerHTML = '';
  if (!filtered.length) {
    const msg = _historyFilter ? 'No matching sessions.' : 'No sessions yet.';
    historyList.innerHTML = `<p class="text-muted text-xs px-3 py-4">${msg}</p>`;
    return;
  }

  const pillStyles = { convergence: 'text-verdictAgree', round_limit: 'text-verdictRevised', halted: 'text-muted', expired: 'text-muted' };
  const pillLabels = { convergence: '\u2713 converged', round_limit: '\u26a0 round limit', halted: '\u23f9 halted', expired: '\u23f3 expired' };
  const activeSessionId = activeTab()?.sessionId || null;

  for (const s of filtered) {
    const row = document.createElement('div');
    row.className = 'relative group text-left w-full px-3 py-2 border-b border-white/5 hover:bg-white/5 transition flex flex-col gap-0.5 cursor-pointer';
    row.dataset.sessionId = s.session_id;

    const goalEl = document.createElement('span');
    goalEl.className = 'text-xs text-user truncate pr-5';
    const numPrefix = s.session_number ? `#${s.session_number} · ` : '';
    goalEl.textContent = numPrefix + (s.goal || '').slice(0, 40) + ((s.goal || '').length > 40 ? '\u2026' : '');

    const metaEl = document.createElement('span');
    metaEl.className = 'text-xs text-muted flex items-center gap-1';
    const tsEl = document.createElement('span');
    tsEl.textContent = s.started_at ? relativeTime(s.started_at) : '';
    metaEl.appendChild(tsEl);
    if (s.end_reason) {
      const pillEl = document.createElement('span');
      pillEl.className = `text-xs ${pillStyles[s.end_reason] || 'text-muted'}`;
      pillEl.textContent = pillLabels[s.end_reason] || s.end_reason;
      metaEl.appendChild(document.createTextNode(' \u00b7 '));
      metaEl.appendChild(pillEl);
    }

    const delBtn = document.createElement('button');
    delBtn.className = 'absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-40 hover:!opacity-100 transition text-muted hover:text-verdictDisagree text-sm leading-none px-1';
    delBtn.textContent = '\u00d7';
    delBtn.title = 'Remove from history';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _pendingDeleteId = s.session_id;
      document.getElementById('modal-confirm-delete').classList.remove('hidden');
    });

    row.appendChild(goalEl);
    row.appendChild(metaEl);
    row.appendChild(delBtn);
    if (activeSessionId && s.session_id === activeSessionId) {
      row.style.borderLeft = '2px solid #cc6600';
      row.style.paddingLeft = 'calc(0.75rem - 2px)';
      row.style.backgroundColor = 'rgba(204, 102, 0, 0.06)';
    }
    row.addEventListener('click', () => openHistorySession(s.session_id, s.goal, s.session_number));
    historyList.appendChild(row);
  }
}

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

  _allSessions = sessions;
  historyList.scrollTop = 0;

  const hCount = document.getElementById('history-count');
  if (hCount) hCount.textContent = sessions.length > 0 ? `${sessions.length}` : '';

  renderHistoryList(sessions);
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

async function openHistorySession(sessionId, goal, sessionNumber) {
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

  const tab = createTab(goal || sessionId, sessionId, 'readonly', sessionNumber || 0);
  switchTab(tab.id);
  stickyBottom = false;
  reconstructSession(tab, data.events);
  dialogue.scrollTop = 0;
  tab.scrollTop = 0;
  updateInputStrip(tab);
  saveOpenTabs();
}

// ------------------------------------------------------------------ session reconstruction

// Background restore: write into tab._nodes only, never touch live DOM.
function reconstructSessionIntoTab(tab, events) {
  _reconstructEvents(events, node => appendNodeToTab(tab, node), tab.sessionNumber);
}

// Foreground open: write into active tab via appendToActiveTab (touches live DOM).
function reconstructSession(tab, events) {
  _reconstructEvents(events, node => appendToActiveTab(node), tab.sessionNumber);
}

// Core reconstruction logic. appendFn adds a node wherever appropriate.
// Maintains a local cardMap so turn_end/turn_interrupted can find their card
// without relying on document.getElementById (which fails for off-DOM nodes).
function _reconstructEvents(events, appendFn, fallbackSessionNumber) {
  const cardMap = {}; // turn_id -> card DOM node
  let _sessionId = null;
  let _sessionNumber = fallbackSessionNumber || 0;
  let _claudeModel = '';
  let _codexModel  = '';
  let _roundLimit  = null;
  let _startedAt   = null;
  let goalCard = null; // hoisted so session_end can update it

  for (const ev of events) {
    const kind = ev.kind;

    if (kind === 'session_start') {
      const sessionNum = ev.payload?.session_number || fallbackSessionNumber || 0;
      _sessionId = ev.session_id || null;
      _sessionNumber = sessionNum;
      _claudeModel = ev.payload?.claude_model || '';
      _codexModel  = ev.payload?.codex_model  || '';
      _roundLimit  = ev.payload?.round_limit  ?? null;
      _startedAt   = ev.payload?.started_at ? new Date(ev.payload.started_at) : null;
      const metaModels = (_claudeModel && _codexModel)
        ? `Claude: ${_claudeModel} · Codex: ${_codexModel} · rounds: ${_roundLimit ?? '?'}`
        : '';
      goalCard = document.createElement('div');
      goalCard.className = 'kollab-goal-card rounded-lg border border-white/10 bg-panel p-3 flex flex-col gap-1.5';
      goalCard.id = 'recon-goal-card';
      goalCard.innerHTML = `
        <div class="flex items-center gap-2 min-w-0">
          <span class="text-xs text-muted uppercase shrink-0">goal</span>
          <span id="goal-text-recon-${_sessionId || 'x'}" class="text-xs text-user flex-1 overflow-hidden" style="display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;">${escHtml(ev.payload?.goal || '')}</span>
          <button id="goal-expand-recon-${_sessionId || 'x'}" class="text-xs text-muted opacity-40 hover:opacity-80 shrink-0 hidden">↓</button>
          <div class="flex items-center gap-2 shrink-0" id="recon-goal-meta">
            ${sessionNum ? `<span class="text-xs text-muted opacity-50">Session #${sessionNum}</span>` : ''}
          </div>
        </div>
        <div class="flex items-center justify-between gap-2 min-w-0">
          <div class="flex items-center gap-3 min-w-0">
            <button id="collapse-toggle-recon" class="text-xs text-muted opacity-40 hover:opacity-80 transition shrink-0">− collapse all</button>
            ${metaModels ? `<span class="text-xs text-muted opacity-40 truncate">${escHtml(metaModels)}</span>` : '<span></span>'}
          </div>
          <div class="flex items-center gap-2 font-mono text-xs text-muted opacity-40 shrink-0" id="recon-goal-timing">
            ${_startedAt ? `<span>started ${fmtTime(_startedAt)}</span>` : ''}
          </div>
        </div>
      `;
      appendFn(goalCard);

      const reconToggleBtn = goalCard.querySelector('#collapse-toggle-recon');
      if (reconToggleBtn) {
        let allCollapsed = false;
        reconToggleBtn.addEventListener('click', () => {
          allCollapsed = !allCollapsed;
          reconToggleBtn.textContent = allCollapsed ? '+ expand all' : '− collapse all';
          const container = goalCard.parentNode;
          if (!container) return;
          container.querySelectorAll('[id^="collapsible-body-"]').forEach(body => {
            body.style.display = allCollapsed ? 'none' : '';
          });
          container.querySelectorAll('[id^="collapse-"]:not([id^="collapse-toggle"])').forEach(chevron => {
            if (!chevron.disabled) {
              chevron.style.transform = allCollapsed ? 'rotate(90deg)' : '';
              chevron.title = allCollapsed ? 'Expand' : 'Collapse';
            }
          });
        });
      }

      requestAnimationFrame(() => {
        const textEl = goalCard.querySelector(`#goal-text-recon-${_sessionId || 'x'}`);
        const expandBtn = goalCard.querySelector(`#goal-expand-recon-${_sessionId || 'x'}`);
        if (!textEl || !expandBtn) return;
        if (textEl.scrollHeight > textEl.clientHeight + 2) {
          expandBtn.classList.remove('hidden');
          let expanded = false;
          expandBtn.addEventListener('click', () => {
            expanded = !expanded;
            if (expanded) {
              textEl.style.webkitLineClamp = 'unset';
              textEl.style.display = 'block';
              expandBtn.textContent = '↑';
            } else {
              textEl.style.display = '-webkit-box';
              textEl.style.webkitLineClamp = '1';
              expandBtn.textContent = '↓';
            }
          });
        }
      });

    } else if (kind === 'turn_start') {
      const card = buildTurnCard({ turn_id: ev.turn_id, actor: ev.actor, role: ev.role });
      cardMap[ev.turn_id] = card;
      appendFn(card);

    } else if (kind === 'turn_end' || kind === 'turn_interrupted') {
      const card = cardMap[ev.turn_id];
      const interrupted = kind === 'turn_interrupted';

      // populate body
      const body = card ? card.querySelector(`#body-${ev.turn_id}`) : null;
      if (body) {
        body.classList.remove('thinking');
        body.textContent = ev.payload?.text || (interrupted ? '(no output before interrupt)' : '');
      }

      // populate tldr summary
      if (ev.payload?.summary && card) {
        const summaryEl = card.querySelector(`#summary-${ev.turn_id}`);
        if (summaryEl) {
          summaryEl.textContent = ev.payload.summary;
          summaryEl.classList.remove('hidden');
        }
      }

      // populate reasoning
      if (ev.payload?.reasoning) {
        const reasoningEl = card ? card.querySelector(`#reasoning-${ev.turn_id}`) : null;
        const pre = card ? card.querySelector(`#reasoning-body-${ev.turn_id}`) : null;
        if (reasoningEl && pre) {
          reasoningEl.classList.remove('hidden');
          if (reasoningEl.tagName === 'DETAILS') reasoningEl.open = true;
          pre.textContent = ev.payload.reasoning;
        }
      }

      // badge: use kollab session_id (consistent across all turn cards and matches JSONL filename)
      // thread_id stays in the JSONL payload for debugging but is not shown in the UI.
      const badgeSessionId = _sessionId || ev.session_id || '';
      if (badgeSessionId && card) {
        const badge = card.querySelector(`#badge-${ev.turn_id}`);
        if (badge) {
          const short = badgeSessionId.length > 14 ? badgeSessionId.slice(0, 14) + '\u2026' : badgeSessionId;
          badge.textContent = `${ev.turn_id} \u00b7 ${short}`;
          badge.title = badgeSessionId;
        }
      }

      // verdict (turn_end only)
      if (!interrupted) applyVerdict(ev.turn_id, ev.payload?.verdict, card);

      // chevron
      enableCollapseChevron(ev.turn_id, card);

      // interrupted note
      if (interrupted && card) {
        const note = document.createElement('div');
        note.className = 'text-xs text-muted border-t border-white/10 pt-2 mt-1';
        note.textContent = '\u23f8 interrupted';
        card.appendChild(note);
      }

    } else if (kind === 'user_input') {
      const targetLabels = { claude: 'CLAUDE', codex: 'CODEX', both: 'CLAUDE, CODEX' };
      const target = ev.payload?.target || 'both';
      const userCard = document.createElement('div');
      userCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
      userCard.innerHTML = `
        <div class="text-xs text-muted uppercase">DIRECTIVE \u2192 ${targetLabels[target] || target.toUpperCase()}</div>
        <pre class="whitespace-pre-wrap text-user">${escHtml(ev.payload?.text || '')}</pre>
      `;
      appendFn(userCard);

    } else if (kind === 'session_end') {
      const reason = ev.payload?.reason || '';
      const reasons = {
        convergence: '\u2713 Converged',
        round_limit: `\u26a0 Round limit${_roundLimit ? ' (' + _roundLimit + ')' : ''}`,
        token_limit: '\u26a0 Token limit',
        halted:      '\u23f9 Halted',
        expired:     '\u23f3 Expired',
      };
      const reasonsFull = {
        convergence: '\u2713 Both agents reached agreement.',
        round_limit: `\u26a0 Round limit reached${_roundLimit ? ' (' + _roundLimit + ' rounds)' : ''}.`,
        token_limit: '\u26a0 Token budget exhausted.',
        halted:      '\u23f9 Session halted.',
        expired:     '\u23f3 Stopped / expired.',
      };

      // Update Goal card to show verdict + readonly pill + export
      const goalMeta = goalCard ? goalCard.querySelector('#recon-goal-meta') : null;
      if (goalMeta) {
        const verdictColors = {
          convergence: 'text-verdictAgree',
          round_limit: 'text-verdictRevised',
          token_limit: 'text-verdictRevised',
          halted: 'text-muted',
          expired: 'text-muted',
        };
        const pill = document.createElement('span');
        pill.className = `text-xs px-1.5 py-0.5 rounded font-bold ${verdictColors[reason] || 'text-muted'} bg-white/10`;
        pill.textContent = reasons[reason] || reason;
        goalMeta.appendChild(pill);
        const roLabel = document.createElement('span');
        roLabel.className = 'text-xs text-muted opacity-50';
        roLabel.textContent = 'read-only';
        goalMeta.appendChild(roLabel);
        if (_sessionId) goalMeta.appendChild(buildExportButton(_sessionId, _sessionNumber));
      }

      const reconTiming = goalCard ? goalCard.querySelector('#recon-goal-timing') : null;
      if (reconTiming && ev.ts) {
        const endedAt = new Date(ev.ts);
        const endedSpan = document.createElement('span');
        endedSpan.textContent = 'ended ' + fmtTime(endedAt);
        reconTiming.appendChild(endedSpan);
        if (_startedAt) {
          const elapsedSpan = document.createElement('span');
          elapsedSpan.textContent = fmtElapsed(endedAt - _startedAt);
          reconTiming.appendChild(elapsedSpan);
        }
      }

      // Bottom session-end banner: reason text + export button
      const banner = document.createElement('div');
      banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted flex items-center justify-center gap-3';
      const bannerText = document.createElement('span');
      bannerText.textContent = reasonsFull[reason] || `Session ended: ${reason}`;
      banner.appendChild(bannerText);
      if (_sessionId) banner.appendChild(buildExportButton(_sessionId, _sessionNumber));
      if (_startedAt && ev.ts) {
        const endedAt = new Date(ev.ts);
        const timingSpan = document.createElement('span');
        timingSpan.className = 'font-mono text-xs text-muted opacity-40 ml-auto';
        timingSpan.textContent = `started ${fmtTime(_startedAt)} · ended ${fmtTime(endedAt)} · ${fmtElapsed(endedAt - _startedAt)}`;
        banner.appendChild(timingSpan);
      }
      appendFn(banner);
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
restoreOpenTabs();
