const RATIO_MAP_HOME = [23.7, 121.0];
const RATIO_MAP_ZOOM = 7;

const ratioMap = L.map('ratioMap', {
  zoomControl: false,
  preferCanvas: true,
  scrollWheelZoom: true,
}).setView(RATIO_MAP_HOME, RATIO_MAP_ZOOM);

ratioMap.createPane('workspaceOverviewPane');
ratioMap.getPane('workspaceOverviewPane').style.zIndex = '390';
ratioMap.createPane('workspaceStationPane');
ratioMap.getPane('workspaceStationPane').style.zIndex = '370';
ratioMap.createPane('workspaceFocusPane');
ratioMap.getPane('workspaceFocusPane').style.zIndex = '430';

L.control.zoom({ position: 'bottomright' }).addTo(ratioMap);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors',
}).addTo(ratioMap);

const workspaceState = {
  crossings: [],
  stations: [],
  filteredCrossings: [],
  selectedCrossingId: null,
  selectedExplanation: null,
  showOsmDiagnostics: false,
  requestToken: 0,
  layers: {
    stations: L.layerGroup().addTo(ratioMap),
    overview: L.layerGroup().addTo(ratioMap),
    focus: L.layerGroup().addTo(ratioMap),
  },
};

const workspaceElements = {
  searchInput: document.getElementById('workspaceSearchInput'),
  count: document.getElementById('workspaceCount'),
  crossingList: document.getElementById('workspaceCrossingList'),
  mapLegend: document.querySelector('.workspace-map-legend'),
  summaryCard: document.getElementById('workspaceSummaryCard'),
  diagnosticCard: document.getElementById('workspaceDiagnosticCard'),
};

function workspaceSelectedSource(explanation = workspaceState.selectedExplanation) {
  return explanation?.ratios?.selected?.source || null;
}

function workspaceShouldDrawOsmDiagnostics(explanation = workspaceState.selectedExplanation) {
  return workspaceState.showOsmDiagnostics;
}

function workspaceShouldDrawProjection(explanation = workspaceState.selectedExplanation) {
  return workspaceSelectedSource(explanation) === 'geometry_projection';
}

function workspaceStationPair(explanation = workspaceState.selectedExplanation) {
  const stationA = workspaceLabel(explanation?.stations?.station_a?.label, '前站');
  const stationB = workspaceLabel(explanation?.stations?.station_b?.label, '後站');
  return { stationA, stationB, text: `${stationA}-${stationB}` };
}

function workspaceMethodMeaning(source) {
  if (source === 'official_route_mileage') return '官方鏈公里';
  if (source === 'osm_path') return '沿 OSM 鐵道量測';
  if (source === 'geometry_projection') return '站點直線投影';
  if (source === 'midpoint') return '中點 fallback';
  return '未標示';
}

function workspaceHaversineMeters(lat1, lon1, lat2, lon2) {
  const radiusMeters = 6371000;
  const toRadians = (value) => (value * Math.PI) / 180;
  const deltaLat = toRadians(lat2 - lat1);
  const deltaLon = toRadians(lon2 - lon1);
  const a = Math.sin(deltaLat / 2) ** 2 + Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) * Math.sin(deltaLon / 2) ** 2;
  return 2 * radiusMeters * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function workspaceOsmPathAssessment(explanation = workspaceState.selectedExplanation) {
  const path = explanation?.ratios?.osm_path;
  const stationA = explanation?.stations?.station_a?.position;
  const stationB = explanation?.stations?.station_b?.position;
  if (!path?.available || !stationA || !stationB) {
    return {
      suspicious: false,
      totalDistanceMeters: Number(path?.total_distance_meters) || null,
      stationSpanMeters: null,
      note: '',
    };
  }

  const stationSpanMeters = workspaceHaversineMeters(
    Number(stationA.PositionLat),
    Number(stationA.PositionLon),
    Number(stationB.PositionLat),
    Number(stationB.PositionLon),
  );
  const totalDistanceMeters = Number(path.total_distance_meters);
  const suspicious = Number.isFinite(totalDistanceMeters) && Number.isFinite(stationSpanMeters)
    ? totalDistanceMeters > Math.max(stationSpanMeters * 3, 20000)
    : false;

  return {
    suspicious,
    totalDistanceMeters,
    stationSpanMeters,
    note: suspicious
      ? `這筆 OSM 路徑長約 ${workspaceFormatMeters(totalDistanceMeters)}，但前後站直線距離只有 ${workspaceFormatMeters(stationSpanMeters)}，跨度明顯異常，比較像 OSM 錯配或吸附錯誤。`
      : '',
  };
}

function workspaceCanDrawSelectedOsmPath(explanation = workspaceState.selectedExplanation) {
  return workspaceSelectedSource(explanation) === 'osm_path' && !workspaceOsmPathAssessment(explanation).suspicious;
}

function workspaceShouldHideSuspiciousCrossing(explanation = workspaceState.selectedExplanation) {
  return workspaceSelectedSource(explanation) === 'osm_path'
    && workspaceOsmPathAssessment(explanation).suspicious
    && !workspaceState.showOsmDiagnostics;
}

function workspaceSnapRoleLabel(index) {
  if (index === 0) return 'crossing snap';
  if (index === 1) return 'station A snap';
  return 'station B snap';
}

function workspaceRenderMapLegend(explanation = workspaceState.selectedExplanation) {
  if (!workspaceElements.mapLegend) return;

  const selectedSource = workspaceSelectedSource(explanation);
  const pathAssessment = workspaceOsmPathAssessment(explanation);
  const chips = [
    '<span class="workspace-legend-chip"><i class="workspace-legend-dot is-crossing"></i>平交道</span>',
    '<span class="workspace-legend-chip"><i class="workspace-legend-dot is-station"></i>所有車站</span>',
    '<span class="workspace-legend-chip"><i class="workspace-legend-dot is-station"></i>前後站</span>',
  ];

  if (workspaceShouldDrawProjection(explanation)) {
    chips.push('<span class="workspace-legend-chip"><i class="workspace-legend-dot is-projection"></i>目前採用的投影線</span>');
  }

  if (workspaceCanDrawSelectedOsmPath(explanation)) {
    chips.push('<span class="workspace-legend-chip"><i class="workspace-legend-dot is-path"></i>目前採用的 OSM 路徑</span>');
  }

  if (workspaceShouldDrawOsmDiagnostics(explanation)) {
    chips.push(
      `<span class="workspace-legend-chip${selectedSource === 'osm_path' && !pathAssessment.suspicious ? '' : ' is-muted'}"><i class="workspace-legend-dot is-path"></i>${selectedSource === 'osm_path' && !pathAssessment.suspicious ? 'OSM 路徑診斷' : 'OSM 候選路徑診斷'}</span>`,
    );
    chips.push('<span class="workspace-legend-chip is-muted"><i class="workspace-legend-dot is-snap"></i>snap 點</span>');
  }

  workspaceElements.mapLegend.innerHTML = chips.join('');
}

function workspaceApi(path) {
  return fetch(path).then(async (response) => {
    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : text;
      throw new Error(detail || `${response.status} ${response.statusText}`);
    }
    return payload;
  });
}

function workspaceEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function workspaceLabel(value, fallback = '') {
  const text = String(value ?? '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/([\u4e00-\u9fff])\s+([\u4e00-\u9fff])/g, '$1$2');
  return text || fallback;
}

function workspaceSearchText(feature) {
  const properties = feature.properties || {};
  return [
    properties.county,
    properties.name,
    properties.line,
    properties.km_marker,
    properties.station_pair_text,
    properties.station_a_name,
    properties.station_b_name,
  ]
    .map((value) => workspaceLabel(value).toLowerCase().replace(/\s+/g, ''))
    .join(' ');
}

function workspaceLatLng(feature) {
  const coordinates = feature?.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) return null;
  const lon = Number(coordinates[0]);
  const lat = Number(coordinates[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lat, lon];
}

function workspacePointToLatLng(point) {
  const lat = Number(point?.lat ?? point?.PositionLat);
  const lon = Number(point?.lon ?? point?.PositionLon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lat, lon];
}

function workspacePathToLatLngs(path) {
  const coordinates = path?.coordinates;
  if (!Array.isArray(coordinates)) return [];
  return coordinates
    .map((coordinate) => {
      if (!Array.isArray(coordinate) || coordinate.length < 2) return null;
      const lon = Number(coordinate[0]);
      const lat = Number(coordinate[1]);
      return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
    })
    .filter(Boolean);
}

function workspaceFormatMeters(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '未提供';
  return `${number.toFixed(number >= 100 ? 0 : 1)} m`;
}

function workspaceFormatRatio(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '未提供';
  return `${(number * 100).toFixed(1)}%`;
}

function workspaceRatioSourceLabel(value) {
  if (value === 'official_route_mileage') return '官方鏈公里';
  if (value === 'osm_path') return 'OSM 軌道路徑';
  if (value === 'geometry_projection') return '站點直線投影';
  if (value === 'midpoint') return '中點 fallback';
  return '尚未選用';
}

function workspaceConfidenceLabel(value) {
  if (value === 'high') return '高信心';
  if (value === 'medium') return '中信心';
  if (value === 'low') return '低信心';
  return '未標示';
}

function workspacePathStatusLabel(reason) {
  if (reason === 'ok') return '可量測';
  if (reason === 'station_pair_unresolved') return '站名無法解析';
  if (reason === 'crossing_cannot_snap') return '平交道無法 snap';
  if (reason === 'station_a_cannot_snap_same_component') return '前站無法在同 component snap';
  if (reason === 'station_b_cannot_snap_same_component') return '後站無法在同 component snap';
  if (reason === 'graph_unavailable') return 'OSM 圖不存在';
  return workspaceLabel(reason, '無法使用');
}

function workspaceUpdateQueryString(crossingId) {
  const url = new URL(window.location.href);
  if (crossingId) {
    url.searchParams.set('crossing', crossingId);
  } else {
    url.searchParams.delete('crossing');
  }
  window.history.replaceState({}, '', url);
}

function workspaceRenderList() {
  const selectedId = workspaceState.selectedCrossingId;
  workspaceElements.count.textContent = `顯示 ${workspaceState.filteredCrossings.length} / ${workspaceState.crossings.length} 筆 active crossings`;

  if (!workspaceState.filteredCrossings.length) {
    workspaceElements.crossingList.innerHTML = `
      <div class="workspace-empty">
        <p>沒有符合搜尋條件的平交道。</p>
      </div>
    `;
    return;
  }

  workspaceElements.crossingList.innerHTML = workspaceState.filteredCrossings
    .map((feature) => {
      const properties = feature.properties || {};
      const isActive = feature.id === selectedId;
      return `
        <button class="workspace-result-item${isActive ? ' is-active' : ''}" type="button" data-crossing-id="${workspaceEscape(feature.id)}">
          <div class="workspace-result-title">
            <strong>${workspaceEscape(workspaceLabel(properties.name, feature.id))}</strong>
            <span>${workspaceEscape(workspaceLabel(properties.county, '未分類'))}</span>
          </div>
          <div class="workspace-result-subline">${workspaceEscape(workspaceLabel(properties.line, '未提供路線'))} · ${workspaceEscape(workspaceLabel(properties.km_marker, '未標公里'))}</div>
          <div class="workspace-result-subline">${workspaceEscape(workspaceLabel(properties.station_pair_text, '未提供站間'))}</div>
        </button>
      `;
    })
    .join('');
}

function workspaceRenderSummary() {
  const explanation = workspaceState.selectedExplanation;
  if (!explanation) {
    workspaceElements.summaryCard.innerHTML = `
      <div class="workspace-empty">
        <p>選一筆平交道後，這裡只會顯示目前採用的區間位置與必要診斷。</p>
      </div>
    `;
    workspaceElements.diagnosticCard.innerHTML = `
      <div class="workspace-empty">
        <p>如果要追查 OSM 候選路徑，再打開診斷即可。</p>
      </div>
    `;
    workspaceRenderMapLegend();
    return;
  }

  const crossing = explanation.crossing || {};
  const selected = explanation.ratios?.selected || {};
  const pair = workspaceStationPair(explanation);
  const pathAssessment = workspaceOsmPathAssessment(explanation);
  const ratioValue = Number(selected.value);
  const ratioPercent = Number.isFinite(ratioValue) ? Math.max(0, Math.min(100, ratioValue * 100)) : 50;

  const mainMeaning = selected.source === 'osm_path'
    ? `表示沿著 OSM 鐵道量時，${workspaceLabel(crossing.name, '這筆平交道')} 大約位在 ${pair.text} 區間的 ${workspaceFormatRatio(selected.value)} 位置。`
    : selected.source === 'geometry_projection'
      ? `表示把 ${workspaceLabel(crossing.name, '這筆平交道')} 投影到 ${pair.text} 的直線後，大約落在這段區間的 ${workspaceFormatRatio(selected.value)} 位置。`
      : selected.source === 'official_route_mileage'
        ? `表示依官方鏈公里，${workspaceLabel(crossing.name, '這筆平交道')} 大約位在 ${pair.text} 區間的 ${workspaceFormatRatio(selected.value)} 位置。`
        : `表示目前只能粗略估計 ${workspaceLabel(crossing.name, '這筆平交道')} 在 ${pair.text} 區間的位置。`;

  const statusNote = selected.source === 'geometry_projection'
    ? '目前沒有採用 OSM，因為 OSM 候選結果不可信。'
    : selected.source === 'osm_path' && pathAssessment.suspicious
      ? '目前後端仍回傳 OSM，但這筆 OSM 路徑跨度異常，地圖預設只保留前後站位置。'
      : selected.source === 'osm_path'
        ? '目前直接採用 OSM 鐵道路徑。'
        : '目前使用的不是 OSM 幾何。';

  const detailNote = selected.source === 'geometry_projection'
    ? workspaceLabel(selected.note, '')
    : selected.source === 'osm_path' && pathAssessment.suspicious
      ? pathAssessment.note
      : '';

  workspaceElements.summaryCard.innerHTML = `
    <div class="workspace-card-head">
      <div>
        <small class="workspace-method-tag"><i class="workspace-inline-dot is-crossing"></i>目前 app 採用值</small>
        <h3>${workspaceEscape(workspaceLabel(crossing.name, '未命名平交道'))}</h3>
      </div>
      <div class="workspace-ratio-value">${workspaceEscape(workspaceFormatRatio(selected.value))}</div>
    </div>
    <div class="workspace-pair-meta">
      <div>
        <strong>${workspaceEscape(workspaceMethodMeaning(selected.source))}</strong>
        <div class="workspace-ratio-caption">${workspaceEscape(pair.text)}</div>
      </div>
      <div class="workspace-ratio-caption">${workspaceEscape(workspaceLabel(crossing.km_marker, '未標公里'))}</div>
    </div>
    <div class="workspace-ratio-track">
      <div class="workspace-ratio-fill" style="width:${ratioPercent}%;"></div>
      <div class="workspace-ratio-pin" style="left:${ratioPercent}%;"></div>
    </div>
    <div class="workspace-ratio-labels">
      <div>
        <strong>${workspaceEscape(pair.stationA)}</strong>
        <span class="workspace-ratio-caption">0%</span>
      </div>
      <div style="text-align:right;">
        <strong>${workspaceEscape(pair.stationB)}</strong>
        <span class="workspace-ratio-caption">100%</span>
      </div>
    </div>
    <p class="workspace-note">${workspaceEscape(mainMeaning)}</p>
    <div class="workspace-badge${selected.source === 'geometry_projection' || pathAssessment.suspicious ? ' is-alert' : ' is-ok'}">
      <div>
        <strong>${workspaceEscape(statusNote)}</strong>
        <small>${workspaceEscape(detailNote)}</small>
      </div>
    </div>
  `;

  workspaceElements.diagnosticCard.innerHTML = workspaceRenderDiagnosticCard(explanation);
  workspaceRenderMapLegend(explanation);
}

function workspaceRenderDiagnosticCard(explanation) {
  const selectedSource = workspaceSelectedSource(explanation);
  const path = explanation?.ratios?.osm_path;
  const pathAssessment = workspaceOsmPathAssessment(explanation);
  const toggleLabel = workspaceState.showOsmDiagnostics ? '隱藏診斷地圖' : '顯示診斷地圖';
  const pair = workspaceStationPair(explanation);

  const heading = selectedSource === 'osm_path' && !pathAssessment.suspicious
    ? 'OSM 診斷'
    : '需要時再看 OSM 診斷';

  const intro = selectedSource === 'osm_path'
    ? pathAssessment.suspicious
      ? pathAssessment.note
      : `如果沿著 OSM 鐵道量，${workspaceLabel(explanation?.crossing?.name, '這筆平交道')} 會落在 ${pair.text} 區間的 ${workspaceFormatRatio(path?.ratio)} 位置。`
    : `OSM 候選值是 ${workspaceFormatRatio(path?.ratio)}，但目前沒有採用，因為 ${workspaceLabel(explanation?.ratios?.selected?.note, '它不夠可信')}。`;

  return `
    <div class="workspace-card-head">
      <div>
        <small class="workspace-method-tag${selectedSource === 'osm_path' && !pathAssessment.suspicious ? '' : ' is-muted'}"><i class="workspace-inline-dot is-path"></i>${workspaceEscape(selectedSource === 'osm_path' && !pathAssessment.suspicious ? '目前採用的 OSM' : 'OSM 候選診斷')}</small>
        <h3>${workspaceEscape(heading)}</h3>
      </div>
      <div class="workspace-ratio-caption">${workspaceEscape(path?.available ? workspaceFormatRatio(path?.ratio) : workspacePathStatusLabel(path?.reason))}</div>
    </div>
    <p>${workspaceEscape(intro)}</p>
    ${workspaceState.showOsmDiagnostics && path?.available ? `
      <div class="workspace-data-list">
        <div class="workspace-data-pill"><span>OSM 區間位置</span><strong>${workspaceEscape(workspaceFormatRatio(path?.ratio))}</strong></div>
        <div class="workspace-data-pill"><span>路徑總長</span><strong>${workspaceEscape(workspaceFormatMeters(path?.total_distance_meters))}</strong></div>
        <div class="workspace-data-pill"><span>前站 → 平交道</span><strong>${workspaceEscape(workspaceFormatMeters(path?.distance_from_station_a_meters))}</strong></div>
        <div class="workspace-data-pill"><span>平交道 → 後站</span><strong>${workspaceEscape(workspaceFormatMeters(path?.distance_to_station_b_meters))}</strong></div>
      </div>
      <div class="workspace-badge">
        <div>
          <strong>紫色 snap 點是什麼</strong>
          <small>它代表把車站或平交道座標吸附到 OSM 鐵道線後，真正拿來量沿軌距離的位置。</small>
        </div>
      </div>
    ` : ''}
    <div class="workspace-card-actions">
      <button class="ghost-button inline-button compact" type="button" data-action="toggle-osm-diagnostics">${workspaceEscape(toggleLabel)}</button>
    </div>
  `;
}

function workspaceRenderOfficialCard(official) {
  const available = Boolean(official?.available);
  return `
    <section class="workspace-card is-official">
      <div class="workspace-card-head">
        <div>
          <small class="workspace-method-tag"><i class="workspace-inline-dot is-station"></i>官方鏈公里</small>
          <h3>${available ? workspaceFormatRatio(official?.value) : '目前不可用'}</h3>
        </div>
        <div class="workspace-ratio-caption">${available ? 'authoritative' : 'missing anchors'}</div>
      </div>
      <div class="workspace-km-grid">
        <article>
          <small>站 A</small>
          <div class="workspace-km-value">${workspaceEscape(workspaceLabel(official?.station_a_km_meters, '未提供'))}</div>
        </article>
        <article>
          <small>平交道</small>
          <div class="workspace-km-value">${workspaceEscape(workspaceLabel(official?.crossing_km_meters, '未提供'))}</div>
        </article>
        <article>
          <small>站 B</small>
          <div class="workspace-km-value">${workspaceEscape(workspaceLabel(official?.station_b_km_meters, '未提供'))}</div>
        </article>
      </div>
      <p class="workspace-note">${workspaceEscape(workspaceLabel(official?.note, '未提供說明'))}</p>
    </section>
  `;
}

function workspaceRenderPathCard(path, selectedSource, selectedNote) {
  const available = Boolean(path?.available);
  const isSelected = selectedSource === 'osm_path';
  const canToggleDiagnostics = available && !isSelected;
  const toggleLabel = workspaceState.showOsmDiagnostics ? '隱藏 OSM 候選診斷' : '顯示 OSM 候選診斷';
  const headingLabel = isSelected ? 'OSM 沿軌路徑' : 'OSM 候選路徑';
  const statusLabel = isSelected ? '目前採用' : '候選但未採用';
  const note = !isSelected && selectedSource === 'geometry_projection'
    ? `${selectedNote || ''} 這張卡片保留的是被拒絕的 OSM 候選值，只用來診斷為什麼它不可信。`
    : path?.note;

  return `
    <section class="workspace-card is-path">
      <div class="workspace-card-head">
        <div>
          <small class="workspace-method-tag${isSelected ? '' : ' is-muted'}"><i class="workspace-inline-dot is-path"></i>${headingLabel}</small>
          <h3>${available ? workspaceFormatRatio(path?.ratio) : workspacePathStatusLabel(path?.reason)}</h3>
        </div>
        <div class="workspace-ratio-caption">${available ? `${statusLabel} · ${workspaceFormatMeters(path?.total_distance_meters)}` : '未建立路徑'}</div>
      </div>
      <div class="workspace-data-list">
        <div class="workspace-data-pill"><span>站 A → crossing</span><strong>${workspaceEscape(workspaceFormatMeters(path?.distance_from_station_a_meters))}</strong></div>
        <div class="workspace-data-pill"><span>crossing → 站 B</span><strong>${workspaceEscape(workspaceFormatMeters(path?.distance_to_station_b_meters))}</strong></div>
        <div class="workspace-data-pill"><span>crossing snap 偏移</span><strong>${workspaceEscape(workspaceFormatMeters(path?.crossing_snap_distance_meters))}</strong></div>
        <div class="workspace-data-pill"><span>前後站 snap 偏移</span><strong>${workspaceEscape(`${workspaceFormatMeters(path?.station_a_snap_distance_meters)} / ${workspaceFormatMeters(path?.station_b_snap_distance_meters)}`)}</strong></div>
      </div>
      <p class="workspace-note">${workspaceEscape(workspaceLabel(note, '未提供說明'))}</p>
      ${canToggleDiagnostics ? `<div class="workspace-card-actions"><button class="ghost-button inline-button compact" type="button" data-action="toggle-osm-diagnostics">${workspaceEscape(toggleLabel)}</button></div>` : ''}
    </section>
  `;
}

function workspaceRenderProjectionCard(projection, selectedSource) {
  const available = Boolean(projection?.available);
  const isSelected = selectedSource === 'geometry_projection';
  const headingLabel = isSelected ? '站點直線投影' : '直線投影候選';
  const note = isSelected
    ? projection?.note
    : `${projection?.note || ''} 這條藍色幾何只是把平交道投影到兩站座標連線上的結果，不代表真實沿軌路徑。`;
  return `
    <section class="workspace-card is-projection">
      <div class="workspace-card-head">
        <div>
          <small class="workspace-method-tag${isSelected ? '' : ' is-muted'}"><i class="workspace-inline-dot is-projection"></i>${headingLabel}</small>
          <h3>${available ? workspaceFormatRatio(projection?.value) : workspacePathStatusLabel(projection?.reason)}</h3>
        </div>
        <div class="workspace-ratio-caption">${available ? `${isSelected ? '目前採用' : '幾何 fallback'} · ${workspaceFormatMeters(projection?.offset_meters)}` : '無投影點'}</div>
      </div>
      <div class="workspace-badge${available ? '' : ' is-alert'}">
        <div>
          <strong>${available ? (isSelected ? '目前採用的地圖幾何' : '只是候選 fallback') : '只能當 fallback'}</strong>
          <small>${workspaceEscape(workspaceLabel(note, '未提供說明'))}</small>
        </div>
        <div class="workspace-ratio-caption">crossing 到投影點偏移</div>
      </div>
    </section>
  `;
}

function workspaceRenderOverview() {
  workspaceState.layers.overview.clearLayers();

  workspaceState.filteredCrossings.forEach((feature) => {
    const latLng = workspaceLatLng(feature);
    if (!latLng) return;
    const isActive = feature.id === workspaceState.selectedCrossingId;
    const marker = L.circleMarker(latLng, {
      pane: 'workspaceOverviewPane',
      radius: isActive ? 7 : 4,
      color: isActive ? '#bf5137' : '#ff7b5b',
      weight: isActive ? 3 : 1,
      fillColor: isActive ? '#bf5137' : '#ff9f85',
      fillOpacity: isActive ? 0.95 : 0.58,
    });
    marker.on('click', () => workspaceSelectCrossing(feature.id));
    marker.bindTooltip(workspaceLabel(feature.properties?.name, feature.id), { direction: 'top', opacity: 0.9 });
    marker.addTo(workspaceState.layers.overview);
  });
}

function workspaceRenderStationOverview() {
  workspaceState.layers.stations.clearLayers();

  workspaceState.stations.forEach((station) => {
    const latLng = workspacePointToLatLng(station?.position);
    if (!latLng) return;

    L.circleMarker(latLng, {
      pane: 'workspaceStationPane',
      radius: 3.5,
      color: '#355c84',
      weight: 1,
      fillColor: '#d7eefb',
      fillOpacity: 0.72,
    })
      .bindTooltip(`車站 · ${workspaceLabel(station?.name, station?.station_id || '未提供')}`, {
        direction: 'top',
        opacity: 0.88,
      })
      .addTo(workspaceState.layers.stations);
  });
}

function workspaceRenderFocusGeometry() {
  workspaceState.layers.focus.clearLayers();

  const explanation = workspaceState.selectedExplanation;
  if (!explanation) return;
  const selectedSource = workspaceSelectedSource(explanation);
  const pathAssessment = workspaceOsmPathAssessment(explanation);
  const drawProjection = workspaceShouldDrawProjection(explanation);
  const drawOsmDiagnostics = workspaceShouldDrawOsmDiagnostics(explanation);
  const drawSelectedOsmPath = workspaceCanDrawSelectedOsmPath(explanation);
  const hideSuspiciousCrossing = workspaceShouldHideSuspiciousCrossing(explanation);

  const focusBounds = [];
  const crossingLatLng = workspacePointToLatLng(explanation.crossing?.geometry);
  if (crossingLatLng && !hideSuspiciousCrossing) {
    focusBounds.push(crossingLatLng);
    L.circleMarker(crossingLatLng, {
      pane: 'workspaceFocusPane',
      radius: 9,
      color: '#bf5137',
      weight: 3,
      fillColor: '#ff7b5b',
      fillOpacity: 0.96,
    }).addTo(workspaceState.layers.focus);
  }

  [
    explanation.stations?.station_a,
    explanation.stations?.station_b,
  ].forEach((station, index) => {
    const latLng = workspacePointToLatLng(station?.position);
    if (!latLng) return;
    focusBounds.push(latLng);
    L.circleMarker(latLng, {
      pane: 'workspaceFocusPane',
      radius: 7,
      color: index === 0 ? '#9b6712' : '#1f446a',
      weight: 2,
      fillColor: index === 0 ? '#ffd36a' : '#90d7ff',
      fillOpacity: 0.95,
    })
      .bindTooltip(`${index === 0 ? '前站' : '後站'} · ${workspaceLabel(station?.label, '未提供')}`, { direction: 'top', opacity: 0.92 })
      .addTo(workspaceState.layers.focus);
  });

  const projection = explanation.ratios?.geometry_projection;
  if (drawProjection) {
    const stationLine = workspacePathToLatLngs(projection?.station_line);
    if (stationLine.length >= 2) {
      stationLine.forEach((point) => focusBounds.push(point));
      L.polyline(stationLine, {
        pane: 'workspaceFocusPane',
        color: '#1f446a',
        weight: 4,
        opacity: 0.6,
        dashArray: '10 10',
      }).addTo(workspaceState.layers.focus);
    }

    const projectionLine = workspacePathToLatLngs(projection?.crossing_to_projection_line);
    if (projectionLine.length >= 2) {
      projectionLine.forEach((point) => focusBounds.push(point));
      L.polyline(projectionLine, {
        pane: 'workspaceFocusPane',
        color: '#1f446a',
        weight: 3,
        opacity: 0.78,
        dashArray: '4 10',
      }).addTo(workspaceState.layers.focus);
    }

    const projectedPoint = workspacePointToLatLng(projection?.projected_point);
    if (projectedPoint) {
      focusBounds.push(projectedPoint);
      L.circleMarker(projectedPoint, {
        pane: 'workspaceFocusPane',
        radius: 6,
        color: '#1f446a',
        weight: 2,
        fillColor: '#ffffff',
        fillOpacity: 0.95,
      })
        .bindTooltip('直線投影點', { direction: 'top', opacity: 0.92 })
        .addTo(workspaceState.layers.focus);
    }
  }

  const path = explanation.ratios?.osm_path;
  if (drawSelectedOsmPath || drawOsmDiagnostics) {
    [path?.station_a_path, path?.station_b_path].forEach((segment, index) => {
      const latLngs = workspacePathToLatLngs(segment);
      if (latLngs.length < 2) return;
      latLngs.forEach((point) => focusBounds.push(point));
      L.polyline(latLngs, {
        pane: 'workspaceFocusPane',
        color: index === 0 ? '#0e7f72' : '#14a38c',
        weight: 6,
        opacity: drawSelectedOsmPath && !drawOsmDiagnostics ? 0.9 : 0.6,
        dashArray: drawSelectedOsmPath && !drawOsmDiagnostics ? undefined : '16 10',
        lineCap: 'round',
        lineJoin: 'round',
      }).addTo(workspaceState.layers.focus);
    });

    if (drawOsmDiagnostics) {
      [
        path?.crossing_snap,
        path?.station_a_snap,
        path?.station_b_snap,
      ].forEach((snap, index) => {
        const latLng = workspacePointToLatLng(snap);
        if (!latLng) return;
        focusBounds.push(latLng);
        L.circleMarker(latLng, {
          pane: 'workspaceFocusPane',
          radius: index === 0 ? 6 : 5,
          color: '#5a3fe0',
          weight: 2,
          fillColor: '#7f66ff',
          fillOpacity: pathAssessment.suspicious ? 0.7 : 0.78,
        })
          .bindTooltip(workspaceSnapRoleLabel(index), {
            direction: 'top',
            opacity: 0.92,
          })
          .addTo(workspaceState.layers.focus);
      });
    }
  }

  if (focusBounds.length) {
    ratioMap.fitBounds(L.latLngBounds(focusBounds), { padding: [42, 42], maxZoom: 15 });
  }
}

function workspaceApplyFilter() {
  const query = workspaceElements.searchInput.value.trim().toLowerCase().replace(/\s+/g, '');
  workspaceState.filteredCrossings = workspaceState.crossings.filter((feature) => feature.searchText.includes(query));
  workspaceRenderList();
  workspaceRenderOverview();
}

async function workspaceSelectCrossing(crossingId) {
  if (!crossingId || workspaceState.selectedCrossingId === crossingId) return;

  workspaceState.selectedCrossingId = crossingId;
  workspaceState.showOsmDiagnostics = false;
  workspaceUpdateQueryString(crossingId);
  workspaceRenderList();
  workspaceRenderOverview();
  workspaceState.selectedExplanation = null;
  workspaceRenderSummary();

  const requestToken = ++workspaceState.requestToken;
  try {
    const explanation = await workspaceApi(`/api/crossings/${encodeURIComponent(crossingId)}/ratio-explanation`);
    if (requestToken !== workspaceState.requestToken) return;
    workspaceState.selectedExplanation = explanation;
    workspaceRenderSummary();
    workspaceRenderFocusGeometry();
  } catch (error) {
    if (requestToken !== workspaceState.requestToken) return;
    workspaceState.selectedExplanation = {
      crossing: { name: crossingId },
      stations: {},
      ratios: {
        selected: { note: error instanceof Error ? error.message : '載入失敗' },
        official_route_mileage: {},
        osm_path: { reason: 'load_failed', note: error instanceof Error ? error.message : '載入失敗' },
        geometry_projection: { reason: 'load_failed', note: error instanceof Error ? error.message : '載入失敗' },
      },
    };
    workspaceRenderSummary();
    workspaceRenderFocusGeometry();
  }
}

async function workspaceLoad() {
  workspaceRenderSummary();
  const [crossingsPayload, stationsPayload] = await Promise.all([
    workspaceApi('/api/crossings?mapped_only=true&limit=5000'),
    workspaceApi('/api/crossings/stations?limit=5000').catch(() => ({ features: [] })),
  ]);
  workspaceState.stations = stationsPayload.features || [];
  workspaceRenderStationOverview();
  workspaceState.crossings = (crossingsPayload.features || [])
    .map((feature) => ({
      ...feature,
      searchText: workspaceSearchText(feature),
    }))
    .sort((featureA, featureB) => {
      const countyA = workspaceLabel(featureA.properties?.county, '');
      const countyB = workspaceLabel(featureB.properties?.county, '');
      if (countyA !== countyB) return countyA.localeCompare(countyB, 'zh-Hant');
      return workspaceLabel(featureA.properties?.name, '').localeCompare(workspaceLabel(featureB.properties?.name, ''), 'zh-Hant');
    });
  workspaceApplyFilter();

  const preferredCrossing = new URL(window.location.href).searchParams.get('crossing');
  const initialCrossing = workspaceState.crossings.find((feature) => feature.id === preferredCrossing)?.id || workspaceState.crossings[0]?.id;
  if (initialCrossing) {
    await workspaceSelectCrossing(initialCrossing);
  }
}

workspaceElements.searchInput.addEventListener('input', () => {
  workspaceApplyFilter();
});

workspaceElements.crossingList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-crossing-id]');
  if (!button) return;
  workspaceSelectCrossing(button.dataset.crossingId || '');
});

workspaceElements.diagnosticCard.addEventListener('click', (event) => {
  const button = event.target.closest('[data-action="toggle-osm-diagnostics"]');
  if (!button || !workspaceState.selectedExplanation) return;
  workspaceState.showOsmDiagnostics = !workspaceState.showOsmDiagnostics;
  workspaceRenderSummary();
  workspaceRenderFocusGeometry();
});

workspaceLoad().catch((error) => {
  workspaceElements.count.textContent = '載入失敗';
  workspaceElements.crossingList.innerHTML = `
    <div class="workspace-empty">
      <p>${workspaceEscape(error instanceof Error ? error.message : '無法載入 crossing 資料')}</p>
    </div>
  `;
});