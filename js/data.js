(function(){
  'use strict';

  var IMG = {
    ORB: 'https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?auto=format&fit=crop&w=900&q=80',
    STUDIO: 'https://images.unsplash.com/photo-1516280440614-37939bbacd81?auto=format&fit=crop&w=900&q=80',
    NIGHT: 'https://images.unsplash.com/photo-1501386761578-eac5c94b800a?auto=format&fit=crop&w=900&q=80'
  };

  var ARTISTS = {
    default: {
      id: 'default',
      name: 'Independent',
      g: 'Electronic / Ambient',
      loc: 'Global',
      img: IMG.ORB,
      ac: '#00E5FF',
      bio: 'Curated for late-night listening and focused listening sessions.'
    }
  };

  var PLAYLISTS = [
    {
      id: 'night-drive',
      title: 'Night Drive',
      subtitle: 'Low light, soft motion, luminous synths.',
      subtitleShort: 'Late-night focus',
      curator: 'SONORA',
      img: IMG.NIGHT,
      tracks: []
    },
    {
      id: 'studio-focus',
      title: 'Studio Focus',
      subtitle: 'Clean, steady, detail-rich listening.',
      subtitleShort: 'Deep work',
      curator: 'SONORA',
      img: IMG.STUDIO,
      tracks: []
    }
  ];

  window.SONORA_DATA = { IMG: IMG, ARTISTS: ARTISTS, PLAYLISTS: PLAYLISTS };
  window.artist = function(id){ return ARTISTS[id] || ARTISTS.default; };
  window.playlist = function(id){
    for (var i = 0; i < PLAYLISTS.length; i++) {
      if (PLAYLISTS[i].id === id) return PLAYLISTS[i];
    }
    return PLAYLISTS[0];
  };
})();
