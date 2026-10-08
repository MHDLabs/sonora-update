(function(){
  'use strict';

  var app = document.getElementById('app');
  var audio = document.getElementById('audio');
  var toastEl = document.getElementById('toast');
  var state = {
    page: 'home',
    tracks: [],
    index: 0,
    playerOpen: false,
    overlay: '',
    volume: 0.82,
    play: false,
    shuffle: false,
    repeat: 'off',
    liked: {},
    playlists: [],
    history: {},
    progress: {},
    search: '',
    sleepAt: 0,
    sleepTimer: null,
    sleepMode: '',
    lyricsOpen: false,
    loading: true
  };

  var STORAGE_KEY = 'sonora-player-v2';

  function readSavedState(){
    try {
      var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      if (!saved || typeof saved !== 'object') return;
      state.liked = saved.liked && typeof saved.liked === 'object' ? saved.liked : {};
      state.playlists = Array.isArray(saved.playlists) ? saved.playlists : [];
      state.history = saved.history && typeof saved.history === 'object' ? saved.history : {};
      state.progress = saved.progress && typeof saved.progress === 'object' ? saved.progress : {};
      state.volume = typeof saved.volume === 'number' ? clamp(saved.volume, 0, 1) : state.volume;
      state.shuffle = !!saved.shuffle;
      state.repeat = ['off', 'all', 'one'].indexOf(saved.repeat) >= 0 ? saved.repeat : 'off';
      state.sleepAt = Number(saved.sleepAt) || 0;
      state.sleepMode = saved.sleepMode || '';
      state.savedTrackId = saved.trackId || '';
      state.savedTime = Number(saved.currentTime) || 0;
      if (window.EQ && saved.eq) window.EQ.restore(saved.eq);
    } catch (e) {}
  }

  function saveState(){
    try {
      var track = currentTrack();
      if (track && audio && Number.isFinite(audio.currentTime) && audio.currentTime > 0) {
        state.progress[track.id] = { time: audio.currentTime, duration: Number(audio.duration) || 0, updatedAt: Date.now() };
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        liked: state.liked,
        playlists: state.playlists,
        history: state.history,
        progress: state.progress,
        volume: state.volume,
        shuffle: state.shuffle,
        repeat: state.repeat,
        trackId: track && track.id,
        currentTime: audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0,
        sleepAt: state.sleepAt,
        sleepMode: state.sleepMode,
        eq: window.EQ && window.EQ.serialize ? window.EQ.serialize() : null
      }));
    } catch (e) {}
  }

  function defaultTracks(){
    return [{
      id: 'placeholder-track',
      file: '',
      title: 'No tracks yet',
      artist: 'Add music via manifest',
      album: 'Ready for import',
      year: 2026,
      genre: 'Production',
      duration: '00:00',
      cover: ''
    }];
  }

  function clamp(value, min, max){
    return Math.min(Math.max(value, min), max);
  }

  function fmtTime(totalSeconds){
    var safe = Math.max(0, Number(totalSeconds) || 0);
    var minutes = Math.floor(safe / 60);
    var seconds = Math.floor(safe % 60);
    return minutes + ':' + String(seconds).padStart(2, '0');
  }

  function escapeHtml(value){
    return String(value || '').replace(/[&<>"']/g, function(ch){
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function setToast(message){
    if (!message) return;
    toastEl.textContent = message;
    toastEl.classList.add('show');
    clearTimeout(setToast.timer);
    setToast.timer = setTimeout(function(){
      toastEl.classList.remove('show');
    }, 1800);
  }

  function normalizeTrack(raw, index){
    var title = raw.title || raw.name || 'Untitled Track';
    return {
      id: String(raw.id || raw.file || title + '-' + index),
      file: raw.file || '',
      title: title,
      artist: raw.artist || 'Independent',
      album: raw.album || 'Single',
      year: raw.year || 2026,
      genre: raw.genre || 'Electronic',
      duration: raw.duration || '03:30',
      cover: raw.cover || '',
      lyrics: raw.lyrics || raw.subtitles || '',
      subtitles: Array.isArray(raw.subtitles) ? raw.subtitles : [],
      playlist: raw.playlist || ''
    };
  }

  function getTracks(){
    return state.tracks && state.tracks.length ? state.tracks : defaultTracks();
  }

  function loadManifest(){
    fetch('audio/manifest.json', { cache: 'no-store' })
      .then(function(response){
        if (!response.ok) throw new Error('Bad manifest');
        return response.json();
      })
      .then(function(data){
        var list = [];
        if (data && Array.isArray(data.tracks)) {
          list = data.tracks;
        } else if (data && Array.isArray(data)) {
          list = data;
        }
        state.tracks = list.length ? list.map(normalizeTrack) : defaultTracks();
        var savedIndex = state.tracks.findIndex(function(track){ return track.id === state.savedTrackId; });
        state.index = savedIndex >= 0 ? savedIndex : 0;
        if (savedIndex >= 0 && audio && state.tracks[savedIndex].file) {
          audio.src = state.tracks[savedIndex].file;
          audio.volume = state.volume;
          audio.load();
        }
        state.loading = false;
        render();
      })
      .catch(function(){
        state.tracks = defaultTracks();
        state.index = 0;
        state.loading = false;
        render();
      });
  }

  function currentTrack(){
    var tracks = getTracks();
    if (!tracks.length) return null;
    return tracks[state.index] || tracks[0];
  }

  function renderNav(){
    return [
      { key: 'home', label: 'Home' },
      { key: 'library', label: 'All music' },
      { key: 'favorites', label: 'Favorites' },
      { key: 'recent', label: 'Recently played' },
      { key: 'continue', label: 'Continue listening' },
      { key: 'playlists', label: 'Playlists' },
      { key: 'about', label: 'About' }
    ].map(function(item){
      var active = state.page === item.key ? 'active' : '';
      return '<button class="nav-link ' + active + '" data-action="nav" data-page="' + item.key + '">' + item.label + '</button>';
    }).join('');
  }

  function renderHome(){
    var tracks = getTracks();
    var featured = tracks.slice(0, 6);
    return `
      <section class="hero-shell">
        <div class="hero-copy">
          <div class="eyebrow">SONORA / GitHub Pages</div>
          <h1>Make room for <span>music.</span></h1>
          <p>A warm, quiet place for your collection, favorite tracks, playlists and listening history.</p>
          <div class="cta-row">
            <button class="primary" data-action="play-index" data-index="0">Play now</button>
            <button class="secondary" data-action="open-player">Open player</button>
          </div>
        </div>
        <div class="hero-art">
          <div class="hero-glow"></div>
          <div class="hero-card">
            <span class="mint">Now playing</span>
            <strong>${escapeHtml((currentTrack() || tracks[0]).title)}</strong>
            <small>${escapeHtml((currentTrack() || tracks[0]).artist)} · ${escapeHtml((currentTrack() || tracks[0]).album)}</small>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-top">
          <div>
            <div class="eyebrow accent">Your collection</div>
            <h2>Recently added</h2>
          </div>
          <button class="txt-btn" data-action="nav" data-page="library">Open library</button>
        </div>
        <div class="track-list">
          ${featured.map(function(track, idx){
            var isCurrent = state.index === idx;
            return `
              <button class="track-row ${isCurrent ? 'active' : ''}" data-action="play-index" data-index="${idx}">
                <span class="badge">${idx + 1}</span>
                <span class="meta">
                  <strong>${escapeHtml(track.title)}</strong>
                  <small>${escapeHtml(track.artist)} · ${escapeHtml(track.album)}</small>
                </span>
                <span class="genre">${escapeHtml(track.genre)}</span>
                <span class="time">${escapeHtml(track.duration)}</span>
              </button>
            `;
          }).join('')}
        </div>
      </section>
    `;
  }

  function renderLibrary(){
    var tracks = getTracks().filter(function(track){
      var query = String(state.search || '').trim().toLowerCase();
      return !query || [track.title, track.artist, track.album, track.genre].join(' ').toLowerCase().indexOf(query) >= 0;
    });
    return `
      <section class="panel">
        <div class="section-top">
          <div>
            <div class="eyebrow accent">Library</div>
            <h2>All tracks</h2>
          </div>
          <label class="search-wrap"><span aria-hidden="true">⌕</span><input type="search" data-action="search" value="${escapeHtml(state.search)}" placeholder="Search title, artist, album" aria-label="Search music"></label>
        </div>
        ${renderTrackList(tracks, true)}
      </section>
    `;
  }

  function renderTrackList(tracks, actions){
    if (!tracks.length) return '<p class="empty-state">No music here yet. Add tracks through the repository manifest.</p>';
    return '<div class="track-list large">' + tracks.map(function(track){
      var idx = getTracks().findIndex(function(item){ return item.id === track.id; });
      var liked = !!state.liked[track.id];
      return '<div class="track-entry"><button class="track-row ' + (state.index === idx ? 'active' : '') + '" data-action="play-index" data-index="' + idx + '"><span class="badge">' + (idx + 1) + '</span><span class="meta"><strong>' + escapeHtml(track.title) + '</strong><small>' + escapeHtml(track.artist) + ' · ' + escapeHtml(track.album) + '</small></span><span class="genre">' + escapeHtml(track.genre) + '</span><span class="time">' + escapeHtml(track.duration) + '</span></button>' + (actions ? '<button class="row-action ' + (liked ? 'liked' : '') + '" data-action="like-track" data-track="' + escapeHtml(track.id) + '" aria-label="' + (liked ? 'Remove from favorites' : 'Add to favorites') + '">' + (liked ? '♥' : '♡') + '</button><button class="row-action" data-action="add-to-playlist" data-track="' + escapeHtml(track.id) + '" aria-label="Add to playlist">＋</button>' : '') + '</div>';
    }).join('') + '</div>';
  }

  function renderCollection(page){
    var tracks = getTracks();
    var title = 'Your collection';
    if (page === 'favorites') {
      title = 'Favorites';
      tracks = tracks.filter(function(track){ return !!state.liked[track.id]; });
    } else if (page === 'recent') {
      title = 'Recently played';
      tracks = tracks.filter(function(track){ return !!state.history[track.id]; }).sort(function(a, b){ return state.history[b.id] - state.history[a.id]; });
    } else if (page === 'continue') {
      title = 'Continue listening';
      tracks = tracks.filter(function(track){
        var progress = state.progress[track.id];
        var duration = Number(progress && progress.duration) || 0;
        return progress && progress.time > 5 && (!duration || progress.time < duration - 10);
      }).sort(function(a, b){ return (state.progress[b.id].updatedAt || 0) - (state.progress[a.id].updatedAt || 0); });
    }
    return '<section class="panel"><div class="section-top"><div><div class="eyebrow accent">Your library</div><h2>' + title + '</h2></div></div>' + renderTrackList(tracks, true) + '</section>';
  }

  function renderPlaylists(){
    return '<section class="panel"><div class="section-top"><div><div class="eyebrow accent">Made for your listening</div><h2>Playlists</h2></div><button class="primary" data-action="create-playlist">＋ New playlist</button></div>' + (state.playlists.length ? '<div class="playlist-grid">' + state.playlists.map(function(list, index){ return '<button class="playlist-card" data-action="open-playlist" data-index="' + index + '"><span class="playlist-art">♫</span><strong>' + escapeHtml(list.name) + '</strong><small>' + list.trackIds.length + ' tracks</small></button>'; }).join('') + '</div>' : '<p class="empty-state">Create a playlist and add tracks from All music.</p>') + '</section>';
  }

  function renderPlaylist(index){
    var list = state.playlists[index];
    if (!list) return renderPlaylists();
    var tracks = getTracks().filter(function(track){ return list.trackIds.indexOf(track.id) >= 0; });
    return '<section class="panel"><div class="section-top"><div><div class="eyebrow accent"><button class="txt-btn" data-action="nav" data-page="playlists">Playlists</button></div><h2>' + escapeHtml(list.name) + '</h2></div><button class="secondary" data-action="delete-playlist" data-index="' + index + '">Delete playlist</button></div>' + renderTrackList(tracks, false) + '</section>';
  }

  function renderLyrics(){
    var track = currentTrack();
    var lines = track && track.subtitles || [];
    if (!lines.length && track && typeof track.lyrics === 'string') lines = track.lyrics.split(/\r?\n/).filter(Boolean);
    var activeIndex = -1;
    if (audio && audio.currentTime && lines.length) {
      lines.forEach(function(line, index){
        var start = typeof line === 'object' ? Number(line.start != null ? line.start : line.time) : NaN;
        if (!Number.isFinite(start) && typeof line === 'string') {
          var match = line.match(/^\s*\[(\d{1,2}):(\d{2}(?:\.\d+)?)\]\s*/);
          if (match) start = Number(match[1]) * 60 + Number(match[2]);
        }
        if (Number.isFinite(start) && start <= audio.currentTime) activeIndex = index;
      });
    }
    return '<div class="lyrics-overlay"><section class="lyrics-panel"><div class="section-top"><div><div class="eyebrow accent">Words & captions</div><h2>Lyrics / subtitles</h2></div><button class="icon-btn" data-action="lyrics-close" aria-label="Close lyrics">✕</button></div><p class="lyrics-track">' + escapeHtml(track ? track.title + ' · ' + track.artist : '') + '</p>' + (lines.length ? '<div class="lyrics-lines">' + lines.map(function(line, index){ var text = typeof line === 'string' ? line.replace(/^\s*\[\d{1,2}:\d{2}(?:\.\d+)?\]\s*/, '') : line.text || ''; return '<p class="' + (index === activeIndex ? 'current' : '') + '">' + escapeHtml(text) + '</p>'; }).join('') + '</div>' : '<p class="empty-state">No lyrics or subtitle cues are included for this track. Add a “lyrics” string or timed “subtitles” array in audio/manifest.json.</p>') + '</section></div>';
  }

  function renderAbout(){
    return `
      <section class="panel prose">
        <div class="eyebrow accent">About</div>
        <h2>Built for simple, clean listening.</h2>
        <p>SONORA is a static music player designed for GitHub Pages. Music lives in the repository and the site stays fully automatic: add a track to the manifest, commit, and it appears in the player.</p>
        <p>Everything extraneous has been removed. The app keeps only the essentials: discovery, library, playback, and queue-based listening.</p>
      </section>
    `;
  }

  function renderMiniPlayer(){
    var current = currentTrack() || getTracks()[0];
    if (!current) return '';
    return `
      <div class="mini-player ${state.playerOpen ? 'open' : ''}">
        <div class="mini-progress"><span style="width:${audio && !isNaN(audio.duration) && audio.duration ? (audio.currentTime / audio.duration * 100) + '%' : '0%'}"></span></div>
        <div class="mini-body">
          <button class="mini-art" data-action="open-player">
            <img src="${escapeHtml(current.cover || 'https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?auto=format&fit=crop&w=400&q=80')}" alt="${escapeHtml(current.title)} cover">
          </button>
          <button class="mini-copy" data-action="open-player">
            <strong>${escapeHtml(current.title)}</strong>
            <small>${escapeHtml(current.artist)}</small>
          </button>
          <div class="mini-controls">
            <button class="icon-btn" data-action="prev" aria-label="Previous">⏮</button>
            <button class="icon-btn primary" data-action="toggle-play" aria-label="Play or pause">${state.play ? '❚❚' : '▶'}</button>
            <button class="icon-btn" data-action="next" aria-label="Next">⏭</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderPlayer(){
    var current = currentTrack() || getTracks()[0];
    var progressPct = audio && audio.duration ? (audio.currentTime / audio.duration * 100) : 0;
    return `
      <div class="player-shell ${state.playerOpen ? 'open' : ''}">
        <div class="player-backdrop"></div>
        <div class="player-panel">
          <div class="player-head">
            <button class="icon-btn" data-action="close-player" aria-label="Close player">✕</button>
            <span class="eyebrow accent">NOW PLAYING</span>
            <button class="icon-btn" data-action="toggle-like" aria-label="Save to library">${state.liked[current.id] ? '♥' : '♡'}</button>
          </div>

          <div class="player-art-wrap">
            <img src="${escapeHtml(current.cover || 'https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?auto=format&fit=crop&w=900&q=80')}" alt="${escapeHtml(current.title)} cover" class="player-art">
          </div>

          <div class="player-meta">
            <h3>${escapeHtml(current.title)}</h3>
            <p>${escapeHtml(current.artist)} · ${escapeHtml(current.album)}</p>
          </div>

          <div class="player-progress">
            <input type="range" min="0" max="100" value="${Math.max(0, Math.min(100, progressPct))}" data-action="seek" aria-label="Seek track">
            <div class="times"><span>${fmtTime(audio ? audio.currentTime : 0)}</span><span>${escapeHtml(current.duration)}</span></div>
          </div>

          <div class="player-controls">
            <button class="icon-btn" data-action="shuffle" aria-label="Shuffle">⇄</button>
            <button class="icon-btn" data-action="prev" aria-label="Previous">⏮</button>
            <button class="play-button" data-action="toggle-play">${state.play ? '❚❚' : '▶'}</button>
            <button class="icon-btn" data-action="next" aria-label="Next">⏭</button>
            <button class="icon-btn" data-action="repeat" aria-label="Repeat">↻</button>
          </div>

          <div class="player-tools">
            <button class="tool-btn" data-action="sleep-open">Sleep timer</button>
            <button class="tool-btn" data-action="lyrics-toggle">Lyrics</button>
            <button class="tool-btn" data-action="eq-toggle">Equalizer</button>
          </div>
          <div id="sleepPanel" class="sleep-panel" ${state.overlay === 'sleep' ? '' : 'hidden'}>
            <strong>Sleep timer</strong>
            <button class="tool-btn" data-action="sleep-minutes" data-minutes="15">15 min</button>
            <button class="tool-btn" data-action="sleep-minutes" data-minutes="30">30 min</button>
            <button class="tool-btn" data-action="sleep-minutes" data-minutes="60">60 min</button>
            <button class="tool-btn" data-action="sleep-end">At track end</button>
            <button class="tool-btn" data-action="sleep-cancel">Cancel</button>
            <span class="sleep-status">${state.sleepAt ? 'Timer active' : ''}</span>
          </div>

          <div id="eqPanel" hidden></div>
        </div>
      </div>
    `;
  }

  function render(){
    if (!app) return;
    app.innerHTML = `
      <div class="shell">
        <header class="topbar">
          <div class="brand">
            <span class="brand-mark"></span>
            <span>SONORA</span>
          </div>
          <nav class="nav">${renderNav()}</nav>
        </header>
        <main class="page-content">
          ${state.page === 'home' ? renderHome() : state.page === 'library' ? renderLibrary() : state.page === 'favorites' || state.page === 'recent' || state.page === 'continue' ? renderCollection(state.page) : state.page === 'playlists' ? renderPlaylists() : state.page === 'playlist' ? renderPlaylist(state.playlistIndex) : renderAbout()}
        </main>
        ${renderMiniPlayer()}
        ${renderPlayer()}
        ${state.lyricsOpen ? renderLyrics() : ''}
      </div>
    `;

    if (window.EQ && window.EQ.mount) {
      var panel = document.getElementById('eqPanel');
      if (panel) {
        window.EQ.mount(panel);
      }
    }
    if (window.EQ && window.EQ.toggle) {
      var eqPanel = document.getElementById('eqPanel');
      if (eqPanel && window.EQ.isOpen()) eqPanel.hidden = false;
    }
  }

  function setVolume(nextVolume){
    state.volume = clamp(nextVolume, 0, 1);
    if (audio) {
      audio.volume = state.volume;
    }
  }

  function playTrack(index, autoplay){
    var tracks = getTracks();
    if (!tracks.length) return;
    var safeIndex = ((index % tracks.length) + tracks.length) % tracks.length;
    state.index = safeIndex;
    var track = tracks[safeIndex];
    if (!track || !track.file) return;
    state.history[track.id] = Date.now();
    if (audio) {
      if (window.EQ && window.EQ.init) {
        window.EQ.init(audio);
      }
      audio.src = track.file;
      audio.load();
      audio.volume = state.volume;
      if (autoplay !== false) {
        var playAttempt = audio.play();
        if (playAttempt && playAttempt.catch) playAttempt.catch(function(){ state.play = false; render(); });
        state.play = true;
      }
    }
    saveState();
    render();
  }

  function togglePlay(){
    if (!audio) return;
    if (!audio.src) {
      playTrack(state.index, true);
      return;
    }
    if (state.play) {
      audio.pause();
      state.play = false;
    } else {
      if (window.EQ && window.EQ.resume) window.EQ.resume();
      var playAttempt = audio.play();
      if (playAttempt && playAttempt.catch) playAttempt.catch(function(){ state.play = false; render(); });
      state.play = true;
    }
    render();
  }

  function nextTrack(){
    var tracks = getTracks();
    if (!tracks.length) return;
    var nextIndex = state.shuffle ? Math.floor(Math.random() * tracks.length) : state.index + 1;
    if (state.repeat === 'one') {
      if (audio) audio.currentTime = 0;
      return;
    }
    playTrack(nextIndex % tracks.length, true);
  }

  function prevTrack(){
    var tracks = getTracks();
    if (!tracks.length) return;
    if (audio && audio.currentTime > 3) {
      audio.currentTime = 0;
      return;
    }
    playTrack((state.index - 1 + tracks.length) % tracks.length, true);
  }

  function toggleLike(){
    var track = currentTrack();
    if (!track) return;
    state.liked[track.id] = !state.liked[track.id];
    setToast(state.liked[track.id] ? 'Added to library' : 'Removed from library');
    saveState();
    render();
  }

  function likeTrack(trackId){
    if (!trackId) return;
    state.liked[trackId] = !state.liked[trackId];
    setToast(state.liked[trackId] ? 'Added to favorites' : 'Removed from favorites');
    saveState();
    render();
  }

  function createPlaylist(){
    var name = window.prompt('Name this playlist:');
    if (!name || !name.trim()) return;
    state.playlists.push({ id: 'playlist-' + Date.now(), name: name.trim().slice(0, 60), trackIds: [] });
    state.page = 'playlists';
    saveState();
    render();
  }

  function addToPlaylist(trackId){
    if (!state.playlists.length) {
      setToast('Create a playlist first');
      return;
    }
    var choices = state.playlists.map(function(list, index){ return (index + 1) + '. ' + list.name; }).join('\n');
    var selected = Number(window.prompt('Add to which playlist? Enter its number:\n' + choices));
    var list = state.playlists[selected - 1];
    if (!list) return;
    if (list.trackIds.indexOf(trackId) < 0) list.trackIds.push(trackId);
    saveState();
    setToast('Added to ' + list.name);
  }

  function setSleepTimer(minutes){
    state.sleepAt = Date.now() + minutes * 60000;
    state.sleepMode = 'timer';
    state.overlay = '';
    saveState();
    setToast('Sleep timer set for ' + minutes + ' minutes');
    render();
  }

  function cancelSleepTimer(){
    state.sleepAt = 0;
    state.sleepMode = '';
    saveState();
    setToast('Sleep timer cancelled');
    render();
  }

  function checkSleepTimer(){
    if (state.sleepMode === 'timer' && state.sleepAt && Date.now() >= state.sleepAt) {
      state.sleepAt = 0;
      state.sleepMode = '';
      if (audio) audio.pause();
      setToast('Sleep timer ended playback');
      saveState();
    }
  }

  function openPlayer(){
    state.playerOpen = true;
    render();
  }

  function closePlayer(){
    state.playerOpen = false;
    state.overlay = '';
    render();
  }

  function seekFromRange(value){
    if (!audio || !audio.duration) return;
    var time = (Number(value) / 100) * audio.duration;
    audio.currentTime = time;
  }

  document.addEventListener('click', function(event){
    var actionTarget = event.target.closest('[data-action]');
    if (!actionTarget) return;
    var action = actionTarget.getAttribute('data-action');
    var index = Number(actionTarget.getAttribute('data-index'));

    if (action === 'nav') {
      state.page = actionTarget.getAttribute('data-page') || 'home';
      state.search = '';
      render();
      return;
    }

    if (action === 'play-index') {
      playTrack(index, true);
      return;
    }

    if (action === 'toggle-play') {
      togglePlay();
      return;
    }

    if (action === 'next') {
      nextTrack();
      return;
    }

    if (action === 'prev') {
      prevTrack();
      return;
    }

    if (action === 'open-player') {
      openPlayer();
      return;
    }

    if (action === 'close-player') {
      closePlayer();
      return;
    }

    if (action === 'toggle-like') {
      toggleLike();
      return;
    }

    if (action === 'like-track') { likeTrack(actionTarget.getAttribute('data-track')); return; }
    if (action === 'create-playlist') { createPlaylist(); return; }
    if (action === 'open-playlist') { state.playlistIndex = index; state.page = 'playlist'; render(); return; }
    if (action === 'delete-playlist') {
      if (window.confirm('Delete this playlist?')) state.playlists.splice(index, 1);
      state.page = 'playlists'; saveState(); render(); return;
    }
    if (action === 'add-to-playlist') { addToPlaylist(actionTarget.getAttribute('data-track')); return; }
    if (action === 'lyrics-toggle') { state.lyricsOpen = !state.lyricsOpen; render(); return; }
    if (action === 'lyrics-close') { state.lyricsOpen = false; render(); return; }
    if (action === 'sleep-open') { state.overlay = state.overlay === 'sleep' ? '' : 'sleep'; render(); return; }
    if (action === 'sleep-minutes') { setSleepTimer(Number(actionTarget.getAttribute('data-minutes'))); return; }
    if (action === 'sleep-end') { state.sleepAt = 0; state.sleepMode = 'end'; state.overlay = ''; saveState(); setToast('Playback will stop at track end'); render(); return; }
    if (action === 'sleep-cancel') { cancelSleepTimer(); return; }
    if (action === 'eq-toggle') { if (window.EQ && window.EQ.toggle) window.EQ.toggle(); return; }

    if (action === 'shuffle') {
      state.shuffle = !state.shuffle;
      saveState();
      setToast(state.shuffle ? 'Shuffle on' : 'Shuffle off');
      render();
      return;
    }

    if (action === 'repeat') {
      var order = ['off', 'all', 'one'];
      var currentIndex = order.indexOf(state.repeat);
      state.repeat = order[(currentIndex + 1) % order.length];
      saveState();
      setToast('Repeat: ' + state.repeat);
      render();
      return;
    }
  });

  document.addEventListener('click', function(event){
    if (event.target.closest('.player-backdrop')) {
      closePlayer();
      return;
    }
    if (state.overlay === 'sleep' && !event.target.closest('#sleepPanel') && !event.target.closest('[data-action="sleep-open"]')) {
      state.overlay = '';
      var panel = document.getElementById('sleepPanel');
      if (panel) panel.hidden = true;
    }
    if (state.lyricsOpen && event.target.classList && event.target.classList.contains('lyrics-overlay')) {
      state.lyricsOpen = false;
      render();
    }
  });

  document.addEventListener('keydown', function(event){
    if (event.key === 'Escape') {
      if (state.playerOpen) closePlayer();
      if (state.lyricsOpen) { state.lyricsOpen = false; render(); }
      state.overlay = '';
    }
  });

  document.addEventListener('input', function(event){
    var target = event.target;
    if (target && target.matches('[data-action="search"]')) {
      var start = target.selectionStart;
      state.search = target.value;
      render();
      var replacement = document.querySelector('[data-action="search"]');
      if (replacement) { replacement.focus(); replacement.setSelectionRange(start, start); }
    }
  });

  document.addEventListener('input', function(event){
    var target = event.target;
    if (!target || target.getAttribute('data-action') !== 'seek') return;
    seekFromRange(target.value);
  });

  if (audio) {
    audio.volume = state.volume;
    audio.addEventListener('loadedmetadata', function(){
      var track = currentTrack();
      var progress = track && state.progress[track.id];
      var resumeTime = progress ? Number(progress.time) : (track && track.id === state.savedTrackId ? state.savedTime : 0);
      if (track && resumeTime > 0 && resumeTime < audio.duration - 2) {
        try { audio.currentTime = resumeTime; } catch (e) {}
        state.savedTime = 0;
      }
      render();
    });
    audio.addEventListener('timeupdate', function(){
      if (!audio.duration) return;
      checkSleepTimer();
      if (Date.now() - (saveState.lastSaved || 0) > 5000) { saveState(); saveState.lastSaved = Date.now(); }
      var pct = audio.currentTime / audio.duration * 100;
      var miniProgress = document.querySelector('.mini-progress span');
      var seek = document.querySelector('[data-action="seek"]');
      var times = document.querySelector('.player-progress .times');
      if (miniProgress) miniProgress.style.width = pct + '%';
      if (seek && document.activeElement !== seek) seek.value = pct;
      if (times) times.innerHTML = '<span>' + fmtTime(audio.currentTime) + '</span><span>' + escapeHtml(fmtTime(audio.duration)) + '</span>';
      var lyrics = document.querySelectorAll('.lyrics-lines p');
      if (lyrics.length) {
        var cues = currentTrack().subtitles || [];
        if (!cues.length && typeof currentTrack().lyrics === 'string') cues = currentTrack().lyrics.split(/\r?\n/).filter(Boolean);
        var activeCue = -1;
        cues.forEach(function(cue, cueIndex){
          var start = typeof cue === 'object' ? Number(cue.start != null ? cue.start : cue.time) : NaN;
          if (!Number.isFinite(start) && typeof cue === 'string') {
            var match = cue.match(/^\s*\[(\d{1,2}):(\d{2}(?:\.\d+)?)\]\s*/);
            if (match) start = Number(match[1]) * 60 + Number(match[2]);
          }
          if (Number.isFinite(start) && start <= audio.currentTime) activeCue = cueIndex;
        });
        lyrics.forEach(function(line, lineIndex){ line.classList.toggle('current', lineIndex === activeCue); });
      }
    });
    audio.addEventListener('play', function(){
      state.play = true;
      render();
    });
    audio.addEventListener('pause', function(){
      state.play = false;
      render();
    });
    audio.addEventListener('ended', function(){
      var finishedTrack = currentTrack();
      if (finishedTrack) delete state.progress[finishedTrack.id];
      saveState();
      if (state.repeat === 'one') {
        audio.currentTime = 0;
        audio.play();
        return;
      }
      if (state.sleepMode === 'end') {
        state.sleepMode = '';
        state.sleepAt = 0;
        audio.pause();
        saveState();
        setToast('Sleep timer ended playback');
        return;
      }
      nextTrack();
    });
  }

  (function init(){
    readSavedState();
    setVolume(state.volume);
    if (window.EQ && window.EQ.onChange !== undefined) window.EQ.onChange = saveState;
    loadManifest();
    render();
    window.setInterval(checkSleepTimer, 15000);
  })();
})();
