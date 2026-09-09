/**
 * SomPark Virtual Parking Gate Terminal — Controller
 * Handles camera optical QR scanning, USB barcode scanner input,
 * 120-second permit countdown auto-closing, and authorization invalidation.
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

  let stream = null;
  let scanning = false;
  let scanTimer = null;

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

  // USB Barcode Scanner & Enter Key Handling
  if (codeInput && form) {
    codeInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        // Trigger check & open action
        let actionInput = form.querySelector('input[name="action"]');
        if (!actionInput) {
          actionInput = document.createElement('input');
          actionInput.type = 'hidden';
          actionInput.name = 'action';
          form.appendChild(actionInput);
        }
        actionInput.value = 'open';
        form.submit();
      }
    });
  }

  // 120-Second Gate Permit Expiration Timer
  const permitSecondsEl = document.getElementById('vg-timer-seconds');
  const permitTimerBanner = document.getElementById('vg-permit-timer');
  const passBtn = document.getElementById('vg-pass');
  const sceneEl = document.getElementById('vg-scene-viewport');
  const statusBanner = document.getElementById('vg-gate-status-banner');
  const statusText = document.getElementById('vg-status-text');

  if (permitSecondsEl && permitTimerBanner && passBtn) {
    let secondsLeft = 120;
    const countdownInterval = setInterval(() => {
      secondsLeft -= 1;
      if (secondsLeft > 0) {
        permitSecondsEl.textContent = secondsLeft;
      } else {
        clearInterval(countdownInterval);
        // Authorization expired: close visual barrier and disable passage confirmation
        permitTimerBanner.style.background = '#fef2f2';
        permitTimerBanner.style.borderColor = '#f87171';
        permitTimerBanner.style.color = '#991b1b';
        permitTimerBanner.innerHTML = '<strong>Gate authorization expired (120s elapsed).</strong> Barrier auto-closed. Re-check ticket.';

        passBtn.disabled = true;
        if (sceneEl) sceneEl.classList.remove('is-open');

        if (statusBanner && statusText) {
          statusBanner.className = 'vg-status-indicator status-closed';
          statusText.textContent = 'BARRIER CLOSED — AUTHORIZATION EXPIRED';
        }
      }
    }, 1000);
  }

  // Invalidate displayed authorization if attendant edits facility, code, or direction
  document.querySelectorAll('#id_zone, #id_code, [name="mode"]').forEach(input => {
    input.addEventListener('input', () => {
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
        statusText.textContent = 'BARRIER CLOSED — TICKET RE-CHECK REQUIRED';
      }
    });
  });

  // Dynamic Direction Label Active Highlight
  document.querySelectorAll('.vg-direction-label input[type="radio"]').forEach(radio => {
    radio.addEventListener('change', () => {
      document.querySelectorAll('.vg-direction-label').forEach(label => {
        label.classList.remove('is-selected');
      });
      const parentLabel = radio.closest('.vg-direction-label');
      if (parentLabel) {
        parentLabel.classList.add('is-selected');
      }
    });
  });

  // Cleanup on page hide or navigate away
  window.addEventListener('pagehide', stopCamera);
  window.addEventListener('beforeunload', stopCamera);
})();
