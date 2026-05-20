const TIME_FORMAT = new Intl.DateTimeFormat('zh-TW', {
  hour: '2-digit',
  minute: '2-digit',
});

const DATE_TIME_FORMAT = new Intl.DateTimeFormat('zh-TW', {
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

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
  crossings: [],
  filteredCrossings: [],
  counties: [],
  query: '',
  selectedCrossingId: null,
  selectedCrossingDetail: null,
  predictionEnvelope: null,
  selectionRequestToken: 0,
  crossingLayer: L.layerGroup().addTo(map),
  stationLayer: L.layerGroup().addTo(map),
};

const elements = {
  regionForm: document.getElementById('regionForm'),
  regionInput: document.getElementById('regionInput'),
  regionSuggestions: document.getElementById('regionSuggestions'),
  focusSelectionButton: document.getElementById('focusSelectionButton'),
  resetRegionButton: document.getElementById('resetRegionButton'),
  refreshSelectionButton: document.getElementById('refreshSelectionButton'),
  mappedMetric: document.getElementById('mappedMetric'),
  filteredMetric: document.getElementById('filteredMetric'),
  warningMetric: document.getElementById('warningMetric'),
  filterSummary: document.getElementById('filterSummary'),
  resultsList: document.getElementById('resultsList'),
  selectionBadge: document.getElementById('selectionBadge'),
  selectedCrossingCard: document.getElementById('selectedCrossingCard'),
  warningCard: document.getElementById('warningCard'),
  predictionList: document.getElementById('predictionList'),
  statusBar: document.getElementById('statusBar'),
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

function normalizeSearchText(value) {
  return String(value ?? '').toLowerCase().replace(/\s+/g, '');
}

function setStatus(message, tone = 'neutral') {
  elements.statusBar.textContent = message;
  elements.statusBar.dataset.tone = tone;
}

function apiUrl(path, params = null) {
  const query = params ? `?${params.toString()}` : '';
  return `${path}${query}`;
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

function buildSearchIndex(feature) {
  const properties = feature.properties || {};
  return normalizeSearchText([
    properties.name,
    properties.county,
    properties.line,
    properties.km_marker,
    properties.station_pair_text,
    properties.station_a_name,
    properties.station_b_name,
  ].join(' '));
}

function getCrossingById(crossingId = state.selectedCrossingId) {
  return state.crossings.find((feature) => feature.id === crossingId) ?? null;
}

function getCrossingLatLng(feature) {
  if (!feature?.geometry?.coordinates) return null;
  return [feature.geometry.coordinates[1], feature.geometry.coordinates[0]];
}

function getStationCoords(position) {
  const lat = Number(position?.PositionLat);
  const lon = Number(position?.PositionLon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lat, lon];
}

function getSelectedStationPoints() {
  const properties = state.selectedCrossingDetail?.properties || {};
  return [
    {
      role: '前站',
      name: properties.station_a_name || '未提供前站',
      coords: getStationCoords(properties.station_a_position),
      color: '#f7b53f',
      className: 'is-upstream',
    },
    {
      role: '後站',
      name: properties.station_b_name || '未提供後站',
      coords: getStationCoords(properties.station_b_position),
      color: '#56b9ff',
      className: 'is-downstream',
    },
  ].filter((station) => station.coords);
}

function formatDateTime(value) {
  if (!value) return '尚未更新';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '尚未更新';
  return DATE_TIME_FORMAT.format(date);
}

function formatTime(value) {
  if (!value) return '--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--';
  return TIME_FORMAT.format(date);
}

function minutesUntil(value) {
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return null;
  return Math.round((target - Date.now()) / 60000);
}

function formatRelativeEta(value) {
  const minutes = minutesUntil(value);
  if (minutes == null) return '時間未知';
  if (minutes <= 0) return '即將通過';
  if (minutes === 1) return '約 1 分鐘';
  return `約 ${minutes} 分鐘`;
}

function formatTrainLabel(record) {
  return [record.train_type, record.train_no].filter(Boolean).join(' · ') || record.train_no || '未命名列車';
}

function confidenceLabel(value) {
  if (value === 'high') return '高信心';
  if (value === 'medium') return '中信心';
  return '低信心';
}

function fitMapToPoints(points, { maxZoom = 14 } = {}) {
  if (!points.length) {
    map.setView(MAP_HOME, MAP_HOME_ZOOM);
    return;
  }

  if (points.length === 1) {
    map.flyTo(points[0], maxZoom + 1, { duration: 0.55 });
    return;
  }

  map.fitBounds(points, {
    padding: [48, 48],
    maxZoom,
    animate: true,
  });
}

function focusFilteredCrossings() {
  const points = state.filteredCrossings
    .map((feature) => getCrossingLatLng(feature))
    .filter(Boolean);
  fitMapToPoints(points, { maxZoom: 13 });
}

function focusSelectedCrossing() {
  const points = [];
  const selectedBase = getCrossingById();
  const crossingPoint = getCrossingLatLng(state.selectedCrossingDetail || selectedBase);
  if (crossingPoint) {
    points.push(crossingPoint);
  }
  getSelectedStationPoints().forEach((station) => points.push(station.coords));
  fitMapToPoints(points, { maxZoom: 15 });
}

function renderSuggestions() {
  const suggestions = new Set();
  state.counties.forEach((county) => suggestions.add(county));
  state.crossings.slice(0, 120).forEach((feature) => {
    const properties = feature.properties || {};
    suggestions.add(properties.name);
    suggestions.add(properties.station_a_name);
    suggestions.add(properties.station_b_name);
  });

  elements.regionSuggestions.innerHTML = [...suggestions]
    .filter(Boolean)
    .sort((a, b) => String(a).localeCompare(String(b), 'zh-Hant'))
    .map((item) => `<option value="${escapeHtml(item)}"></option>`)
    .join('');
}

function updateMetrics() {
  const mappedCount = state.overview?.dataset?.mapped_feature_count ?? state.crossings.length;
  const warningCount = safeArray(state.predictionEnvelope?.predictions).filter((record) => record.warning).length;
  elements.mappedMetric.textContent = String(mappedCount);
  elements.filteredMetric.textContent = String(state.filteredCrossings.length);
  elements.warningMetric.textContent = String(warningCount);
}

function renderFilterSummary() {
  if (!state.crossings.length) {
    elements.filterSummary.textContent = '載入平交道資料中…';
    return;
  }

  if (!state.query) {
    elements.filterSummary.textContent = `目前顯示全部 ${state.crossings.length} 個已整合平交道，先輸入縣市或車站名稱再聚焦。`;
    return;
  }

  if (!state.filteredCrossings.length) {
    elements.filterSummary.textContent = `「${state.query}」目前沒有對應結果，請改用縣市、車站或平交道名稱。`;
    return;
  }

  elements.filterSummary.textContent = `「${state.query}」找到 ${state.filteredCrossings.length} 個平交道，地圖已聚焦到這個範圍。`;
}

function renderSelectionBadge() {
  const selected = getCrossingById();
  if (!selected) {
    elements.selectionBadge.innerHTML = `
      <div class="selection-shell is-empty">
        <span class="selection-kicker">start here</span>
        <strong>輸入地區後，從地圖或左側清單選擇平交道</strong>
        <small>右側會立即顯示大約通過時間與減速提醒。</small>
      </div>
    `;
    return;
  }

  const properties = (state.selectedCrossingDetail || selected).properties || {};
  elements.selectionBadge.innerHTML = `
    <div class="selection-shell">
      <span class="selection-kicker">target crossing</span>
      <strong>${escapeHtml(properties.name || '未命名平交道')}</strong>
      <span>${escapeHtml(properties.line || '未提供路線')} · ${escapeHtml(properties.km_marker || '未標公里')}</span>
      <small>${escapeHtml(properties.station_pair_text || '未提供站間資訊')}</small>
    </div>
  `;
}

function renderResults() {
  const selectedId = state.selectedCrossingId;
  if (!state.filteredCrossings.length) {
    elements.resultsList.innerHTML = '<div class="empty-block"><strong>沒有結果</strong><span>換個縣市、車站或平交道名稱再試一次。</span></div>';
    return;
  }

  elements.resultsList.innerHTML = state.filteredCrossings
    .map((feature) => {
      const properties = feature.properties || {};
      const isSelected = feature.id === selectedId;
      return `
        <button class="result-item ${isSelected ? 'is-active' : ''}" type="button" data-crossing-id="${escapeHtml(feature.id)}">
          <span class="result-mark ${properties.manual_mapping_applied ? 'is-reviewed' : ''}"></span>
          <div class="result-copy">
            <strong>${escapeHtml(properties.name || '未命名平交道')}</strong>
            <span>${escapeHtml(properties.county || '未知縣市')} · ${escapeHtml(properties.line || '未提供路線')} · ${escapeHtml(properties.km_marker || '未標公里')}</span>
            <small>${escapeHtml(properties.station_pair_text || '未提供站間資訊')}</small>
          </div>
          <span class="result-badge ${properties.manual_mapping_applied ? 'is-reviewed' : ''}">${properties.manual_mapping_applied ? '已校正' : confidenceLabel(properties.geolocation_confidence)}</span>
        </button>
      `;
    })
    .join('');
}

function renderCrossingMarkers() {
  state.crossingLayer.clearLayers();

  state.filteredCrossings.forEach((feature) => {
    const point = getCrossingLatLng(feature);
    if (!point) return;
    const isSelected = feature.id === state.selectedCrossingId;
    const marker = L.circleMarker(point, {
      renderer: canvasRenderer,
      radius: isSelected ? 9 : 5.2,
      weight: isSelected ? 3.4 : 1.5,
      color: isSelected ? '#0d3558' : '#b94d38',
      fillColor: isSelected ? '#0d3558' : '#f47e57',
      fillOpacity: 0.95,
    });
    marker.on('click', () => {
      selectCrossing(feature.id, { focusMap: false });
    });
    marker.addTo(state.crossingLayer);
    if (isSelected) {
      marker.bringToFront();
    }
  });
}

function renderStationContext() {
  state.stationLayer.clearLayers();
  const stations = getSelectedStationPoints();
  if (!stations.length) return;

  if (stations.length === 2) {
    L.polyline(stations.map((station) => station.coords), {
      color: '#154c79',
      weight: 4,
      opacity: 0.72,
      dashArray: '10 10',
      lineCap: 'round',
      interactive: false,
    }).addTo(state.stationLayer);
  }

  stations.forEach((station) => {
    L.circleMarker(station.coords, {
      renderer: canvasRenderer,
      radius: 14,
      weight: 2,
      color: station.color,
      fillColor: station.color,
      fillOpacity: 0.18,
      interactive: false,
    }).addTo(state.stationLayer);

    const marker = L.circleMarker(station.coords, {
      renderer: canvasRenderer,
      radius: 7.5,
      weight: 3,
      color: '#0f243a',
      fillColor: station.color,
      fillOpacity: 1,
      interactive: false,
    });
    marker.bindTooltip(
      `<div class="station-context-label"><span>${escapeHtml(station.role)}</span><strong>${escapeHtml(station.name)}</strong></div>`,
      {
        permanent: true,
        direction: 'top',
        offset: [0, -16],
        className: `station-context-tooltip ${station.className}`,
      }
    );
    marker.addTo(state.stationLayer);
    marker.bringToFront();
  });
}

function renderSelectedCrossingCard() {
  const selected = getCrossingById();
  if (!selected) {
    elements.selectedCrossingCard.innerHTML = `
      <div class="empty-block large">
        <strong>先選一個平交道</strong>
        <span>輸入地區後，直接點地圖上的平交道，右側就會顯示即時通過預測。</span>
      </div>
    `;
    return;
  }

  const properties = (state.selectedCrossingDetail || selected).properties || {};
  const stations = getSelectedStationPoints();
  elements.selectedCrossingCard.innerHTML = `
    <div class="card-kicker-row">
      <span class="section-pill">${escapeHtml(properties.county || '未知縣市')}</span>
      <span class="section-pill ${properties.manual_mapping_applied ? 'is-reviewed' : ''}">${properties.manual_mapping_applied ? '人工校正' : confidenceLabel(properties.geolocation_confidence)}</span>
    </div>
    <h2 class="card-title">${escapeHtml(properties.name || '未命名平交道')}</h2>
    <div class="chip-row">
      <span class="info-chip">${escapeHtml(properties.line || '未提供路線')}</span>
      <span class="info-chip">${escapeHtml(properties.km_marker || '未標公里')}</span>
      <span class="info-chip">${escapeHtml(properties.road_type || '未提供類型')}</span>
    </div>
    <div class="station-pair-card">
      <strong>${escapeHtml(properties.station_pair_text || '未提供站間資訊')}</strong>
      <span>${stations.length ? stations.map((station) => `${station.role} ${station.name}`).join(' · ') : '目前無法解析前後車站位置'}</span>
    </div>
    <div class="meta-row">
      <span>OSM ${escapeHtml(properties.matched_osm_id || '未提供')}</span>
      <span>${properties.manual_mapping_applied ? '使用已標記成果' : '使用自動整合成果'}</span>
    </div>
  `;
}

function renderWarningCard() {
  const selected = getCrossingById();
  if (!selected) {
    elements.warningCard.innerHTML = `
      <div class="warning-hero is-empty">
        <span class="hero-pill">待選定</span>
        <h2>尚未指定目標平交道</h2>
        <p>先在地圖或左側清單選擇平交道，系統才會開始計算列車何時接近。</p>
      </div>
    `;
    return;
  }

  const predictions = safeArray(state.predictionEnvelope?.predictions);
  const imminent = predictions.find((record) => record.warning) || null;
  const nearest = imminent || predictions[0] || null;

  if (!nearest) {
    elements.warningCard.innerHTML = `
      <div class="warning-hero is-safe">
        <span class="hero-pill">暫無列車</span>
        <h2>目前不需要減速提醒</h2>
        <p>未來 ${escapeHtml(state.predictionEnvelope?.horizon_minutes || 30)} 分鐘內，沒有觀察到會接近平交道的列車。</p>
      </div>
    `;
    return;
  }

  const shouldWarn = Boolean(imminent);
  elements.warningCard.innerHTML = `
    <div class="warning-hero ${shouldWarn ? 'is-alert' : 'is-safe'}">
      <span class="hero-pill">${shouldWarn ? '請放慢速度' : '提前留意'}</span>
      <h2>${formatRelativeEta(nearest.eta)} 後列車將接近平交道</h2>
      <p>${escapeHtml(formatTrainLabel(nearest))} 將由 ${escapeHtml(nearest.upstream_station_name)} 往 ${escapeHtml(nearest.downstream_station_name)} 通過。</p>
      <div class="hero-meta">
        <span>${escapeHtml(formatTime(nearest.eta))}</span>
        <span>${shouldWarn ? `落在 ${nearest.warning_window_minutes} 分鐘提醒窗` : '尚未進入提醒窗'}</span>
      </div>
    </div>
  `;
}

function renderPredictionList() {
  const selected = getCrossingById();
  if (!selected) {
    elements.predictionList.innerHTML = '<div class="empty-block"><strong>尚未選定平交道</strong><span>右側這裡會列出列車通過的大約時間。</span></div>';
    return;
  }

  const predictions = safeArray(state.predictionEnvelope?.predictions);
  if (!predictions.length) {
    elements.predictionList.innerHTML = '<div class="empty-block"><strong>暫無近期列車</strong><span>未來 30 分鐘內沒有觀察到接近此平交道的列車。</span></div>';
    return;
  }

  elements.predictionList.innerHTML = predictions
    .map((record) => `
      <article class="prediction-card ${record.warning ? 'is-warning' : ''}">
        <div class="prediction-head">
          <div>
            <strong>${escapeHtml(formatTrainLabel(record))}</strong>
            <span>${escapeHtml(record.upstream_station_name)} → ${escapeHtml(record.downstream_station_name)}</span>
          </div>
          <span class="eta-chip ${record.warning ? 'is-warning' : ''}">${escapeHtml(formatRelativeEta(record.eta))}</span>
        </div>
        <div class="prediction-meta">
          <span>${escapeHtml(formatTime(record.eta))}</span>
          <span>${record.data_basis === 'liveboard' ? `即時 + 延誤 ${record.delay_minutes} 分` : '時刻表估算'}</span>
          <span>${confidenceLabel(record.confidence)}</span>
        </div>
      </article>
    `)
    .join('');
}

function renderAllPanels() {
  renderFilterSummary();
  renderSelectionBadge();
  renderSelectedCrossingCard();
  renderWarningCard();
  renderPredictionList();
  updateMetrics();
}

function clearSelection() {
  state.selectedCrossingId = null;
  state.selectedCrossingDetail = null;
  state.predictionEnvelope = null;
}

function filterCrossings(query) {
  const normalized = normalizeSearchText(query);
  if (!normalized) {
    return [...state.crossings];
  }

  const matchedCounties = state.counties.filter((county) => normalizeSearchText(county).includes(normalized));
  if (matchedCounties.length) {
    const countySet = new Set(matchedCounties);
    return state.crossings.filter((feature) => countySet.has(feature.properties?.county));
  }

  return state.crossings.filter((feature) => feature.searchIndex.includes(normalized));
}

function applyQuery({ focusMap = true } = {}) {
  state.query = elements.regionInput.value.trim();
  state.filteredCrossings = filterCrossings(state.query);

  if (state.selectedCrossingId && !state.filteredCrossings.some((feature) => feature.id === state.selectedCrossingId)) {
    clearSelection();
  }

  renderResults();
  renderCrossingMarkers();
  renderStationContext();
  renderAllPanels();

  if (focusMap) {
    if (state.filteredCrossings.length) {
      focusFilteredCrossings();
      setStatus(`已聚焦 ${state.filteredCrossings.length} 個符合條件的平交道。`, 'success');
    } else {
      map.setView(MAP_HOME, MAP_HOME_ZOOM);
      setStatus(`找不到「${state.query}」對應的平交道。`, 'warning');
    }
  }
}

async function selectCrossing(crossingId, { focusMap = true, refreshOnly = false } = {}) {
  const baseFeature = getCrossingById(crossingId);
  if (!baseFeature) return;

  state.selectedCrossingId = crossingId;
  if (!refreshOnly) {
    renderResults();
    renderCrossingMarkers();
    renderAllPanels();
  }

  const token = ++state.selectionRequestToken;
  setStatus(`正在計算 ${baseFeature.properties?.name || crossingId} 的通過預測…`);

  try {
    const [detail, envelope] = await Promise.all([
      apiRequest(`/api/crossings/${encodeURIComponent(crossingId)}`),
      apiRequest(`/api/predictions/${encodeURIComponent(crossingId)}`, {
        params: new URLSearchParams({ horizon_minutes: '30', warning_minutes: '5' }),
      }),
    ]);

    if (token !== state.selectionRequestToken) return;
    state.selectedCrossingDetail = detail;
    state.predictionEnvelope = envelope;
    renderCrossingMarkers();
    renderStationContext();
    renderAllPanels();
    if (focusMap) {
      focusSelectedCrossing();
    }

    const warningCount = safeArray(envelope.predictions).filter((record) => record.warning).length;
    if (warningCount) {
      setStatus(`已載入 ${baseFeature.properties?.name || crossingId} 的通過預測，目前有 ${warningCount} 筆減速提醒。`, 'warning');
    } else {
      setStatus(`已載入 ${baseFeature.properties?.name || crossingId} 的通過預測。`, 'success');
    }
  } catch (error) {
    if (token !== state.selectionRequestToken) return;
    state.selectedCrossingDetail = null;
    state.predictionEnvelope = null;
    renderStationContext();
    renderAllPanels();
    setStatus(`載入預測失敗：${error.message}`, 'error');
  }
}

function attachEventListeners() {
  elements.regionForm.addEventListener('submit', (event) => {
    event.preventDefault();
    applyQuery({ focusMap: true });
  });

  elements.resetRegionButton.addEventListener('click', () => {
    elements.regionInput.value = '';
    state.query = '';
    state.filteredCrossings = [...state.crossings];
    clearSelection();
    renderResults();
    renderCrossingMarkers();
    renderStationContext();
    renderAllPanels();
    map.setView(MAP_HOME, MAP_HOME_ZOOM);
    setStatus('已回到全台平交道總覽。', 'neutral');
  });

  elements.resultsList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-crossing-id]');
    if (!button) return;
    selectCrossing(button.dataset.crossingId, { focusMap: true });
  });

  elements.focusSelectionButton.addEventListener('click', () => {
    if (!state.selectedCrossingId) {
      setStatus('先選一個平交道，才能定位目標。', 'warning');
      return;
    }
    focusSelectedCrossing();
  });

  elements.refreshSelectionButton.addEventListener('click', () => {
    if (!state.selectedCrossingId) {
      setStatus('先選一個平交道，再更新預測。', 'warning');
      return;
    }
    selectCrossing(state.selectedCrossingId, { focusMap: false, refreshOnly: true });
  });
}

async function bootstrap() {
  setStatus('載入平交道與列車資料中…');
  const [overview, crossingsPayload] = await Promise.all([
    apiRequest('/api/system/overview'),
    apiRequest('/api/crossings', { params: new URLSearchParams({ limit: '5000', mapped_only: 'true' }) }),
  ]);

  state.overview = overview;
  state.counties = safeArray(crossingsPayload.counties);
  state.crossings = safeArray(crossingsPayload.features).map((feature) => ({
    ...feature,
    searchIndex: buildSearchIndex(feature),
  }));
  state.filteredCrossings = [...state.crossings];

  renderSuggestions();
  renderResults();
  renderCrossingMarkers();
  renderStationContext();
  renderAllPanels();
  attachEventListeners();
  setStatus(`已載入 ${state.crossings.length} 個已整合平交道，請先輸入地區。`, 'success');
}

bootstrap().catch((error) => {
  console.error(error);
  setStatus(`載入失敗：${error.message}`, 'error');
});
