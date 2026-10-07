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
    volume: 0.82,
    play: false,
    shuffle: false,
    repeat: 'off',
    liked: {},
    loading: true
  };

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
      cover: raw.cover || ''
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
        if (!state.index || !getTracks()[state.index]) {
          state.index = 0;
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
      { key: 'library', label: 'Library' },
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
          <h1>Listen in <span>neon</span> mode.</h1>
          <p>Pure streaming energy, reduced to the essentials. Just the music and the player.</p>
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
            <div class="eyebrow accent">Featured</div>
            <h2>Fresh from the queue</h2>
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
    var tracks = getTracks();
    return `
      <section class="panel">
        <div class="section-top">
          <div>
            <div class="eyebrow accent">Library</div>
            <h2>All tracks</h2>
          </div>
        </div>
        <div class="track-list large">
          ${tracks.map(function(track, idx){
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
          ${state.page === 'home' ? renderHome() : state.page === 'library' ? renderLibrary() : renderAbout()}
        </main>
        ${renderMiniPlayer()}
        ${renderPlayer()}
      </div>
    `;

    if (window.EQ && window.EQ.mount) {
      var panel = document.getElementById('eqPanel');
      if (panel) {
        window.EQ.mount(panel);
      }
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
    if (audio) {
      if (window.EQ && window.EQ.init) {
        window.EQ.init(audio);
      }
      audio.src = track.file;
      audio.load();
      audio.volume = state.volume;
      if (autoplay !== false) {
        audio.play().catch(function(){});
        state.play = true;
      }
    }
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
      audio.play().catch(function(){});
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
    render();
  }

  function openPlayer(){
    state.playerOpen = true;
    render();
  }

  function closePlayer(){
    state.playerOpen = false;
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

    if (action === 'shuffle') {
      state.shuffle = !state.shuffle;
      setToast(state.shuffle ? 'Shuffle on' : 'Shuffle off');
      render();
      return;
    }

    if (action === 'repeat') {
      var order = ['off', 'all', 'one'];
      var currentIndex = order.indexOf(state.repeat);
      state.repeat = order[(currentIndex + 1) % order.length];
      setToast('Repeat: ' + state.repeat);
      render();
      return;
    }
  });

  document.addEventListener('input', function(event){
    var target = event.target;
    if (!target || target.getAttribute('data-action') !== 'seek') return;
    seekFromRange(target.value);
  });

  if (audio) {
    audio.volume = state.volume;
    audio.addEventListener('timeupdate', function(){
      if (!audio.duration) return;
      render();
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
      if (state.repeat === 'one') {
        audio.currentTime = 0;
        audio.play();
        return;
      }
      nextTrack();
    });
  }

  (function init(){
    setVolume(state.volume);
    loadManifest();
    render();
  })();
})();
