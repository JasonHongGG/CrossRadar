const LOCAL_DATE_FORMAT = new Intl.DateTimeFormat('zh-TW', {
  hour: '2-digit',
  minute: '2-digit',
  month: 'numeric',
  day: 'numeric',
});

const DEFAULT_VIEW_MODE = 'pending';
const MAP_HOME = [23.7, 121.0];
const MAP_HOME_ZOOM = 7;
const canvasRenderer = L.canvas({ padding: 0.5 });

const map = L.map('map', {
  zoomControl: false,
  preferCanvas: true,
  scrollWheelZoom: true,
}).setView(MAP_HOME, MAP_HOME_ZOOM);

L.control.zoom({ position: 'bottomright' }).addTo(map);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors',
}).addTo(map);

const state = {
  overview: null,
  reviewPayload: null,
  reviewEntries: [],
  mappedFeatures: [],
  osmFeatures: [],
  activeReviewId: null,
  draftOsmId: null,
  viewMode: DEFAULT_VIEW_MODE,
  showCurated: true,
  showOsm: true,
  autoAdvance: false,
  curatedLayer: L.layerGroup().addTo(map),
  osmLayer: L.layerGroup().addTo(map),
  stationLayer: L.layerGroup().addTo(map),
};

const elements = {
  activeBadge: document.getElementById('activeBadge'),
  autoAdvanceButton: document.getElementById('autoAdvanceButton'),
  candidateCard: document.getElementById('candidateCard'),
  clearDraftButton: document.getElementById('clearDraftButton'),
  curatedToggleButton: document.getElementById('curatedToggleButton'),
  fitActiveButton: document.getElementById('fitActiveButton'),
  mappedMetric: document.getElementById('mappedMetric'),
  officialCard: document.getElementById('officialCard'),
  osmToggleButton: document.getElementById('osmToggleButton'),
  pendingMetric: document.getElementById('pendingMetric'),
  progressPercent: document.getElementById('progressPercent'),
  progressRing: document.getElementById('progressRing'),
  queueFilter: document.getElementById('queueFilter'),
  queueList: document.getElementById('queueList'),
  reloadButton: document.getElementById('reloadButton'),
  removeMappingButton: document.getElementById('removeMappingButton'),
  resolvedMetric: document.getElementById('resolvedMetric'),
  saveMappingButton: document.getElementById('saveMappingButton'),
  statusBar: document.getElementById('statusBar'),
  nextPendingButton: document.getElementById('nextPendingButton'),
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function setStatus(message, tone = 'neutral') {
  elements.statusBar.textContent = message;
  elements.statusBar.dataset.tone = tone;
}

function formatDateTime(value) {
  if (!value) return '尚未更新';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '尚未更新';
  return LOCAL_DATE_FORMAT.format(date);
}

function apiUrl(path, params = null) {
  const query = params ? `?${params.toString()}` : '';
  return `${path}${query}`;
}

async function apiGet(path, params = null) {
  return apiRequest(path, { params });
}

async function apiRequest(path, { method = 'GET', params = null, body = null } = {}) {
  const response = await fetch(apiUrl(path, params), {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : text;
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return payload;
}

function getReviewById(crossingId = state.activeReviewId) {
  return state.reviewEntries.find((entry) => entry.crossing_id === crossingId) ?? null;
}

function getSavedOsmId(entry) {
  return entry?.manual_mapping?.osm_id ?? null;
}

function getOsmFeatureById(osmId) {
  if (osmId == null) return null;
  return state.osmFeatures.find((feature) => feature.properties?.osm_id === osmId) ?? null;
}

function getMappedFeatureByCrossingId(crossingId) {
  return state.mappedFeatures.find((feature) => feature.id === crossingId) ?? null;
}

function getStationCoords(position) {
  const lat = Number(position?.PositionLat);
  const lon = Number(position?.PositionLon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lat, lon];
}

function getActiveStationContext() {
  const entry = getReviewById();
  if (!entry) return [];

  return [
    {
      role: '前站',
      name: entry.station_a_name || '未提供前站',
      coords: getStationCoords(entry.station_a_position),
      fillColor: '#ffd166',
      tooltipClass: 'is-a',
    },
    {
      role: '後站',
      name: entry.station_b_name || '未提供後站',
      coords: getStationCoords(entry.station_b_position),
      fillColor: '#7dc7ff',
      tooltipClass: 'is-b',
    },
  ].filter((station) => station.coords);
}

function getOsmDisplayName(feature) {
  return feature?.properties?.name || feature?.properties?.road_names?.[0] || `OSM ${feature?.properties?.osm_id}`;
}

function getRoadLabel(feature) {
  return safeArray(feature?.properties?.road_names).slice(0, 2).join(' · ') || '未命名道路';
}

function getRailLabel(feature) {
  return safeArray(feature?.properties?.rail_names).slice(0, 2).join(' · ') || '未命名鐵道';
}

function categoryShortLabel(category) {
  if (category === 'road_name_mismatch_or_unnamed_osm_road') return '路名差異';
  if (category === 'duplicate_official_name_requires_km_disambiguation') return '同名拆分';
  if (category === 'local_place_name_not_reflected_in_osm') return '地名型';
  if (category === 'facility_or_private_crossing_name_not_reflected_in_osm') return '專用型';
  return '人工判讀';
}

function categoryTone(category) {
  if (category === 'road_name_mismatch_or_unnamed_osm_road') return 'tone-coral';
  if (category === 'duplicate_official_name_requires_km_disambiguation') return 'tone-gold';
  if (category === 'facility_or_private_crossing_name_not_reflected_in_osm') return 'tone-teal';
  return 'tone-violet';
}

function buildMatchedOsmLookup() {
  const lookup = new Map();
  state.mappedFeatures.forEach((feature) => {
    const matchedOsmId = feature.properties?.matched_osm_id;
    if (matchedOsmId == null) return;
    const key = String(matchedOsmId);
    const entries = lookup.get(key) || [];
    entries.push(feature);
    lookup.set(key, entries);
  });
  return lookup;
}

function getVisibleEntries() {
  if (state.viewMode === 'resolved') {
    return state.reviewEntries.filter((entry) => entry.resolved);
  }
  if (state.viewMode === 'all') {
    return [...state.reviewEntries];
  }
  return state.reviewEntries.filter((entry) => !entry.resolved);
}

function isVisibleEntryId(crossingId) {
  return getVisibleEntries().some((entry) => entry.crossing_id === crossingId);
}

function ensureActiveEntry(preferredId = null) {
  const visibleEntries = getVisibleEntries();
  const fallbackEntries = visibleEntries.length
    ? visibleEntries
    : state.viewMode === 'all'
      ? state.reviewEntries
      : [];
  const nextId = [preferredId, state.activeReviewId]
    .filter(Boolean)
    .find((crossingId) => fallbackEntries.some((entry) => entry.crossing_id === crossingId)) || fallbackEntries[0]?.crossing_id || null;

  const changed = state.activeReviewId !== nextId;
  state.activeReviewId = nextId;

  const activeEntry = getReviewById();
  if (!activeEntry) {
    state.draftOsmId = null;
    return;
  }

  const savedOsmId = getSavedOsmId(activeEntry);
  if (changed) {
    state.draftOsmId = savedOsmId;
    return;
  }

  if (state.draftOsmId != null && getOsmFeatureById(state.draftOsmId) != null) {
    return;
  }

  state.draftOsmId = savedOsmId;
}

function updateProgressRing(percent) {
  const degrees = Math.max(0, Math.min(360, percent * 3.6));
  elements.progressRing.style.setProperty('--progress', `${degrees}deg`);
  elements.progressPercent.textContent = `${percent}%`;
}

function renderHeader() {
  const dataset = state.overview?.dataset || {};
  const reviewMeta = state.reviewPayload?.metadata || {};
  const pending = reviewMeta.pending_count ?? 0;
  const resolved = reviewMeta.resolved_count ?? 0;
  const total = pending + resolved;
  const percent = total ? Math.round((resolved / total) * 100) : 0;

  elements.mappedMetric.textContent = String(dataset.mapped_feature_count ?? 0);
  elements.pendingMetric.textContent = String(pending);
  elements.resolvedMetric.textContent = String(resolved);
  updateProgressRing(percent);
}

function syncToggleButtons() {
  elements.curatedToggleButton.classList.toggle('is-active', state.showCurated);
  elements.curatedToggleButton.setAttribute('aria-pressed', String(state.showCurated));
  elements.osmToggleButton.classList.toggle('is-active', state.showOsm);
  elements.osmToggleButton.setAttribute('aria-pressed', String(state.showOsm));
  elements.autoAdvanceButton.classList.toggle('is-active', state.autoAdvance);
  elements.autoAdvanceButton.setAttribute('aria-pressed', String(state.autoAdvance));
}

function renderQueue(preserveScroll = true) {
  const visibleEntries = getVisibleEntries();
  const scrollTop = preserveScroll ? elements.queueList.scrollTop : 0;

  if (!visibleEntries.length) {
    elements.queueList.innerHTML = '<div class="queue-empty">目前這個篩選下沒有項目。</div>';
    updateQueueSelection();
    return;
  }

  elements.queueList.innerHTML = visibleEntries
    .map((entry, index) => `
      <button
        class="queue-item ${entry.resolved ? 'is-resolved' : ''}"
        type="button"
        data-review-id="${escapeHtml(entry.crossing_id)}"
        style="--delay:${Math.min(index, 10) * 30}ms"
      >
        <span class="queue-stripe ${categoryTone(entry.analysis?.manual_mapping_category)}"></span>
        <div class="queue-copy">
          <strong>${escapeHtml(entry.name)}</strong>
          <span>${escapeHtml(entry.line)} · ${escapeHtml(entry.km_marker || '未標公里')}</span>
        </div>
        <span class="queue-state ${entry.resolved ? 'queue-state-resolved' : 'queue-state-pending'}"></span>
      </button>
    `)
    .join('');

  elements.queueList.scrollTop = scrollTop;
  updateQueueSelection();
}

function updateQueueSelection(scrollIntoView = false) {
  const activeId = state.activeReviewId;
  const items = elements.queueList.querySelectorAll('[data-review-id]');
  items.forEach((item) => {
    const isActive = item.dataset.reviewId === activeId;
    item.classList.toggle('is-active', isActive);
    if (isActive && scrollIntoView) {
      item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });

  elements.queueFilter.querySelectorAll('[data-filter]').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.filter === state.viewMode);
  });
}

function renderActiveBadge() {
  const entry = getReviewById();
  if (!entry) {
    elements.activeBadge.innerHTML = `
      <div class="active-shell is-complete">
        <span class="active-caption">all clear</span>
        <strong>沒有待處理項目</strong>
      </div>
    `;
    return;
  }

  elements.activeBadge.innerHTML = `
    <div class="active-shell ${entry.resolved ? 'is-resolved' : ''}">
      <span class="active-caption ${entry.resolved ? 'state-resolved' : 'state-pending'}">${entry.resolved ? 'resolved' : 'pending'}</span>
      <strong>${escapeHtml(entry.name)}</strong>
      <span>${escapeHtml(entry.line)} · ${escapeHtml(entry.km_marker || '未標公里')}</span>
      <small>${escapeHtml(entry.station_pair_text || '')}</small>
    </div>
  `;
}

function renderOfficialCard() {
  const entry = getReviewById();
  if (!entry) {
    elements.officialCard.innerHTML = '<div class="empty-card"><strong>Queue 已清空</strong><span>切到「全部」可以回看已存映射。</span></div>';
    return;
  }

  const position = state.reviewEntries.findIndex((item) => item.crossing_id === entry.crossing_id) + 1;
  elements.officialCard.innerHTML = `
    <div class="card-kicker">
      <span class="section-pill ${entry.resolved ? 'is-success' : 'is-alert'}">${entry.resolved ? '已定位' : '待定位'}</span>
      <span class="mini-code">${position}/${state.reviewEntries.length}</span>
    </div>
    <h2 class="card-title">${escapeHtml(entry.name)}</h2>
    <div class="chip-row">
      <span class="info-chip">${escapeHtml(entry.line)}</span>
      <span class="info-chip">${escapeHtml(entry.km_marker || '未標公里')}</span>
      <span class="info-chip ${categoryTone(entry.analysis?.manual_mapping_category)}">${escapeHtml(categoryShortLabel(entry.analysis?.manual_mapping_category))}</span>
    </div>
    <div class="route-ribbon">${escapeHtml(entry.station_pair_text || '未提供站間')}</div>
    <div class="meta-row">
      <span>${escapeHtml(entry.county || '未知縣市')}</span>
      <span>${formatDateTime(state.reviewPayload?.metadata?.manual_mapping_file?.updated_at)}</span>
    </div>
  `;
}

function renderCandidateCard() {
  const entry = getReviewById();
  if (!entry) {
    elements.candidateCard.classList.remove('is-draft');
    elements.candidateCard.innerHTML = '<div class="empty-card"><strong>完成</strong><span>已經沒有候選需要處理。</span></div>';
    return;
  }

  const savedOsmId = getSavedOsmId(entry);
  const draftFeature = getOsmFeatureById(state.draftOsmId);
  const savedFeature = getOsmFeatureById(savedOsmId);
  const candidateFeature = draftFeature || savedFeature;
  const isDraft = state.draftOsmId != null && state.draftOsmId !== savedOsmId;
  const matchedLookup = buildMatchedOsmLookup();
  const conflictNames = candidateFeature
    ? safeArray(matchedLookup.get(String(candidateFeature.properties?.osm_id)))
      .filter((feature) => feature.id !== entry.crossing_id)
      .map((feature) => feature.properties?.name)
      .filter(Boolean)
    : [];

  elements.candidateCard.classList.toggle('is-draft', isDraft);

  if (!candidateFeature) {
    elements.candidateCard.innerHTML = `
      <div class="empty-card empty-card-focus">
        <span class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M4 9V4H9" />
            <path d="M15 4H20V9" />
            <path d="M20 15V20H15" />
            <path d="M9 20H4V15" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </span>
        <strong>點地圖選 OSM 點</strong>
        <span>候選會固定在這裡，不再把整個面板重繪到最上面。</span>
      </div>
    `;
    return;
  }

  elements.candidateCard.innerHTML = `
    <div class="card-kicker">
      <span class="section-pill ${isDraft ? 'is-draft' : savedOsmId != null ? 'is-success' : ''}">${isDraft ? 'draft' : 'saved'}</span>
      <span class="mini-code">OSM ${escapeHtml(candidateFeature.properties?.osm_id)}</span>
    </div>
    <h2 class="card-title card-title-small">${escapeHtml(getOsmDisplayName(candidateFeature))}</h2>
    <div class="candidate-stack">
      <div class="candidate-row">
        <svg viewBox="0 0 20 20" fill="none">
          <path d="M4 14L8 6L12 14L16 8" />
        </svg>
        <span>${escapeHtml(getRoadLabel(candidateFeature))}</span>
      </div>
      <div class="candidate-row">
        <svg viewBox="0 0 20 20" fill="none">
          <path d="M6 4V16" />
          <path d="M14 4V16" />
          <path d="M6 7H14" />
          <path d="M6 13H14" />
        </svg>
        <span>${escapeHtml(getRailLabel(candidateFeature))}</span>
      </div>
    </div>
    ${savedOsmId != null && isDraft ? `<div class="subtle-note">已存 OSM ${escapeHtml(savedOsmId)}</div>` : ''}
    ${conflictNames.length ? `<div class="warning-chip">已被 ${conflictNames.map((name) => escapeHtml(name)).join(' · ')} 使用</div>` : ''}
  `;
}

function updateActionButtons() {
  const activeEntry = getReviewById();
  const savedOsmId = getSavedOsmId(activeEntry);
  const hasDraft = state.draftOsmId != null;
  const saveDisabled = !activeEntry || !hasDraft || state.draftOsmId === savedOsmId;
  const clearDisabled = !activeEntry || (!hasDraft && savedOsmId == null) || (savedOsmId != null && state.draftOsmId === savedOsmId);
  const removeDisabled = !activeEntry || savedOsmId == null;

  elements.saveMappingButton.disabled = saveDisabled;
  elements.clearDraftButton.disabled = clearDisabled;
  elements.removeMappingButton.disabled = removeDisabled;
  elements.saveMappingButton.textContent = hasDraft ? `儲存 OSM ${state.draftOsmId}` : '儲存映射';
  syncToggleButtons();
}

function renderPanels() {
  renderHeader();
  renderActiveBadge();
  renderOfficialCard();
  renderCandidateCard();
  updateActionButtons();
}

function selectOsmCandidate(osmId, activeEntry = getReviewById()) {
  if (!activeEntry || osmId == null) return false;
  state.draftOsmId = osmId;
  renderPanels();
  renderMapLayers();
  setStatus(`已選擇 OSM ${osmId} 作為 ${activeEntry.name} 的候選。`, 'success');
  return true;
}

function findNearestOsmFeature(containerPoint, maxDistancePx = 14) {
  const maxDistanceSquared = maxDistancePx * maxDistancePx;
  let nearestFeature = null;
  let nearestDistanceSquared = Number.POSITIVE_INFINITY;

  state.osmFeatures.forEach((feature) => {
    const coordinates = feature.geometry?.coordinates;
    if (!coordinates) return;
    const featurePoint = map.latLngToContainerPoint([coordinates[1], coordinates[0]]);
    const dx = featurePoint.x - containerPoint.x;
    const dy = featurePoint.y - containerPoint.y;
    const distanceSquared = (dx * dx) + (dy * dy);

    if (distanceSquared > maxDistanceSquared || distanceSquared >= nearestDistanceSquared) {
      return;
    }

    nearestDistanceSquared = distanceSquared;
    nearestFeature = feature;
  });

  return nearestFeature;
}

function renderCuratedMarkers() {
  state.curatedLayer.clearLayers();
  if (!state.showCurated) return;

  state.mappedFeatures.forEach((feature) => {
    if (!feature.geometry?.coordinates) return;
    const [lon, lat] = feature.geometry.coordinates;
    const isActive = feature.id === state.activeReviewId;
    const marker = L.circleMarker([lat, lon], {
      renderer: canvasRenderer,
      radius: isActive ? 7 : 5,
      weight: isActive ? 2.6 : 1.8,
      color: isActive ? '#0d2f4f' : '#b84630',
      fillColor: isActive ? '#10b8a6' : '#f06449',
      fillOpacity: 1,
      interactive: false,
    });
    marker.addTo(state.curatedLayer);
    marker.bringToFront();
  });
}

function renderStationContext() {
  state.stationLayer.clearLayers();

  const stations = getActiveStationContext();
  if (!stations.length) return;

  if (stations.length === 2) {
    L.polyline(stations.map((station) => station.coords), {
      color: '#154c79',
      weight: 5,
      opacity: 0.72,
      dashArray: '10 10',
      lineCap: 'round',
      lineJoin: 'round',
      interactive: false,
    }).addTo(state.stationLayer);
  }

  stations.forEach((station) => {
    L.circleMarker(station.coords, {
      renderer: canvasRenderer,
      radius: 16,
      weight: 2,
      color: station.fillColor,
      opacity: 0.5,
      fillColor: station.fillColor,
      fillOpacity: 0.14,
      interactive: false,
    }).addTo(state.stationLayer);

    const marker = L.circleMarker(station.coords, {
      renderer: canvasRenderer,
      radius: 8.5,
      weight: 3,
      color: '#10273f',
      fillColor: station.fillColor,
      fillOpacity: 1,
      interactive: false,
    });

    marker.bindTooltip(
      `<div class="station-context-label"><span>${escapeHtml(station.role)}</span><strong>${escapeHtml(station.name)}</strong></div>`,
      {
        permanent: true,
        direction: 'top',
        offset: [0, -16],
        className: `station-context-tooltip ${station.tooltipClass}`,
      }
    );
    marker.addTo(state.stationLayer);
    marker.bringToFront();
  });
}

function renderOsmMarkers() {
  state.osmLayer.clearLayers();
  if (!state.showOsm) return;

  const matchedLookup = buildMatchedOsmLookup();
  const activeEntry = getReviewById();
  const savedOsmId = getSavedOsmId(activeEntry);

  state.osmFeatures.forEach((feature) => {
    if (!feature.geometry?.coordinates) return;
    const [lon, lat] = feature.geometry.coordinates;
    const osmId = feature.properties?.osm_id;
    const matchedCount = safeArray(matchedLookup.get(String(osmId))).length;
    const isDraft = state.draftOsmId === osmId;
    const isSaved = savedOsmId === osmId;

    const marker = L.circleMarker([lat, lon], {
      renderer: canvasRenderer,
      radius: isDraft ? 8 : isSaved ? 6.5 : matchedCount ? 3.7 : 4.2,
      weight: isDraft || isSaved ? 2.4 : 1,
      color: isDraft ? '#925f04' : isSaved ? '#0d6b63' : matchedCount ? '#6b7ea3' : '#6d4cff',
      fillColor: isDraft ? '#f5a524' : isSaved ? '#10b8a6' : matchedCount ? '#c7d2e8' : '#a084ff',
      fillOpacity: isDraft || isSaved ? 0.95 : matchedCount ? 0.34 : 0.58,
    });

    marker.on('click', () => {
      selectOsmCandidate(osmId, activeEntry);
    });
    marker.addTo(state.osmLayer);
  });
}

function renderMapLayers() {
  renderOsmMarkers();
  renderCuratedMarkers();
  renderStationContext();
}

function getActiveFocusPoints() {
  const points = [];
  const focusCoords = getFocusCoords();
  if (focusCoords) {
    points.push([focusCoords[1], focusCoords[0]]);
  }
  getActiveStationContext().forEach((station) => {
    points.push(station.coords);
  });
  return points;
}

function getFocusCoords() {
  const draftFeature = getOsmFeatureById(state.draftOsmId);
  if (draftFeature?.geometry?.coordinates) {
    return draftFeature.geometry.coordinates;
  }

  const activeEntry = getReviewById();
  const savedFeature = getOsmFeatureById(getSavedOsmId(activeEntry));
  if (savedFeature?.geometry?.coordinates) {
    return savedFeature.geometry.coordinates;
  }

  const mappedFeature = getMappedFeatureByCrossingId(state.activeReviewId);
  return mappedFeature?.geometry?.coordinates || null;
}

function focusActive({ silent = false } = {}) {
  const points = getActiveFocusPoints();
  if (!points.length) {
    if (!silent) {
      setStatus('這筆目前還沒有可聚焦的位置。', 'warning');
    }
    return;
  }

  if (points.length === 1) {
    map.flyTo(points[0], 16, { duration: 0.55 });
    return;
  }

  map.fitBounds(points, {
    padding: [72, 72],
    maxZoom: 14,
    animate: true,
  });
}

function selectReviewEntry(crossingId, { scrollIntoView = false, focusMap = true } = {}) {
  if (!state.reviewEntries.some((entry) => entry.crossing_id === crossingId)) return;

  state.activeReviewId = crossingId;
  state.draftOsmId = getSavedOsmId(getReviewById());
  updateQueueSelection(scrollIntoView);
  renderPanels();
  renderMapLayers();
  if (focusMap) {
    focusActive({ silent: true });
  }
}

function getPendingEntries() {
  return state.reviewEntries.filter((entry) => !entry.resolved);
}

function nextPendingId(fromCrossingId = state.activeReviewId) {
  const pendingEntries = getPendingEntries();
  if (!pendingEntries.length) return null;
  const currentIndex = pendingEntries.findIndex((entry) => entry.crossing_id === fromCrossingId);
  if (currentIndex === -1) return pendingEntries[0].crossing_id;
  return pendingEntries[Math.min(currentIndex + 1, pendingEntries.length - 1)].crossing_id;
}

function jumpToNextPending({ scrollIntoView = true } = {}) {
  const nextId = nextPendingId();
  if (!nextId) {
    setStatus('目前沒有下一筆待處理項目。', 'warning');
    return;
  }
  selectReviewEntry(nextId, { scrollIntoView });
}

async function fetchDatasets() {
  const [osmPayload] = await Promise.all([
    apiGet('/api/crossings/osm', new URLSearchParams({ limit: '5000' })),
    fetchReviewState(),
  ]);

  state.osmFeatures = safeArray(osmPayload.features);
}

async function fetchReviewState() {
  const [overview, mappedPayload, reviewPayload] = await Promise.all([
    apiGet('/api/system/overview'),
    apiGet('/api/crossings', new URLSearchParams({ limit: '5000', mapped_only: 'true' })),
    apiGet('/api/crossings/manual-review'),
  ]);

  state.overview = overview;
  state.mappedFeatures = safeArray(mappedPayload.features);
  state.reviewPayload = reviewPayload;
  state.reviewEntries = safeArray(reviewPayload.entries);
}

async function reloadAll({ preferredId = state.activeReviewId, preserveQueueScroll = true } = {}) {
  await fetchDatasets();
  ensureActiveEntry(preferredId);
  renderQueue(preserveQueueScroll);
  renderPanels();
  renderMapLayers();
}

async function reloadReviewState({ preferredId = state.activeReviewId, preserveQueueScroll = true } = {}) {
  await fetchReviewState();
  ensureActiveEntry(preferredId);
  renderQueue(preserveQueueScroll);
  renderPanels();
  renderMapLayers();
}

async function saveCurrentMapping() {
  const activeEntry = getReviewById();
  if (!activeEntry || state.draftOsmId == null) {
    setStatus('先選一個 OSM 點再儲存。', 'warning');
    return;
  }

  const nextPending = nextPendingId(activeEntry.crossing_id);
  const preferredId = state.autoAdvance || state.viewMode === 'pending'
    ? nextPending || activeEntry.crossing_id
    : activeEntry.crossing_id;
  await apiRequest(`/api/crossings/manual-mappings/${encodeURIComponent(activeEntry.crossing_id)}`, {
    method: 'PUT',
    body: { osm_id: state.draftOsmId },
  });
  await reloadReviewState({ preferredId, preserveQueueScroll: true });
  if (!isVisibleEntryId(state.activeReviewId)) {
    ensureActiveEntry();
    renderQueue(true);
    renderPanels();
    renderMapLayers();
  }
  setStatus(`已儲存 ${activeEntry.name} → OSM ${state.draftOsmId}`, 'success');
  if (state.autoAdvance && state.activeReviewId) {
    updateQueueSelection(true);
  }
}

async function removeCurrentMapping() {
  const activeEntry = getReviewById();
  if (!activeEntry?.manual_mapping) {
    setStatus('這筆沒有已存映射可移除。', 'warning');
    return;
  }

  await apiRequest(`/api/crossings/manual-mappings/${encodeURIComponent(activeEntry.crossing_id)}`, {
    method: 'DELETE',
  });
  await reloadReviewState({ preferredId: activeEntry.crossing_id, preserveQueueScroll: true });
  state.draftOsmId = null;
  renderPanels();
  renderMapLayers();
  setStatus(`已移除 ${activeEntry.name} 的已存映射。`, 'success');
}

elements.queueList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-review-id]');
  if (!button) return;
  selectReviewEntry(button.dataset.reviewId, { scrollIntoView: false });
});

map.on('click', (event) => {
  if (!getReviewById() || !state.showOsm) return;
  const nearestFeature = findNearestOsmFeature(map.latLngToContainerPoint(event.latlng));
  const osmId = nearestFeature?.properties?.osm_id;
  if (osmId == null) return;
  selectOsmCandidate(osmId);
});

elements.queueFilter.addEventListener('click', (event) => {
  const button = event.target.closest('[data-filter]');
  if (!button || button.dataset.filter === state.viewMode) return;
  state.viewMode = button.dataset.filter;
  ensureActiveEntry();
  renderQueue(false);
  renderPanels();
  renderMapLayers();
});

elements.nextPendingButton.addEventListener('click', () => {
  jumpToNextPending({ scrollIntoView: true });
});

elements.fitActiveButton.addEventListener('click', () => {
  focusActive();
});

elements.reloadButton.addEventListener('click', async () => {
  try {
    await reloadAll({ preferredId: state.activeReviewId, preserveQueueScroll: true });
    setStatus('資料已重新同步。', 'success');
  } catch (error) {
    console.error(error);
    setStatus(`同步失敗：${error.message}`, 'error');
  }
});

elements.curatedToggleButton.addEventListener('click', () => {
  state.showCurated = !state.showCurated;
  syncToggleButtons();
  renderMapLayers();
});

elements.osmToggleButton.addEventListener('click', () => {
  state.showOsm = !state.showOsm;
  syncToggleButtons();
  renderMapLayers();
});

elements.autoAdvanceButton.addEventListener('click', () => {
  state.autoAdvance = !state.autoAdvance;
  syncToggleButtons();
});

elements.clearDraftButton.addEventListener('click', () => {
  const activeEntry = getReviewById();
  state.draftOsmId = getSavedOsmId(activeEntry);
  renderPanels();
  renderMapLayers();
  setStatus('草稿已清除。', 'neutral');
});

elements.saveMappingButton.addEventListener('click', async () => {
  try {
    await saveCurrentMapping();
  } catch (error) {
    console.error(error);
    setStatus(`儲存失敗：${error.message}`, 'error');
  }
});

elements.removeMappingButton.addEventListener('click', async () => {
  try {
    await removeCurrentMapping();
  } catch (error) {
    console.error(error);
    setStatus(`移除失敗：${error.message}`, 'error');
  }
});

async function bootstrap() {
  setStatus('載入中…');
  await fetchDatasets();
  ensureActiveEntry();
  renderQueue(false);
  renderPanels();
  renderMapLayers();
  syncToggleButtons();
  setStatus('地圖與標記佇列已就緒。', 'success');
}

bootstrap().catch((error) => {
  console.error(error);
  setStatus(`載入失敗：${error.message}`, 'error');
});
