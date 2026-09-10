/**
 * Shared accessible confirmation dialog for customer reservation cancellation.
 */
(function () {
  'use strict';

  function initReservationCancelDialog() {
    const dialog = document.getElementById('reservation-cancel-dialog');
    if (!dialog) return;

    const noButton = document.getElementById('reservation-cancel-no');
    const yesButton = document.getElementById('reservation-cancel-yes');
    const ticketDisplay = document.getElementById('reservation-cancel-ticket');
    const zoneDisplay = document.getElementById('reservation-cancel-zone');
    const zoneWrap = document.getElementById('reservation-cancel-zone-wrap');

    let pendingForm = null;
    let lastTrigger = null;

    function resetButtons() {
      yesButton.disabled = false;
      yesButton.removeAttribute('aria-busy');
      yesButton.textContent = 'Yes, cancel reservation';
      noButton.disabled = false;
    }

    function closeDialog() {
      if (dialog.hasAttribute('open')) {
        if (typeof dialog.close === 'function') {
          dialog.close();
        } else {
          dialog.removeAttribute('open');
        }
      }
    }

    document.addEventListener('submit', function (event) {
      const form = event.target.closest('form[data-cancel-confirm]');
      if (!form) return;

      if (form.dataset.cancelConfirmed === 'true') {
        delete form.dataset.cancelConfirmed;
        return;
      }

      event.preventDefault();
      pendingForm = form;
      lastTrigger = event.submitter || form.querySelector('[type="submit"]');

      const ticket = form.dataset.ticketCode || '';
      const zone = form.dataset.zoneName || '';
      ticketDisplay.textContent = ticket ? '#' + ticket : 'this booking';
      zoneDisplay.textContent = zone;
      zoneWrap.hidden = !zone;
      resetButtons();

      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
      noButton.focus();
    });

    noButton.addEventListener('click', closeDialog);

    yesButton.addEventListener('click', function () {
      if (!pendingForm) return;

      yesButton.disabled = true;
      yesButton.setAttribute('aria-busy', 'true');
      yesButton.textContent = 'Cancelling...';
      noButton.disabled = true;
      pendingForm.dataset.cancelConfirmed = 'true';
      pendingForm.requestSubmit();
    });

    dialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeDialog();
    });

    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) closeDialog();
    });

    dialog.addEventListener('close', function () {
      pendingForm = null;
      resetButtons();
      if (lastTrigger && typeof lastTrigger.focus === 'function') lastTrigger.focus();
      lastTrigger = null;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReservationCancelDialog);
  } else {
    initReservationCancelDialog();
  }
})();
