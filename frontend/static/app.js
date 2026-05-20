const map = L.map('map', {
  zoomControl: false,
}).setView([23.7, 121.0], 7);

L.control.zoom({ position: 'bottomright' }).addTo(map);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors',
}).addTo(map);

const state = {
  allFeatures: [],
  markerLayer: L.layerGroup().addTo(map),
  selectedCounty: '',
};

const countySelect = document.getElementById('countySelect');
const statusEl = document.getElementById('status');
const detailPanel = document.getElementById('detailPanel');
const reloadButton = document.getElementById('reloadButton');

function setStatus(message) {
  statusEl.textContent = message;
}

function confidenceColor(confidence) {
  if (confidence === 'high') return '#d1495b';
  if (confidence === 'medium') return '#edae49';
  return '#5b8e7d';
}

function renderMarkers(features) {
  state.markerLayer.clearLayers();
  if (!features.length) {
    setStatus('目前沒有符合條件且可定位的平交道。');
    return;
  }

  const bounds = [];
  features.forEach((feature) => {
    if (!feature.geometry || !feature.geometry.coordinates) return;
    const [lon, lat] = feature.geometry.coordinates;
    const properties = feature.properties || {};
    const marker = L.circleMarker([lat, lon], {
      radius: 7,
      weight: 2,
      color: '#102542',
      fillColor: confidenceColor(properties.geolocation_confidence),
      fillOpacity: 0.85,
    });
    marker.on('click', () => loadCrossingDetail(feature.id));
    marker.bindTooltip(`${properties.name} (${properties.county || '未知'})`);
    marker.addTo(state.markerLayer);
    bounds.push([lat, lon]);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
  }
  setStatus(`已載入 ${features.length} 個可定位平交道。`);
}

function renderCountyOptions(counties) {
  const current = countySelect.value;
  countySelect.innerHTML = '<option value="">全部</option>';
  counties.forEach((county) => {
    const option = document.createElement('option');
    option.value = county;
    option.textContent = county;
    countySelect.appendChild(option);
  });
  countySelect.value = current;
}

async function loadCrossings() {
  setStatus('正在載入平交道資料…');
  const params = new URLSearchParams();
  if (state.selectedCounty) params.set('county', state.selectedCounty);
  const response = await fetch(`/api/crossings?${params.toString()}`);
  const payload = await response.json();
  state.allFeatures = payload.features || [];
  renderCountyOptions(payload.counties || []);
  renderMarkers(state.allFeatures);
}

function formatPrediction(prediction) {
  const eta = new Date(prediction.eta).toLocaleTimeString('zh-TW', {
    hour: '2-digit',
    minute: '2-digit',
  });
  const badge = prediction.warning ? '<span class="badge warn">提醒中</span>' : '<span class="badge">觀察中</span>';
  return `
    <li class="prediction-item">
      <div class="prediction-head">
        <strong>車次 ${prediction.train_no}</strong>
        ${badge}
      </div>
      <p>ETA ${eta}，資料信心 ${prediction.confidence}，延誤 ${prediction.delay_minutes} 分。</p>
      <p>${prediction.reason}</p>
    </li>
  `;
}

async function loadCrossingDetail(crossingId) {
  detailPanel.innerHTML = '<h2>平交道資訊</h2><p class="placeholder">正在載入…</p>';
  const [crossingRes, predictionRes] = await Promise.all([
    fetch(`/api/crossings/${crossingId}`),
    fetch(`/api/predictions/${crossingId}`),
  ]);
  const crossing = await crossingRes.json();
  const prediction = await predictionRes.json();
  const props = crossing.properties || {};
  const predictions = prediction.predictions || [];
  detailPanel.innerHTML = `
    <h2>${props.name}</h2>
    <dl class="meta-grid">
      <div><dt>路線</dt><dd>${props.line || '未知'}</dd></div>
      <div><dt>公里標</dt><dd>${props.km_marker || '未知'}</dd></div>
      <div><dt>站間</dt><dd>${props.station_pair_text || '未知'}</dd></div>
      <div><dt>縣市</dt><dd>${props.county || '未知'}</dd></div>
      <div><dt>定位信心</dt><dd>${props.geolocation_confidence || 'low'}</dd></div>
      <div><dt>匹配來源</dt><dd>${props.match_method || '未匹配'}</dd></div>
    </dl>
    <h3>即將通過列車</h3>
    ${predictions.length ? `<ul class="prediction-list">${predictions.map(formatPrediction).join('')}</ul>` : '<p class="placeholder">目前沒有落在查詢視窗內的候選列車。</p>'}
  `;
}

countySelect.addEventListener('change', async (event) => {
  state.selectedCounty = event.target.value;
  await loadCrossings();
});

reloadButton.addEventListener('click', async () => {
  await loadCrossings();
});

loadCrossings().catch((error) => {
  console.error(error);
  setStatus(`載入失敗：${error.message}`);
});
