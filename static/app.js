const $ = (id) => document.getElementById(id);
let sources = [], selected = null, filter = 'all', preview = null, poll = null, generation = 0;
let recordingState = null, recordingRequest = false, viewerState = 'stopped', folderRequest = false, recordingReachable = false;
const labels = {connecting: 'VERBINDEN', live: 'LIVE', buffering: 'BUFFEREN', error: 'GEEN SIGNAAL', stopped: 'GESTOPT'};
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 6000); }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {'Content-Type': 'application/json', ...options.headers} });
  if (response.status === 204) return;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'De verbinding met de app is onderbroken. Probeer opnieuw.');
  return data;
}
function renderSources() {
  const list = $('source-list'); list.replaceChildren();
  $('count').textContent = sources.filter(s => s.kind !== 'DEMO').length;
  const query = $('search').value.toLowerCase();
  const visible = sources.filter(s => (filter === 'all' || (filter === 'stream' ? ['RTSP','HTTP'].includes(s.kind) : s.kind === filter)) && `${s.name} ${s.address}`.toLowerCase().includes(query));
  for (const source of visible) {
    const button = document.createElement('button'); button.className = 'source' + (selected?.id === source.id ? ' selected' : '');
    button.setAttribute('aria-pressed', String(selected?.id === source.id));
    const icon = document.createElement('span'); icon.className = 'source-icon'; icon.textContent = source.kind === 'NDI' ? '◈' : source.kind === 'DEMO' ? '▧' : '▹';
    const copy = document.createElement('span'); copy.className = 'source-copy';
    const title = document.createElement('span'); title.className = 'source-title'; title.textContent = source.name;
    const sub = document.createElement('span'); sub.className = 'source-sub'; sub.textContent = source.origin;
    const badge = document.createElement('span'); badge.className = 'source-kind'; badge.textContent = source.kind;
    copy.append(title, sub); button.append(icon, copy, badge); button.addEventListener('click', () => connect(source)); list.append(button);
  }
  if (!visible.length) { const empty = document.createElement('p'); empty.className = 'empty-list'; empty.textContent = 'Geen bronnen gevonden. Voeg een adres toe of zoek opnieuw.'; list.append(empty); }
}
async function discover() {
  $('refresh').disabled = true; $('scan-note').textContent = 'Netwerkbronnen zoeken…';
  try {
    const data = await api('/api/sources'); sources = data.sources; renderSources();
    const count = sources.filter(s => s.origin.startsWith('Netwerk')).length;
    $('scan-note').textContent = count ? `${count} netwerkbron${count === 1 ? '' : 'nen'} gevonden` : 'Geen netwerkfeeds gevonden · voeg een adres toe';
    if (data.ndi_discovery_warning) $('scan-note').textContent = 'NDI-detectie vereist Avahi / D-Bus op Linux';
    $('capabilities').textContent = `NDI ${data.ndi ? 'beschikbaar' : 'niet beschikbaar'} · FFmpeg ${data.ffmpeg ? 'beschikbaar' : 'ontbreekt'} · mDNS ${data.mdns ? 'actief' : 'niet beschikbaar'}`;
    if (!data.ffmpeg) toast('FFmpeg ontbreekt. Installeer FFmpeg om RTSP- en HTTP-streams te bekijken.');
  } catch (error) { $('scan-note').textContent = 'Zoeken mislukt · probeer opnieuw'; toast(error.message); }
  finally { $('refresh').disabled = false; }
}
function showStatus(state, message) {
  viewerState = state;
  $('live-badge').textContent = labels[state] || 'STAND-BY'; $('live-badge').classList.toggle('live', state === 'live');
  $('state-text').textContent = message; $('state-dot').className = 'dot' + (state === 'live' ? '' : state === 'error' ? ' error' : ' muted');
  $('connection').hidden = state === 'live' || state === 'stopped';
  $('connection').classList.toggle('failed', state === 'error');
  $('connection').querySelector('h3').textContent = state === 'error' ? 'Geen beeld beschikbaar' : state === 'buffering' ? 'Wachten op beeld' : 'Verbinding maken';
  $('connection-message').textContent = message;
}
async function connect(source) {
  if (collectingClip()) { toast('Wacht tot de huidige opname klaar is voordat je van bron wisselt.'); return; }
  if (connect.busy) return;
  connect.busy = true;
  const token = ++generation;
  clearTimeout(poll); selected = source; preview = null; renderSources();
  $('video').removeAttribute('src'); $('video').hidden = true; $('placeholder').hidden = true;
  $('viewer-name').textContent = source.name; $('detail-type').textContent = source.kind; $('detail-address').textContent = source.address; $('detail-resolution').textContent = '—';
  $('stop').disabled = false; showStatus('connecting', 'Verbinding maken met de bron…');
  try {
    const data = await api('/api/preview', {method:'POST', body:JSON.stringify({source_id:source.id})});
    if (token !== generation) { await api(`/api/preview/${data.id}`, {method:'DELETE'}); return; }
    preview = data.id; $('video').src = `/api/preview/${preview}/video`;
    async function status() {
      if (token !== generation) return;
      try {
        const state = await api(`/api/preview/${data.id}`);
        if (token !== generation) return;
        showStatus(state.state, state.message);
        $('video').hidden = !['live','buffering'].includes(state.state);
        if (state.width) $('detail-resolution').textContent = `${state.width} × ${state.height}`;
        if (!['error','stopped'].includes(state.state)) poll = setTimeout(status, 700);
        else { $('video').removeAttribute('src'); $('stop').disabled = true; }
      } catch (error) { if (token === generation) { showStatus('error', error.message); $('video').removeAttribute('src'); } }
    }
    status();
  } catch (error) { if (token === generation) showStatus('error', error.message); }
  finally { connect.busy = false; }
}
$('stop').addEventListener('click', async () => {
  if (collectingClip()) { toast('Wacht tot de huidige opname klaar is.'); return; }
  ++generation; clearTimeout(poll); const id = preview; preview = null;
  $('video').removeAttribute('src'); $('video').hidden = true; $('placeholder').hidden = false;
  showStatus('stopped', 'Weergave gestopt'); $('stop').disabled = true;
  if (id) { try { await api(`/api/preview/${id}`, {method:'DELETE'}); } catch (error) { toast(error.message); } }
});
$('refresh').addEventListener('click', discover); $('search').addEventListener('input', renderSources);
for (const tab of document.querySelectorAll('[data-filter]')) tab.addEventListener('click', () => {
  filter = tab.dataset.filter;
  for (const t of document.querySelectorAll('[data-filter]')) { t.classList.toggle('active', t === tab); t.setAttribute('aria-pressed', String(t === tab)); }
  renderSources();
});
$('try-demo').addEventListener('click', () => { const demo = sources.find(s => s.kind === 'DEMO'); if (demo) connect(demo); else toast('Wacht tot de bronnen geladen zijn.'); });
$('fullscreen').addEventListener('click', async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await $('screen').requestFullscreen(); } catch { toast('Volledig scherm is niet beschikbaar in deze browser.'); } });
$('add').addEventListener('click', () => { $('form-error').textContent = ''; $('add-dialog').showModal(); $('source-url').focus(); });
for (const id of ['close-dialog', 'cancel-dialog']) $(id).addEventListener('click', () => $('add-dialog').close());
$('add-form').addEventListener('submit', async event => {
  event.preventDefault(); $('form-error').textContent = ''; $('submit-source').disabled = true;
  try {
    const data = await api('/api/sources', {method:'POST', body:JSON.stringify({name:$('source-name').value, url:$('source-url').value})});
    if (!sources.some(s => s.id === data.source.id)) sources.push(data.source);
    filter = 'all'; document.querySelector('[data-filter="all"]').click(); $('search').value = '';
    $('add-dialog').close(); $('add-form').reset(); renderSources(); connect(data.source);
  } catch (error) { $('form-error').textContent = error.message; }
  finally { $('submit-source').disabled = false; }
});
discover();


function collectingClip() { return recordingState?.active?.state === 'collecting'; }
function updateRecordingControls() {
  const active = recordingState?.active;
  const buffer = recordingState?.buffer;
  const ready = preview && buffer?.source_id === preview && buffer.ready && viewerState === 'live';
  $('record').disabled = !recordingReachable || !ready || !!active || recordingRequest || folderRequest;
  $('record').innerHTML = active?.state === 'collecting' ? '<span aria-hidden="true">●</span> Opname loopt…' : active?.state === 'saving' ? 'MP4 opslaan…' : '<span aria-hidden="true">●</span> Neem 10 seconden op';
  $('buffer-progress').value = buffer?.source_id === preview ? buffer.seconds : 0;
  let message = 'Selecteer een bron om de beeldbuffer te vullen.';
  if (active?.state === 'collecting') message = `Opname loopt · nog ${active.remaining} seconden. Laat de bron actief.`;
  else if (active?.state === 'saving') message = 'MP4 opslaan… Laat VTO open tot de clip klaar is.';
  else if (ready) message = 'Klaar · 3 seconden vóór de klik worden meegenomen.';
  else if (preview && viewerState === 'live') message = `Beeldbuffer vullen… ${Math.min(3, buffer?.seconds || 0).toFixed(1)} / 3 seconden`;
  else if (preview) message = 'Wachten op ononderbroken live beeld…';
  $('record-status').textContent = message;
  const nativePicker = typeof window.pywebview?.api?.choose_recording_folder === 'function';
  $('choose-folder').disabled = !nativePicker || !!active || folderRequest;
  $('choose-folder').title = nativePicker ? 'Kies waar clips worden bewaard' : 'Map kiezen is beschikbaar in de desktopapp';
  if (recordingState) $('recording-folder').textContent = recordingState.folder;
  $('stop').disabled = !preview || ['stopped', 'error'].includes(viewerState) || collectingClip();
}
function renderRecordings() {
  const list = $('recording-list'); list.replaceChildren();
  for (const clip of (recordingState?.items || []).slice(0, 4)) {
    const row = document.createElement('li');
    const name = document.createElement('span'); name.textContent = clip.filename;
    const state = document.createElement('span');
    state.className = clip.state === 'saved' ? 'clip-saved' : clip.state === 'error' ? 'clip-error' : 'clip-pending';
    state.textContent = clip.state === 'saved' ? '✓ Opgeslagen · 10 s' : clip.state === 'collecting' ? `${clip.remaining} s resterend` : clip.message;
    row.append(name, state); list.append(row);
  }
}
async function refreshRecordings() {
  try {
    recordingState = await api('/api/recordings');
    recordingReachable = true;
    renderRecordings(); updateRecordingControls();
  } catch {
    recordingReachable = false;
    $('record').disabled = true;
    $('record-status').textContent = 'Opnamestatus niet beschikbaar. Controleer de verbinding met VTO.';
  }
}
$('record').addEventListener('click', async () => {
  if (!preview || recordingRequest) return;
  recordingRequest = true; updateRecordingControls();
  try {
    await api(`/api/preview/${preview}/recordings`, {method:'POST'});
    await refreshRecordings();
  } catch (error) { toast(error.message); }
  finally { recordingRequest = false; updateRecordingControls(); }
});
$('choose-folder').addEventListener('click', async () => {
  folderRequest = true; updateRecordingControls();
  try {
    const result = await window.pywebview.api.choose_recording_folder();
    if (result?.error) toast(result.error);
    await refreshRecordings();
  } catch { toast('De mapkiezer kon niet worden geopend. Probeer opnieuw.'); }
  finally { folderRequest = false; updateRecordingControls(); }
});
$('open-folder').addEventListener('click', async () => {
  try { await api('/api/recordings/open-folder', {method:'POST'}); }
  catch (error) { toast(error.message); }
});
window.addEventListener('pywebviewready', updateRecordingControls);
async function pollRecordings() { await refreshRecordings(); setTimeout(pollRecordings, 500); }
pollRecordings();
