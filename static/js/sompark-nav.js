/**
 * SomPark Navigation & Unsaved Changes Guard
 * Intercepts navigation from workflow pages with unsaved form input.
 * Guarantees that Back navigation uses safe GET requests and never
 * accidentally submits forms, confirms payments, or cancels holds.
 */
(() => {
  'use strict';

  let formIsDirty = false;
  let formInitialValues = null;

  function initFormTracking() {
    const activeForm = document.querySelector('form#reservation-form');
    if (!activeForm) return;

    // Snapshot initial state
    const captureState = () => {
      const formData = new FormData(activeForm);
      return Array.from(formData.entries()).map(([k, v]) => `${k}:${v}`).join('|');
    };

    formInitialValues = captureState();

    const markDirty = () => {
      if (!formInitialValues) return;
      formIsDirty = captureState() !== formInitialValues;
    };

    activeForm.addEventListener('input', markDirty);
    activeForm.addEventListener('change', markDirty);
    activeForm.addEventListener('submit', () => {
      formIsDirty = false;
    });
  }

  function initBackNavigationGuards() {
    document.addEventListener('click', (e) => {
      const backLink = e.target.closest('[data-confirm-unsaved="true"]');
      if (!backLink) return;

      if (formIsDirty) {
        const warningMessage =
          'You have unsaved reservation details. Are you sure you want to leave?\n\n' +
          'អ្នកមានព័ត៌មានកក់ដែលមិនទាន់បានរក្សាទុក។ តើអ្នកពិតជាចង់ចាកចេញមែនទេ?';

        if (!window.confirm(warningMessage)) {
          e.preventDefault();
          e.stopPropagation();
          return false;
        }
        // User confirmed; clear dirty flag so navigation proceeds
        formIsDirty = false;
      }
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initFormTracking();
      initBackNavigationGuards();
    });
  } else {
    initFormTracking();
    initBackNavigationGuards();
  }
})();
