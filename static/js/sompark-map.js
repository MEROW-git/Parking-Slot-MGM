/**
 * SomPark Phnom Penh - Google Maps Demo Integration
 * --------------------------------------------------------------------------
 * Features:
 * - Displays live parking locations and real-time availability across Phnom Penh.
 * - Color-coded markers based on vacancy: Green (Available), Amber (Limited), Red (Full).
 * - Rich InfoWindow with direct "Reserve Spot (កក់)" preserving the booking flow (/book/?zone=<slug>).
 * - Resilient fallback handling: gm_authFailure hook, script onerror, and 5s watchdog timeout.
 * - Demo key isolation: never accesses or exposes backend keys.
 */

(function () {
  'use strict';

  var mapInitialized = false;
  var fallbackTriggered = false;

  // Global error hook called by Google Maps API if authentication fails (e.g. demo key restrictions)
  window.gm_authFailure = function () {
    console.warn('[SomPark Maps Demo] Google Maps authentication failed or key restricted. Switching to fallback directory.');
    triggerFallback('Google Maps Demo authentication failed or domain restricted. Displaying live parking directory below.');
  };

  // Called if the Google Maps script fails to download (network error, ad blocker, etc.)
  window.somparkMapScriptError = function () {
    console.warn('[SomPark Maps Demo] Google Maps script failed to load.');
    triggerFallback('Google Maps could not be loaded. Displaying live parking directory below.');
  };

  // Explicit fallback trigger callable manually or on watchdog timeout
  window.initSomParkMapFallback = function (customMessage) {
    triggerFallback(customMessage || 'Displaying live parking directory below.');
  };

  function triggerFallback(message) {
    if (fallbackTriggered) return;
    fallbackTriggered = true;

    // Homepage multi-zone map fallback
    var mainCanvas = document.getElementById('sompark-map-canvas');
    var mainFallback = document.getElementById('sompark-map-fallback');
    if (mainCanvas && mainFallback) {
      mainCanvas.style.display = 'none';
      mainFallback.style.display = 'block';
      if (message) {
        var noticeEl = mainFallback.querySelector('.sp-fallback-message');
        if (noticeEl) noticeEl.textContent = message;
      }
    }

    // Individual zone detail page fallback
    var singleCanvas = document.getElementById('sompark-single-map-canvas');
    var singleFallback = document.getElementById('sompark-single-map-fallback');
    if (singleCanvas && singleFallback) {
      singleCanvas.style.display = 'none';
      singleFallback.style.display = 'block';
    }
  }

  // 5-second watchdog timer: if Google Maps hasn't initialized within 5 seconds, switch to fallback
  setTimeout(function () {
    if (!mapInitialized && !fallbackTriggered) {
      console.info('[SomPark Maps Demo] 5-second watchdog timeout reached. Checking map status.');
      if (typeof google === 'undefined' || !google.maps) {
        triggerFallback('Map loading timed out. Displaying live parking directory below.');
      }
    }
  }, 5000);

  // SVG Marker Pin Generator based on status
  function createPinIcon(status) {
    var fillColor = '#10b981'; // green for available
    if (status === 'limited') {
      fillColor = '#f59e0b'; // amber
    } else if (status === 'full') {
      fillColor = '#ef4444'; // red
    }

    var svg = [
      '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="42" viewBox="0 0 32 42">',
      '<path fill="' + fillColor + '" stroke="#ffffff" stroke-width="2" d="M16 0C7.163 0 0 7.163 0 16c0 11.5 16 26 16 26s16-14.5 16-26C32 7.163 24.837 0 16 0z"/>',
      '<circle cx="16" cy="15" r="7" fill="#ffffff"/>',
      '<text x="16" y="19" font-family="sans-serif" font-size="11" font-weight="900" fill="' + fillColor + '" text-anchor="middle">P</text>',
      '</svg>'
    ].join('');

    return {
      url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg),
      scaledSize: new google.maps.Size(32, 42),
      anchor: new google.maps.Point(16, 42)
    };
  }

  // Main Google Maps Initialization Callback
  window.initSomParkMap = function () {
    if (typeof google === 'undefined' || !google.maps) {
      triggerFallback('Google Maps library unavailable.');
      return;
    }

    mapInitialized = true;

    // 1. Check for Homepage Multi-Zone Map
    var mainMapCanvas = document.getElementById('sompark-map-canvas');
    if (mainMapCanvas) {
      var rawZonesData = mainMapCanvas.getAttribute('data-zones');
      var zones = [];
      try {
        zones = rawZonesData ? JSON.parse(rawZonesData) : [];
      } catch (e) {
        console.error('[SomPark Maps] Failed to parse zones JSON:', e);
      }

      if (zones.length > 0) {
        initMultiZoneMap(mainMapCanvas, zones);
      } else {
        triggerFallback('No parking zones available to display.');
      }
    }

    // 2. Check for Single Zone Detail Map
    var singleMapCanvas = document.getElementById('sompark-single-map-canvas');
    if (singleMapCanvas) {
      var rawZoneData = singleMapCanvas.getAttribute('data-zone');
      var singleZone = null;
      try {
        singleZone = rawZoneData ? JSON.parse(rawZoneData) : null;
      } catch (e) {
        console.error('[SomPark Maps] Failed to parse single zone JSON:', e);
      }

      if (singleZone) {
        initSingleZoneMap(singleMapCanvas, singleZone);
      }
    }
  };

  function initMultiZoneMap(container, zones) {
    // Center on Phnom Penh
    var defaultCenter = { lat: 11.5621, lng: 104.9160 };

    var map = new google.maps.Map(container, {
      center: defaultCenter,
      zoom: 13,
      mapTypeId: google.maps.MapTypeId.ROADMAP,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: true,
      zoomControl: true,
      styles: [
        {
          featureType: 'poi',
          elementType: 'labels',
          stylers: [{ visibility: 'off' }]
        }
      ]
    });

    var bounds = new google.maps.LatLngBounds();
    var infoWindow = new google.maps.InfoWindow({
      maxWidth: 320
    });

    zones.forEach(function (zone) {
      var pos = { lat: parseFloat(zone.lat), lng: parseFloat(zone.lng) };
      bounds.extend(pos);

      var marker = new google.maps.Marker({
        position: pos,
        map: map,
        title: zone.name,
        icon: createPinIcon(zone.availability_status)
      });

      var statusBadgeColor = zone.availability_status === 'available'
        ? '#10b981'
        : zone.availability_status === 'limited'
        ? '#f59e0b'
        : '#ef4444';

      var statusText = zone.availability_status === 'full'
        ? 'Currently Full (ពេញ)'
        : zone.vacant_slots + ' / ' + zone.num_of_slots + ' Spaces Free';

      var infoContent = [
        '<div class="sp-infowindow">',
        '  <div class="sp-iw-header">',
        '    <div class="sp-iw-tags">',
        '      <span class="sp-iw-district">' + (zone.district || 'Phnom Penh') + '</span>',
        '      <span class="sp-iw-hours">' + (zone.operating_hours || '24/7 Access') + '</span>',
        '    </div>',
        '  </div>',
        '  <h4 class="sp-iw-title">' + zone.name + '</h4>',
        zone.khmer_name ? '  <div class="sp-iw-khmer">' + zone.khmer_name + '</div>' : '',
        '  <p class="sp-iw-address">',
        '    <svg class="sp-iw-pin-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>',
        '    <span>' + zone.address + '</span>',
        '  </p>',
        '  <div class="sp-iw-meta-bar">',
        '    <div class="sp-iw-avail sp-avail-' + zone.availability_status + '">',
        '      <span class="sp-iw-dot"></span>',
        '      <span class="sp-iw-avail-text">' + statusText + '</span>',
        '    </div>',
        '    <div class="sp-iw-price">',
        '      <span class="sp-iw-amount">' + zone.price_formatted + '</span>',
        '    </div>',
        '  </div>',
        '  <div class="sp-iw-actions">',
        zone.availability_status !== 'full'
          ? '    <a href="' + zone.book_url + '" class="sp-iw-btn sp-iw-btn-book"><span>Reserve Spot (កក់)</span> <span class="sp-iw-arrow">&rarr;</span></a>'
          : '    <span class="sp-iw-btn sp-iw-btn-disabled">Zone Full (ពេញ)</span>',
        '    <a href="' + zone.detail_url + '" class="sp-iw-btn sp-iw-btn-details">Details</a>',
        '  </div>',
        '</div>'
      ].join('');

      marker.addListener('click', function () {
        infoWindow.setContent(infoContent);
        infoWindow.open(map, marker);
      });
    });

    if (zones.length > 1) {
      map.fitBounds(bounds, { top: 40, bottom: 40, left: 40, right: 40 });
    }
  }

  function initSingleZoneMap(container, zone) {
    var pos = { lat: parseFloat(zone.lat), lng: parseFloat(zone.lng) };

    var map = new google.maps.Map(container, {
      center: pos,
      zoom: 15,
      mapTypeId: google.maps.MapTypeId.ROADMAP,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: true,
      zoomControl: true
    });

    var marker = new google.maps.Marker({
      position: pos,
      map: map,
      title: zone.name,
      icon: createPinIcon(zone.availability_status)
    });

    var singleInfoContent = [
      '<div class="sp-infowindow" style="width: 270px; padding: 14px 16px;">',
      '  <div class="sp-iw-header">',
      '    <div class="sp-iw-tags">',
      '      <span class="sp-iw-district">' + (zone.district || 'Phnom Penh') + '</span>',
      '    </div>',
      '  </div>',
      '  <h4 class="sp-iw-title">' + zone.name + '</h4>',
      zone.khmer_name ? '  <div class="sp-iw-khmer">' + zone.khmer_name + '</div>' : '',
      '  <p class="sp-iw-address">',
      '    <svg class="sp-iw-pin-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>',
      '    <span>' + zone.address + '</span>',
      '  </p>',
      '  <div class="sp-iw-meta-bar" style="margin-bottom:0;">',
      '    <div class="sp-iw-avail sp-avail-' + zone.availability_status + '">',
      '      <span class="sp-iw-dot"></span>',
      '      <span class="sp-iw-avail-text">' + zone.vacant_slots + ' / ' + zone.num_of_slots + ' Vacant</span>',
      '    </div>',
      '    <div class="sp-iw-price">',
      '      <span class="sp-iw-amount">' + zone.price_formatted + '</span>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join('');

    var infoWindow = new google.maps.InfoWindow({
      content: singleInfoContent
    });

    marker.addListener('click', function () {
      infoWindow.open(map, marker);
    });
  }
})();
