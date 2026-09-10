/**
 * SomPark Real-Time Status Synchronization Engine
 * Lightweight, visibility-aware, robust synchronization across open tabs and pages.
 *
 * Rules & Guarantees:
 * - Read-only GET requests every 12s while visible (10–15s window).
 * - Pauses polling in hidden tabs; resumes immediately with >=3s throttling on tab focus/online.
 * - Prevents overlapping requests; backs off with jitter on errors and respects HTTP 429 Retry-After.
 * - Batches queries for dashboard and history lists.
 * - Rejects stale/out-of-order responses using monotonic server timestamps.
 * - Stops polling when tickets reach terminal states (CHECKED_OUT, CANCELLED, EXPIRED).
 * - Renders countdowns locally without polling every second.
 */
(() => {
  'use strict';

  const DEFAULT_INTERVAL_MS = 12000;
  const MIN_THROTTLE_MS = 3000;
  const MAX_BACKOFF_MS = 60000;

  class StatusPoller {
    constructor(options) {
      this.fetchFn = options.fetchFn;
      this.onSuccess = options.onSuccess;
      this.onError = options.onError || null;
      this.intervalMs = options.intervalMs || DEFAULT_INTERVAL_MS;
      this.currentIntervalMs = this.intervalMs;
      this.isTerminalFn = options.isTerminalFn || (() => false);

      this.timerId = null;
      this.inFlight = false;
      this.lastPollTime = 0;
      this.lastAppliedVersion = 0;
      this.stopped = false;
      this.abortController = null;
      this.consecutiveFailures = 0;

      this.boundVisibilityHandler = this.handleVisibilityChange.bind(this);
      this.boundOnlineHandler = this.handleOnline.bind(this);
      this.boundUnloadHandler = this.stop.bind(this);

      document.addEventListener('visibilitychange', this.boundVisibilityHandler);
      window.addEventListener('online', this.boundOnlineHandler);
      window.addEventListener('pagehide', this.boundUnloadHandler);
      window.addEventListener('beforeunload', this.boundUnloadHandler);

      this.schedule(this.intervalMs);
    }

    schedule(delayMs) {
      this.clearTimer();
      if (this.stopped || document.hidden) return;
      this.timerId = setTimeout(() => {
        this.poll();
      }, Math.max(100, delayMs));
    }

    clearTimer() {
      if (this.timerId) {
        clearTimeout(this.timerId);
        this.timerId = null;
      }
    }

    handleVisibilityChange() {
      if (document.hidden) {
        this.clearTimer();
        if (this.abortController) {
          try { this.abortController.abort(); } catch (_) {}
          this.abortController = null;
          this.inFlight = false;
        }
      } else {
        const elapsed = Date.now() - this.lastPollTime;
        if (elapsed >= MIN_THROTTLE_MS) {
          this.poll();
        } else {
          this.schedule(MIN_THROTTLE_MS - elapsed);
        }
      }
    }

    handleOnline() {
      if (document.hidden || this.stopped) return;
      const elapsed = Date.now() - this.lastPollTime;
      if (elapsed >= MIN_THROTTLE_MS) {
        this.poll();
      } else {
        this.schedule(MIN_THROTTLE_MS - elapsed);
      }
    }

    async poll() {
      if (this.stopped || this.inFlight || document.hidden) return;

      this.inFlight = true;
      this.lastPollTime = Date.now();
      this.abortController = new AbortController();

      try {
        const res = await this.fetchFn(this.abortController.signal);

        if (res.status === 429) {
          const retryAfter = parseInt(res.headers.get('Retry-After') || '30', 10);
          const backoff = (retryAfter > 0 ? retryAfter : 30) * 1000;
          this.currentIntervalMs = Math.min(MAX_BACKOFF_MS, backoff);
          this.schedule(this.currentIntervalMs);
          return;
        }

        if (!res.ok) {
          throw new Error(`HTTP error status ${res.status}`);
        }

        const data = await res.json();
        this.consecutiveFailures = 0;
        this.currentIntervalMs = this.intervalMs;

        // Reject stale / out-of-order data
        if (data.version && data.version < this.lastAppliedVersion) {
          // Stale response ignored
        } else {
          if (data.version) this.lastAppliedVersion = data.version;
          this.onSuccess(data);
        }

        if (this.isTerminalFn(data)) {
          this.stop();
          return;
        }

        this.schedule(this.intervalMs);
      } catch (err) {
        if (err.name === 'AbortError') return;

        this.consecutiveFailures++;
        if (this.onError) this.onError(err, this.consecutiveFailures);

        // Exponential backoff with jitter
        const base = Math.min(MAX_BACKOFF_MS, this.currentIntervalMs * 2);
        const jitter = (0.8 + Math.random() * 0.4); // ±20% jitter
        this.currentIntervalMs = Math.round(base * jitter);
        this.schedule(this.currentIntervalMs);
      } finally {
        this.inFlight = false;
        this.abortController = null;
      }
    }

    stop() {
      this.stopped = true;
      this.clearTimer();
      if (this.abortController) {
        try { this.abortController.abort(); } catch (_) {}
        this.abortController = null;
      }
      document.removeEventListener('visibilitychange', this.boundVisibilityHandler);
      window.removeEventListener('online', this.boundOnlineHandler);
      window.removeEventListener('pagehide', this.boundUnloadHandler);
      window.removeEventListener('beforeunload', this.boundUnloadHandler);
    }
  }

  // Active Pollers Registry
  const pollers = new Map();

  const SomParkSync = {
    /**
     * Start observing a single ticket by ticket_code.
     */
    observeTicket(ticketCode, onUpdate, options = {}) {
      if (!ticketCode) return null;
      const key = `ticket:${ticketCode}`;
      if (pollers.has(key)) {
        pollers.get(key).stop();
      }

      const poller = new StatusPoller({
        fetchFn: (signal) => fetch(`/api/ticket/${encodeURIComponent(ticketCode)}/status/`, {
          method: 'GET',
          headers: { 'Accept': 'application/json' },
          signal,
        }),
        onSuccess: (data) => {
          if (typeof onUpdate === 'function') onUpdate(data);
        },
        onError: options.onError,
        intervalMs: options.intervalMs || DEFAULT_INTERVAL_MS,
        isTerminalFn: (data) => Boolean(data && data.is_terminal),
      });

      pollers.set(key, poller);
      return poller;
    },

    /**
     * Start observing a batch of tickets (e.g. for dashboard or ticket history).
     */
    observeBatchTickets(ticketCodes, onUpdate, options = {}) {
      const activeCodes = Array.from(new Set((ticketCodes || []).filter(Boolean)));
      if (!activeCodes.length) return null;

      const key = `batch:${activeCodes.sort().join(',')}`;
      if (pollers.has(key)) {
        pollers.get(key).stop();
      }

      let remainingCodes = [...activeCodes];

      const poller = new StatusPoller({
        fetchFn: (signal) => fetch(`/api/tickets/status/?codes=${encodeURIComponent(remainingCodes.join(','))}`, {
          method: 'GET',
          headers: { 'Accept': 'application/json' },
          signal,
        }),
        onSuccess: (data) => {
          if (data && data.tickets && typeof onUpdate === 'function') {
            onUpdate(data.tickets);
            // Drop terminal tickets from subsequent polls
            remainingCodes = remainingCodes.filter(code => {
              const t = data.tickets[code];
              return !(t && t.is_terminal);
            });
          }
        },
        intervalMs: options.intervalMs || DEFAULT_INTERVAL_MS,
        isTerminalFn: () => remainingCodes.length === 0,
      });

      pollers.set(key, poller);
      return poller;
    },

    /**
     * Start observing live parking zone availability.
     */
    observeZones(slugs, onUpdate, options = {}) {
      const key = `zones:${(slugs || []).join(',')}`;
      if (pollers.has(key)) {
        pollers.get(key).stop();
      }

      const queryStr = slugs && slugs.length ? `?slugs=${encodeURIComponent(slugs.join(','))}` : '';
      const poller = new StatusPoller({
        fetchFn: (signal) => fetch(`/api/zones/status/${queryStr}`, {
          method: 'GET',
          headers: { 'Accept': 'application/json' },
          signal,
        }),
        onSuccess: (data) => {
          if (data && data.zones && typeof onUpdate === 'function') {
            onUpdate(data.zones);
          }
        },
        intervalMs: options.intervalMs || DEFAULT_INTERVAL_MS,
      });

      pollers.set(key, poller);
      return poller;
    },

    /**
     * Immediately applies new state into local cache and triggers any active poller callback.
     * Useful when the acting page receives an immediate server response from a POST action.
     */
    applyState(ticketCode, data) {
      if (!ticketCode || !data) return;
      const key = `ticket:${ticketCode}`;
      const poller = pollers.get(key);
      if (poller) {
        if (data.version) poller.lastAppliedVersion = data.version;
        if (poller.onSuccess) poller.onSuccess(data);
        if (data.is_terminal) poller.stop();
      }
    },

    /**
     * Local high-performance countdown timer helper.
     * Updates an element every 1 second locally from a server-issued ISO deadline.
     */
    bindCountdown(elementIdOrEl, targetIsoString, onExpire = null) {
      const el = typeof elementIdOrEl === 'string' ? document.getElementById(elementIdOrEl) : elementIdOrEl;
      if (!el || !targetIsoString) return null;

      const targetTime = new Date(targetIsoString).getTime();
      if (isNaN(targetTime)) return null;

      function formatRemaining(totalSec) {
        const hours = Math.floor(totalSec / 3600);
        const mins = Math.floor((totalSec % 3600) / 60);
        const secs = totalSec % 60;
        if (hours > 0) {
          return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
      }

      function update() {
        const now = Date.now();
        const diffSec = Math.max(0, Math.floor((targetTime - now) / 1000));
        el.textContent = formatRemaining(diffSec);

        if (diffSec <= 0) {
          clearInterval(timer);
          if (typeof onExpire === 'function') onExpire();
        }
      }

      update();
      const timer = setInterval(update, 1000);
      return timer;
    },

    stopAll() {
      pollers.forEach(poller => poller.stop());
      pollers.clear();
    }
  };

  window.SomParkSync = SomParkSync;
})();
