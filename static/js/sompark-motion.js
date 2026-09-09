/**
 * SomPark Native Motion Controller
 * Lightweight, accessible, zero-dependency progressive motion controller.
 * Utilizes IntersectionObserver for performant, one-time scroll reveals.
 */
(function() {
  'use strict';

  // Guard against non-browser environments
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return;
  }

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

  function isReducedMotion() {
    return motionQuery.matches;
  }

  function revealElement(el) {
    if (!el || el.classList.contains('is-revealed')) return;

    // Apply restrained stagger delay if specified (max 300ms)
    const delayAttr = el.getAttribute('data-reveal-delay');
    if (delayAttr) {
      const delayMs = Math.min(Math.max(parseInt(delayAttr, 10) || 0, 0), 300);
      if (delayMs > 0 && !isReducedMotion()) {
        el.style.transitionDelay = delayMs + 'ms';
      }
    }

    el.classList.add('is-revealed');
  }

  function revealAll() {
    const elements = document.querySelectorAll('[data-reveal]');
    elements.forEach(function(el) {
      el.classList.add('is-revealed');
      el.style.transitionDelay = '';
    });
  }

  function initMotion() {
    try {
      const revealElements = document.querySelectorAll('[data-reveal]');
      if (!revealElements.length) return;

      // If reduced motion is requested, reveal all instantly and exit
      if (isReducedMotion()) {
        revealAll();
        return;
      }

      // Check for IntersectionObserver support
      if (!('IntersectionObserver' in window)) {
        revealAll();
        return;
      }

      // Mark document element for CSS progressive enhancement
      document.documentElement.classList.add('js-motion');

      const observerOptions = {
        root: null,
        rootMargin: '0px 0px -20px 0px',
        threshold: 0.08
      };

      const observer = new IntersectionObserver(function(entries, obs) {
        entries.forEach(function(entry) {
          if (entry.isIntersecting) {
            revealElement(entry.target);
            obs.unobserve(entry.target);
          }
        });
      }, observerOptions);

      // Observe each reveal element
      revealElements.forEach(function(el) {
        // Fast-path: if already intersecting or near top of viewport, reveal immediately
        const rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight && rect.bottom > 0) {
          revealElement(el);
        } else {
          observer.observe(el);
        }
      });

      // Handle dynamic preference changes
      if (motionQuery.addEventListener) {
        motionQuery.addEventListener('change', function(e) {
          if (e.matches) {
            revealAll();
          }
        });
      } else if (motionQuery.addListener) {
        motionQuery.addListener(function(e) {
          if (e.matches) {
            revealAll();
          }
        });
      }

      // Handle browser back/forward cache restoration (bfcache)
      window.addEventListener('pageshow', function(event) {
        if (event.persisted) {
          revealAll();
        }
      });

    } catch (err) {
      // In case of any initialization error, ensure all content is visible
      console.warn('SomPark motion initialization bypassed:', err);
      document.documentElement.classList.remove('js-motion');
      revealAll();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMotion);
  } else {
    initMotion();
  }
})();
