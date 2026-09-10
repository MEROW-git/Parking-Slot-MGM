/**
 * SomPark Virtual Parking Gate Terminal — Controller
 * Handles optical QR camera scanning, USB barcode scanner input,
 * absolute server-issued permit countdown with tab-resume synchronization,
 * authorization invalidation, asynchronous passage animation choreography,
 * HTML fallback animation, and visual-only replay.
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
  const zoneSelect = document.getElementById('id_zone') || document.querySelector('select[name="zone"]');
  const modeRadios = document.querySelectorAll('input[name="mode"]');
  const checkBtn = document.getElementById('btn-check-open');
  const reopenBtn = document.getElementById('btn-reopen-barrier');

  const permitSecondsEl = document.getElementById('vg-timer-seconds');
  const permitTimerBanner = document.getElementById('vg-permit-timer');
  const passBtn = document.getElementById('vg-pass');
  const passText = document.getElementById('vg-pass-text');
  const closeBtn = document.getElementById('vg-close');
  const sceneEl = document.getElementById('vg-scene-viewport');
  const statusBanner = document.getElementById('vg-gate-status-banner');
  const statusText = document.getElementById('vg-status-text');

  function updateGateDirection() {
    const selectedMode = document.querySelector('input[name="mode"]:checked')?.value || 'entry';
    if (sceneEl) {
      sceneEl.dataset.direction = selectedMode;
    }
    if (passText) {
      if (selectedMode === 'exit') {
        passText.innerHTML = 'Confirm Vehicle Departure &mdash; Close Barrier (ឡានចេញរួច)';
      } else {
        passText.innerHTML = 'Confirm Vehicle Entry &mdash; Close Barrier (ឡានចូលរួច)';
      }
    }
  }

  let stream = null;
  let scanning = false;
  let scanTimer = null;

  let countdownInterval = null;
  let permitExpiresAt = null;
  let isCrossing = false;
  let isPassageInFlight = false;

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
  function waitForTransition(element, expectedProp, maxMs, eventName = 'transitionend') {
    return new Promise(resolve => {
      if (!element) {
        resolve();
        return;
      }
      let resolved = false;
      const timer = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          element.removeEventListener(eventName, onEnd);
          resolve();
        }
      }, maxMs);

      function onEnd(e) {
        if (e.target === element && (!expectedProp || e.propertyName === expectedProp || e.animationName === expectedProp)) {
          if (!resolved) {
            resolved = true;
            clearTimeout(timer);
            element.removeEventListener(eventName, onEnd);
            resolve();
          }
        }
      }

      element.addEventListener(eventName, onEnd);
    });
  }

  function waitForArmOpening() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return Promise.resolve();
    return waitForTransition(document.getElementById('vg-barrier-arm'), 'vg-arm-open', 900, 'animationend');
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
    const replayBox = document.getElementById('vg-replay-box');
    if (replayBox) {
      replayBox.hidden = true;
    }
    const standardActions = document.getElementById('vg-standard-actions');
    if (standardActions) {
      standardActions.style.display = '';
      const checkBtn = document.getElementById('btn-check-open');
      if (checkBtn) checkBtn.disabled = false;
    }
    const exitFlow = document.getElementById('vg-exit-flow');
    if (exitFlow) exitFlow.style.display = 'none';
    const settlementBox = document.getElementById('vg-settlement-box');
    if (settlementBox) settlementBox.style.display = 'none';
    const reopenBox = document.getElementById('vg-reopen-box');
    if (reopenBox) reopenBox.style.display = 'none';
    const resetBox = document.getElementById('vg-reset-box');
    if (resetBox) resetBox.style.display = 'none';

    const anprEl = document.getElementById('vg-anpr-camera-unit');
    if (anprEl) {
      anprEl.classList.remove('is-scanning', 'is-detected', 'is-matched', 'is-mismatched');
      anprEl.dataset.state = 'ready';
    }
    const anprTextEl = document.getElementById('vg-anpr-hud-text');
    if (anprTextEl) {
      anprTextEl.textContent = 'CAMERA READY';
    }
    const checkBtnEl = document.getElementById('btn-check-open');
    if (checkBtnEl) {
      checkBtnEl.dataset.anprProcessed = '';
    }
  }

  document.querySelectorAll('#id_zone, #id_code, #simulate-plate-mismatch-cb, #custom-detected-plate-input').forEach(input => {
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
      if (checkBtn) checkBtn.dataset.anprProcessed = '';
      if (anprUnit) {
        anprUnit.classList.remove('is-scanning', 'is-detected', 'is-matched', 'is-mismatched');
        anprUnit.dataset.state = 'ready';
      }
      if (anprHudText) anprHudText.textContent = 'CAMERA READY';
    });
  });

  // Initialize countdown if gate is open on page load
  if (permitSecondsEl && permitTimerBanner && passBtn && !passBtn.disabled) {
    startPermitCountdown();
    if (sceneEl?.classList.contains('is-open')) {
      passBtn.disabled = true;
      if (statusText) statusText.textContent = 'BARRIER OPENING — PLEASE WAIT';
      waitForArmOpening().then(() => {
        // Input changes or permit expiry may have closed the gate while lifting.
        if (sceneEl.classList.contains('is-open') && Date.now() / 1000 < permitExpiresAt) {
          passBtn.disabled = false;
          if (statusText) statusText.textContent = 'BARRIER OPEN — WAITING FOR VEHICLE';
        }
      });
    }
  }

  // =========================================================================
  // Optical Roadside ANPR License Plate Camera Simulator Controller
  // CAMERA READY → SCANNING PLATE → PLATE DETECTED → (MATCH / MISMATCH)
  // =========================================================================
  const anprUnit = document.getElementById('vg-anpr-camera-unit');
  const anprHudText = document.getElementById('vg-anpr-hud-text');
  const carPlateEl = document.getElementById('vg-car-plate');
  const detectedPlateInput = document.getElementById('vg-detected-plate-input');
  const customPlateInput = document.getElementById('custom-detected-plate-input');
  const mismatchCb = document.getElementById('simulate-plate-mismatch-cb');

  function normalizePlate(p) {
    if (!p) return '';
    return String(p).replace(/[\s\-_.]+/g, '').toUpperCase();
  }

  // When the user unchecks "Simulate plate mismatch", clear any custom mismatch input so it reverts to the matching plate
  if (mismatchCb) {
    mismatchCb.addEventListener('change', () => {
      if (!mismatchCb.checked) {
        if (customPlateInput) customPlateInput.value = '';
        if (detectedPlateInput) detectedPlateInput.value = '';
        const expectedVal = document.getElementById('vg-telemetry-expected-plate')?.textContent?.trim() || '';
        if (carPlateEl) carPlateEl.textContent = expectedVal || 'CAM-OK';
        setAnprState('READY');
      } else {
        if (customPlateInput && !customPlateInput.value.trim()) {
          customPlateInput.value = '2X-9999';
        }
      }
    });
  }

  function setAnprState(state, detected, expected) {
    if (!anprUnit || !anprHudText) return;

    anprUnit.classList.remove('is-scanning', 'is-detected', 'is-matched', 'is-mismatched');
    anprUnit.dataset.state = state.toLowerCase();

    if (state === 'READY') {
      anprHudText.textContent = 'CAMERA READY';
    } else if (state === 'SCANNING') {
      anprUnit.classList.add('is-scanning');
      anprHudText.textContent = 'SCANNING';
    } else if (state === 'DETECTED') {
      anprUnit.classList.add('is-detected');
      anprHudText.textContent = 'PLATE FOUND';
      if (carPlateEl && detected) {
        carPlateEl.textContent = detected;
      }
    } else if (state === 'MATCH') {
      anprUnit.classList.add('is-matched');
      anprHudText.textContent = 'MATCHED';
      if (carPlateEl && detected) {
        carPlateEl.textContent = detected;
      }
    } else if (state === 'MISMATCH') {
      anprUnit.classList.add('is-mismatched');
      anprHudText.textContent = 'MISMATCH';
      if (carPlateEl && detected) {
        carPlateEl.textContent = detected;
      }
    }
  }

  // Initialize ANPR state on page load based on rendered server telemetry
  const plateStatusBadge = document.getElementById('vg-telemetry-plate-status');
  const detectedTelemetry = document.getElementById('vg-telemetry-detected-plate');
  const expectedTelemetry = document.getElementById('vg-telemetry-expected-plate');

  if (plateStatusBadge) {
    const text = plateStatusBadge.textContent || '';
    const detectedVal = detectedTelemetry?.textContent?.trim() || '';
    const expectedVal = expectedTelemetry?.textContent?.trim() || '';

    if (text.includes('PLATE MATCH')) {
      setAnprState('MATCH', detectedVal, expectedVal);
    } else if (text.includes('PLATE MISMATCH')) {
      setAnprState('MISMATCH', detectedVal, expectedVal);
    } else {
      setAnprState('READY');
    }
  }

  // Animate ANPR scan sequence on "Check ticket & open barrier" click
  if (checkBtn && form) {
    checkBtn.addEventListener('click', async (e) => {
      if (checkBtn.dataset.anprProcessed === 'true') {
        // Already animated, proceed with submit
        return;
      }

      e.preventDefault();

      let simulatedDetected = '';
      const isMismatch = mismatchCb?.checked;
      const customVal = customPlateInput?.value?.trim();
      const currentDetected = detectedPlateInput?.value?.trim();
      const expectedVal = document.getElementById('vg-telemetry-expected-plate')?.textContent?.trim() || '';

      if (isMismatch) {
        simulatedDetected = customVal || '2X-9999';
      } else {
        // Mismatch is OFF: clear stale mismatch overrides so we detect the real matching plate
        if (customPlateInput && customVal && normalizePlate(customVal) !== normalizePlate(expectedVal)) {
          customPlateInput.value = '';
        }
        if (detectedPlateInput) {
          detectedPlateInput.value = '';
        }
        simulatedDetected = expectedVal || '2AZ-1234';
      }

      // 1. CAMERA READY
      setAnprState('READY');

      // 2. SCANNING PLATE (pulse beam)
      await new Promise(r => setTimeout(r, 60));
      setAnprState('SCANNING');

      // 3. PLATE DETECTED
      await new Promise(r => setTimeout(r, 450));
      setAnprState('DETECTED', simulatedDetected);

      // Brief pause to display detected plate on car before submitting
      await new Promise(r => setTimeout(r, 200));

      checkBtn.dataset.anprProcessed = 'true';

      let actionInput = form.querySelector('input[name="action"]');
      if (!actionInput) {
        actionInput = document.createElement('input');
        actionInput.type = 'hidden';
        actionInput.name = 'action';
        form.appendChild(actionInput);
      }
      actionInput.value = 'open';

      form.submit();
    });
  }

  // =========================================================================
  // Passage Animation Controller (Asynchronous 7-Stage Sequence)
  // Idle → Opening → Waiting → Passage pending → Moving → Closing → Complete
  // =========================================================================
  if (passBtn && form) {
    passBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      // Immediate guard against re-entry while in-flight or animating
      if (isCrossing || isPassageInFlight) return;
      isPassageInFlight = true;

      // 1. CRITICAL: Snapshot FormData BEFORE disabling any form controls!
      // In HTML standard, disabled form elements are omitted from FormData.
      const formData = new FormData(form);
      formData.set('action', 'pass');

      // Explicitly guarantee required fields are included in the payload
      const permitInput = document.getElementById('vg-permit-input');
      if (permitInput && !formData.get('permit')) {
        formData.set('permit', permitInput.value);
      }
      const selectedMode = form.querySelector('input[name="mode"]:checked');
      if (selectedMode && !formData.get('mode')) {
        formData.set('mode', selectedMode.value);
      }
      if (zoneSelect && !formData.get('zone')) {
        formData.set('zone', zoneSelect.value);
      }
      if (codeInput && !formData.get('code')) {
        formData.set('code', codeInput.value.trim());
      }
      const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
      if (csrfInput && !formData.get('csrfmiddlewaretoken')) {
        formData.set('csrfmiddlewaretoken', csrfInput.value);
      }
      const detectedPlateHidden = document.getElementById('vg-detected-plate-input');
      if (detectedPlateHidden && !formData.get('detected_plate')) {
        formData.set('detected_plate', detectedPlateHidden.value);
      }

      // 2. NOW disable conflicting controls to prevent duplicate submissions
      passBtn.disabled = true;
      if (closeBtn) closeBtn.disabled = true;
      if (checkBtn) checkBtn.disabled = true;
      if (codeInput) codeInput.disabled = true;
      if (zoneSelect) zoneSelect.disabled = true;
      modeRadios.forEach(r => r.disabled = true);

      stopPermitCountdown();

      if (statusText) statusText.textContent = 'CONFIRMING PASSAGE WITH SERVER...';

      let result = null;
      try {
        const postUrl = form.getAttribute('action') || window.location.pathname || window.location.href;
        const response = await fetch(postUrl, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
          },
          body: formData
        });

        if (response.ok) {
          result = await response.json();
        } else if (response.status >= 400 && response.status < 500) {
          // Explicit client/validation rejection (e.g. 400 Bad Request, expired permit, capacity full)
          const errData = await response.json().catch(() => ({}));

          // Remove open visual state: lower barrier immediately so an open gate doesn't sit next to closed text
          if (sceneEl) sceneEl.classList.remove('is-open');
          if (statusBanner && statusText) {
            statusBanner.className = 'vg-status-indicator status-closed';
            statusText.textContent = 'BARRIER CLOSED — PASSAGE REJECTED';
          }

          // Show rejection notice
          let noticeBox = document.querySelector('.vg-notice');
          if (!noticeBox && statusBanner && statusBanner.parentNode) {
            noticeBox = document.createElement('div');
            statusBanner.parentNode.insertBefore(noticeBox, statusBanner.nextSibling);
          }
          if (noticeBox) {
            noticeBox.className = 'vg-notice vg-alert-error';
            noticeBox.textContent = errData.notice || 'Passage authorization rejected. Re-check ticket.';
          }

          // Restore controls
          passBtn.disabled = false;
          if (closeBtn) closeBtn.disabled = false;
          if (checkBtn) checkBtn.disabled = false;
          if (codeInput) codeInput.disabled = false;
          if (zoneSelect) zoneSelect.disabled = false;
          modeRadios.forEach(r => r.disabled = false);

          isPassageInFlight = false;
          return;
        } else {
          throw new Error(`Server returned error status ${response.status}`);
        }
      } catch (err) {
        // Genuine network drop or server connection lost
        // Only reconcile if there is recent evidence within the last 20 seconds
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
              const ts = modeVal === 'entry' ? checkData.checked_in_at : checkData.checked_out_at;
              if (ts) {
                const ageSec = (Date.now() - new Date(ts).getTime()) / 1000;
                if (ageSec >= 0 && ageSec <= 20) {
                  result = {
                    success: true,
                    passed: true,
                    notice: 'Vehicle passage reconciled via recent server timestamp.',
                    status: checkData.status,
                    status_display: checkData.status_display
                  };
                  reconciled = true;
                }
              }
            }
          } catch (_) {}
        }

        if (!reconciled) {
          // Rejection or failure: DO NOT animate passage
          if (sceneEl) sceneEl.classList.remove('is-open');
          passBtn.disabled = false;
          if (closeBtn) closeBtn.disabled = false;
          if (checkBtn) checkBtn.disabled = false;
          if (codeInput) codeInput.disabled = false;
          if (zoneSelect) zoneSelect.disabled = false;
          modeRadios.forEach(r => r.disabled = false);

          if (statusBanner && statusText) {
            statusBanner.className = 'vg-status-indicator status-closed';
            statusText.textContent = 'NETWORK UNCERTAINTY — PASSAGE NOT VERIFIED';
          }
          isPassageInFlight = false;
          alert('Network connection error. Passage could not be verified. Please re-check ticket status.');
          return;
        }
      }

      // 3. Server confirmed passage: execute visible crossing animation
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

      // 4. Closing stage: car cleared barrier arm; now lower the arm
      if (statusText) statusText.textContent = 'VEHICLE CLEARED — CLOSING BARRIER...';
      if (sceneEl) sceneEl.classList.remove('is-open');

      if (!reducedMotion && armEl) {
        await waitForTransition(armEl, 'transform', 900);
      } else {
        await new Promise(r => setTimeout(r, 20));
      }

      // 5. Complete stage: mark passed and show final status
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

      // Update stepper to Step 3 Completed
      const step3 = document.getElementById('vg-step-3');
      if (step3) {
        step3.classList.remove('is-active', 'is-pending');
        step3.classList.add('is-completed');
      }
      const conn23 = document.getElementById('vg-connector-2-3');
      if (conn23) {
        conn23.classList.add('is-completed');
        conn23.classList.remove('is-active');
      }
      const step3Desc = document.getElementById('vg-step-3-desc');
      if (step3Desc) step3Desc.textContent = 'Vehicle passed · Closed';

      // Show reset box for "Start another ticket"
      const resetBox = document.getElementById('vg-reset-box');
      if (resetBox) resetBox.style.display = 'block';

      // Hide standard actions while reset box is active
      const standardActions = document.getElementById('vg-standard-actions');
      if (standardActions) standardActions.style.display = 'none';

      // Show replay box
      const replayBox = document.getElementById('vg-replay-box');
      if (replayBox) replayBox.hidden = false;

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

      // Re-enable form fields; preserve selected facility, direction, and ticket code
      if (checkBtn) checkBtn.disabled = false;
      if (codeInput) codeInput.disabled = false;
      if (zoneSelect) zoneSelect.disabled = false;
      modeRadios.forEach(r => r.disabled = false);

      isCrossing = false;
      isPassageInFlight = false;
    });
  }

  // =========================================================================
  // Controlled Completion Animation for HTML Fallback Response
  // =========================================================================
  if (sceneEl && sceneEl.dataset.justPassed === 'true') {
    const runFallbackAnimation = async () => {
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const carTrack = document.getElementById('vg-car-track');
      const armEl = document.getElementById('vg-barrier-arm');

      // Ensure barrier starts visually raised
      sceneEl.classList.add('is-open');
      sceneEl.classList.remove('is-passed');

      // Wait for paint
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      await waitForArmOpening();

      // Animate crossing
      sceneEl.classList.add('is-moving');
      if (!reducedMotion && carTrack) {
        await waitForTransition(carTrack, 'transform', 1500);
      }

      // Lower arm
      sceneEl.classList.remove('is-open');
      if (!reducedMotion && armEl) {
        await waitForTransition(armEl, 'transform', 900);
      }

      sceneEl.classList.remove('is-moving');
      sceneEl.classList.add('is-passed');
    };

    runFallbackAnimation();
  }

  // =========================================================================
  // Visual-only Replay Animation Handler (No database updates)
  // =========================================================================
  const replayBtn = document.getElementById('vg-replay-animation');
  if (replayBtn) {
    replayBtn.addEventListener('click', async () => {
      if (isCrossing || isPassageInFlight) return;
      isCrossing = true;

      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const carTrack = document.getElementById('vg-car-track');
      const armEl = document.getElementById('vg-barrier-arm');

      replayBtn.disabled = true;

      // Reset the vehicle without animating it backwards across a closed arm.
      if (carTrack) carTrack.style.transition = 'none';
      sceneEl.classList.remove('is-passed', 'is-moving', 'is-open');
      void sceneEl.offsetWidth;
      if (carTrack) carTrack.style.removeProperty('transition');
      if (statusText) statusText.textContent = 'REPLAY — BARRIER OPENING';
      sceneEl.classList.add('is-open');
      await waitForArmOpening();

      // 2. Animate vehicle crossing
      if (statusText) statusText.textContent = 'REPLAY — VEHICLE CROSSING';
      sceneEl.classList.add('is-moving');
      if (!reducedMotion && carTrack) {
        await waitForTransition(carTrack, 'transform', 1500);
      } else {
        await new Promise(r => setTimeout(r, 20));
      }

      // 3. Lower barrier arm
      if (statusText) statusText.textContent = 'REPLAY — BARRIER CLOSING';
      sceneEl.classList.remove('is-open');
      if (!reducedMotion && armEl) {
        await waitForTransition(armEl, 'transform', 900);
      } else {
        await new Promise(r => setTimeout(r, 20));
      }

      // 4. Return to completed state
      sceneEl.classList.remove('is-moving');
      sceneEl.classList.add('is-passed');

      if (statusText) statusText.textContent = 'VEHICLE PASSAGE CONFIRMED — BARRIER CLOSED';
      replayBtn.disabled = false;
      isCrossing = false;
    });
  }

  // =========================================================================
  // Walk-in Parking & Exit Payment Controller
  // =========================================================================
  const zonesScript = document.getElementById('vg-zones-info-data');
  let zonesInfo = {};
  if (zonesScript) {
    try {
      zonesInfo = JSON.parse(zonesScript.textContent || '{}');
    } catch (_) {}
  }

  const walkinCard = document.getElementById('vg-walkin-card');
  const walkinRateVal = document.getElementById('vg-walkin-rate-val');
  const walkinCapVal = document.getElementById('vg-walkin-cap-val');
  const showWalkinBtn = document.getElementById('btn-show-walkin-confirm');
  const walkinConfirmModal = document.getElementById('vg-walkin-confirm-modal');
  const closeWalkinConfirmBtn = document.getElementById('btn-close-walkin-confirm');
  const cancelWalkinConfirmBtn = document.getElementById('btn-cancel-walkin-confirm');
  const issueWalkinTicketBtn = document.getElementById('btn-issue-walkin-ticket');
  const walkinPlateInput = document.getElementById('vg-walkin-plate-input');

  const confirmFacilityName = document.getElementById('vg-confirm-facility-name');
  const confirmRate = document.getElementById('vg-confirm-rate');
  const confirmPlate = document.getElementById('vg-confirm-plate');

  const ticketPrintModal = document.getElementById('vg-ticket-print-modal');
  const closeTicketModalBtn = document.getElementById('btn-close-ticket-modal');
  const dismissTicketBtn = document.getElementById('btn-dismiss-ticket');
  const printTicketBtn = document.getElementById('btn-print-ticket');

  function updateWalkinFacilityDisplay() {
    if (!zoneSelect) return;
    const zoneId = zoneSelect.value;
    const info = zonesInfo[zoneId];
    if (info) {
      if (walkinRateVal) walkinRateVal.textContent = `${info.walk_in_price_formatted} / day`;
      if (walkinCapVal) {
        if (info.unreserved_capacity > 0) {
          walkinCapVal.textContent = `${info.unreserved_capacity} space${info.unreserved_capacity > 1 ? 's' : ''} available`;
          walkinCapVal.style.color = '#10b981';
          if (showWalkinBtn) showWalkinBtn.disabled = false;
        } else {
          walkinCapVal.textContent = `0 spaces (Full / Reserved)`;
          walkinCapVal.style.color = '#ef4444';
          if (showWalkinBtn) showWalkinBtn.disabled = true;
        }
      }
    } else {
      if (walkinRateVal) walkinRateVal.textContent = '7,000 ៛ / day';
      if (walkinCapVal) {
        walkinCapVal.textContent = '—';
        walkinCapVal.style.color = '';
      }
    }
  }

  if (zoneSelect) {
    zoneSelect.addEventListener('change', updateWalkinFacilityDisplay);
    updateWalkinFacilityDisplay();
  }

  // Update card visibility & simulator direction on gate mode change (Entrance / Exit)
  updateGateDirection();
  modeRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      updateGateDirection();
      if (walkinCard) {
        if (radio.value === 'entry' && (!codeInput || !codeInput.value.trim())) {
          walkinCard.style.display = 'block';
          updateWalkinFacilityDisplay();
        } else {
          walkinCard.style.display = 'none';
        }
      }
    });
  });

  // Open Walk-in Confirmation Modal
  if (showWalkinBtn) {
    showWalkinBtn.addEventListener('click', () => {
      const zoneId = zoneSelect?.value;
      if (!zoneId) {
        alert('Please select a parking facility first.');
        zoneSelect?.focus();
        return;
      }
      const info = zonesInfo[zoneId];
      if (info && info.unreserved_capacity <= 0) {
        alert(`Cannot issue walk-in ticket: Facility '${info.name}' has no available unreserved spaces. All slots are occupied or held by active reservations.`);
        return;
      }

      if (confirmFacilityName) confirmFacilityName.textContent = info ? info.name : 'Selected Facility';
      if (confirmRate) confirmRate.textContent = info ? `${info.walk_in_price_formatted} / day` : '7,000 ៛ / day';
      const plate = walkinPlateInput?.value?.trim() || '';
      if (confirmPlate) confirmPlate.textContent = plate ? plate.toUpperCase() : 'Not captured (Optional)';

      if (walkinConfirmModal) walkinConfirmModal.hidden = false;
    });
  }

  function hideWalkinConfirm() {
    if (walkinConfirmModal) walkinConfirmModal.hidden = true;
  }
  if (closeWalkinConfirmBtn) closeWalkinConfirmBtn.addEventListener('click', hideWalkinConfirm);
  if (cancelWalkinConfirmBtn) cancelWalkinConfirmBtn.addEventListener('click', hideWalkinConfirm);

  // Issue Walk-in Ticket via Server Request
  let walkInInFlight = false;
  if (issueWalkinTicketBtn) {
    issueWalkinTicketBtn.addEventListener('click', async () => {
      if (walkInInFlight) return;
      walkInInFlight = true;
      issueWalkinTicketBtn.disabled = true;

      const zoneId = zoneSelect?.value;
      const plate = walkinPlateInput?.value?.trim() || '';
      const csrfToken = form?.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
      const idempotencyKey = 'walkin_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);

      const formData = new FormData();
      formData.set('csrfmiddlewaretoken', csrfToken);
      formData.set('zone', zoneId);
      formData.set('mode', 'entry');
      formData.set('action', 'walk_in_issue');
      formData.set('walk_in_plate', plate);
      formData.set('idempotency_key', idempotencyKey);

      try {
        const postUrl = form?.getAttribute('action') || window.location.pathname || window.location.href;
        const resp = await fetch(postUrl, {
          method: 'POST',
          headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
          body: formData
        });

        const data = await resp.json();
        if (resp.ok && data.success) {
          hideWalkinConfirm();

          // Populate printable ticket modal
          const ticketFacility = document.getElementById('vg-ticket-facility-name');
          const ticketCodeDisplay = document.getElementById('vg-ticket-code-display');
          const ticketQrImg = document.getElementById('vg-ticket-qr-img');
          const ticketRateDisplay = document.getElementById('vg-ticket-rate-display');
          const ticketPlateDisplay = document.getElementById('vg-ticket-plate-display');

          if (ticketFacility) ticketFacility.textContent = zonesInfo[zoneId]?.name || 'SomPark Facility';
          if (ticketCodeDisplay) ticketCodeDisplay.textContent = data.ticket_code;
          if (ticketQrImg) ticketQrImg.src = data.ticket_qr_base64;
          if (ticketRateDisplay) ticketRateDisplay.textContent = `${data.daily_rate_formatted} / day (Walk-in rate)`;
          if (ticketPlateDisplay) ticketPlateDisplay.textContent = data.plate_number || '—';

          // Show printable ticket modal
          if (ticketPrintModal) ticketPrintModal.hidden = false;

          // Set form ticket code
          if (codeInput) codeInput.value = data.ticket_code;

          // Open simulated barrier arm immediately
          if (sceneEl) {
            sceneEl.classList.add('is-open');
            sceneEl.classList.remove('is-passed');
          }
          if (statusBanner && statusText) {
            statusBanner.className = 'vg-status-indicator status-open';
            statusText.textContent = 'BARRIER OPEN — WAITING FOR VEHICLE';
          }

          // Permit countdown & passage actions
          const permitInput = document.getElementById('vg-permit-input');
          if (permitInput) permitInput.value = data.permit;
          if (permitTimerBanner) permitTimerBanner.dataset.expiresAt = data.permit_expires_at;
          startPermitCountdown();

          updateGateDirection();
          const passBox = document.getElementById('vg-pass-actions-box');
          if (passBox) passBox.style.display = 'block';

          // Hide walk-in card while ticket is in active passage hold
          if (walkinCard) walkinCard.style.display = 'none';

          // Update notice
          let noticeBox = document.querySelector('.vg-notice');
          if (!noticeBox && statusBanner && statusBanner.parentNode) {
            noticeBox = document.createElement('div');
            statusBanner.parentNode.insertBefore(noticeBox, statusBanner.nextSibling);
          }
          if (noticeBox) {
            noticeBox.className = 'vg-notice is-success';
            noticeBox.textContent = data.notice;
          }

          // Update cached unreserved capacity
          if (zonesInfo[zoneId] && typeof data.unreserved_capacity === 'number') {
            zonesInfo[zoneId].unreserved_capacity = data.unreserved_capacity;
            updateWalkinFacilityDisplay();
          }
        } else {
          alert(data.notice || 'Failed to issue walk-in ticket. Please try again.');
          hideWalkinConfirm();
        }
      } catch (err) {
        alert('Network connection error while issuing walk-in ticket.');
      } finally {
        walkInInFlight = false;
        issueWalkinTicketBtn.disabled = false;
      }
    });
  }

  // Close ticket printable modal
  function hideTicketModal() {
    if (ticketPrintModal) ticketPrintModal.hidden = true;
  }
  if (closeTicketModalBtn) closeTicketModalBtn.addEventListener('click', hideTicketModal);
  if (dismissTicketBtn) dismissTicketBtn.addEventListener('click', hideTicketModal);
  if (printTicketBtn) {
    printTicketBtn.addEventListener('click', () => {
      window.print();
    });
  }

  // Direct exit payment settlement (Requirement 9: continue directly to barrier opening & passage without re-scanning)
  const cashBtn = document.getElementById('btn-confirm-cash');
  const demoSuccessBtn = document.getElementById('btn-demo-qr-success');
  const demoFailureBtn = document.getElementById('btn-demo-qr-failure');
  const demoCancelBtn = document.getElementById('btn-demo-qr-cancel');

  async function handleExitSettlement(provider, outcome) {
    const csrfToken = form?.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
    const zoneId = zoneSelect?.value;
    const codeVal = codeInput?.value?.trim();

    const formData = new FormData();
    formData.set('csrfmiddlewaretoken', csrfToken);
    formData.set('zone', zoneId);
    formData.set('mode', 'exit');
    formData.set('code', codeVal);
    formData.set('action', 'settle');
    formData.set('payment_provider', provider);
    formData.set('outcome', outcome);

    const mismatchCb = document.getElementById('simulate-plate-mismatch-cb');
    if (mismatchCb && mismatchCb.checked) {
      formData.set('simulate_plate_mismatch', 'true');
      const detectedPlateHidden = document.getElementById('vg-detected-plate-input');
      if (detectedPlateHidden && detectedPlateHidden.value) {
        formData.set('detected_plate', detectedPlateHidden.value);
      }
      const customDetectedPlate = document.getElementById('custom-detected-plate-input');
      if (customDetectedPlate && customDetectedPlate.value) {
        formData.set('custom_detected_plate', customDetectedPlate.value);
      }
    }

    try {
      const postUrl = form?.getAttribute('action') || window.location.pathname || window.location.href;
      const resp = await fetch(postUrl, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
        body: formData
      });

      const data = await resp.json();
      if (resp.ok && data.success && data.settled) {
        // Step 2 Completed
        const step2 = document.getElementById('vg-step-2');
        if (step2) {
          step2.classList.remove('is-active', 'is-pending');
          step2.classList.add('is-completed');
        }
        const conn12 = document.getElementById('vg-connector-1-2');
        if (conn12) conn12.classList.add('is-completed');
        const conn23 = document.getElementById('vg-connector-2-3');
        if (conn23) conn23.classList.add('is-active');
        const step2Desc = document.getElementById('vg-step-2-desc');
        if (step2Desc) step2Desc.textContent = '0 KHR due · Settled';

        // Hide settlement box
        const settleBox = document.getElementById('vg-settlement-box');
        if (settleBox) settleBox.style.display = 'none';

        // Step 3 Active: Barrier opened
        const step3 = document.getElementById('vg-step-3');
        if (step3) {
          step3.classList.remove('is-pending');
          step3.classList.add('is-active');
        }
        const step3Desc = document.getElementById('vg-step-3-desc');
        if (step3Desc) step3Desc.textContent = 'Barrier OPEN · Waiting';

        // Open barrier arm immediately
        if (sceneEl) {
          sceneEl.classList.add('is-open');
          sceneEl.classList.remove('is-passed');
        }
        if (statusBanner && statusText) {
          statusBanner.className = 'vg-status-indicator status-open';
          statusText.textContent = 'BARRIER OPEN — WAITING FOR VEHICLE';
        }

        // Set permit and start countdown
        const permitInput = document.getElementById('vg-permit-input');
        if (permitInput) permitInput.value = data.permit;
        if (permitTimerBanner) permitTimerBanner.dataset.expiresAt = data.permit_expires_at;
        startPermitCountdown();

        // Show passage actions with correct direction label
        updateGateDirection();
        const passBox = document.getElementById('vg-pass-actions-box');
        if (passBox) passBox.style.display = 'block';

        // Update notice
        let noticeBox = document.querySelector('.vg-notice');
        if (!noticeBox && statusBanner && statusBanner.parentNode) {
          noticeBox = document.createElement('div');
          statusBanner.parentNode.insertBefore(noticeBox, statusBanner.nextSibling);
        }
        if (noticeBox) {
          noticeBox.className = 'vg-notice is-success';
          noticeBox.textContent = data.notice;
        }

        // Update balance due display in telemetry
        const balEl = document.querySelector('.vg-balance-amount');
        if (balEl) {
          balEl.textContent = '0 KHR';
          balEl.classList.add('is-zero');
        }
      } else {
        // Payment failed, cancelled, or plate mismatch
        let noticeBox = document.querySelector('.vg-notice');
        if (!noticeBox && statusBanner && statusBanner.parentNode) {
          noticeBox = document.createElement('div');
          statusBanner.parentNode.insertBefore(noticeBox, statusBanner.nextSibling);
        }
        if (noticeBox) {
          noticeBox.className = 'vg-notice vg-alert-error';
          noticeBox.textContent = data.notice || 'Payment processing failed.';
        }
      }
    } catch (err) {
      alert('Network error during exit payment settlement.');
    }
  }

  if (cashBtn) {
    cashBtn.addEventListener('click', (e) => {
      e.preventDefault();
      handleExitSettlement('CASH', 'success');
    });
  }
  if (demoSuccessBtn) {
    demoSuccessBtn.addEventListener('click', (e) => {
      e.preventDefault();
      handleExitSettlement('DEMO', 'success');
    });
  }
  if (demoFailureBtn) {
    demoFailureBtn.addEventListener('click', (e) => {
      e.preventDefault();
      handleExitSettlement('DEMO', 'failure');
    });
  }
  if (demoCancelBtn) {
    demoCancelBtn.addEventListener('click', (e) => {
      e.preventDefault();
      handleExitSettlement('DEMO', 'cancel');
    });
  }

  // Reopen Barrier Action Handler (When settled and barrier needs to reopen for exit)
  if (reopenBtn && form) {
    reopenBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      reopenBtn.disabled = true;

      const formData = new FormData(form);
      formData.set('action', 'open');

      try {
        const postUrl = form.getAttribute('action') || window.location.pathname || window.location.href;
        const resp = await fetch(postUrl, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
          },
          body: formData
        });

        const data = await resp.json();
        if (resp.ok && data.success && data.gate_open) {
          if (sceneEl) {
            sceneEl.classList.add('is-open');
            sceneEl.classList.remove('is-passed');
          }
          if (statusBanner && statusText) {
            statusBanner.className = 'vg-status-indicator status-open';
            statusText.textContent = 'BARRIER OPEN — WAITING FOR VEHICLE';
          }
          const reopenBox = document.getElementById('vg-reopen-box');
          if (reopenBox) reopenBox.style.display = 'none';

          const permitInput = document.getElementById('vg-permit-input');
          if (permitInput) permitInput.value = data.permit;
          if (permitTimerBanner) permitTimerBanner.dataset.expiresAt = data.permit_expires_at;
          startPermitCountdown();

          updateGateDirection();
          const passBox = document.getElementById('vg-pass-actions-box');
          if (passBox) passBox.style.display = 'block';

          let noticeBox = document.querySelector('.vg-notice');
          if (!noticeBox && statusBanner && statusBanner.parentNode) {
            noticeBox = document.createElement('div');
            statusBanner.parentNode.insertBefore(noticeBox, statusBanner.nextSibling);
          }
          if (noticeBox) {
            noticeBox.className = 'vg-notice is-success';
            noticeBox.textContent = data.notice || 'Barrier is OPEN — waiting for vehicle to pass.';
          }
        } else {
          // If server rejects or non-JSON, submit standard form
          const actionInput = document.createElement('input');
          actionInput.type = 'hidden';
          actionInput.name = 'action';
          actionInput.value = 'open';
          form.appendChild(actionInput);
          form.submit();
        }
      } catch (err) {
        const actionInput = document.createElement('input');
        actionInput.type = 'hidden';
        actionInput.name = 'action';
        actionInput.value = 'open';
        form.appendChild(actionInput);
        form.submit();
      } finally {
        reopenBtn.disabled = false;
      }
    });
  }

  // View Mode Toggles (Roadway & Record vs Compact)
  const viewBtnAll = document.getElementById('vg-view-btn-all');
  const viewBtnCompact = document.getElementById('vg-view-btn-compact');
  if (viewBtnAll && viewBtnCompact && sceneEl) {
    viewBtnCompact.addEventListener('click', () => {
      sceneEl.classList.add('is-compact');
      viewBtnCompact.classList.add('is-active');
      viewBtnAll.classList.remove('is-active');
      try { localStorage.setItem('sompark_vg_view', 'compact'); } catch (_) {}
    });
    viewBtnAll.addEventListener('click', () => {
      sceneEl.classList.remove('is-compact');
      viewBtnAll.classList.add('is-active');
      viewBtnCompact.classList.remove('is-active');
      try { localStorage.setItem('sompark_vg_view', 'all'); } catch (_) {}
    });

    try {
      if (localStorage.getItem('sompark_vg_view') === 'compact') {
        sceneEl.classList.add('is-compact');
        viewBtnCompact.classList.add('is-active');
        viewBtnAll.classList.remove('is-active');
      }
    } catch (_) {}
  }

  // Cleanup on page hide or navigate away
  window.addEventListener('pagehide', stopCamera);
  window.addEventListener('beforeunload', stopCamera);
})();
