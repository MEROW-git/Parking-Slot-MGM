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

        if (diff <= 0) {
          el.textContent = 'EXPIRED (ផុតកំណត់)';
          el.classList.add('sp-timer-expired');
          var parentBox = el.closest('.sp-countdown-box');
          if (parentBox) {
            parentBox.classList.add('sp-countdown-expired');
          }
        } else {
          var hours = Math.floor(diff / (1000 * 60 * 60));
          var minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
          var seconds = Math.floor((diff % (1000 * 60)) / 1000);

          var pad = function(n) { return n < 10 ? '0' + n : n; };

          if (hours > 0) {
            el.textContent = pad(hours) + ':' + pad(minutes) + ':' + pad(seconds);
          } else {
            el.textContent = pad(minutes) + ':' + pad(seconds);
          }
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
