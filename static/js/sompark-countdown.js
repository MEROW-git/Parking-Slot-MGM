/**
 * SomPark Real-time Countdown Timer
 * Handles arrival holds (3 hours) and payment checkout timeouts (15 minutes).
 */
(function() {
  'use strict';

  function initCountdowns() {
    var timerEls = document.querySelectorAll('[data-target]');
    if (!timerEls.length) return;

    function updateTimers() {
      var now = new Date().getTime();

      timerEls.forEach(function(el) {
        var targetAttr = el.getAttribute('data-target');
        if (!targetAttr) return;

        var targetTime = new Date(targetAttr).getTime();
        if (isNaN(targetTime)) return;

        var diff = targetTime - now;

        var parentArrivalBanner = el.closest('.sp-arrival-banner');
        var parentCountdownBox = el.closest('.sp-countdown-box');
        var parentExitBanner = el.closest('.sp-exit-banner');

        if (diff <= 0) {
          if (parentExitBanner || el.id === 'exit-timer') {
            el.textContent = 'Exit window expired (ផុតកំណត់ពេលចេញ)';
            if (parentExitBanner) {
              parentExitBanner.classList.add('sp-countdown-expired');
            }
          } else if (parentArrivalBanner || el.id === 'arrival-timer') {
            el.textContent = 'Arrival window expired (ផុតកំណត់ពេលមកដល់)';
            if (parentArrivalBanner) {
              parentArrivalBanner.classList.add('sp-countdown-expired');
            }
          } else {
            el.textContent = 'EXPIRED (ផុតកំណត់)';
            if (parentCountdownBox) {
              parentCountdownBox.classList.add('sp-countdown-expired');
            }
          }

          el.classList.add('sp-timer-expired');

          // Refresh authoritative reservation state from server once expired
          if (!el.dataset.reloaded) {
            el.dataset.reloaded = 'true';
            setTimeout(function() {
              window.location.reload();
            }, 2500);
          }
        } else {
          var totalSeconds = Math.floor(diff / 1000);
          var hours = Math.floor(totalSeconds / 3600);
          var minutes = Math.floor((totalSeconds % 3600) / 60);
          var seconds = totalSeconds % 60;

          var pad = function(n) { return n < 10 ? '0' + n : n; };

          // Consistent HH:MM:SS format with tabular numerals
          el.textContent = pad(hours) + ':' + pad(minutes) + ':' + pad(seconds);
        }
      });
    }

    updateTimers();
    setInterval(updateTimers, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCountdowns);
  } else {
    initCountdowns();
  }
})();
