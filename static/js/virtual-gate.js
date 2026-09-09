/**
 * SomPark Virtual Parking Gate Terminal — Controller
 * Handles optical QR camera scanning, USB barcode scanner input,
 * absolute server-issued permit countdown with tab-resume synchronization,
 * authorization invalidation, and asynchronous passage animation choreography.
 */
(() => {
  'use strict';

  const toggleBtn = document.getElementById('vg-camera-toggle');
  const toggleBtnText = document.getElementById('vg-camera-btn-text');
  const cameraBox = document.getElementById('vg-camera-box');
  const video = document.getElementById('vg-video');
  const statusEl = document.getElementById('vg-camera-status');
  const codeInput = document.getElementById('id_code');
  const form = document.getElementById('gate-machine-form');

  const permitSecondsEl = document.getElementById('vg-timer-seconds');
  const permitTimerBanner = document.getElementById('vg-permit-timer');
  const passBtn = document.getElementById('vg-pass');
  const closeBtn = document.getElementById('vg-close');
  const sceneEl = document.getElementById('vg-scene-viewport');
  const statusBanner = document.getElementById('vg-gate-status-banner');
  const statusText = document.getElementById('vg-status-text');

  let stream = null;
  let scanning = false;
  let scanTimer = null;

  let countdownInterval = null;
  let permitExpiresAt = null;
  let isCrossing = false;

  // Stop camera tracks cleanly
  function stopCamera() {
    scanning = false;
    if (scanTimer) {
      clearTimeout(scanTimer);
      scanTimer = null;
    }
    if (stream) {
      stream.getTracks().forEach(track => {
        try { track.stop(); } catch (_) {}
      });
      stream = null;
    }
    if (video) {
      video.srcObject = null;
    }
    if (cameraBox) {
      cameraBox.hidden = true;
    }
    if (toggleBtnText) {
      toggleBtnText.textContent = 'Scan QR with camera';
    }
  }

  // Camera QR Scanning Handler
  if (toggleBtn && video && statusEl && codeInput) {
    toggleBtn.addEventListener('click', async () => {
      if (scanning) {
        stopCamera();
        statusEl.textContent = 'Camera stopped.';
        return;
      }

      if (!navigator.mediaDevices?.getUserMedia) {
        statusEl.textContent = 'Camera access is not supported by this browser. Enter the code manually or scan with a USB barcode reader.';
        return;
      }

      if (!window.BarcodeDetector) {
        statusEl.textContent = 'Native BarcodeDetector is unavailable in this browser. Please type the ticket code or scan with a USB barcode reader.';
        return;
      }

      toggleBtn.disabled = true;
      statusEl.textContent = 'Initializing camera...';

      try {
        const supported = await BarcodeDetector.getSupportedFormats();
        if (!supported.includes('qr_code')) {
          throw new Error('QR code format not supported');
        }

        const detector = new BarcodeDetector({ formats: ['qr_code'] });
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false
        });

        video.srcObject = stream;
        cameraBox.hidden = false;
        await video.play();

        scanning = true;
        if (toggleBtnText) toggleBtnText.textContent = 'Stop camera';
        statusEl.textContent = 'Camera active. Center the access QR inside the viewfinder.';

        async function detectLoop() {
          if (!scanning) return;
          try {
            const barcodes = await detector.detect(video);
            if (!scanning) return;

            if (barcodes && barcodes.length > 0) {
              const rawValue = barcodes[0].rawValue?.trim();
              if (rawValue) {
                codeInput.value = rawValue;
                // Dispatch input event to notify authorization invalidation listeners
                codeInput.dispatchEvent(new Event('input', { bubbles: true }));
                codeInput.dispatchEvent(new Event('change', { bubbles: true }));
                stopCamera();
                statusEl.textContent = `QR detected (${rawValue.substring(0, 16)}...). Click "Check ticket & open barrier" to verify.`;
                codeInput.focus();
                return;
              }
            }
            scanTimer = setTimeout(detectLoop, 200);
          } catch (err) {
            if (scanning) {
              scanTimer = setTimeout(detectLoop, 300);
            }
          }
        }

        detectLoop();
      } catch (err) {
        stopCamera();
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          statusEl.textContent = 'Camera permission denied. Please grant camera permission or enter the ticket code manually.';
        } else {
          statusEl.textContent = 'Unable to open camera. Please use the ticket code input or a USB scanner.';
        }
      } finally {
        toggleBtn.disabled = false;
      }
    });
  }

  // USB Barcode Scanner & Enter Key Handling:
  // Explicitly triggers #btn-check-open click rather than injecting hidden input and submitting form.
  if (codeInput && form) {
    codeInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const checkBtn = document.getElementById('btn-check-open');
        if (checkBtn) {
          checkBtn.click();
        }
      }
    });
  }

  // Helper: wait for CSS transition with safety timeout fallback
  function waitForTransition(element, expectedProp, maxMs) {
    return new Promise(resolve => {
      if (!element) {
        resolve();
        return;
      }
      let resolved = false;
      const timer = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          element.removeEventListener('transitionend', onEnd);
          resolve();
        }
      }, maxMs);

      function onEnd(e) {
        if (e.target === element && (!expectedProp || e.propertyName === expectedProp)) {
          if (!resolved) {
            resolved = true;
            clearTimeout(timer);
            element.removeEventListener('transitionend', onEnd);
            resolve();
          }
        }
      }

      element.addEventListener('transitionend', onEnd);
    });
  }

  // Stop permit countdown
  function stopPermitCountdown() {
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
  }

  // Expire permit handler
  function expirePermit() {
    stopPermitCountdown();
    if (permitTimerBanner) {
      permitTimerBanner.style.background = '#fef2f2';
      permitTimerBanner.style.borderColor = '#f87171';
      permitTimerBanner.style.color = '#991b1b';
      permitTimerBanner.innerHTML = '<strong>Gate authorization expired.</strong> Barrier auto-closed. Re-check ticket.';
    }
    if (passBtn) passBtn.disabled = true;
    if (sceneEl) sceneEl.classList.remove('is-open');
    if (statusBanner && statusText) {
      statusBanner.className = 'vg-status-indicator status-closed';
      statusText.textContent = 'BARRIER CLOSED — AUTHORIZATION EXPIRED';
    }
  }

  // Start permit countdown using absolute server timestamp if provided
  function startPermitCountdown() {
    stopPermitCountdown();
    if (!permitSecondsEl || !permitTimerBanner || !passBtn) return;

    const expiresAtAttr = permitTimerBanner.dataset.expiresAt;
    if (expiresAtAttr && parseInt(expiresAtAttr, 10)) {
      permitExpiresAt = parseInt(expiresAtAttr, 10);
    } else {
      permitExpiresAt = Math.floor(Date.now() / 1000) + 120;
    }

    function tick() {
      if (isCrossing) return; // Do not expire during active crossing playback
      const nowSec = Math.floor(Date.now() / 1000);
      const remaining = Math.max(0, permitExpiresAt - nowSec);
      permitSecondsEl.textContent = remaining;

      if (remaining <= 0) {
        expirePermit();
      }
    }

    tick();
    countdownInterval = setInterval(tick, 1000);
  }

  // Reconcile permit countdown on tab resume (visibility change)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && permitExpiresAt && countdownInterval && !isCrossing) {
      const nowSec = Math.floor(Date.now() / 1000);
      const remaining = Math.max(0, permitExpiresAt - nowSec);
      if (remaining <= 0) {
        expirePermit();
      } else if (permitSecondsEl) {
        permitSecondsEl.textContent = remaining;
      }
    }
  });

  // Invalidate authorization and clear obsolete timers upon input edits
  function invalidateAuthorization(reason) {
    stopPermitCountdown();
    if (passBtn) {
      passBtn.disabled = true;
      passBtn.title = 'Input modified. Re-check ticket to authorize barrier.';
    }
    if (sceneEl) {
      sceneEl.classList.remove('is-open');
    }
    if (permitTimerBanner) {
      permitTimerBanner.style.display = 'none';
    }
    if (statusBanner && statusText) {
      statusBanner.className = 'vg-status-indicator status-closed';
      statusText.textContent = reason || 'BARRIER CLOSED — TICKET RE-CHECK REQUIRED';
    }
  }

  document.querySelectorAll('#id_zone, #id_code').forEach(input => {
    input.addEventListener('input', () => {
      invalidateAuthorization('BARRIER CLOSED — INPUT MODIFIED');
    });
  });

  // Dynamic Direction Label & Immediate Scene Arrangement Reset
  document.querySelectorAll('.vg-direction-label input[type="radio"]').forEach(radio => {
    radio.addEventListener('change', () => {
      document.querySelectorAll('.vg-direction-label').forEach(label => {
        label.classList.remove('is-selected');
      });
      const parentLabel = radio.closest('.vg-direction-label');
      if (parentLabel) {
        parentLabel.classList.add('is-selected');
      }

      // Immediately switch scene direction attribute and reset visual arrangement
      if (sceneEl) {
        sceneEl.dataset.direction = radio.value;
        sceneEl.classList.remove('is-open', 'is-passed', 'is-moving');
      }

      invalidateAuthorization('BARRIER CLOSED — DIRECTION CHANGED');
    });
  });

  // Initialize countdown if gate is open on page load
  if (permitSecondsEl && permitTimerBanner && passBtn && !passBtn.disabled) {
    startPermitCountdown();
  }

  // =========================================================================
  // Passage Animation Controller (Asynchronous 7-Stage Sequence)
  // Idle → Opening → Waiting → Passage pending → Moving → Closing → Complete
  // =========================================================================
  if (passBtn && form) {
    passBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      if (isCrossing) return;

      const checkBtn = document.getElementById('btn-check-open');
      const zoneSelect = document.getElementById('id_zone');
      const modeRadios = document.querySelectorAll('input[name="mode"]');

      // 1. Passage pending: disable conflicting controls and cancel idle timer
      passBtn.disabled = true;
      if (closeBtn) closeBtn.disabled = true;
      if (checkBtn) checkBtn.disabled = true;
      if (codeInput) codeInput.disabled = true;
      if (zoneSelect) zoneSelect.disabled = true;
      modeRadios.forEach(r => r.disabled = true);

      stopPermitCountdown();

      if (statusText) statusText.textContent = 'CONFIRMING PASSAGE WITH SERVER...';

      const formData = new FormData(form);
      formData.set('action', 'pass');

      let result = null;
      try {
        const response = await fetch(form.action || window.location.href, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
          },
          body: formData
        });

        if (response.ok) {
          result = await response.json();
        } else {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.notice || `Server error (${response.status})`);
        }
      } catch (err) {
        // Ambiguous network failure: query server state before retrying or giving up
        const zoneVal = document.getElementById('id_zone')?.value;
        const codeVal = codeInput?.value?.trim();
        const modeVal = document.querySelector('input[name="mode"]:checked')?.value || 'entry';

        let reconciled = false;
        if (zoneVal && codeVal) {
          try {
            const checkUrl = `${window.location.pathname}?zone=${encodeURIComponent(zoneVal)}&code=${encodeURIComponent(codeVal)}&mode=${encodeURIComponent(modeVal)}`;
            const checkResp = await fetch(checkUrl, {
              headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
            });
            if (checkResp.ok) {
              const checkData = await checkResp.json();
              if ((modeVal === 'entry' && checkData.status === 'CHECKED_IN') ||
                  (modeVal === 'exit' && checkData.status === 'CHECKED_OUT')) {
                result = {
                  success: true,
                  passed: true,
                  notice: 'Vehicle passage reconciled with server status.',
                  status: checkData.status,
                  status_display: checkData.status_display
                };
                reconciled = true;
              }
            }
          } catch (_) {}
        }

        if (!reconciled) {
          // Rejection or failure: DO NOT animate passage
          passBtn.disabled = false;
          if (closeBtn) closeBtn.disabled = false;
          if (checkBtn) checkBtn.disabled = false;
          if (codeInput) codeInput.disabled = false;
          if (zoneSelect) zoneSelect.disabled = false;
          modeRadios.forEach(r => r.disabled = false);

          if (statusBanner && statusText) {
            statusBanner.className = 'vg-status-indicator status-closed';
            statusText.textContent = 'PASSAGE NOT RECORDED — RE-CHECK REQUIRED';
          }
          alert(err.message || 'Passage confirmation failed.');
          return;
        }
      }

      // 2. Server confirmed passage: execute visible crossing animation
      isCrossing = true;
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

      // Moving stage: keep arm raised while vehicle crosses lane
      if (statusText) statusText.textContent = 'VEHICLE CROSSING BARRIER...';
      if (sceneEl) sceneEl.classList.add('is-moving');

      const carTrack = document.getElementById('vg-car-track');
      const armEl = document.getElementById('vg-barrier-arm');

      if (!reducedMotion && carTrack) {
        await waitForTransition(carTrack, 'transform', 1500);
      } else {
        await new Promise(r => setTimeout(r, 20));
      }

      // 3. Closing stage: car cleared barrier arm; now lower the arm
      if (statusText) statusText.textContent = 'VEHICLE CLEARED — CLOSING BARRIER...';
      if (sceneEl) sceneEl.classList.remove('is-open');

      if (!reducedMotion && armEl) {
        await waitForTransition(armEl, 'transform', 900);
      } else {
        await new Promise(r => setTimeout(r, 20));
      }

      // 4. Complete stage: mark passed and show final status
      if (sceneEl) {
        sceneEl.classList.remove('is-moving');
        sceneEl.classList.add('is-passed');
      }

      if (statusBanner && statusText) {
        statusBanner.className = 'vg-status-indicator status-passed';
        statusText.textContent = 'VEHICLE PASSAGE CONFIRMED — BARRIER CLOSED';
      }

      // Hide pass action controls
      const passBox = document.getElementById('vg-pass-actions-box');
      if (passBox) passBox.style.display = 'none';

      // Update or create notice banner
      let noticeBox = document.querySelector('.vg-notice');
      if (!noticeBox && statusBanner && statusBanner.parentNode) {
        noticeBox = document.createElement('div');
        noticeBox.className = 'vg-notice is-success';
        statusBanner.parentNode.insertBefore(noticeBox, statusBanner.nextSibling);
      }
      if (noticeBox) {
        noticeBox.className = 'vg-notice is-success';
        noticeBox.textContent = result?.notice || 'Vehicle passage recorded. Barrier closed.';
      }

      // Update reservation telemetry status badge if present
      const statusBadge = document.querySelector('.vg-details-grid dd .vg-badge');
      if (statusBadge && result?.status_display) {
        statusBadge.className = result.status === 'CHECKED_IN' ? 'vg-badge badge-green' : 'vg-badge badge-muted';
        statusBadge.textContent = `${result.status} (${result.status_display})`;
      }

      // Re-enable form fields for next vehicle check
      if (checkBtn) checkBtn.disabled = false;
      if (codeInput) {
        codeInput.disabled = false;
        codeInput.value = '';
      }
      if (zoneSelect) zoneSelect.disabled = false;
      modeRadios.forEach(r => r.disabled = false);

      isCrossing = false;
    });
  }

  // Cleanup on page hide or navigate away
  window.addEventListener('pagehide', stopCamera);
  window.addEventListener('beforeunload', stopCamera);
})();
