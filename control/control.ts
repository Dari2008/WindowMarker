/// <reference types="vite/client" />
import '../src/style.css';

const btnAllOn      = document.getElementById('btn-all-on')      as HTMLButtonElement;
const btnAllOff     = document.getElementById('btn-all-off')     as HTMLButtonElement;
const btnRandom     = document.getElementById('btn-random')      as HTMLButtonElement;
const btnDemo       = document.getElementById('btn-demo')        as HTMLButtonElement;
const btnEmergency  = document.getElementById('btn-emergency')   as HTMLButtonElement;

const fieldCycleActive = document.getElementById('cycle-active')     as HTMLInputElement;
const fieldCycleSpeed  = document.getElementById('cycle-speed')      as HTMLInputElement;
const labelCycleSpeed  = document.getElementById('cycle-speed-label') as HTMLSpanElement;

const statSegmentCount = document.getElementById('stat-segment-count') as HTMLSpanElement;
const statWindowCount  = document.getElementById('stat-window-count')  as HTMLSpanElement;
const statActiveCount  = document.getElementById('stat-active-count')  as HTMLSpanElement;
const statLightMode    = document.getElementById('stat-light-mode')    as HTMLSpanElement;
const clockElement     = document.getElementById('clock')              as HTMLDivElement;
const consoleLogs      = document.getElementById('console-logs')       as HTMLDivElement;

function logEvent(message: string) {
  const time = new Date().toLocaleTimeString('de-DE');
  const logDiv = document.createElement('div');
  logDiv.textContent = `[${time}] ${message}`;
  consoleLogs.appendChild(logDiv);
  consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

function postToParent(type: string, data: object = {}) {
  window.parent.postMessage({ type, ...data }, '*');
}

btnAllOn?.addEventListener('click', () => {
  postToParent('CONTROL_ALL_ON');
  logEvent('Befehl gesendet: Alles AN');
});

btnAllOff?.addEventListener('click', () => {
  postToParent('CONTROL_ALL_OFF');
  logEvent('Befehl gesendet: Alles AUS');
});

btnRandom?.addEventListener('click', () => {
  postToParent('CONTROL_RANDOM');
  logEvent('Befehl gesendet: Zufalls-Mix');
});

btnDemo?.addEventListener('click', () => {
  postToParent('CONTROL_DEMO');
  logEvent('Befehl gesendet: Demo-Modus starten');
});

btnEmergency?.addEventListener('click', () => {
  postToParent('CONTROL_EMERGENCY');
  logEvent('NOT-AUS ausgelöst!');
});

fieldCycleActive?.addEventListener('change', () => {
  postToParent('CONTROL_SET_CYCLE_ACTIVE', { active: fieldCycleActive.checked });
  logEvent(`Tag-Nacht-Zyklus ${fieldCycleActive.checked ? 'aktiviert' : 'deaktiviert'}.`);
});

fieldCycleSpeed?.addEventListener('input', () => {
  const speed = parseInt(fieldCycleSpeed.value) || 5;
  if (labelCycleSpeed) labelCycleSpeed.textContent = `1 Sek = ${speed} Min`;
  postToParent('CONTROL_SET_CYCLE_SPEED', { speed });
});

window.addEventListener('message', (event) => {
  const msg = event.data;
  if (!msg || typeof msg !== 'object') return;

  switch ((msg as { type: string }).type) {
    case 'UPDATE_STATS': {
      const m = msg as {
        type: string;
        segmentCount?: number;
        windowCount?: number;
        activeCount?: number;
        lightMode?: string;
        timeString?: string;
        cycleActive?: boolean;
        cycleSpeed?: number;
      };
      if (statSegmentCount) statSegmentCount.textContent = String(m.segmentCount ?? 0);
      if (statWindowCount)  statWindowCount.textContent  = String(m.windowCount ?? 0);
      if (statActiveCount)  statActiveCount.textContent  = String(m.activeCount ?? 0);
      if (statLightMode)    statLightMode.textContent    = String(m.lightMode ?? 'Standard');
      if (clockElement && m.timeString) clockElement.textContent = `Modell-Zeit: ${m.timeString}`;
      if (fieldCycleActive && typeof m.cycleActive === 'boolean') fieldCycleActive.checked = m.cycleActive;
      if (fieldCycleSpeed && typeof m.cycleSpeed === 'number') {
        fieldCycleSpeed.value = String(m.cycleSpeed);
        if (labelCycleSpeed) labelCycleSpeed.textContent = `1 Sek = ${m.cycleSpeed} Min`;
      }
      break;
    }
    case 'LOG_MESSAGE': {
      const m = msg as { type: string; text?: string };
      if (m.text) logEvent(m.text);
      break;
    }
  }
});

// Periodically announce presence to parent
setInterval(() => postToParent('CONTROL_HANDSHAKE'), 1000);

logEvent('Stellwerk-Konsole bereit.');
