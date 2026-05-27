const TIME_FORMAT = new Intl.DateTimeFormat('zh-TW', {
  hour: '2-digit',
  minute: '2-digit',
});

const PRECISE_TIME_FORMAT = new Intl.DateTimeFormat('zh-TW', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

const MAP_HOME = [23.7, 121.0];
const MAP_HOME_ZOOM = 7;
const COUNTDOWN_TICK_MS = 1000;
const DISPLAY_UPCOMING_PREDICTIONS = 2;
const PREDICTION_RECENT_WINDOW_MINUTES = 10;
const PREDICTION_WARNING_WINDOW_MINUTES = 5;
const STATION_REFERENCE_FALLBACK = 'UK 未提供';
const STATION_REFERENCE_NOTE = '車站 UK 為推估參考值，非精準量測。';
const STATION_LABEL_MIN_ZOOM = 11;
const STATION_VIEWPORT_PADDING = 0.18;

const map = L.map('map', {
  zoomControl: false,
  preferCanvas: true,
  scrollWheelZoom: true,
}).setView(MAP_HOME, MAP_HOME_ZOOM);

map.createPane('stationPane');
map.getPane('stationPane').style.zIndex = '410';
map.createPane('stationOverviewPane');
map.getPane('stationOverviewPane').style.zIndex = '405';
map.createPane('crossingPane');
map.getPane('crossingPane').style.zIndex = '430';

const crossingRenderer = L.canvas({ padding: 0.5, pane: 'crossingPane' });
const stationRenderer = L.canvas({ padding: 0.5, pane: 'stationPane' });
const stationOverviewRenderer = L.canvas({ padding: 0.5, pane: 'stationOverviewPane' });

L.control.zoom({ position: 'bottomright' }).addTo(map);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors',
}).addTo(map);

const state = {
  crossings: [],
  stations: [],
  filteredCrossings: [],
  countyGroups: [],
  query: '',
  activeSearchOption: null,
  searchPanelOpen: false,
  selectedCrossingId: null,
  selectedCrossingDetail: null,
  predictionEnvelope: null,
  selectionLoading: false,
  selectionRequestToken: 0,
  clock: {
    nowMs: Date.now(),
    envelopeGeneratedAtMs: null,
  },
  predictionRuntimeByCrossing: new Map(),
  timers: {
    countdown: null,
  },
  crossingLayer: L.layerGroup().addTo(map),
  stationOverviewLayer: L.layerGroup().addTo(map),
  stationLayer: L.layerGroup().addTo(map),
};

const elements = {
  regionForm: document.getElementById('regionForm'),
  regionInput: document.getElementById('regionInput'),
  searchStack: document.getElementById('searchStack'),
  searchMenuButton: document.getElementById('searchMenuButton'),
  searchPanel: document.getElementById('searchPanel'),
  focusRegionButton: document.getElementById('focusRegionButton'),
  resetRegionButton: document.getElementById('resetRegionButton'),
  focusSelectionButton: document.getElementById('focusSelectionButton'),
  refreshSelectionButton: document.getElementById('refreshSelectionButton'),
  mappedMetric: document.getElementById('mappedMetric'),
  filteredMetric: document.getElementById('filteredMetric'),
  warningMetric: document.getElementById('warningMetric'),
  scopeLabel: document.getElementById('scopeLabel'),
  resultsCount: document.getElementById('resultsCount'),
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

function squishLabel(value) {
  return String(value ?? '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/([\u4e00-\u9fff])\s+([\u4e00-\u9fff])/g, '$1$2');
}

function displayLabel(value, fallback = '') {
  const text = squishLabel(value);
  return text || fallback;
}

function getPairSourceLabel(value) {
  if (value === 'authoritative_reference') return '站間：官方校正';
  if (value === 'official_query') return '站間：官網欄位';
  return '站間：未標示';
}

function getRatioSourceLabel(value) {
  if (value === 'official_route_mileage') return '比例：官方鏈公里';
  if (value === 'osm_path') return '比例：OSM 軌道路徑';
  if (value === 'geometry_projection') return '比例：座標投影';
  if (value === 'midpoint') return '比例：中點 fallback';
  return '比例：未標示';
}

function buildPredictionSourceLine(record) {
  const parts = [];
  if (record?.ratio_source) parts.push(getRatioSourceLabel(record.ratio_source));
  if (record?.station_pair_source) parts.push(getPairSourceLabel(record.station_pair_source));
  return parts.join(' · ');
}

function isLivePrediction(record) {
  return record?.data_basis === 'liveboard';
}

function getPredictionBasisLabel(record) {
  return isLivePrediction(record) ? '即時' : '班表';
}

function getPredictionTone(record) {
  return isLivePrediction(record) ? 'is-live' : 'is-scheduled';
}

function getConfidenceHint(meta) {
  if (meta.manualMappingApplied) return { label: '人工校正', tone: 'is-reviewed' };
  if (meta.ratioSource === 'official_route_mileage') return { label: '官方鏈公里', tone: 'is-strong' };
  if (meta.ratioSource === 'osm_path') return { label: '軌道路徑', tone: 'is-soft' };
  if (meta.ratioSource === 'geometry_projection') return { label: '座標估算', tone: 'is-caution' };
  if (meta.ratioSource === 'midpoint') return { label: '資料不足', tone: 'is-caution' };
  return null;
}

function normalizeSearchText(value) {
  return displayLabel(value).toLowerCase().replace(/\s+/g, '');
}

function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function setStatus(message, tone = 'neutral') {
  elements.statusBar.textContent = message;
  elements.statusBar.dataset.tone = tone;
}

function icon(name) {
  if (name === 'route') {
    return `
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M5 12H19" />
        <path d="M13 6L19 12L13 18" />
      </svg>
    `;
  }
  if (name === 'county') {
    return `
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M5 5H19V19H5Z" />
        <path d="M9 5V19" />
        <path d="M5 11H19" />
      </svg>
    `;
  }
  if (name === 'station') {
    return `
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M8 4H16V16H8Z" />
        <path d="M10 16V20" />
        <path d="M14 16V20" />
        <path d="M8 10H16" />
      </svg>
    `;
  }
  return `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 4C8 4 5 7 5 11C5 15.5 12 20 12 20C12 20 19 15.5 19 11C19 7 16 4 12 4Z" />
      <circle cx="12" cy="11" r="2.5" />
    </svg>
  `;
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

function getFeatureLatitude(feature) {
  const lat = Number(feature?.geometry?.coordinates?.[1]);
  return Number.isFinite(lat) ? lat : null;
}

function sortFeaturesSouthToNorth(features) {
  return [...features].sort((featureA, featureB) => {
    const latA = getFeatureLatitude(featureA);
    const latB = getFeatureLatitude(featureB);
    if (latA == null && latB == null) return 0;
    if (latA == null) return 1;
    if (latB == null) return -1;
    if (latA !== latB) return latA - latB;
    return getFeatureMeta(featureA).name.localeCompare(getFeatureMeta(featureB).name, 'zh-Hant');
  });
}

function getFeatureMeta(feature) {
  if (!feature) {
    return {
      county: '',
      name: '',
      line: '',
      km: '',
      roadType: '',
      stationA: '',
      stationB: '',
      stationPair: '',
      manualMappingApplied: false,
    };
  }

  if (feature.meta) return feature.meta;

  const properties = feature.properties || {};
  return {
    county: displayLabel(properties.county, '未分類'),
    name: displayLabel(properties.name, feature.id || '未命名平交道'),
    line: displayLabel(properties.line, '未提供路線'),
    km: displayLabel(properties.km_marker, '未標公里'),
    roadType: displayLabel(properties.road_type, ''),
    stationA: displayLabel(properties.station_a_name, ''),
    stationB: displayLabel(properties.station_b_name, ''),
    stationPair: displayLabel(properties.station_pair_text, ''),
    queryStationPair: displayLabel(properties.query_station_pair_text, ''),
    stationPairSource: displayLabel(properties.station_pair_source, ''),
    ratioSource: displayLabel(properties.ratio_source, ''),
    segmentConfidenceReason: displayLabel(properties.segment_confidence_reason, ''),
    manualMappingApplied: Boolean(properties.manual_mapping_applied),
  };
}

function buildSearchIndex(feature) {
  const meta = getFeatureMeta(feature);
  return normalizeSearchText([
    meta.name,
    meta.county,
    meta.line,
    meta.km,
    meta.stationPair,
    meta.stationA,
    meta.stationB,
  ].join(' '));
}

function buildCountyGroups(features) {
  const countyMap = new Map();

  features.forEach((feature) => {
    const meta = getFeatureMeta(feature);
    const county = meta.county || '未分類';
    const latitude = getFeatureLatitude(feature);
    let group = countyMap.get(county);
    if (!group) {
      group = {
        county,
        latitudes: [],
        stations: new Map(),
        crossings: [],
      };
      countyMap.set(county, group);
    }

    if (latitude != null) {
      group.latitudes.push(latitude);
    }
    group.crossings.push(feature);

    [meta.stationA, meta.stationB].filter(Boolean).forEach((stationName) => {
      let station = group.stations.get(stationName);
      if (!station) {
        station = { label: stationName, latitudes: [], count: 0 };
        group.stations.set(stationName, station);
      }
      station.count += 1;
      if (latitude != null) {
        station.latitudes.push(latitude);
      }
    });
  });

  return [...countyMap.values()]
    .map((group) => ({
      county: group.county,
      avgLatitude: average(group.latitudes),
      crossings: sortFeaturesSouthToNorth(group.crossings),
      stations: [...group.stations.values()]
        .map((station) => ({
          label: station.label,
          avgLatitude: average(station.latitudes),
          count: station.count,
        }))
        .sort((stationA, stationB) => {
          if (stationA.avgLatitude !== stationB.avgLatitude) {
            return stationA.avgLatitude - stationB.avgLatitude;
          }
          return stationA.label.localeCompare(stationB.label, 'zh-Hant');
        }),
    }))
    .sort((groupA, groupB) => {
      if (groupA.avgLatitude !== groupB.avgLatitude) {
        return groupA.avgLatitude - groupB.avgLatitude;
      }
      return groupA.county.localeCompare(groupB.county, 'zh-Hant');
    });
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

function getStationSummaryCoords(station) {
  return getStationCoords(station?.position);
}

function getStationUkPrimary(value) {
  const text = displayLabel(value, '');
  return text || null;
}

function getStationUkDisplay(value) {
  return getStationUkPrimary(value) || STATION_REFERENCE_FALLBACK;
}

function getStationUkContextLine(value) {
  const uk = getStationUkPrimary(value);
  return uk ? `參考 UK · ${uk}` : STATION_REFERENCE_FALLBACK;
}

function getStationReferenceNote(value) {
  return displayLabel(value, STATION_REFERENCE_NOTE);
}

function getSelectedStationIds() {
  const properties = state.selectedCrossingDetail?.properties || {};
  return new Set([properties.station_a_id, properties.station_b_id].filter(Boolean));
}

function getSelectedStationPoints() {
  const properties = state.selectedCrossingDetail?.properties || {};
  return [
    {
      role: '前站',
      name: displayLabel(properties.station_a_name, ''),
      uk: getStationUkPrimary(properties.station_a_uk_primary),
      coords: getStationCoords(properties.station_a_position),
      color: '#ffd36a',
      className: 'is-upstream',
    },
    {
      role: '後站',
      name: displayLabel(properties.station_b_name, ''),
      uk: getStationUkPrimary(properties.station_b_uk_primary),
      coords: getStationCoords(properties.station_b_position),
      color: '#84d8ff',
      className: 'is-downstream',
    },
  ].filter((station) => station.coords && station.name);
}

function formatTime(value) {
  if (!value) return '--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--';
  return TIME_FORMAT.format(date);
}

function formatPreciseTime(value) {
  if (!value) return '--:--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return PRECISE_TIME_FORMAT.format(date);
}

function formatClockMs(value) {
  if (!Number.isFinite(value)) return '--:--:--';
  return PRECISE_TIME_FORMAT.format(new Date(value));
}

function parseTimestampMs(value) {
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? null : timestamp;
}

function syncNow(nowMs = Date.now()) {
  state.clock.nowMs = nowMs;
}

function syncEnvelopeClock(envelope, receivedAtMs = Date.now()) {
  syncNow(receivedAtMs);
  state.clock.envelopeGeneratedAtMs = parseTimestampMs(envelope?.generated_at);
}

function getNowMs() {
  return Number.isFinite(state.clock.nowMs) ? state.clock.nowMs : Date.now();
}

function getPredictionRuntime(crossingId = state.selectedCrossingId, create = true) {
  if (!crossingId) return null;
  let runtime = state.predictionRuntimeByCrossing.get(crossingId) || null;
  if (!runtime && create) {
    runtime = {
      lastPassedRecord: null,
      processedKeys: new Set(),
    };
    state.predictionRuntimeByCrossing.set(crossingId, runtime);
  }
  return runtime;
}

function getPredictionKey(record) {
  return [
    record?.train_no,
    record?.upstream_station_id,
    record?.downstream_station_id,
    record?.eta,
  ].map((value) => String(value ?? '')).join('|');
}

function primePredictionRuntime(crossingId, envelope) {
  const runtime = getPredictionRuntime(crossingId);
  if (!runtime) return;
  const nowMs = getNowMs();
  safeArray(envelope?.predictions).forEach((record) => {
    const etaMs = parseTimestampMs(record?.eta);
    if (Number.isFinite(etaMs) && etaMs <= nowMs) {
      runtime.processedKeys.add(getPredictionKey(record));
    }
  });
}

function updateLastPassedPrediction(crossingId = state.selectedCrossingId) {
  if (!crossingId || !state.predictionEnvelope || crossingId !== state.selectedCrossingId) {
    return;
  }

  const runtime = getPredictionRuntime(crossingId, false);
  if (!runtime) return;

  const nowMs = getNowMs();
  const newlyPassed = safeArray(state.predictionEnvelope?.predictions)
    .filter((record) => {
      const etaMs = parseTimestampMs(record?.eta);
      if (!Number.isFinite(etaMs) || etaMs > nowMs) {
        return false;
      }
      return !runtime.processedKeys.has(getPredictionKey(record));
    })
    .sort((recordA, recordB) => parseTimestampMs(recordA?.eta) - parseTimestampMs(recordB?.eta));

  if (!newlyPassed.length) return;

  newlyPassed.forEach((record) => {
    runtime.processedKeys.add(getPredictionKey(record));
  });
  runtime.lastPassedRecord = { ...newlyPassed[newlyPassed.length - 1] };
}

function formatTrainNo(record) {
  return record?.train_no ? `${record.train_no}次` : '未提供班次';
}

function getCountdownParts(value) {
  const target = parseTimestampMs(value);
  if (!Number.isFinite(target)) {
    return {
      seconds: null,
      timer: '--:--',
      label: '時間未知',
      short: '時間未知',
    };
  }

  const totalSeconds = Math.max(0, Math.ceil((target - getNowMs()) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (totalSeconds === 0) {
    return {
      seconds: totalSeconds,
      timer: '00:00',
      label: '即將通過',
      short: '即將通過',
    };
  }

  return {
    seconds: totalSeconds,
    timer: `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`,
    label: `${minutes ? `${minutes} 分 ` : ''}${seconds} 秒後`,
    short: minutes ? `${minutes}分${String(seconds).padStart(2, '0')}秒` : `${seconds}秒`,
  };
}

function getRelativeEtaParts(value) {
  const target = parseTimestampMs(value);
  if (!Number.isFinite(target)) {
    return {
      seconds: null,
      label: '時間未知',
      short: '時間未知',
      isPast: false,
    };
  }

  const deltaMs = target - getNowMs();
  const isPast = deltaMs < 0;
  const totalSeconds = Math.ceil(Math.abs(deltaMs) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (totalSeconds === 0) {
    return {
      seconds: totalSeconds,
      label: '即將通過',
      short: '即將通過',
      isPast: false,
    };
  }

  if (isPast) {
    return {
      seconds: totalSeconds,
      label: `${minutes ? `${minutes} 分 ` : ''}${seconds} 秒前通過`,
      short: minutes ? `${minutes}分${String(seconds).padStart(2, '0')}秒前` : `${seconds}秒前`,
      isPast: true,
    };
  }

  return {
    seconds: totalSeconds,
    label: `${minutes ? `${minutes} 分 ` : ''}${seconds} 秒後`,
    short: minutes ? `${minutes}分${String(seconds).padStart(2, '0')}秒` : `${seconds}秒`,
    isPast: false,
  };
}

function isWithinWarningWindow(record) {
  const eta = parseTimestampMs(record?.eta);
  if (!Number.isFinite(eta)) return false;
  const warningWindowMinutes = Number(record?.warning_window_minutes ?? state.predictionEnvelope?.warning_window_minutes ?? 0);
  const nowMs = getNowMs();
  return eta >= nowMs && eta <= nowMs + (warningWindowMinutes * 60 * 1000);
}

function getDirectionLabel(record) {
  const properties = state.selectedCrossingDetail?.properties || {};
  const stationA = getStationCoords(properties.station_a_position);
  const stationB = getStationCoords(properties.station_b_position);
  const isAtoB = record?.upstream_station_id && record?.downstream_station_id
    && record.upstream_station_id === properties.station_a_id
    && record.downstream_station_id === properties.station_b_id;
  const isBtoA = record?.upstream_station_id && record?.downstream_station_id
    && record.upstream_station_id === properties.station_b_id
    && record.downstream_station_id === properties.station_a_id;

  if (stationA && stationB && (isAtoB || isBtoA)) {
    const northbound = isAtoB ? stationB[0] > stationA[0] : stationA[0] > stationB[0];
    return northbound ? '北上' : '南下';
  }

  if (stationA && stationB && record?.direction != null) {
    const canonicalNorthbound = stationB[0] > stationA[0];
    if (record.direction === 0) {
      return canonicalNorthbound ? '北上' : '南下';
    }
    if (record.direction === 1) {
      return canonicalNorthbound ? '南下' : '北上';
    }
  }

  if (record?.direction === 0) return '順行';
  if (record?.direction === 1) return '逆行';
  return '行駛中';
}

function getPredictionRoute(record) {
  return {
    origin: displayLabel(record?.origin_station_name || record?.upstream_station_name, '未知'),
    destination: displayLabel(record?.destination_station_name || record?.downstream_station_name, '未知'),
    approachFrom: displayLabel(record?.upstream_station_name, '未知'),
    approachTo: displayLabel(record?.downstream_station_name, '未知'),
  };
}

function getStopTiming(record) {
  return {
    previousName: displayLabel(record?.previous_stop_station_name || record?.upstream_station_name, '未提供'),
    previousDeparture: formatTime(record?.previous_stop_departure),
    nextName: displayLabel(record?.next_stop_station_name || record?.downstream_station_name, '未提供'),
    nextArrival: formatTime(record?.next_stop_arrival),
  };
}

function getAllUpcomingPredictions() {
  const nowMs = getNowMs();
  return safeArray(state.predictionEnvelope?.predictions)
    .filter((record) => {
      const eta = parseTimestampMs(record?.eta);
      return Number.isFinite(eta) && eta >= nowMs;
    });
}

function getUpcomingPredictions() {
  const nowMs = getNowMs();
  const envelopeUpcoming = safeArray(state.predictionEnvelope?.upcoming_predictions)
    .filter((record) => {
      const eta = parseTimestampMs(record?.eta);
      return Number.isFinite(eta) && eta >= nowMs;
    });

  if (envelopeUpcoming.length) {
    return envelopeUpcoming.slice(0, DISPLAY_UPCOMING_PREDICTIONS);
  }

  return getAllUpcomingPredictions().slice(0, DISPLAY_UPCOMING_PREDICTIONS);
}

function getRecentPrediction() {
  const runtime = getPredictionRuntime(state.selectedCrossingId, false);
  const record = runtime?.lastPassedRecord || null;
  const eta = parseTimestampMs(record?.eta);
  if (!record || !Number.isFinite(eta) || eta > getNowMs()) {
    return null;
  }
  return record;
}

function getScheduleSlots() {
  const upcoming = getUpcomingPredictions();

  return [
    {
      key: 'recent',
      label: '上一班',
      record: getRecentPrediction(),
      emptyTitle: '暫無上一班資料',
      emptySubtitle: '本次開啟後尚未記錄到通過列車',
    },
    {
      key: 'next',
      label: '下一班',
      record: upcoming[0] || null,
      emptyTitle: '暫無下一班資料',
      emptySubtitle: '目前沒有接近平交道的列車',
    },
    {
      key: 'following',
      label: '第二班',
      record: upcoming[1] || null,
      emptyTitle: '暫無第二班資料',
      emptySubtitle: '目前還找不到第二班預測',
    },
  ];
}

function getPrimaryPrediction() {
  const predictions = getAllUpcomingPredictions();
  if (!predictions.length) return null;
  return predictions.find((record) => isLivePrediction(record) && isWithinWarningWindow(record))
    || predictions.find((record) => isLivePrediction(record))
    || predictions.find((record) => isWithinWarningWindow(record))
    || predictions[0];
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
    padding: [56, 56],
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
  const selectedFeature = state.selectedCrossingDetail || selectedBase;
  const crossingPoint = getCrossingLatLng(selectedFeature);
  if (crossingPoint) {
    points.push(crossingPoint);
  }
  getSelectedStationPoints().forEach((station) => points.push(station.coords));
  fitMapToPoints(points, { maxZoom: 15 });
}

function buildSearchGroups(query) {
  const normalized = normalizeSearchText(query);

  return state.countyGroups
    .map((group) => {
      const options = [];
      const seen = new Set();

      function pushOption(option) {
        const key = `${option.type}:${normalizeSearchText(option.label)}:${option.crossingId || option.county || ''}`;
        if (seen.has(key)) return;
        seen.add(key);
        options.push(option);
      }

      if (!normalized || normalizeSearchText(group.county).includes(normalized)) {
        pushOption({
          type: 'county',
          county: group.county,
          label: group.county,
          meta: `${group.crossings.length} 處`,
        });
      }

      group.stations
        .filter((station) => !normalized || normalizeSearchText(station.label).includes(normalized))
        .slice(0, normalized ? 8 : 7)
        .forEach((station) => {
          pushOption({
            type: 'station',
            county: group.county,
            label: station.label,
            meta: `車站 · ${station.count}`,
          });
        });

      if (normalized) {
        group.crossings
          .filter((feature) => normalizeSearchText(getFeatureMeta(feature).name).includes(normalized))
          .slice(0, 5)
          .forEach((feature) => {
            const meta = getFeatureMeta(feature);
            pushOption({
              type: 'crossing',
              county: group.county,
              label: meta.name,
              meta: `${meta.line} · ${meta.km}`,
              crossingId: feature.id,
            });
          });
      }

      return {
        county: group.county,
        options,
      };
    })
    .filter((group) => group.options.length);
}

function renderSearchPanel() {
  if (!state.searchPanelOpen) {
    elements.searchPanel.hidden = true;
    elements.searchMenuButton.setAttribute('aria-expanded', 'false');
    return;
  }

  const groups = buildSearchGroups(elements.regionInput.value.trim());
  elements.searchPanel.hidden = false;
  elements.searchMenuButton.setAttribute('aria-expanded', 'true');

  if (!groups.length) {
    elements.searchPanel.innerHTML = '<div class="search-empty">找不到對應地區</div>';
    return;
  }

  elements.searchPanel.innerHTML = groups
    .map((group) => `
      <section class="search-group">
        <header class="search-group-title">${escapeHtml(group.county)}</header>
        <div class="search-option-list">
          ${group.options.map((option) => `
            <button
              class="search-option"
              type="button"
              data-search-type="${escapeHtml(option.type)}"
              data-label="${escapeHtml(option.label)}"
              data-county="${escapeHtml(option.county || '')}"
              data-crossing-id="${escapeHtml(option.crossingId || '')}"
            >
              <span class="search-option-icon">${icon(option.type)}</span>
              <span class="search-option-copy">
                <strong>${escapeHtml(option.label)}</strong>
                <small>${escapeHtml(option.meta || '')}</small>
              </span>
            </button>
          `).join('')}
        </div>
      </section>
    `)
    .join('');
}

function findExactSearchOption(query) {
  const normalized = normalizeSearchText(query);
  if (!normalized) return null;

  for (const group of state.countyGroups) {
    if (normalizeSearchText(group.county) === normalized) {
      return { type: 'county', county: group.county, label: group.county };
    }

    const station = group.stations.find((item) => normalizeSearchText(item.label) === normalized);
    if (station) {
      return { type: 'station', county: group.county, label: station.label };
    }

    const crossing = group.crossings.find((feature) => normalizeSearchText(getFeatureMeta(feature).name) === normalized);
    if (crossing) {
      return {
        type: 'crossing',
        county: group.county,
        label: getFeatureMeta(crossing).name,
        crossingId: crossing.id,
      };
    }
  }

  return null;
}

function filterCrossings(query, option = null) {
  const normalized = normalizeSearchText(query);
  const activeOption = option || findExactSearchOption(query);

  if (!normalized && !activeOption) {
    return [...state.crossings];
  }

  if (activeOption?.type === 'county') {
    return state.crossings.filter((feature) => getFeatureMeta(feature).county === activeOption.county);
  }

  if (activeOption?.type === 'station') {
    const stationName = normalizeSearchText(activeOption.label);
    return state.crossings.filter((feature) => {
      const meta = getFeatureMeta(feature);
      return normalizeSearchText(meta.stationA) === stationName || normalizeSearchText(meta.stationB) === stationName;
    });
  }

  if (activeOption?.type === 'crossing') {
    return state.crossings.filter((feature) => feature.id === activeOption.crossingId);
  }

  const matchingCounties = state.countyGroups
    .filter((group) => normalizeSearchText(group.county).includes(normalized))
    .map((group) => group.county);
  if (matchingCounties.length) {
    const countySet = new Set(matchingCounties);
    return state.crossings.filter((feature) => countySet.has(getFeatureMeta(feature).county));
  }

  return state.crossings.filter((feature) => feature.searchIndex.includes(normalized));
}

function updateControls() {
  elements.focusSelectionButton.disabled = !state.selectedCrossingId;
  elements.refreshSelectionButton.disabled = !state.selectedCrossingId || state.selectionLoading;
}

function updateMetrics() {
  const mappedCount = state.crossings.length;
  const warningCount = getAllUpcomingPredictions().filter((record) => isLivePrediction(record) && isWithinWarningWindow(record)).length;
  elements.mappedMetric.textContent = String(mappedCount);
  elements.filteredMetric.textContent = String(state.filteredCrossings.length);
  elements.warningMetric.textContent = String(warningCount);
}

function renderScopeSummary() {
  const scopeText = !state.query
    ? '全台'
    : state.activeSearchOption?.type === 'station'
      ? `${state.activeSearchOption.county} · ${state.activeSearchOption.label}`
      : state.activeSearchOption?.label || state.query;
  elements.scopeLabel.textContent = scopeText;
  elements.resultsCount.textContent = String(state.filteredCrossings.length);
}

function renderSelectionBadge() {
  const selected = getCrossingById();
  if (!selected) {
    elements.selectionBadge.innerHTML = `
      <div class="selection-shell is-empty">
        <span>${escapeHtml(state.query || '全台')}</span>
        <strong>${escapeHtml(String(state.filteredCrossings.length))}</strong>
      </div>
    `;
    return;
  }

  const meta = getFeatureMeta(state.selectedCrossingDetail || selected);
  elements.selectionBadge.innerHTML = `
    <div class="selection-shell">
      <strong>${escapeHtml(meta.name)}</strong>
      <small>${escapeHtml(meta.km)} · ${escapeHtml(meta.stationPair || `${meta.stationA} - ${meta.stationB}`)}</small>
    </div>
  `;
}

function renderResults() {
  const selectedId = state.selectedCrossingId;
  if (!state.filteredCrossings.length) {
    elements.resultsList.innerHTML = `
      <div class="empty-block compact">
        <strong>沒有對應平交道</strong>
        <span>換個地區或車站名稱再試一次</span>
      </div>
    `;
    return;
  }

  elements.resultsList.innerHTML = state.filteredCrossings
    .map((feature) => {
      const meta = getFeatureMeta(feature);
      const isSelected = feature.id === selectedId;
      return `
        <button class="result-item ${isSelected ? 'is-active' : ''}" type="button" data-crossing-id="${escapeHtml(feature.id)}">
          <span class="result-rail ${meta.manualMappingApplied ? 'is-reviewed' : ''}"></span>
          <div class="result-body">
            <strong>${escapeHtml(meta.name)}</strong>
            <span>${escapeHtml(meta.county)} · ${escapeHtml(meta.line)}</span>
            <div class="result-meta-row">
              <span class="result-chip">${escapeHtml(meta.km)}</span>
              ${meta.stationPair ? `<span class="result-chip is-soft">${escapeHtml(meta.stationPair)}</span>` : ''}
            </div>
          </div>
          <span class="result-endcap ${isSelected ? 'is-active' : ''}">${isSelected ? '已選' : '定位'}</span>
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

    if (isSelected) {
      L.circleMarker(point, {
        renderer: crossingRenderer,
        radius: 17,
        weight: 0,
        color: '#ff845f',
        fillColor: '#ff845f',
        fillOpacity: 0.22,
        interactive: false,
      }).addTo(state.crossingLayer);
    }

    const marker = L.circleMarker(point, {
      renderer: crossingRenderer,
      radius: isSelected ? 9.4 : 6.2,
      weight: isSelected ? 2.8 : 1.5,
      color: isSelected ? '#fff6e9' : '#ffffff',
      fillColor: isSelected ? '#1f446a' : '#ff7b5b',
      fillOpacity: 0.98,
    });
    marker.on('click', () => {
      selectCrossing(feature.id, { focusMap: false });
    });
    marker.addTo(state.crossingLayer);
  });
}

function renderStationOverview() {
  state.stationOverviewLayer.clearLayers();
  if (!state.stations.length) return;

  const selectedStationIds = getSelectedStationIds();
  const showUkLabels = map.getZoom() >= STATION_LABEL_MIN_ZOOM;
  const visibleBounds = map.getBounds().pad(STATION_VIEWPORT_PADDING);

  state.stations.forEach((station) => {
    const coords = getStationSummaryCoords(station);
    const ukPrimary = getStationUkPrimary(station?.uk_primary);
    if (!coords || !ukPrimary || selectedStationIds.has(station.station_id)) return;
    if (!visibleBounds.contains(coords)) return;

    const marker = L.circleMarker(coords, {
      renderer: stationOverviewRenderer,
      radius: showUkLabels ? 4.4 : 2.8,
      weight: showUkLabels ? 1.4 : 0.8,
      color: '#355c84',
      fillColor: '#d7eefb',
      fillOpacity: showUkLabels ? 0.96 : 0.88,
      interactive: false,
    });
    if (showUkLabels) {
      marker.bindTooltip(
        `<div class="station-overview-label"><strong>${escapeHtml(ukPrimary)}</strong><span>${escapeHtml(displayLabel(station.name, '未命名車站'))}</span><small>推估參考</small></div>`,
        {
          permanent: true,
          direction: 'top',
          offset: [0, -12],
          className: 'station-overview-tooltip',
        }
      );
    }
    marker.addTo(state.stationOverviewLayer);
  });
}

function renderStationContext() {
  state.stationLayer.clearLayers();
  const stations = getSelectedStationPoints();
  if (!stations.length) return;

  if (stations.length === 2) {
    L.polyline(stations.map((station) => station.coords), {
      renderer: stationRenderer,
      color: '#2c5e87',
      weight: 3.2,
      opacity: 0.48,
      dashArray: '8 10',
      lineCap: 'round',
      interactive: false,
    }).addTo(state.stationLayer);
  }

  stations.forEach((station) => {
    L.circleMarker(station.coords, {
      renderer: stationRenderer,
      radius: 12,
      weight: 2,
      color: station.color,
      fillColor: station.color,
      fillOpacity: 0.14,
      interactive: false,
    }).addTo(state.stationLayer);

    const marker = L.circleMarker(station.coords, {
      renderer: stationRenderer,
      radius: 7,
      weight: 2.8,
      color: '#17304d',
      fillColor: station.color,
      fillOpacity: 1,
      interactive: false,
    });
    marker.bindTooltip(
      `<div class="station-context-label"><span>${escapeHtml(station.role)}</span><strong>${escapeHtml(station.name)}</strong><small>${escapeHtml(getStationUkContextLine(station.uk))}</small></div>`,
      {
        permanent: true,
        direction: 'top',
        offset: [0, -16],
        className: `station-context-tooltip ${station.className}`,
      }
    );
    marker.addTo(state.stationLayer);
  });
}

function renderSelectedCrossingCard() {
  const selected = getCrossingById();
  if (!selected) {
    elements.selectedCrossingCard.innerHTML = `
      <div class="empty-block large">
        <strong>選一個平交道</strong>
        <span>地圖與左側清單都可以直接選取</span>
      </div>
    `;
    return;
  }

  if (state.selectionLoading && !state.selectedCrossingDetail) {
    elements.selectedCrossingCard.innerHTML = '<div class="loading-block"></div>';
    return;
  }

  const meta = getFeatureMeta(state.selectedCrossingDetail || selected);
  const properties = state.selectedCrossingDetail?.properties || {};
  const confidenceHint = getConfidenceHint(meta);
  const stationAUk = getStationUkDisplay(properties.station_a_uk_primary);
  const stationBUk = getStationUkDisplay(properties.station_b_uk_primary);
  const stationUkNote = getStationReferenceNote(properties.station_uk_reference_note);
  elements.selectedCrossingCard.innerHTML = `
    <div class="crossing-top-row compact">
      <span class="tiny-pill">${escapeHtml(meta.county)}</span>
      ${confidenceHint ? `<span class="tiny-pill ${escapeHtml(confidenceHint.tone)}">${escapeHtml(confidenceHint.label)}</span>` : ''}
    </div>
    <div class="crossing-head">
      <h2 class="crossing-title">${escapeHtml(meta.name)}</h2>
      <div class="crossing-meta-line">
        <span>${escapeHtml(meta.line)}</span>
        <i class="crossing-meta-separator" aria-hidden="true"></i>
        <span>${escapeHtml(meta.km)}</span>
        ${meta.roadType ? `<i class="crossing-meta-separator" aria-hidden="true"></i><span>${escapeHtml(meta.roadType)}</span>` : ''}
      </div>
    </div>
    <div class="station-band is-compact is-detailed">
      <div class="station-band-stop">
        <small>前站</small>
        <strong>${escapeHtml(meta.stationA || '未提供')}</strong>
        <span>${escapeHtml(stationAUk)}</span>
      </div>
      ${icon('route')}
      <div class="station-band-stop">
        <small>後站</small>
        <strong>${escapeHtml(meta.stationB || '未提供')}</strong>
        <span>${escapeHtml(stationBUk)}</span>
      </div>
    </div>
    <div class="station-reference-note">${escapeHtml(stationUkNote)}</div>
    <div class="crossing-foot-row">
      <span class="source-pill">${escapeHtml(getPairSourceLabel(meta.stationPairSource).replace('站間：', ''))}</span>
      <span class="source-pill is-soft">${escapeHtml(getRatioSourceLabel(meta.ratioSource).replace('比例：', ''))}</span>
    </div>
  `;
}

function renderWarningCard() {
  const selected = getCrossingById();
  if (!selected) {
    elements.warningCard.innerHTML = `
      <div class="empty-block large">
        <strong>尚未指定目標</strong>
        <span>選定平交道後會立刻顯示下一班車</span>
      </div>
    `;
    return;
  }

  if (state.selectionLoading && !state.predictionEnvelope) {
    elements.warningCard.innerHTML = '<div class="loading-block"></div>';
    return;
  }

  const primary = getPrimaryPrediction();
  if (!primary) {
    elements.warningCard.innerHTML = `
      <div class="hero-shell is-idle">
        <div class="hero-chip-row">
          <span class="hero-chip">暫無列車</span>
        </div>
        <div class="hero-countdown">
          <strong>SAFE</strong>
          <span>目前沒有接近平交道的列車資料</span>
        </div>
      </div>
    `;
    return;
  }

  const countdown = getCountdownParts(primary.eta);
  const route = getPredictionRoute(primary);
  const stopTiming = getStopTiming(primary);
  const directionLabel = getDirectionLabel(primary);
  const isLive = isLivePrediction(primary);
  const warning = isLive && isWithinWarningWindow(primary);

  elements.warningCard.innerHTML = `
    <div class="hero-shell ${warning ? 'is-alert' : isLive ? 'is-watch' : 'is-scheduled'}">
      <div class="hero-chip-row">
        <span class="hero-chip ${escapeHtml(getPredictionTone(primary))}">${escapeHtml(getPredictionBasisLabel(primary))}</span>
        <span class="hero-chip is-strong">${escapeHtml(formatTrainNo(primary))}</span>
        <span class="hero-chip">${escapeHtml(directionLabel)}</span>
      </div>
      <div class="hero-countdown">
        <strong>${escapeHtml(countdown.short)}</strong>
        <span>${escapeHtml(`現在 ${formatClockMs(getNowMs())} · 預計 ${formatPreciseTime(primary.eta)} 通過`)}</span>
      </div>
      <div class="hero-route-line">
        <span>${escapeHtml(route.origin)}</span>
        ${icon('route')}
        <span>${escapeHtml(route.destination)}</span>
      </div>
      <div class="hero-route-meta">
        <span>${escapeHtml(primary.train_type || '列車')}</span>
        <span>${escapeHtml(isLive ? `即時倒數 · ${route.approachFrom} → ${route.approachTo}` : `班表預估 · ${route.approachFrom} → ${route.approachTo}`)}</span>
      </div>
      <div class="hero-stop-grid">
        <div class="stop-timing-card">
          <span class="stop-timing-label">上一停靠</span>
          <strong>${escapeHtml(stopTiming.previousName)}</strong>
          <span class="stop-timing-time">${escapeHtml(`${stopTiming.previousDeparture} 離站`)}</span>
        </div>
        <div class="stop-timing-card">
          <span class="stop-timing-label">下一停靠</span>
          <strong>${escapeHtml(stopTiming.nextName)}</strong>
          <span class="stop-timing-time">${escapeHtml(`${stopTiming.nextArrival} 到站`)}</span>
        </div>
      </div>
    </div>
  `;
}

function renderPredictionList() {
  const selected = getCrossingById();
  if (!selected) {
    elements.predictionList.innerHTML = `
      <div class="empty-block compact">
        <strong>還沒有列車資料</strong>
        <span>先選一個平交道</span>
      </div>
    `;
    return;
  }

  if (state.selectionLoading && !state.predictionEnvelope) {
    elements.predictionList.innerHTML = Array.from({ length: 3 }, () => '<div class="loading-block compact"></div>').join('');
    return;
  }

  elements.predictionList.innerHTML = getScheduleSlots()
    .map((slot) => {
      if (!slot.record) {
        return `
          <article class="train-card is-empty">
            <div class="train-main">
              <div class="train-slot-row">
                <span class="train-slot-label">${escapeHtml(slot.label)}</span>
              </div>
              <div class="train-route">${escapeHtml(slot.emptyTitle)}</div>
              <div class="train-subroute">${escapeHtml(slot.emptySubtitle)}</div>
            </div>
          </article>
        `;
      }

      const record = slot.record;
      const countdown = getRelativeEtaParts(record.eta);
      const route = getPredictionRoute(record);
      const stopTiming = getStopTiming(record);
      const isLive = isLivePrediction(record);
      const warning = isLive && isWithinWarningWindow(record);
      const isPast = countdown.isPast;
      return `
        <article class="train-card ${warning ? 'is-warning' : ''} ${isPast ? 'is-passed' : ''} ${escapeHtml(getPredictionTone(record))}">
          <div class="train-main">
            <div class="train-slot-row">
              <span class="train-slot-label">${escapeHtml(slot.label)}</span>
              <span class="train-slot-status ${escapeHtml(getPredictionTone(record))}">${escapeHtml(isPast ? '已通過' : getPredictionBasisLabel(record))}</span>
            </div>
            <div class="train-title-row">
              <strong>${escapeHtml(formatTrainNo(record))}</strong>
              <span>${escapeHtml(record.train_type || '列車')}</span>
            </div>
            <div class="train-route">${escapeHtml(route.origin)} → ${escapeHtml(route.destination)}</div>
            <div class="train-subroute">${escapeHtml(getDirectionLabel(record))}</div>
            <div class="train-stop-grid">
              <div class="train-stop-item">
                <span class="stop-timing-label">上一停靠</span>
                <strong>${escapeHtml(stopTiming.previousName)}</strong>
                <span class="stop-timing-time">${escapeHtml(`${stopTiming.previousDeparture} 離站`)}</span>
              </div>
              <div class="train-stop-item">
                <span class="stop-timing-label">下一停靠</span>
                <strong>${escapeHtml(stopTiming.nextName)}</strong>
                <span class="stop-timing-time">${escapeHtml(`${stopTiming.nextArrival} 到站`)}</span>
              </div>
            </div>
          </div>
          <div class="train-side">
            <span class="countdown-pill ${warning ? 'is-warning' : ''} ${isPast ? 'is-passed' : ''}">${escapeHtml(countdown.short)}</span>
            <small>${escapeHtml(formatPreciseTime(record.eta))}</small>
          </div>
        </article>
      `;
    })
    .join('');
}

function renderStaticUi() {
  syncNow();
  if (state.predictionEnvelope) {
    updateLastPassedPrediction();
  }
  renderScopeSummary();
  renderResults();
  renderSelectionBadge();
  renderCrossingMarkers();
  renderStationOverview();
  renderStationContext();
  renderSelectedCrossingCard();
  renderWarningCard();
  renderPredictionList();
  updateMetrics();
  updateControls();
  renderSearchPanel();
}

function clearSelection() {
  state.selectedCrossingId = null;
  state.selectedCrossingDetail = null;
  state.predictionEnvelope = null;
  state.selectionLoading = false;
  state.clock.envelopeGeneratedAtMs = null;
}

function setSearchPanelOpen(isOpen) {
  state.searchPanelOpen = isOpen;
  renderSearchPanel();
}

function applyQuery({ focusMap = true } = {}) {
  state.query = elements.regionInput.value.trim();
  state.activeSearchOption = state.query ? (state.activeSearchOption && normalizeSearchText(state.activeSearchOption.label) === normalizeSearchText(state.query)
    ? state.activeSearchOption
    : findExactSearchOption(state.query)) : null;
  state.filteredCrossings = filterCrossings(state.query, state.activeSearchOption);

  if (state.selectedCrossingId && !state.filteredCrossings.some((feature) => feature.id === state.selectedCrossingId)) {
    clearSelection();
  }

  renderStaticUi();

  if (!focusMap) return;

  if (state.filteredCrossings.length) {
    focusFilteredCrossings();
    setStatus(`已聚焦 ${state.filteredCrossings.length} 個平交道。`, 'success');
    return;
  }

  map.setView(MAP_HOME, MAP_HOME_ZOOM);
  setStatus(`找不到「${state.query}」對應的平交道。`, 'warning');
}

function applySearchOption(option) {
  state.activeSearchOption = option;
  elements.regionInput.value = option.label;
  setSearchPanelOpen(false);
  applyQuery({ focusMap: true });
  if (option.type === 'crossing' && option.crossingId) {
    selectCrossing(option.crossingId, { focusMap: true });
  }
}

async function selectCrossing(crossingId, { focusMap = true, refreshOnly = false, silent = false } = {}) {
  const baseFeature = getCrossingById(crossingId);
  if (!baseFeature) return;

  state.selectedCrossingId = crossingId;
  state.selectionLoading = true;
  if (!refreshOnly) {
    state.selectedCrossingDetail = null;
    state.predictionEnvelope = null;
  }

  renderStaticUi();
  if (!silent) {
    setStatus(`正在更新 ${getFeatureMeta(baseFeature).name} 的列車預測…`);
  }

  const token = ++state.selectionRequestToken;
  try {
    const predictionRequest = apiRequest(`/api/predictions/${encodeURIComponent(crossingId)}`, {
        params: new URLSearchParams({
          recent_minutes: String(PREDICTION_RECENT_WINDOW_MINUTES),
          warning_minutes: String(PREDICTION_WARNING_WINDOW_MINUTES),
        }),
      });
    const detailRequest = refreshOnly && state.selectedCrossingDetail
      ? Promise.resolve(state.selectedCrossingDetail)
      : apiRequest(`/api/crossings/${encodeURIComponent(crossingId)}`);
    const [detail, envelope] = await Promise.all([detailRequest, predictionRequest]);
    const receivedAtMs = Date.now();

    if (token !== state.selectionRequestToken) return;
    syncNow(receivedAtMs);
    updateLastPassedPrediction(crossingId);
    state.selectedCrossingDetail = detail;
    state.predictionEnvelope = envelope;
    syncEnvelopeClock(envelope, receivedAtMs);
    primePredictionRuntime(crossingId, envelope);
    state.selectionLoading = false;
    renderStaticUi();
    if (focusMap) {
      focusSelectedCrossing();
    }

    const warningCount = getAllUpcomingPredictions().filter((record) => isLivePrediction(record) && isWithinWarningWindow(record)).length;
    if (!silent) {
      setStatus(
        warningCount
          ? `${getFeatureMeta(baseFeature).name} 已更新，現在有 ${warningCount} 筆提醒。`
          : `${getFeatureMeta(baseFeature).name} 已更新。`,
        warningCount ? 'warning' : 'success'
      );
    }
  } catch (error) {
    if (token !== state.selectionRequestToken) return;
    state.selectionLoading = false;
    state.selectedCrossingDetail = refreshOnly ? state.selectedCrossingDetail : null;
    state.predictionEnvelope = refreshOnly ? state.predictionEnvelope : null;
    renderStaticUi();
    if (!silent) {
      setStatus(`載入預測失敗：${error.message}`, 'error');
    }
  }
}

function startTimers() {
  if (state.timers.countdown) {
    window.clearInterval(state.timers.countdown);
  }

  state.timers.countdown = window.setInterval(() => {
    if (!state.predictionEnvelope) return;
    syncNow();
    updateLastPassedPrediction();
    renderWarningCard();
    renderPredictionList();
    updateMetrics();
  }, COUNTDOWN_TICK_MS);
}

function attachEventListeners() {
  map.on('zoomend moveend', () => {
    renderStationOverview();
  });

  elements.regionInput.addEventListener('focus', () => {
    setSearchPanelOpen(true);
  });

  elements.regionInput.addEventListener('input', () => {
    state.activeSearchOption = null;
    state.query = elements.regionInput.value.trim();
    setSearchPanelOpen(true);
    applyQuery({ focusMap: false });
  });

  elements.regionInput.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setSearchPanelOpen(false);
    }
  });

  elements.regionForm.addEventListener('submit', (event) => {
    event.preventDefault();
    setSearchPanelOpen(false);
    applyQuery({ focusMap: true });
  });

  elements.focusRegionButton.addEventListener('click', () => {
    setSearchPanelOpen(false);
    applyQuery({ focusMap: true });
  });

  elements.searchMenuButton.addEventListener('click', () => {
    setSearchPanelOpen(!state.searchPanelOpen);
  });

  elements.searchPanel.addEventListener('pointerdown', (event) => {
    const button = event.target.closest('[data-search-type]');
    if (!button) return;
    event.preventDefault();
    applySearchOption({
      type: button.dataset.searchType,
      label: button.dataset.label,
      county: button.dataset.county,
      crossingId: button.dataset.crossingId || null,
    });
  });

  document.addEventListener('click', (event) => {
    if (!elements.searchStack.contains(event.target)) {
      setSearchPanelOpen(false);
    }
  });

  elements.resetRegionButton.addEventListener('click', () => {
    elements.regionInput.value = '';
    state.query = '';
    state.activeSearchOption = null;
    state.filteredCrossings = [...state.crossings];
    clearSelection();
    setSearchPanelOpen(false);
    renderStaticUi();
    map.setView(MAP_HOME, MAP_HOME_ZOOM);
    setStatus('已回到全台總覽。', 'neutral');
  });

  elements.resultsList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-crossing-id]');
    if (!button) return;
    selectCrossing(button.dataset.crossingId, { focusMap: true });
  });

  elements.focusSelectionButton.addEventListener('click', () => {
    if (!state.selectedCrossingId) {
      setStatus('先選一個平交道。', 'warning');
      return;
    }
    focusSelectedCrossing();
  });

  elements.refreshSelectionButton.addEventListener('click', () => {
    if (!state.selectedCrossingId) {
      setStatus('先選一個平交道。', 'warning');
      return;
    }
    selectCrossing(state.selectedCrossingId, { focusMap: false, refreshOnly: true });
  });
}

async function bootstrap() {
  setStatus('載入平交道、車站與列車資料中…');
  const [crossingsPayload, stationsPayload] = await Promise.all([
    apiRequest('/api/crossings', { params: new URLSearchParams({ limit: '5000', mapped_only: 'true' }) }),
    apiRequest('/api/crossings/stations', { params: new URLSearchParams({ limit: '5000' }) }),
  ]);
  state.crossings = sortFeaturesSouthToNorth(safeArray(crossingsPayload.features)).map((feature) => {
    const meta = getFeatureMeta(feature);
    return {
      ...feature,
      meta,
      searchIndex: buildSearchIndex({ ...feature, meta }),
    };
  });
  state.stations = safeArray(stationsPayload.features)
    .filter((station) => getStationSummaryCoords(station) && getStationUkPrimary(station.uk_primary));
  state.filteredCrossings = [...state.crossings];
  state.countyGroups = buildCountyGroups(state.crossings);

  attachEventListeners();
  startTimers();
  renderStaticUi();
  setStatus(`已載入 ${state.crossings.length} 個已整合平交道與 ${state.stations.length} 座參考車站。`, 'success');
}

bootstrap().catch((error) => {
  console.error(error);
  setStatus(`載入失敗：${error.message}`, 'error');
});
