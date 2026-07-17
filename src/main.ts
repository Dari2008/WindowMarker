import './style.css';

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface WindowConfig {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface HouseMetadata {
  name: string;
  windows: WindowConfig[];
}

interface Sequence {
  id: string;
  name: string;
  nodes: NodeConfig[];
}

interface WindowSettings {
  lightMode: 'cycle' | 'color' | 'nodes';
  active: boolean;
  followCycle: boolean;
  effects: {
    party: boolean;
    tv: boolean;
    fire: boolean;
    office: boolean;
    welding: boolean;
    neon: boolean;
  };
  customColor: string;
  sequenceId: string | null;
  // Node player runtime state
  isNodeRunning?: boolean;
  currentNodeIndex?: number;
  nodeTimeoutId?: ReturnType<typeof setTimeout>;
  nodeAnimationId?: number;
  nodeFlickerIntervals?: ReturnType<typeof setInterval>[];
  nodeStepStart?: number;
  nodeStepDuration?: number;
}

interface SceneryBuilding {
  id: string;
  imageKey: string;
  name: string;
  windows: WindowConfig[];
  activeWindows: { [windowId: string]: boolean };
  windowSettings: { [windowId: string]: WindowSettings };
  windowColors?: { [windowId: string]: string };
  refW?: number;
  refH?: number;
}

type NodeType = 'delay' | 'color' | 'transition' | 'flicker';

interface NodeConfig {
  id: string;
  type: NodeType;
  params: {
    delayType?: 'fixed' | 'random';
    delaySeconds?: number;
    delayMin?: number;
    delayMax?: number;
    colorType?: 'fixed' | 'random';
    colorValue?: string;
    transitionColor?: string;
    transitionSeconds?: number;
    flickerFrequency?: number;
    flickerDuration?: number;
  };
}

// ──────────────────────────────────────────────────────────────────────────────
// Global state
// ──────────────────────────────────────────────────────────────────────────────

let cycleActive = true;
let cycleSpeed = 5;
let selectedBuildingId: string | null = null;
let selectedWindowId: string | null = null;
let templates: { [key: string]: HouseMetadata } = {};
let availableImages: string[] = [];
let scenery: SceneryBuilding[] = [];
let sequences: Sequence[] = [];
let modelHour = 20;
let modelMinute = 0;
let modelTimeInterval: ReturnType<typeof setInterval> | null = null;

// Sequence editor state
let editingSequenceId: string | null = null;
let editingNodeIndex: number | null = null;
let editingNodeType: NodeType = 'delay';

// Viewport zoom/pan state
let zoom = 1;
let panX = 0;
let panY = 0;
let isPanning = false;
let panStartX = 0;
let panStartY = 0;
let fitOnNextRender = false;

// ──────────────────────────────────────────────────────────────────────────────
// DOM references
// ──────────────────────────────────────────────────────────────────────────────

const tabControl = document.getElementById('tab-control') as HTMLButtonElement;
const tabBuild = document.getElementById('tab-build') as HTMLButtonElement;
const panelControl = document.getElementById('panel-control') as HTMLElement;
const panelBuild = document.getElementById('panel-build') as HTMLElement;
const controlIframe = document.getElementById('control-iframe') as HTMLIFrameElement;

const sidebarEmptyState = document.getElementById('sidebar-empty-state') as HTMLElement;
const sidebarActiveSettings = document.getElementById('sidebar-active-settings') as HTMLElement;
const selectedWindowBadge = document.getElementById('selected-window-badge') as HTMLSpanElement;
const activeSettingsHouseName = document.getElementById('active-settings-house-name') as HTMLSpanElement;
const activeSettingsWindowName = document.getElementById('active-settings-window-name') as HTMLSpanElement;
const windowStateToggle = document.getElementById('window-state-toggle') as HTMLInputElement;
const windowFollowCycle = document.getElementById('window-follow-cycle') as HTMLInputElement;

const modalSelector = document.getElementById('modal-selector') as HTMLElement;
const btnCloseSelector = document.getElementById('btn-close-selector') as HTMLButtonElement;
const selectorGrid = document.getElementById('selector-grid') as HTMLElement;
const btnAddHouseHeader = document.getElementById('btn-add-house-header') as HTMLButtonElement;
const btnAddHouseCenter = document.getElementById('btn-add-house-center') as HTMLButtonElement;
const btnClearScenery = document.getElementById('btn-clear-scenery') as HTMLButtonElement;
const buildEmptyState = document.getElementById('build-empty-state') as HTMLElement;
const buildViewport = document.getElementById('build-viewport') as HTMLElement;
const buildCanvas = document.getElementById('build-canvas') as HTMLElement;
const sceneryRow = document.getElementById('scenery-row') as HTMLElement;
const zoomLabel = document.getElementById('zoom-label') as HTMLSpanElement;
const btnZoomIn = document.getElementById('btn-zoom-in') as HTMLButtonElement;
const btnZoomOut = document.getElementById('btn-zoom-out') as HTMLButtonElement;
const btnZoomFit = document.getElementById('btn-zoom-fit') as HTMLButtonElement;

const setTabCycle = document.getElementById('set-tab-cycle') as HTMLButtonElement;
const setTabColor = document.getElementById('set-tab-color') as HTMLButtonElement;
const setTabNodes = document.getElementById('set-tab-nodes') as HTMLButtonElement;
const setPanelCycle = document.getElementById('set-panel-cycle') as HTMLElement;
const setPanelColor = document.getElementById('set-panel-color') as HTMLElement;
const setPanelNodes = document.getElementById('set-panel-nodes') as HTMLElement;

const fieldEffectParty = document.getElementById('effect-party') as HTMLInputElement;
const fieldEffectTv = document.getElementById('effect-tv') as HTMLInputElement;
const fieldEffectFire = document.getElementById('effect-fire') as HTMLInputElement;
const fieldEffectOffice = document.getElementById('effect-office') as HTMLInputElement;
const fieldEffectWelding = document.getElementById('effect-welding') as HTMLInputElement;
const fieldEffectNeon = document.getElementById('effect-neon') as HTMLInputElement;
const customColorPicker = document.getElementById('custom-color-picker') as HTMLInputElement;
const customColorHex = document.getElementById('custom-color-hex') as HTMLSpanElement;

// Sequence / player elements
const sequenceSelect = document.getElementById('sequence-select') as HTMLSelectElement;
const btnNewSequence = document.getElementById('btn-new-sequence') as HTMLButtonElement;
const btnEditSequence = document.getElementById('btn-edit-sequence') as HTMLButtonElement;
const nodePlayerStatus = document.getElementById('node-player-status') as HTMLSpanElement;
const btnNodePlay = document.getElementById('btn-node-play') as HTMLButtonElement;
const btnNodePause = document.getElementById('btn-node-pause') as HTMLButtonElement;
const btnNodeClear = document.getElementById('btn-node-clear') as HTMLButtonElement;

// Sequence editor modal
const modalSequenceEditor = document.getElementById('modal-sequence-editor') as HTMLElement;
const seqEditorName = document.getElementById('seq-editor-name') as HTMLInputElement;
const seqEditorSteps = document.getElementById('seq-editor-steps') as HTMLElement;
const btnCloseSeqEditor = document.getElementById('btn-close-seq-editor') as HTMLButtonElement;
const btnSeqAddStep = document.getElementById('btn-seq-add-step') as HTMLButtonElement;
const btnSeqSave = document.getElementById('btn-seq-save') as HTMLButtonElement;

// Step config modal
const modalStepConfig = document.getElementById('modal-step-config') as HTMLElement;
const stepConfigForm = document.getElementById('step-config-form') as HTMLElement;
const btnCloseStepConfig = document.getElementById('btn-close-step-config') as HTMLButtonElement;
const btnStepConfigSave = document.getElementById('btn-step-config-save') as HTMLButtonElement;
const btnStepConfigCancel = document.getElementById('btn-step-config-cancel') as HTMLButtonElement;

// ──────────────────────────────────────────────────────────────────────────────
// Init & Storage
// ──────────────────────────────────────────────────────────────────────────────

function init() {
  loadFromLocalStorage();
  setupEventListeners();
  fetchImagesList();
  startModelClock();
}

function loadFromLocalStorage() {
  try {
    const storedCycleActive = localStorage.getItem('kulisse_cycle_active');
    if (storedCycleActive !== null) cycleActive = storedCycleActive === 'true';

    const storedCycleSpeed = localStorage.getItem('kulisse_cycle_speed');
    if (storedCycleSpeed !== null) cycleSpeed = parseInt(storedCycleSpeed) || 5;

    const storedScenery = localStorage.getItem('kulisse_scenery');
    if (storedScenery) scenery = JSON.parse(storedScenery);

    const storedSeqs = localStorage.getItem('kulisse_sequences');
    if (storedSeqs) sequences = JSON.parse(storedSeqs);
  } catch (e) {
    console.error('Fehler beim Laden aus LocalStorage:', e);
  }

  scenery.forEach(b => {
    if (!b.windowSettings) b.windowSettings = {};
    b.windows.forEach(w => {
      const legacyActive = b.activeWindows?.[w.id] ?? true;
      if (!b.windowSettings[w.id]) {
        b.windowSettings[w.id] = getDefaultWindowSettings(b.imageKey, w.id);
        b.windowSettings[w.id].active = legacyActive;
      }
      const ws = b.windowSettings[w.id];
      // Migrate old per-window nodes to a global sequence
      const anyWs = ws as WindowSettings & { nodes?: NodeConfig[] };
      if (anyWs.nodes && anyWs.nodes.length > 0 && !ws.sequenceId) {
        const seq: Sequence = {
          id: `seq-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          name: `${b.name} – ${w.id}`,
          nodes: anyWs.nodes,
        };
        sequences.push(seq);
        ws.sequenceId = seq.id;
      }
      delete anyWs.nodes;
    });
  });

  if (scenery.length > 0) fitOnNextRender = true;

  switchTab('control');
  applyLightModeStyles();
}

function saveToLocalStorage() {
  try {
    localStorage.setItem('kulisse_cycle_active', String(cycleActive));
    localStorage.setItem('kulisse_cycle_speed', String(cycleSpeed));
    localStorage.setItem('kulisse_scenery', JSON.stringify(scenery));
    localStorage.setItem('kulisse_sequences', JSON.stringify(sequences));
  } catch (e) {
    console.error('Fehler beim Speichern in LocalStorage:', e);
  }
}

function getDefaultWindowSettings(houseKey: string, windowId: string): WindowSettings {
  const isOffice = houseKey === 'haus3';
  const isWelding = houseKey === 'haus4' && windowId === 'h4-w5';

  return {
    lightMode: 'cycle',
    active: true,
    followCycle: true,
    effects: {
      party: false,
      tv: false,
      fire: false,
      office: isOffice,
      welding: isWelding,
      neon: false,
    },
    customColor: '#f59e0b',
    sequenceId: null,
  };
}

// ──────────────────────────────────────────────────────────────────────────────
// Tab switching
// ──────────────────────────────────────────────────────────────────────────────

function switchTab(tab: 'control' | 'build') {
  if (tab === 'control') {
    tabControl.className = 'px-6 py-2 rounded-full font-medium text-sm transition-all duration-200 bg-slate-800 text-white shadow-sm';
    tabBuild.className = 'px-6 py-2 rounded-full font-medium text-sm transition-all duration-200 text-slate-400 hover:text-slate-200';
    panelControl.classList.remove('hidden');
    panelBuild.classList.add('hidden');
    deselectWindow();
    setTimeout(() => postToControlIframe('UPDATE_STATS', getStats()), 100);
  } else {
    tabBuild.className = 'px-6 py-2 rounded-full font-medium text-sm transition-all duration-200 bg-slate-800 text-white shadow-sm';
    tabControl.className = 'px-6 py-2 rounded-full font-medium text-sm transition-all duration-200 text-slate-400 hover:text-slate-200';
    panelBuild.classList.remove('hidden');
    panelControl.classList.add('hidden');
    renderScenery();
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Settings sub-tabs & window selection
// ──────────────────────────────────────────────────────────────────────────────

function switchSettingsTab(tab: 'cycle' | 'color' | 'nodes') {
  if (!selectedBuildingId || !selectedWindowId) return;
  const building = scenery.find(b => b.id === selectedBuildingId);
  if (!building) return;
  const winSettings = building.windowSettings[selectedWindowId];
  if (!winSettings) return;

  if (tab !== 'nodes') {
    stopWindowNodePlayer(winSettings);
  }

  winSettings.lightMode = tab;
  saveToLocalStorage();
  updateSidebarSettings();
  applyLightModeStyles();

  // Auto-start when switching to nodes mode with an assigned sequence
  if (tab === 'nodes' && winSettings.sequenceId && !winSettings.isNodeRunning) {
    startWindowNodePlayer(selectedBuildingId, selectedWindowId);
  }
}

function selectWindow(buildingId: string, windowId: string) {
  selectedBuildingId = buildingId;
  selectedWindowId = windowId;

  document.querySelectorAll('[id^="window-"]').forEach(el => el.classList.remove('window-selected'));

  const activeWinEl = document.getElementById(`window-${buildingId}-${windowId}`);
  if (activeWinEl) activeWinEl.classList.add('window-selected');

  if (selectedWindowBadge) {
    selectedWindowBadge.textContent = 'Aktiv';
    selectedWindowBadge.className = 'px-2 py-0.5 rounded bg-indigo-900/60 text-[9px] text-indigo-300 font-bold uppercase tracking-wider border border-indigo-700/50';
  }

  sidebarEmptyState.classList.add('hidden');
  sidebarActiveSettings.classList.remove('hidden');
  updateSidebarSettings();

  // Auto-start node player if in nodes mode
  const building = scenery.find(b => b.id === buildingId);
  if (building) {
    const ws = building.windowSettings[windowId];
    if (ws && ws.lightMode === 'nodes' && ws.sequenceId && !ws.isNodeRunning) {
      startWindowNodePlayer(buildingId, windowId);
    }
  }
}

function deselectWindow() {
  selectedBuildingId = null;
  selectedWindowId = null;

  document.querySelectorAll('[id^="window-"]').forEach(el => el.classList.remove('window-selected'));

  if (selectedWindowBadge) {
    selectedWindowBadge.textContent = 'Auswahl';
    selectedWindowBadge.className = 'px-2 py-0.5 rounded bg-slate-800 text-[9px] text-slate-400 font-bold uppercase tracking-wider';
  }

  sidebarEmptyState.classList.remove('hidden');
  sidebarActiveSettings.classList.add('hidden');
}

function updateSidebarSettings() {
  if (!selectedBuildingId || !selectedWindowId) return;
  const building = scenery.find(b => b.id === selectedBuildingId);
  if (!building) return;
  const winSettings = building.windowSettings[selectedWindowId];
  if (!winSettings) return;

  if (activeSettingsHouseName) activeSettingsHouseName.textContent = building.name;
  if (activeSettingsWindowName) activeSettingsWindowName.textContent = `Fenster: ${selectedWindowId}`;
  if (windowStateToggle) windowStateToggle.checked = winSettings.active;
  if (windowFollowCycle) windowFollowCycle.checked = winSettings.followCycle ?? true;

  const tabs = [
    { key: 'cycle', btn: setTabCycle, panel: setPanelCycle },
    { key: 'color', btn: setTabColor, panel: setPanelColor },
    { key: 'nodes', btn: setTabNodes, panel: setPanelNodes },
  ];

  tabs.forEach(t => {
    if (t.key === winSettings.lightMode) {
      t.btn.className = 'flex-1 py-1.5 rounded-md bg-slate-800 text-slate-200 transition font-semibold shadow-inner';
      t.panel.classList.remove('hidden');
    } else {
      t.btn.className = 'flex-1 py-1.5 rounded-md text-slate-400 hover:text-slate-200 transition';
      t.panel.classList.add('hidden');
    }
  });

  if (fieldEffectParty) fieldEffectParty.checked = winSettings.effects.party;
  if (fieldEffectTv) fieldEffectTv.checked = winSettings.effects.tv;
  if (fieldEffectFire) fieldEffectFire.checked = winSettings.effects.fire;
  if (fieldEffectOffice) fieldEffectOffice.checked = winSettings.effects.office;
  if (fieldEffectWelding) fieldEffectWelding.checked = winSettings.effects.welding;
  if (fieldEffectNeon) fieldEffectNeon.checked = winSettings.effects.neon;

  if (customColorPicker) customColorPicker.value = winSettings.customColor;
  if (customColorHex) customColorHex.textContent = winSettings.customColor.toUpperCase();

  // Nodes tab
  renderSequenceDropdown();
  if (sequenceSelect) sequenceSelect.value = winSettings.sequenceId || '';

  if (winSettings.isNodeRunning) {
    btnNodePlay?.classList.add('hidden');
    btnNodePause?.classList.remove('hidden');
    if (nodePlayerStatus) nodePlayerStatus.textContent = 'Läuft…';
  } else {
    btnNodePlay?.classList.remove('hidden');
    btnNodePause?.classList.add('hidden');
    if (nodePlayerStatus) nodePlayerStatus.textContent = winSettings.sequenceId ? 'Gestoppt' : 'Kein Ablauf';
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Data loading
// ──────────────────────────────────────────────────────────────────────────────

async function fetchImagesList() {
  try {
    const res = await fetch('/houses/images.json');
    if (!res.ok) throw new Error('images.json nicht gefunden');
    const data = await res.json();
    availableImages = data.images || [];

    const templatePromises = availableImages.map(async (key) => {
      const metadataRes = await fetch(`/houses/${key}/${key}.json`);
      if (metadataRes.ok) {
        const tmplData = await metadataRes.json();
        // Ensure every window has an id (real JSON files may omit it)
        tmplData.windows = (tmplData.windows as WindowConfig[]).map(
          (w: WindowConfig, i: number) => ({ ...w, id: w.id ?? `${key}-w${i}` })
        );
        templates[key] = tmplData;
      }
    });

    await Promise.all(templatePromises);
    renderSelectorGrid();
    renderScenery();
  } catch {
    setupMockTemplates();
  }
}

function setupMockTemplates() {
  availableImages = ['haus1', 'haus2', 'haus3', 'haus4'];
  templates = {
    haus1: {
      name: 'Haus A (Wohnhaus)',
      windows: [
        { id: 'h1-w1', x: 80, y: 80, w: 80, h: 100 },
        { id: 'h1-w2', x: 260, y: 80, w: 80, h: 100 },
        { id: 'h1-w3', x: 440, y: 80, w: 80, h: 100 },
        { id: 'h1-w4', x: 80, y: 220, w: 80, h: 100 },
        { id: 'h1-w5', x: 260, y: 220, w: 80, h: 100 },
        { id: 'h1-w6', x: 440, y: 220, w: 80, h: 100 },
      ],
    },
    haus2: {
      name: 'Haus B (Stadthaus)',
      windows: [
        { id: 'h2-w1', x: 60, y: 70, w: 70, h: 90 },
        { id: 'h2-w2', x: 190, y: 70, w: 70, h: 90 },
        { id: 'h2-w3', x: 320, y: 70, w: 70, h: 90 },
        { id: 'h2-w4', x: 450, y: 70, w: 70, h: 90 },
        { id: 'h2-w5', x: 60, y: 220, w: 70, h: 90 },
        { id: 'h2-w6', x: 190, y: 220, w: 70, h: 90 },
        { id: 'h2-w7', x: 320, y: 220, w: 70, h: 90 },
        { id: 'h2-w8', x: 450, y: 220, w: 70, h: 90 },
      ],
    },
    haus3: {
      name: 'Haus C (Geschäftshaus)',
      windows: [
        { id: 'h3-w1', x: 70, y: 80, w: 90, h: 100 },
        { id: 'h3-w2', x: 240, y: 80, w: 90, h: 100 },
        { id: 'h3-w3', x: 410, y: 80, w: 90, h: 100 },
        { id: 'h3-w4', x: 70, y: 240, w: 180, h: 110 },
        { id: 'h3-w5', x: 310, y: 240, w: 180, h: 110 },
      ],
    },
    haus4: {
      name: 'Haus D (Industriegebäude)',
      windows: [
        { id: 'h4-w1', x: 70, y: 60, w: 80, h: 60 },
        { id: 'h4-w2', x: 240, y: 60, w: 80, h: 60 },
        { id: 'h4-w3', x: 410, y: 60, w: 80, h: 60 },
        { id: 'h4-w4', x: 70, y: 160, w: 80, h: 60 },
        { id: 'h4-w5', x: 240, y: 160, w: 80, h: 60 },
        { id: 'h4-w6', x: 410, y: 160, w: 80, h: 60 },
        { id: 'h4-w7', x: 70, y: 260, w: 80, h: 60 },
        { id: 'h4-w8', x: 240, y: 260, w: 80, h: 60 },
        { id: 'h4-w9', x: 410, y: 260, w: 80, h: 60 },
      ],
    },
  };
  renderSelectorGrid();
  renderScenery();
}

// ──────────────────────────────────────────────────────────────────────────────
// Viewport transform helpers
// ──────────────────────────────────────────────────────────────────────────────

function applyTransform() {
  buildCanvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
  updateOverlays();
}

let lastZoomForOverlays = -1;
function updateOverlays() {
  if (zoom === lastZoomForOverlays) return;
  lastZoomForOverlays = zoom;
  document.querySelectorAll<HTMLElement>('.panorama-building-overlay').forEach(el => {
    const bldgH = (el.parentElement?.offsetHeight || 0);
    if (bldgH === 0) return;
    el.style.width = `${260 * zoom}px`;
    el.style.height = `${bldgH * zoom}px`;
    el.style.transform = `scale(${1 / zoom})`;
    el.style.transformOrigin = '0 0';
  });
}

function fitToScreen() {
  if (scenery.length === 0) return;
  requestAnimationFrame(() => {
    const rowH = sceneryRow.offsetHeight;
    const rowW = sceneryRow.offsetWidth;
    if (rowH === 0 || rowW === 0) {
      const img = sceneryRow.querySelector('img') as HTMLImageElement | null;
      if (img && !img.complete) {
        img.addEventListener('load', fitToScreen, { once: true });
      }
      return;
    }
    const vpW = buildViewport.clientWidth;
    const vpH = buildViewport.clientHeight;
    if (vpW === 0 || vpH === 0) return;

    zoom = Math.min(vpH / rowH, vpW / rowW, 3);
    zoom = Math.max(0.1, zoom);

    const scaledW = rowW * zoom;
    panX = scaledW < vpW ? Math.round((vpW - scaledW) / 2) : 0;
    panY = 0;
    applyTransform();
  });
}

// ──────────────────────────────────────────────────────────────────────────────
// Scenery rendering
// ──────────────────────────────────────────────────────────────────────────────

function renderScenery() {
  if (scenery.length === 0) {
    buildEmptyState.classList.remove('hidden');
    buildCanvas.classList.add('hidden');
  } else {
    buildEmptyState.classList.add('hidden');
    buildCanvas.classList.remove('hidden');
    applyTransform();

    sceneryRow.innerHTML = '';
    scenery.forEach((building, index) => {
      const buildingContainer = document.createElement('div');
      buildingContainer.className = 'panorama-building relative overflow-hidden flex-shrink-0 group';
      buildingContainer.style.width = '260px';
      buildingContainer.draggable = true;

      buildingContainer.addEventListener('dragstart', (e) => {
        e.dataTransfer?.setData('text/plain', String(index));
        buildingContainer.classList.add('dragging');
      });
      buildingContainer.addEventListener('dragover', (e) => {
        e.preventDefault();
        buildingContainer.classList.add('drag-target');
      });
      buildingContainer.addEventListener('dragleave', () => {
        buildingContainer.classList.remove('drag-target');
      });
      buildingContainer.addEventListener('drop', (e) => {
        e.preventDefault();
        buildingContainer.classList.remove('drag-target');
        const fromIndex = parseInt(e.dataTransfer?.getData('text/plain') || '-1');
        if (!isNaN(fromIndex) && fromIndex !== index && fromIndex >= 0) {
          moveSceneryItem(fromIndex, index);
        }
      });
      buildingContainer.addEventListener('dragend', () => {
        buildingContainer.classList.remove('dragging');
        document.querySelectorAll('.panorama-building').forEach(el => el.classList.remove('drag-target'));
      });

      const img = document.createElement('img');
      img.src = `/houses/${building.imageKey}/${building.imageKey}.jpg`;
      img.className = 'w-full h-auto block select-none pointer-events-none';
      img.addEventListener('load', () => {
        building.refW = img.naturalWidth;
        building.refH = img.naturalHeight;
        lastZoomForOverlays = -1;
        updateOverlays();
        applyLightModeStyles();
      }, { once: true });
      img.onerror = () => {
        img.style.display = 'none';
        const fallback = document.createElement('div');
        fallback.className = 'absolute inset-0 bg-slate-900 flex items-center justify-center text-center p-3 text-[11px] font-mono text-slate-500';
        fallback.innerHTML = `<div>[${building.imageKey}.jpg]</div>`;
        buildingContainer.appendChild(fallback);
      };
      buildingContainer.appendChild(img);

      const overlay = document.createElement('div');
      overlay.className = 'panorama-building-overlay absolute top-0 left-0 bg-black/40 flex flex-col justify-between p-2.5 z-20 overflow-hidden';
      overlay.innerHTML = `
        <div class="flex items-center justify-between text-[10px] text-slate-200">
          <span class="font-bold truncate select-none drop-shadow-md pr-1">${building.name}</span>
          <button class="btn-remove-building p-1 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 rounded transition active:scale-95 border border-slate-700" data-index="${index}" title="Entfernen">✕</button>
        </div>
        <div class="flex justify-center gap-1">
          <button class="btn-move-left px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 text-xs rounded transition active:scale-95 border border-slate-700" data-index="${index}" title="Nach links" ${index === 0 ? 'disabled style="opacity:0.3;"' : ''}>◀</button>
          <button class="btn-move-right px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 text-xs rounded transition active:scale-95 border border-slate-700" data-index="${index}" title="Nach rechts" ${index === scenery.length - 1 ? 'disabled style="opacity:0.3;"' : ''}>▶</button>
        </div>
      `;
      buildingContainer.appendChild(overlay);

      building.windows.forEach((win) => {
        const winEl = document.createElement('div');
        winEl.id = `window-${building.id}-${win.id}`;
        winEl.className = 'absolute cursor-pointer rounded-sm select-none transition-all duration-200 z-30';
        const rW = building.refW || 600;
        const rH = building.refH || 400;
        winEl.style.left = `${(win.x / rW) * 100}%`;
        winEl.style.top = `${(win.y / rH) * 100}%`;
        winEl.style.width = `${(win.w / rW) * 100}%`;
        winEl.style.height = `${(win.h / rH) * 100}%`;
        winEl.title = `${building.name}: Fenster ${win.id}`;

        const winSettings = building.windowSettings[win.id];
        const isActive = winSettings ? winSettings.active : true;
        winEl.classList.add(isActive ? 'window-glow' : 'window-dark');

        if (selectedBuildingId === building.id && selectedWindowId === win.id) {
          winEl.classList.add('window-selected');
        }

        winEl.addEventListener('click', (e) => {
          e.stopPropagation();
          selectWindow(building.id, win.id);
        });

        buildingContainer.appendChild(winEl);
      });

      sceneryRow.appendChild(buildingContainer);
    });

    document.querySelectorAll('.btn-move-left').forEach(b => {
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt((e.currentTarget as HTMLElement).getAttribute('data-index')!);
        moveSceneryItem(idx, idx - 1);
      });
    });
    document.querySelectorAll('.btn-move-right').forEach(b => {
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt((e.currentTarget as HTMLElement).getAttribute('data-index')!);
        moveSceneryItem(idx, idx + 1);
      });
    });
    document.querySelectorAll('.btn-remove-building').forEach(b => {
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt((e.currentTarget as HTMLElement).getAttribute('data-index')!);
        removeSceneryBuilding(idx);
      });
    });

    lastZoomForOverlays = -1;
    updateOverlays();

    if (fitOnNextRender) {
      fitOnNextRender = false;
      fitToScreen();
    }
  }

  updateControlStats();
}

function moveSceneryItem(from: number, to: number) {
  if (to < 0 || to >= scenery.length) return;
  const item = scenery.splice(from, 1)[0];
  scenery.splice(to, 0, item);
  saveToLocalStorage();
  renderScenery();
  applyLightModeStyles();
  sendControlLog(`Segment '${item.name}' verschoben.`);
}

function removeSceneryBuilding(index: number) {
  const item = scenery[index];
  scenery.splice(index, 1);
  deselectWindow();
  saveToLocalStorage();
  renderScenery();
  applyLightModeStyles();
  sendControlLog(`Segment '${item.name}' gelöscht.`);
}

// ──────────────────────────────────────────────────────────────────────────────
// Selector popup
// ──────────────────────────────────────────────────────────────────────────────

function renderSelectorGrid() {
  if (!selectorGrid) return;
  selectorGrid.innerHTML = '';

  availableImages.forEach((key) => {
    const meta = templates[key];
    if (!meta) return;

    const card = document.createElement('div');
    card.className = 'bg-slate-900 border border-slate-800 rounded-xl overflow-hidden hover:border-slate-600 hover:scale-[1.01] transition-all cursor-pointer flex flex-col p-3 space-y-3 shadow';
    card.innerHTML = `
      <h4 class="font-semibold text-xs text-slate-200 flex justify-between items-center">
        <span>${meta.name}</span>
        <span class="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">${meta.windows.length} Fenster</span>
      </h4>
    `;

    const container = document.createElement('div');
    container.className = 'relative w-full aspect-[3/2] bg-slate-950 rounded-lg overflow-hidden border border-slate-800 shadow-inner flex items-center justify-center';

    const img = document.createElement('img');
    img.src = `/houses/${key}/${key}.jpg`;
    img.className = 'w-full h-full object-cover opacity-80 pointer-events-none select-none';
    img.onerror = () => {
      img.style.display = 'none';
      const fallback = document.createElement('div');
      fallback.className = 'absolute inset-0 bg-slate-900 flex items-center justify-center text-center p-3 text-[11px] font-mono text-slate-500';
      fallback.innerHTML = `<div>[${key}.jpg]</div>`;
      container.appendChild(fallback);
    };
    container.appendChild(img);

    meta.windows.forEach((win) => {
      const overlay = document.createElement('div');
      overlay.className = 'absolute rounded-sm border border-yellow-400 bg-yellow-500/50 shadow-[0_0_8px_rgba(251,191,36,0.8)]';
      overlay.style.left = `${(win.x / 600) * 100}%`;
      overlay.style.top = `${(win.y / 400) * 100}%`;
      overlay.style.width = `${(win.w / 600) * 100}%`;
      overlay.style.height = `${(win.h / 400) * 100}%`;
      container.appendChild(overlay);
    });

    card.appendChild(container);

    const selectBtn = document.createElement('button');
    selectBtn.className = 'w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg font-bold text-xs tracking-wide transition border border-slate-700 uppercase';
    selectBtn.textContent = 'Hinzufügen';
    card.appendChild(selectBtn);

    card.addEventListener('click', () => {
      addBuildingToScenery(key);
      modalSelector.classList.add('hidden');
    });

    selectorGrid.appendChild(card);
  });
}

function addBuildingToScenery(key: string) {
  const meta = templates[key];
  if (!meta) return;

  const wasEmpty = scenery.length === 0;
  const instanceId = `bldg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  const activeWindowsMap: { [key: string]: boolean } = {};
  const settingsMap: { [key: string]: WindowSettings } = {};

  meta.windows.forEach(w => {
    activeWindowsMap[w.id] = true;
    settingsMap[w.id] = getDefaultWindowSettings(key, w.id);
  });

  const newBuilding: SceneryBuilding = {
    id: instanceId,
    imageKey: key,
    name: meta.name,
    windows: JSON.parse(JSON.stringify(meta.windows)),
    activeWindows: activeWindowsMap,
    windowSettings: settingsMap,
    windowColors: {},
  };

  scenery.push(newBuilding);
  if (wasEmpty) fitOnNextRender = true;
  saveToLocalStorage();
  renderScenery();
  applyLightModeStyles();
  sendControlLog(`Gebäude hinzugefügt: ${meta.name}`);
}

// ──────────────────────────────────────────────────────────────────────────────
// Model clock
// ──────────────────────────────────────────────────────────────────────────────

function startModelClock() {
  if (modelTimeInterval) clearInterval(modelTimeInterval);

  modelTimeInterval = setInterval(() => {
    if (cycleActive) {
      modelMinute += cycleSpeed;
      if (modelMinute >= 60) {
        modelHour += Math.floor(modelMinute / 60);
        modelMinute = modelMinute % 60;
      }
      if (modelHour >= 24) modelHour = modelHour % 24;
    }

    applyLightModeStyles();
    updateControlStats();
  }, 1000);
}

function getFormattedModelTime(): string {
  const hh = String(modelHour).padStart(2, '0');
  const mm = String(modelMinute).padStart(2, '0');
  return `${hh}:${mm}:00`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Light mode styles
// ──────────────────────────────────────────────────────────────────────────────

function staggerThreshold(buildingId: string, windowId: string): number {
  const hash = (buildingId + windowId).split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
  return (hash % 10) / 10;
}

function applyLightModeStyles() {
  const isNightGlobal = modelHour >= 20 || modelHour < 6;

  scenery.forEach((building) => {
    building.windows.forEach((win) => {
      const el = document.getElementById(`window-${building.id}-${win.id}`);
      if (!el) return;

      const winSettings = building.windowSettings[win.id];
      if (!winSettings) return;

      const isSelected = selectedBuildingId === building.id && selectedWindowId === win.id;

      // Neon animation must not restart on every clock tick — skip reset if already running
      const wantsNeon = winSettings.active && winSettings.lightMode === 'cycle' &&
                        winSettings.effects.neon && isNightGlobal;
      if (wantsNeon && el.classList.contains('effect-neon-active')) {
        el.classList.toggle('window-selected', isSelected);
        return;
      }

      el.className = 'absolute cursor-pointer rounded-sm select-none transition-all duration-200 z-30';
      if (isSelected) el.classList.add('window-selected');

      el.removeAttribute('style');
      const rW = building.refW || 600;
      const rH = building.refH || 400;
      el.style.left = `${(win.x / rW) * 100}%`;
      el.style.top = `${(win.y / rH) * 100}%`;
      el.style.width = `${(win.w / rW) * 100}%`;
      el.style.height = `${(win.h / rH) * 100}%`;

      if (!winSettings.active) {
        el.classList.add('window-dark');
        return;
      }

      if (winSettings.lightMode === 'cycle') {
        if (!(winSettings.followCycle ?? true)) {
          el.classList.add('window-glow');
          return;
        }
        const isNight = isNightGlobal;
        const isDusk = modelHour >= 18 && modelHour < 20;
        const isDawn = modelHour >= 6 && modelHour < 8;

        if (isNight) {
          if (winSettings.effects.tv) {
            el.classList.add('effect-tv-active');
          } else if (winSettings.effects.fire) {
            el.classList.add('effect-fire-active');
          } else if (winSettings.effects.party) {
            el.classList.add('effect-party-active');
          } else if (winSettings.effects.welding) {
            el.classList.add('effect-welding-active');
          } else if (winSettings.effects.neon) {
            el.classList.add('effect-neon-active');
          } else {
            el.classList.add('window-glow');
          }
        } else if (isDusk) {
          const progress = ((modelHour - 18) * 60 + modelMinute) / 120;
          const threshold = staggerThreshold(building.id, win.id);
          if (progress >= threshold) {
            el.classList.add('window-glow');
            el.style.setProperty('--glow-bg', `rgba(245, 158, 11, ${progress * 0.85})`);
          } else {
            el.classList.add('window-dark');
          }
        } else if (isDawn) {
          const progress = ((modelHour - 6) * 60 + modelMinute) / 120;
          const threshold = staggerThreshold(building.id, win.id);
          if (progress < (1 - threshold)) {
            el.classList.add('window-glow');
            el.style.setProperty('--glow-bg', `rgba(245, 158, 11, ${(1 - progress) * 0.85})`);
          } else {
            el.classList.add('window-dark');
          }
        } else {
          if (winSettings.effects.office) {
            el.classList.add('window-glow');
            el.style.setProperty('--glow-color', '#f0f9ff');
            el.style.setProperty('--glow-bg', 'rgba(240, 249, 255, 0.9)');
          } else {
            el.classList.add('window-dark');
          }
        }
      } else if (winSettings.lightMode === 'color') {
        const c = winSettings.customColor || '#f59e0b';
        el.classList.add('window-glow');
        el.style.setProperty('--glow-color', c);
        el.style.setProperty('--glow-bg', `${c}dd`);
      } else if (winSettings.lightMode === 'nodes') {
        const c = building.windowColors?.[win.id] || winSettings.customColor || '#f59e0b';
        el.classList.add('window-glow');
        el.style.setProperty('--glow-color', c);
        el.style.setProperty('--glow-bg', `${c}dd`);
      }
    });
  });
}

// ──────────────────────────────────────────────────────────────────────────────
// Node sequence player
// ──────────────────────────────────────────────────────────────────────────────

function startWindowNodePlayer(bldgId: string, winId: string) {
  const building = scenery.find(b => b.id === bldgId);
  if (!building) return;
  const winSettings = building.windowSettings[winId];
  if (!winSettings) return;

  const seq = sequences.find(s => s.id === winSettings.sequenceId);
  if (!seq || seq.nodes.length === 0) return;

  winSettings.isNodeRunning = true;
  winSettings.currentNodeIndex = 0;
  winSettings.nodeFlickerIntervals = [];

  executeWindowNodeStep(bldgId, winId);
  updateSidebarSettings();
  sendControlLog(`Ablauf '${seq.name}' für Fenster '${winId}' gestartet.`);
}

function stopWindowNodePlayer(winSettings: WindowSettings) {
  winSettings.isNodeRunning = false;

  if (winSettings.nodeTimeoutId !== undefined) {
    clearTimeout(winSettings.nodeTimeoutId);
    winSettings.nodeTimeoutId = undefined;
  }
  if (winSettings.nodeAnimationId !== undefined) {
    cancelAnimationFrame(winSettings.nodeAnimationId);
    winSettings.nodeAnimationId = undefined;
  }
  if (winSettings.nodeFlickerIntervals) {
    winSettings.nodeFlickerIntervals.forEach(clearInterval);
    winSettings.nodeFlickerIntervals = [];
  }
}

function executeWindowNodeStep(bldgId: string, winId: string) {
  const building = scenery.find(b => b.id === bldgId);
  if (!building) return;
  const winSettings = building.windowSettings[winId];
  if (!winSettings || !winSettings.isNodeRunning) return;

  const seq = sequences.find(s => s.id === winSettings.sequenceId);
  if (!seq || seq.nodes.length === 0) {
    winSettings.isNodeRunning = false;
    return;
  }

  if (winSettings.currentNodeIndex === undefined || winSettings.currentNodeIndex >= seq.nodes.length) {
    winSettings.currentNodeIndex = 0;
  }

  const node = seq.nodes[winSettings.currentNodeIndex];

  if (winSettings.nodeFlickerIntervals) {
    winSettings.nodeFlickerIntervals.forEach(clearInterval);
    winSettings.nodeFlickerIntervals = [];
  } else {
    winSettings.nodeFlickerIntervals = [];
  }

  if (!building.windowColors) building.windowColors = {};

  switch (node.type) {
    case 'delay': {
      // Values stored in model hours; convert to real ms: hours * 60min / cycleSpeed * 1000ms
      const minsPerRealSec = cycleSpeed;
      const msPerModelHour = (60 / minsPerRealSec) * 1000;
      let duration = msPerModelHour;
      if (node.params.delayType === 'fixed') {
        duration = (node.params.delaySeconds ?? 1) * msPerModelHour;
      } else {
        const min = node.params.delayMin ?? 0.5;
        const max = node.params.delayMax ?? 2;
        duration = (min + Math.random() * (max - min)) * msPerModelHour;
      }
      winSettings.nodeTimeoutId = setTimeout(() => {
        winSettings.currentNodeIndex!++;
        executeWindowNodeStep(bldgId, winId);
      }, duration);
      break;
    }

    case 'color': {
      let color = '#f59e0b';
      if (node.params.colorType === 'fixed') {
        color = node.params.colorValue ?? '#f59e0b';
      } else {
        color = '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0');
      }
      building.windowColors[winId] = color;
      applyLightModeStyles();
      winSettings.currentNodeIndex!++;
      executeWindowNodeStep(bldgId, winId);
      break;
    }

    case 'transition': {
      const targetColor = node.params.transitionColor ?? '#ffffff';
      const duration = (node.params.transitionSeconds ?? 2) * 1000;

      winSettings.nodeStepStart = performance.now();
      winSettings.nodeStepDuration = duration;

      const startHex = building.windowColors[winId] || winSettings.customColor;
      const startRgb = hexToRgb(startHex);
      const targetRgb = hexToRgb(targetColor);

      const animateTransition = (now: number) => {
        const elapsed = now - (winSettings.nodeStepStart || 0);
        const progress = Math.min(elapsed / (winSettings.nodeStepDuration || 1000), 1);

        const r = Math.round(startRgb.r + (targetRgb.r - startRgb.r) * progress);
        const g = Math.round(startRgb.g + (targetRgb.g - startRgb.g) * progress);
        const b = Math.round(startRgb.b + (targetRgb.b - startRgb.b) * progress);

        building.windowColors![winId] = rgbToHex(r, g, b);
        applyLightModeStyles();

        if (progress < 1) {
          winSettings.nodeAnimationId = requestAnimationFrame(animateTransition);
        } else {
          winSettings.currentNodeIndex!++;
          executeWindowNodeStep(bldgId, winId);
        }
      };

      winSettings.nodeAnimationId = requestAnimationFrame(animateTransition);
      break;
    }

    case 'flicker': {
      const freq = node.params.flickerFrequency ?? 6;
      const duration = (node.params.flickerDuration ?? 3) * 1000;
      const period = 1000 / freq;

      let isOn = true;
      const flickerTimer = setInterval(() => {
        isOn = !isOn;
        const color = isOn ? (node.params.colorValue || winSettings.customColor) : '#000000';
        building.windowColors![winId] = color;
        applyLightModeStyles();
      }, period);

      winSettings.nodeFlickerIntervals!.push(flickerTimer);
      winSettings.nodeTimeoutId = setTimeout(() => {
        winSettings.currentNodeIndex!++;
        executeWindowNodeStep(bldgId, winId);
      }, duration);
      break;
    }
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Sequence management
// ──────────────────────────────────────────────────────────────────────────────

function renderSequenceDropdown() {
  if (!sequenceSelect) return;
  const currentVal = sequenceSelect.value;
  sequenceSelect.innerHTML = '<option value="">(Kein Ablauf)</option>';
  sequences.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.name;
    sequenceSelect.appendChild(opt);
  });
  // Restore selection if still valid
  if (sequences.find(s => s.id === currentVal)) {
    sequenceSelect.value = currentVal;
  }
}

function openSequenceEditor(seqId: string | null) {
  if (seqId === null) {
    editingSequenceId = `seq-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const newSeq: Sequence = { id: editingSequenceId, name: 'Neuer Ablauf', nodes: [] };
    sequences.push(newSeq);
    saveToLocalStorage();
    renderSequenceDropdown();
  } else {
    editingSequenceId = seqId;
  }

  const seq = sequences.find(s => s.id === editingSequenceId);
  if (!seq) return;

  seqEditorName.value = seq.name;
  renderSequenceEditorSteps();
  modalSequenceEditor.classList.remove('hidden');
}

function closeSequenceEditor() {
  modalSequenceEditor.classList.add('hidden');
  editingSequenceId = null;
  renderSequenceDropdown();
  updateSidebarSettings();
}

function saveSequenceEditor() {
  if (!editingSequenceId) return;
  const seq = sequences.find(s => s.id === editingSequenceId);
  if (!seq) return;

  seq.name = seqEditorName.value.trim() || 'Ablauf';
  saveToLocalStorage();

  // Auto-assign to current window if it has no sequence yet
  if (selectedBuildingId && selectedWindowId) {
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (building) {
      const ws = building.windowSettings[selectedWindowId];
      if (ws && !ws.sequenceId) {
        ws.sequenceId = editingSequenceId;
        saveToLocalStorage();
      }
    }
  }

  closeSequenceEditor();
}

function renderSequenceEditorSteps() {
  if (!editingSequenceId || !seqEditorSteps) return;
  const seq = sequences.find(s => s.id === editingSequenceId);
  if (!seq) return;

  seqEditorSteps.innerHTML = '';

  if (seq.nodes.length === 0) {
    seqEditorSteps.innerHTML = `<div class="text-center text-slate-500 text-[11px] py-8">Keine Schritte vorhanden.<br>Mit "+ Schritt hinzufügen" beginnen.</div>`;
    return;
  }

  seq.nodes.forEach((node, index) => {
    let typeChar = '';
    let label = '';
    let details = '';

    if (node.type === 'delay') {
      typeChar = '⏱';
      label = 'Verzögerung';
      details = node.params.delayType === 'fixed'
        ? `${node.params.delaySeconds?.toFixed(1)}h MBZ (fest)`
        : `${node.params.delayMin?.toFixed(1)}h – ${node.params.delayMax?.toFixed(1)}h MBZ (Zufall)`;
    } else if (node.type === 'color') {
      typeChar = '◉';
      label = 'Farbe';
      details = node.params.colorType === 'fixed'
        ? `${node.params.colorValue?.toUpperCase()}`
        : 'Zufällig';
    } else if (node.type === 'transition') {
      typeChar = '↗';
      label = 'Überblenden';
      details = `${node.params.transitionSeconds?.toFixed(1)}s → ${node.params.transitionColor?.toUpperCase()}`;
    } else if (node.type === 'flicker') {
      typeChar = '~';
      label = 'Flimmern';
      details = `${node.params.flickerFrequency}Hz, ${node.params.flickerDuration?.toFixed(1)}s`;
    }

    const card = document.createElement('div');
    card.className = 'flex items-center gap-2 bg-slate-800/30 border border-slate-700/60 rounded-lg px-3 py-2 text-[11px] group/step cursor-grab';
    card.setAttribute('draggable', 'true');

    card.innerHTML = `
      <span class="text-slate-600 text-[9px] flex-shrink-0 select-none">⠿</span>
      <span class="text-slate-500 text-sm flex-shrink-0">${typeChar}</span>
      <div class="flex flex-col flex-grow min-w-0">
        <span class="font-bold text-slate-200">#${index + 1} ${label}</span>
        <span class="text-[10px] text-slate-500 truncate mt-0.5">${details}</span>
      </div>
      <div class="flex items-center gap-0.5 flex-shrink-0 opacity-0 group-hover/step:opacity-100 transition-opacity">
        <button class="btn-step-edit w-6 h-6 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 rounded text-[10px] transition" data-index="${index}" title="Bearbeiten">✏</button>
        <button class="btn-step-del w-6 h-6 flex items-center justify-center bg-slate-800 hover:bg-red-900/60 text-slate-500 hover:text-red-300 rounded text-[10px] transition" data-index="${index}" title="Löschen">✕</button>
      </div>
    `;

    card.addEventListener('dragstart', (e) => {
      e.dataTransfer?.setData('text/plain', String(index));
      card.classList.add('opacity-40');
    });
    card.addEventListener('dragover', (e) => {
      e.preventDefault();
      card.classList.add('node-drag-target');
    });
    card.addEventListener('dragleave', () => {
      card.classList.remove('node-drag-target');
    });
    card.addEventListener('drop', (e) => {
      e.preventDefault();
      card.classList.remove('node-drag-target');
      const fromIndex = parseInt(e.dataTransfer?.getData('text/plain') || '-1');
      if (!isNaN(fromIndex) && fromIndex !== index && fromIndex >= 0) {
        moveSeqNode(fromIndex, index);
      }
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('opacity-40');
      seqEditorSteps.querySelectorAll('.node-drag-target').forEach(el => el.classList.remove('node-drag-target'));
    });

    seqEditorSteps.appendChild(card);
  });

  seqEditorSteps.querySelectorAll('.btn-step-edit').forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = parseInt((e.currentTarget as HTMLElement).getAttribute('data-index')!);
      openStepConfig(idx);
    });
  });
  seqEditorSteps.querySelectorAll('.btn-step-del').forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = parseInt((e.currentTarget as HTMLElement).getAttribute('data-index')!);
      deleteSeqNode(idx);
    });
  });
}

function moveSeqNode(from: number, to: number) {
  if (!editingSequenceId) return;
  const seq = sequences.find(s => s.id === editingSequenceId);
  if (!seq || to < 0 || to >= seq.nodes.length) return;
  const item = seq.nodes.splice(from, 1)[0];
  seq.nodes.splice(to, 0, item);
  saveToLocalStorage();
  renderSequenceEditorSteps();
}

function deleteSeqNode(index: number) {
  if (!editingSequenceId) return;
  const seq = sequences.find(s => s.id === editingSequenceId);
  if (!seq) return;
  seq.nodes.splice(index, 1);
  saveToLocalStorage();
  renderSequenceEditorSteps();
}

// ──────────────────────────────────────────────────────────────────────────────
// Step config popup
// ──────────────────────────────────────────────────────────────────────────────

function openStepConfig(index: number | null) {
  editingNodeIndex = index;

  let params: NodeConfig['params'] = {};
  if (index !== null && editingSequenceId) {
    const seq = sequences.find(s => s.id === editingSequenceId);
    if (seq && seq.nodes[index]) {
      editingNodeType = seq.nodes[index].type;
      params = seq.nodes[index].params;
    }
  } else {
    editingNodeType = 'delay';
  }

  renderStepTypeTabs(editingNodeType);
  renderStepConfigForm(editingNodeType, params);
  modalStepConfig.classList.remove('hidden');
}

function closeStepConfig() {
  modalStepConfig.classList.add('hidden');
}

function renderStepTypeTabs(activeType: NodeType) {
  document.querySelectorAll('.step-type-btn').forEach(btn => {
    const t = (btn as HTMLElement).getAttribute('data-type') as NodeType;
    btn.className = t === activeType
      ? 'step-type-btn flex-1 py-1.5 text-[10px] font-bold rounded-md bg-slate-800 text-slate-200 border border-slate-700 transition'
      : 'step-type-btn flex-1 py-1.5 text-[10px] font-bold rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition';
  });
}

function renderStepConfigForm(type: NodeType, params: NodeConfig['params']) {
  if (!stepConfigForm) return;
  stepConfigForm.innerHTML = '';

  if (type === 'delay') {
    const isRandom = params.delayType === 'random';
    stepConfigForm.innerHTML = `
      <div class="flex items-center gap-4 select-none">
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="radio" name="sc-delay" value="fixed" ${!isRandom ? 'checked' : ''} id="sc-delay-fixed" class="text-indigo-600 bg-slate-900 border-slate-700">
          <span class="text-[11px] text-slate-300">Fest</span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="radio" name="sc-delay" value="random" ${isRandom ? 'checked' : ''} id="sc-delay-random" class="text-indigo-600 bg-slate-900 border-slate-700">
          <span class="text-[11px] text-slate-300">Zufällig</span>
        </label>
      </div>
      <div id="sc-delay-fixed-group" class="flex justify-between items-center gap-2 ${isRandom ? 'hidden' : ''}">
        <span class="text-[10px] text-slate-400">Dauer (h MBZ):</span>
        <input type="number" id="sc-delay-secs" value="${params.delaySeconds ?? 1}" step="0.5" min="0.1" class="bg-slate-900 border border-slate-700 text-slate-100 rounded p-1 text-center w-20 focus:outline-none focus:border-indigo-500">
      </div>
      <div id="sc-delay-random-group" class="grid grid-cols-2 gap-2 ${!isRandom ? 'hidden' : ''}">
        <div class="space-y-1">
          <span class="text-[9px] text-slate-400 block">Min (h MBZ):</span>
          <input type="number" id="sc-delay-min" value="${params.delayMin ?? 0.5}" step="0.5" min="0.1" class="bg-slate-900 border border-slate-700 text-slate-100 rounded p-1 text-center w-full focus:outline-none focus:border-indigo-500">
        </div>
        <div class="space-y-1">
          <span class="text-[9px] text-slate-400 block">Max (h MBZ):</span>
          <input type="number" id="sc-delay-max" value="${params.delayMax ?? 2}" step="0.5" min="0.1" class="bg-slate-900 border border-slate-700 text-slate-100 rounded p-1 text-center w-full focus:outline-none focus:border-indigo-500">
        </div>
      </div>
    `;
    document.getElementById('sc-delay-fixed')?.addEventListener('change', () => {
      document.getElementById('sc-delay-fixed-group')?.classList.remove('hidden');
      document.getElementById('sc-delay-random-group')?.classList.add('hidden');
    });
    document.getElementById('sc-delay-random')?.addEventListener('change', () => {
      document.getElementById('sc-delay-fixed-group')?.classList.add('hidden');
      document.getElementById('sc-delay-random-group')?.classList.remove('hidden');
    });

  } else if (type === 'color') {
    const isRandom = params.colorType === 'random';
    const colorVal = params.colorValue ?? '#3b82f6';
    stepConfigForm.innerHTML = `
      <div class="flex items-center gap-4 select-none">
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="radio" name="sc-color" value="fixed" ${!isRandom ? 'checked' : ''} id="sc-color-fixed" class="text-indigo-600 bg-slate-900 border-slate-700">
          <span class="text-[11px] text-slate-300">Wunschfarbe</span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="radio" name="sc-color" value="random" ${isRandom ? 'checked' : ''} id="sc-color-random" class="text-indigo-600 bg-slate-900 border-slate-700">
          <span class="text-[11px] text-slate-300">Zufällig</span>
        </label>
      </div>
      <div id="sc-color-group" class="flex items-center gap-2 justify-between ${isRandom ? 'opacity-30' : ''}">
        <span class="text-[10px] text-slate-400">Farbe:</span>
        <div class="flex items-center gap-1.5">
          <input type="color" id="sc-color-picker" value="${colorVal}" class="w-7 h-7 bg-transparent border-none cursor-pointer" ${isRandom ? 'disabled' : ''}>
          <input type="text" id="sc-color-text" value="${colorVal.toUpperCase()}" class="bg-slate-900 border border-slate-700 text-slate-200 rounded p-1 text-[10px] text-center w-16 focus:outline-none focus:border-indigo-500 uppercase" ${isRandom ? 'disabled' : ''}>
        </div>
      </div>
    `;
    const picker = document.getElementById('sc-color-picker') as HTMLInputElement;
    const text = document.getElementById('sc-color-text') as HTMLInputElement;
    const group = document.getElementById('sc-color-group') as HTMLElement;
    document.getElementById('sc-color-fixed')?.addEventListener('change', () => { group.classList.remove('opacity-30'); picker.disabled = false; text.disabled = false; });
    document.getElementById('sc-color-random')?.addEventListener('change', () => { group.classList.add('opacity-30'); picker.disabled = true; text.disabled = true; });
    picker?.addEventListener('input', () => { if (text) text.value = picker.value.toUpperCase(); });
    text?.addEventListener('input', () => { if (picker && text.value.startsWith('#') && text.value.length === 7) picker.value = text.value; });

  } else if (type === 'transition') {
    const color = params.transitionColor ?? '#10b981';
    const secs = params.transitionSeconds ?? 2;
    stepConfigForm.innerHTML = `
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1">
          <span class="text-[10px] text-slate-400 block">Zielfarbe:</span>
          <div class="flex items-center gap-1">
            <input type="color" id="sc-trans-picker" value="${color}" class="w-7 h-7 bg-transparent border-none cursor-pointer">
            <input type="text" id="sc-trans-text" value="${color.toUpperCase()}" class="bg-slate-900 border border-slate-700 text-slate-200 rounded p-1 text-[9px] text-center w-14 focus:outline-none focus:border-indigo-500 uppercase">
          </div>
        </div>
        <div class="space-y-1">
          <span class="text-[10px] text-slate-400 block">Zeit (s):</span>
          <input type="number" id="sc-trans-secs" value="${secs}" step="0.5" min="0.1" class="bg-slate-900 border border-slate-700 text-slate-100 rounded p-1 text-center w-full focus:outline-none focus:border-indigo-500">
        </div>
      </div>
    `;
    const tPicker = document.getElementById('sc-trans-picker') as HTMLInputElement;
    const tText = document.getElementById('sc-trans-text') as HTMLInputElement;
    tPicker?.addEventListener('input', () => { if (tText) tText.value = tPicker.value.toUpperCase(); });
    tText?.addEventListener('input', () => { if (tPicker && tText.value.startsWith('#') && tText.value.length === 7) tPicker.value = tText.value; });

  } else if (type === 'flicker') {
    const freq = params.flickerFrequency ?? 6;
    const dur = params.flickerDuration ?? 3;
    stepConfigForm.innerHTML = `
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1">
          <span class="text-[9px] text-slate-400 block">Frequenz (Hz):</span>
          <input type="number" id="sc-flicker-freq" value="${freq}" min="1" max="50" class="bg-slate-900 border border-slate-700 text-slate-100 rounded p-1 text-center w-full focus:outline-none focus:border-indigo-500">
        </div>
        <div class="space-y-1">
          <span class="text-[9px] text-slate-400 block">Dauer (s):</span>
          <input type="number" id="sc-flicker-dur" value="${dur}" min="0.5" step="0.5" class="bg-slate-900 border border-slate-700 text-slate-100 rounded p-1 text-center w-full focus:outline-none focus:border-indigo-500">
        </div>
      </div>
    `;
  }
}

function saveStepConfig() {
  if (!editingSequenceId) return;
  const seq = sequences.find(s => s.id === editingSequenceId);
  if (!seq) return;

  const type = editingNodeType;
  const params: NodeConfig['params'] = {};

  if (type === 'delay') {
    const isFixed = (document.querySelector('input[name="sc-delay"]:checked') as HTMLInputElement)?.value === 'fixed';
    if (isFixed) {
      params.delayType = 'fixed';
      params.delaySeconds = parseFloat((document.getElementById('sc-delay-secs') as HTMLInputElement)?.value) || 3;
    } else {
      params.delayType = 'random';
      params.delayMin = parseFloat((document.getElementById('sc-delay-min') as HTMLInputElement)?.value) || 1;
      params.delayMax = parseFloat((document.getElementById('sc-delay-max') as HTMLInputElement)?.value) || 5;
    }
  } else if (type === 'color') {
    const isFixed = (document.querySelector('input[name="sc-color"]:checked') as HTMLInputElement)?.value === 'fixed';
    if (isFixed) {
      params.colorType = 'fixed';
      params.colorValue = (document.getElementById('sc-color-text') as HTMLInputElement)?.value || '#3b82f6';
    } else {
      params.colorType = 'random';
    }
  } else if (type === 'transition') {
    params.transitionColor = (document.getElementById('sc-trans-text') as HTMLInputElement)?.value || '#10b981';
    params.transitionSeconds = parseFloat((document.getElementById('sc-trans-secs') as HTMLInputElement)?.value) || 2;
  } else if (type === 'flicker') {
    params.flickerFrequency = parseInt((document.getElementById('sc-flicker-freq') as HTMLInputElement)?.value) || 6;
    params.flickerDuration = parseFloat((document.getElementById('sc-flicker-dur') as HTMLInputElement)?.value) || 3;
  }

  if (editingNodeIndex !== null) {
    seq.nodes[editingNodeIndex] = { ...seq.nodes[editingNodeIndex], type, params };
  } else {
    const id = `node-${Date.now()}-${Math.floor(Math.random() * 100)}`;
    seq.nodes.push({ id, type, params });
  }

  saveToLocalStorage();
  renderSequenceEditorSteps();
  closeStepConfig();
}

// ──────────────────────────────────────────────────────────────────────────────
// Iframe communication
// ──────────────────────────────────────────────────────────────────────────────

function postToControlIframe(type: string, data: object) {
  if (controlIframe && controlIframe.contentWindow) {
    controlIframe.contentWindow.postMessage({ type, ...data }, '*');
  }
}

function sendControlLog(text: string) {
  postToControlIframe('LOG_MESSAGE', { text });
}

function getStats() {
  let windowCount = 0;
  let activeCount = 0;
  scenery.forEach(b => {
    windowCount += b.windows.length;
    b.windows.forEach(w => {
      const ws = b.windowSettings[w.id];
      if (ws && ws.active) activeCount++;
    });
  });

  return {
    segmentCount: scenery.length,
    windowCount,
    activeCount,
    lightMode: scenery.length > 0 ? 'Fenster-Spezifisch' : 'Standard',
    timeString: getFormattedModelTime(),
    cycleActive,
    cycleSpeed,
  };
}

function updateControlStats() {
  postToControlIframe('UPDATE_STATS', getStats());
}

// ──────────────────────────────────────────────────────────────────────────────
// Event listeners
// ──────────────────────────────────────────────────────────────────────────────

function setupEventListeners() {
  tabControl?.addEventListener('click', () => switchTab('control'));
  tabBuild?.addEventListener('click', () => switchTab('build'));

  modalSelector?.addEventListener('click', (e) => {
    if (e.target === modalSelector) modalSelector.classList.add('hidden');
  });

  const openSelector = () => modalSelector.classList.remove('hidden');
  btnAddHouseHeader?.addEventListener('click', openSelector);
  btnAddHouseCenter?.addEventListener('click', openSelector);
  btnCloseSelector?.addEventListener('click', () => modalSelector.classList.add('hidden'));

  btnClearScenery?.addEventListener('click', () => {
    if (confirm('Kulisse wirklich zurücksetzen? Alle Segmente werden gelöscht.')) {
      scenery = [];
      deselectWindow();
      saveToLocalStorage();
      renderScenery();
      applyLightModeStyles();
      sendControlLog('Kulisse zurückgesetzt.');
    }
  });

  windowStateToggle?.addEventListener('change', () => {
    if (!selectedBuildingId || !selectedWindowId) return;
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (!building) return;
    const winSettings = building.windowSettings[selectedWindowId];
    if (winSettings) {
      winSettings.active = windowStateToggle.checked;
      saveToLocalStorage();
      renderScenery();
      applyLightModeStyles();
    }
  });

  windowFollowCycle?.addEventListener('change', () => {
    if (!selectedBuildingId || !selectedWindowId) return;
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (!building) return;
    const winSettings = building.windowSettings[selectedWindowId];
    if (winSettings) {
      winSettings.followCycle = windowFollowCycle.checked;
      saveToLocalStorage();
      applyLightModeStyles();
    }
  });

  const attachCheckbox = (el: HTMLInputElement, effectKey: keyof WindowSettings['effects']) => {
    el?.addEventListener('change', () => {
      if (!selectedBuildingId || !selectedWindowId) return;
      const building = scenery.find(b => b.id === selectedBuildingId);
      if (!building) return;
      const winSettings = building.windowSettings[selectedWindowId];
      if (winSettings) {
        winSettings.effects[effectKey] = el.checked;
        saveToLocalStorage();
        applyLightModeStyles();
      }
    });
  };

  attachCheckbox(fieldEffectParty, 'party');
  attachCheckbox(fieldEffectTv, 'tv');
  attachCheckbox(fieldEffectFire, 'fire');
  attachCheckbox(fieldEffectOffice, 'office');
  attachCheckbox(fieldEffectWelding, 'welding');
  attachCheckbox(fieldEffectNeon, 'neon');

  customColorPicker?.addEventListener('input', () => {
    if (!selectedBuildingId || !selectedWindowId) return;
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (!building) return;
    const winSettings = building.windowSettings[selectedWindowId];
    if (winSettings) {
      winSettings.customColor = customColorPicker.value;
      if (customColorHex) customColorHex.textContent = winSettings.customColor.toUpperCase();
      saveToLocalStorage();
      applyLightModeStyles();
    }
  });

  document.querySelectorAll('.btn-color-preset').forEach(btn => {
    btn.addEventListener('click', (e) => {
      if (!selectedBuildingId || !selectedWindowId) return;
      const building = scenery.find(b => b.id === selectedBuildingId);
      if (!building) return;
      const winSettings = building.windowSettings[selectedWindowId];
      if (winSettings) {
        const color = (e.currentTarget as HTMLElement).getAttribute('data-color')!;
        winSettings.customColor = color;
        if (customColorPicker) customColorPicker.value = color;
        if (customColorHex) customColorHex.textContent = color.toUpperCase();
        saveToLocalStorage();
        applyLightModeStyles();
      }
    });
  });

  setTabCycle?.addEventListener('click', () => switchSettingsTab('cycle'));
  setTabColor?.addEventListener('click', () => switchSettingsTab('color'));
  setTabNodes?.addEventListener('click', () => switchSettingsTab('nodes'));

  // ── Sequence / player listeners ────────────────────────────────────────────

  sequenceSelect?.addEventListener('change', () => {
    if (!selectedBuildingId || !selectedWindowId) return;
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (!building) return;
    const ws = building.windowSettings[selectedWindowId];
    if (!ws) return;

    stopWindowNodePlayer(ws);
    ws.sequenceId = sequenceSelect.value || null;
    saveToLocalStorage();
    updateSidebarSettings();

    // Auto-start if in nodes mode
    if (ws.lightMode === 'nodes' && ws.sequenceId) {
      startWindowNodePlayer(selectedBuildingId, selectedWindowId);
    }
  });

  btnNewSequence?.addEventListener('click', () => openSequenceEditor(null));

  btnEditSequence?.addEventListener('click', () => {
    if (!selectedBuildingId || !selectedWindowId) return;
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (!building) return;
    const ws = building.windowSettings[selectedWindowId];
    const seqId = ws?.sequenceId || sequenceSelect?.value || null;
    if (seqId) {
      openSequenceEditor(seqId);
    } else {
      openSequenceEditor(null);
    }
  });

  btnNodePlay?.addEventListener('click', () => {
    if (selectedBuildingId && selectedWindowId) {
      startWindowNodePlayer(selectedBuildingId, selectedWindowId);
    }
  });

  btnNodePause?.addEventListener('click', () => {
    if (selectedBuildingId && selectedWindowId) {
      const building = scenery.find(b => b.id === selectedBuildingId);
      if (building) {
        const ws = building.windowSettings[selectedWindowId];
        if (ws) {
          stopWindowNodePlayer(ws);
          updateSidebarSettings();
        }
      }
    }
  });

  btnNodeClear?.addEventListener('click', () => {
    if (!selectedBuildingId || !selectedWindowId) return;
    const building = scenery.find(b => b.id === selectedBuildingId);
    if (!building) return;
    const ws = building.windowSettings[selectedWindowId];
    if (ws) {
      stopWindowNodePlayer(ws);
      ws.sequenceId = null;
      saveToLocalStorage();
      updateSidebarSettings();
    }
  });

  // ── Sequence editor modal ──────────────────────────────────────────────────

  btnCloseSeqEditor?.addEventListener('click', closeSequenceEditor);
  btnSeqSave?.addEventListener('click', saveSequenceEditor);
  btnSeqAddStep?.addEventListener('click', () => openStepConfig(null));

  modalSequenceEditor?.addEventListener('click', (e) => {
    if (e.target === modalSequenceEditor) closeSequenceEditor();
  });

  // ── Step config modal ──────────────────────────────────────────────────────

  document.getElementById('step-type-tabs')?.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement).closest('.step-type-btn') as HTMLElement | null;
    if (!btn) return;
    const type = btn.getAttribute('data-type') as NodeType;
    editingNodeType = type;
    renderStepTypeTabs(type);
    renderStepConfigForm(type, {});
  });

  btnStepConfigSave?.addEventListener('click', saveStepConfig);
  btnStepConfigCancel?.addEventListener('click', closeStepConfig);
  btnCloseStepConfig?.addEventListener('click', closeStepConfig);

  modalStepConfig?.addEventListener('click', (e) => {
    if (e.target === modalStepConfig) closeStepConfig();
  });

  // ── Zoom buttons ───────────────────────────────────────────────────────────

  btnZoomIn?.addEventListener('click', () => {
    zoom = Math.min(5, zoom * 1.2);
    applyTransform();
  });
  btnZoomOut?.addEventListener('click', () => {
    zoom = Math.max(0.1, zoom / 1.2);
    applyTransform();
  });
  btnZoomFit?.addEventListener('click', () => fitToScreen());

  // ── Viewport wheel zoom ────────────────────────────────────────────────────

  buildViewport?.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    const rect = buildViewport.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const newZoom = Math.max(0.1, Math.min(5, zoom * factor));
    panX = mx - (mx - panX) * (newZoom / zoom);
    panY = my - (my - panY) * (newZoom / zoom);
    zoom = newZoom;
    applyTransform();
  }, { passive: false });

  // ── Viewport pan ───────────────────────────────────────────────────────────

  buildViewport?.addEventListener('mousedown', (e) => {
    if (scenery.length === 0) return;
    const target = e.target as HTMLElement;
    if (target.tagName === 'BUTTON' || target.closest('button')) return;
    if (target.classList.contains('z-30')) return;
    isPanning = true;
    panStartX = e.clientX - panX;
    panStartY = e.clientY - panY;
    buildViewport.style.cursor = 'grabbing';
  });

  buildViewport?.addEventListener('mousemove', (e) => {
    if (!isPanning) return;
    panX = e.clientX - panStartX;
    panY = e.clientY - panStartY;
    applyTransform();
  });

  const stopPan = () => {
    if (!isPanning) return;
    isPanning = false;
    buildViewport.style.cursor = '';
  };
  buildViewport?.addEventListener('mouseup', stopPan);
  buildViewport?.addEventListener('mouseleave', stopPan);
  buildViewport?.addEventListener('dragstart', () => { isPanning = false; buildViewport.style.cursor = ''; });

  // ── postMessage from control iframe ───────────────────────────────────────

  window.addEventListener('message', (event) => {
    const msg = event.data;
    if (!msg || typeof msg !== 'object') return;

    switch (msg.type) {
      case 'CONTROL_HANDSHAKE':
        updateControlStats();
        break;

      case 'CONTROL_SET_CYCLE_ACTIVE':
        cycleActive = msg.active === true;
        saveToLocalStorage();
        break;

      case 'CONTROL_SET_CYCLE_SPEED':
        cycleSpeed = parseInt(msg.speed) || 5;
        saveToLocalStorage();
        break;

      case 'CONTROL_ALL_ON':
        scenery.forEach(b => b.windows.forEach(w => { if (b.windowSettings[w.id]) b.windowSettings[w.id].active = true; }));
        saveToLocalStorage(); renderScenery(); applyLightModeStyles();
        if (selectedBuildingId && selectedWindowId) updateSidebarSettings();
        sendControlLog('Befehl ausgeführt: Alles AN');
        break;

      case 'CONTROL_ALL_OFF':
        scenery.forEach(b => b.windows.forEach(w => { if (b.windowSettings[w.id]) b.windowSettings[w.id].active = false; }));
        saveToLocalStorage(); renderScenery(); applyLightModeStyles();
        if (selectedBuildingId && selectedWindowId) updateSidebarSettings();
        sendControlLog('Befehl ausgeführt: Alles AUS');
        break;

      case 'CONTROL_RANDOM':
        scenery.forEach(b => b.windows.forEach(w => { if (b.windowSettings[w.id]) b.windowSettings[w.id].active = Math.random() > 0.5; }));
        saveToLocalStorage(); renderScenery(); applyLightModeStyles();
        if (selectedBuildingId && selectedWindowId) updateSidebarSettings();
        sendControlLog('Befehl ausgeführt: Zufalls-Mix');
        break;

      case 'CONTROL_DEMO':
        triggerDemoMode();
        break;

      case 'CONTROL_EMERGENCY':
        triggerEmergencyShutoff();
        break;
    }
  });
}

// ──────────────────────────────────────────────────────────────────────────────
// Demo & Emergency
// ──────────────────────────────────────────────────────────────────────────────

function triggerDemoMode() {
  if (scenery.length === 0 && availableImages.length > 0) {
    availableImages.forEach(imgKey => addBuildingToScenery(imgKey));
  }

  cycleActive = true;
  cycleSpeed = 15;
  modelHour = 18;
  modelMinute = 0;

  scenery.forEach(b => b.windows.forEach(w => {
    const ws = b.windowSettings[w.id];
    if (ws) { ws.lightMode = 'cycle'; ws.active = true; }
  }));

  saveToLocalStorage();
  renderScenery();
  applyLightModeStyles();
  if (selectedBuildingId && selectedWindowId) updateSidebarSettings();
  sendControlLog('Demo-Modus aktiv: Schneller Zyklus ab 18:00.');
}

function triggerEmergencyShutoff() {
  scenery.forEach(b => b.windows.forEach(w => {
    const ws = b.windowSettings[w.id];
    if (ws) {
      stopWindowNodePlayer(ws);
      ws.lightMode = 'color';
      ws.customColor = '#ef4444';
      ws.active = true;
    }
  }));

  saveToLocalStorage();
  renderScenery();
  applyLightModeStyles();
  if (selectedBuildingId && selectedWindowId) updateSidebarSettings();
  sendControlLog('NOT-AUS: Rote Notbeleuchtung an allen Fenstern.');
}

// ──────────────────────────────────────────────────────────────────────────────
// Color utilities
// ──────────────────────────────────────────────────────────────────────────────

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result
    ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) }
    : { r: 245, g: 158, b: 11 };
}

function rgbToHex(r: number, g: number, b: number): string {
  return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
}

// ──────────────────────────────────────────────────────────────────────────────
// Start
// ──────────────────────────────────────────────────────────────────────────────

init();
