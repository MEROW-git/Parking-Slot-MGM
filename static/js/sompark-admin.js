/**
 * SomPark Staff Operations Workbench · Admin Modal Dialog & Actions
 * Accessible native <dialog> handling, focus restoration, backdrop dismiss fallback,
 * and double-submission protection with loading feedback.
 */
(function () {
  'use strict';

  function initAdminDialog() {
    const dialog = document.getElementById('admin-checkout-dialog');
    if (!dialog) return;

    const cancelBtn = document.getElementById('dialog-btn-cancel');
    const form = document.getElementById('dialog-checkout-form');
    const confirmBtn = document.getElementById('dialog-btn-confirm');
    const ticketCodeInput = document.getElementById('dialog-input-ticket-code');
    const ticketCodeDisplay = document.getElementById('dialog-ticket-code');
    const plateNumberDisplay = document.getElementById('dialog-plate-number');
    const zoneNameDisplay = document.getElementById('dialog-zone-name');

    let lastActiveElement = null;
    let isSubmitting = false;

    // Attach click listeners to all admin checkout trigger buttons
    document.querySelectorAll('[data-admin-checkout-btn]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        lastActiveElement = btn;

        const ticket = btn.getAttribute('data-ticket-code') || '';
        const plate = btn.getAttribute('data-plate-number') || '';
        const zone = btn.getAttribute('data-zone-name') || '';

        if (ticketCodeInput) ticketCodeInput.value = ticket;
        if (ticketCodeDisplay) ticketCodeDisplay.textContent = ticket ? '#' + ticket : '';
        if (plateNumberDisplay) plateNumberDisplay.textContent = plate;
        if (zoneNameDisplay) zoneNameDisplay.textContent = zone;

        // Reset submit state
        isSubmitting = false;
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.removeAttribute('aria-busy');
          confirmBtn.removeAttribute('data-state');
          confirmBtn.textContent = 'Yes, check out';
        }
        if (cancelBtn) {
          cancelBtn.disabled = false;
        }

        if (typeof dialog.showModal === 'function') {
          dialog.showModal();
          // Initial focus must go to the safe "No, keep active" button
          if (cancelBtn) {
            cancelBtn.focus();
          }
        } else {
          // Fallback if HTML5 dialog not natively supported
          dialog.setAttribute('open', '');
          if (cancelBtn) cancelBtn.focus();
        }
      });
    });

    function closeDialog() {
      if (dialog.hasAttribute('open')) {
        if (typeof dialog.close === 'function') {
          dialog.close();
        } else {
          dialog.removeAttribute('open');
        }
      }
      // Return focus to the original button that opened the modal
      if (lastActiveElement && typeof lastActiveElement.focus === 'function') {
        lastActiveElement.focus();
      }
    }

    if (cancelBtn) {
      cancelBtn.addEventListener('click', function (e) {
        e.preventDefault();
        closeDialog();
      });
    }

    // Escape closes the dialog natively in showModal(), but ensure focus is restored
    dialog.addEventListener('close', function () {
      if (lastActiveElement && typeof lastActiveElement.focus === 'function') {
        lastActiveElement.focus();
      }
    });

    dialog.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeDialog();
      }
    });

    // Fallback backdrop click dismiss for browsers without native closedby support
    dialog.addEventListener('click', function (event) {
      if (event.target !== dialog) return;

      const rect = dialog.getBoundingClientRect();
      const isInside = (
        rect.top <= event.clientY &&
        event.clientY <= rect.top + rect.height &&
        rect.left <= event.clientX &&
        event.clientX <= rect.left + rect.width
      );

      if (!isInside) {
        closeDialog();
      }
    });

    // Prevent double form submissions and show loading state
    if (form) {
      form.addEventListener('submit', function (e) {
        if (isSubmitting) {
          e.preventDefault();
          return;
        }

        isSubmitting = true;
        if (confirmBtn) {
          confirmBtn.setAttribute('aria-busy', 'true');
          confirmBtn.setAttribute('data-state', 'loading');
          confirmBtn.textContent = 'Checking out... (កំពុងដំណើរការ)';
        }
        if (cancelBtn) {
          cancelBtn.disabled = true;
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAdminDialog);
  } else {
    initAdminDialog();
  }
})();
