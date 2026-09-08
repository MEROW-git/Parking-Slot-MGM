/**
 * SomPark Toast Notification System
 * Handles auto-dismissal, hover/focus pause & resume, and accessible dismissal.
 */
(function () {
  'use strict';

  function initToasts() {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toasts = container.querySelectorAll('.sp-toast');
    toasts.forEach(function (toast) {
      initToast(toast);
    });
  }

  function initToast(toast) {
    if (toast.dataset.spToastInitialized) return;
    toast.dataset.spToastInitialized = 'true';

    const isAutoDismiss = toast.getAttribute('data-auto-dismiss') === 'true';
    const delay = parseInt(toast.getAttribute('data-delay') || '5000', 10);
    const closeBtn = toast.querySelector('.sp-toast-close');

    let remaining = delay;
    let startTime = Date.now();
    let timerId = null;
    let isPaused = false;

    function dismiss() {
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
      }
      toast.classList.add('sp-toast-dismissing');

      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const animDuration = prefersReducedMotion ? 40 : 260;

      setTimeout(function () {
        toast.remove();
        const container = document.getElementById('toast-container');
        if (container && container.querySelectorAll('.sp-toast').length === 0) {
          container.remove();
        }
      }, animDuration);
    }

    function pause() {
      if (!isAutoDismiss) return;
      isPaused = true;
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
      }
      const elapsed = Date.now() - startTime;
      remaining = Math.max(0, remaining - elapsed);
    }

    function resume() {
      if (!isAutoDismiss || !isPaused) return;
      // Do not resume if user is still hovering or focusing inside the toast
      try {
        if (toast.matches(':hover') || toast.matches(':focus-within')) {
          return;
        }
      } catch (e) {
        // Fallback for older browsers
      }
      isPaused = false;
      startTime = Date.now();
      timerId = setTimeout(dismiss, Math.max(remaining, 1000));
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        dismiss();
      });
    }

    toast.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        dismiss();
      }
    });

    if (isAutoDismiss) {
      toast.addEventListener('mouseenter', pause);
      toast.addEventListener('mouseleave', resume);
      toast.addEventListener('focusin', pause);
      toast.addEventListener('focusout', resume);

      startTime = Date.now();
      timerId = setTimeout(dismiss, delay);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initToasts);
  } else {
    initToasts();
  }
})();
