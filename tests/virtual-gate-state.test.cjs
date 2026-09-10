// Dependency-free controller unit tests. No browser, server, database or payment API.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/virtual-gate.js'), 'utf8');

function element() {
  const classes = new Set();
  return {
    classList: { add: (...names) => names.forEach(n => classes.add(n)),
      remove: (...names) => names.forEach(n => classes.delete(n)), contains: n => classes.has(n) },
    style: {}, dataset: {}, value: '', disabled: false, textContent: '',
  };
}

function controller(direction = 'exit') {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  };
  let finishOpening;
  const notice = element();
  const sandbox = {
    document: { getElementById: get, querySelector: selector =>
      selector === '.vg-notice' ? notice : selector === 'input[name="mode"]:checked' ? {value: direction} : null },
    Date, Number, Error, FormData,
    setInterval: () => 1, clearInterval: () => {},
    countdownInterval: null, permitExpiresAt: null, isCrossing: false,
    authorizationRevision: 0, isSettlementInFlight: false,
    waitForArmOpening: () => new Promise(resolve => { finishOpening = resolve; }),
    window: { location: { pathname: '/admin/virtual-gate/' } },
    alert: message => { throw Error(message); },
    form: { querySelector: () => ({value: 'csrf'}), getAttribute: () => '/admin/virtual-gate/' },
  };
  for (const [binding, id] of Object.entries({
    sceneEl: 'vg-scene-viewport', passBtn: 'vg-pass', passText: 'vg-pass-text',
    closeBtn: 'vg-close', statusBanner: 'vg-gate-status-banner', statusText: 'vg-status-text',
    permitSecondsEl: 'vg-timer-seconds', permitTimerBanner: 'vg-permit-timer',
    checkBtn: 'btn-check-open', zoneSelect: 'id_zone', codeInput: 'id_code',
  })) sandbox[binding] = get(id);
  sandbox.passBtn.disabled = true;
  sandbox.zoneSelect.value = '1';
  sandbox.codeInput.value = 'SPK-TEST';
  vm.createContext(sandbox);
  // Execute the real function bodies, supplying only DOM/timing/network test doubles.
  for (const name of ['updateGateDirection', 'stopPermitCountdown', 'expirePermit',
    'startPermitCountdown', 'showAuthorizedOpen', 'showGateNotice', 'handleExitSettlement']) {
    const match = source.match(new RegExp(`  (?:async )?function ${name}\\(`));
    assert.ok(match, `Missing controller function ${name}`);
    const start = match.index;
    const end = source.indexOf('\n  }', start) + 4;
    vm.runInContext(source.slice(start, end), sandbox);
  }
  return {sandbox, get, notice, finish: () => finishOpening()};
}

const permit = () => ({gate_open: true, permit: 'signed-permit', permit_expires_at: Math.floor(Date.now()/1000) + 120});

for (const direction of ['entry', 'exit']) {
  test(`${direction}: opens first, enables passage after opening, never auto-moves car`, async () => {
    const c = controller(direction);
    const opening = c.sandbox.showAuthorizedOpen(permit());
    assert.equal(c.sandbox.sceneEl.dataset.direction, direction);
    assert.equal(c.sandbox.sceneEl.classList.contains('is-open'), true);
    assert.equal(c.sandbox.passBtn.disabled, true);
    assert.equal(c.sandbox.sceneEl.classList.contains('is-moving'), false);
    c.finish(); await opening;
    assert.equal(c.sandbox.passBtn.disabled, false);
    assert.equal(c.sandbox.sceneEl.classList.contains('is-moving'), false);
    assert.match(c.sandbox.statusText.textContent, /WAITING FOR VEHICLE/);
  });
}

test('expired permit can reopen without losing its countdown or leaving passage disabled', async () => {
  const c = controller();
  c.sandbox.expirePermit();
  assert.equal(c.sandbox.passBtn.disabled, true);
  assert.equal(c.sandbox.permitSecondsEl.textContent, '0');
  const opening = c.sandbox.showAuthorizedOpen(permit());
  c.finish(); await opening;
  assert.equal(c.sandbox.passBtn.disabled, false);
  assert.ok(Number(c.sandbox.permitSecondsEl.textContent) > 0);
  assert.equal(c.get('vg-pass-actions-box').style.display, 'block');
});

test('expiry while arm opens does not re-enable passage', async () => {
  const c = controller();
  const opening = c.sandbox.showAuthorizedOpen(permit());
  c.sandbox.expirePermit();
  c.finish(); await opening;
  assert.equal(c.sandbox.passBtn.disabled, true);
  assert.equal(c.sandbox.sceneEl.classList.contains('is-open'), false);
});

test('closed, missing, or expired server permits cannot open the visual barrier', async () => {
  for (const data of [{gate_open:false}, {...permit(), permit:null}, {...permit(), permit_expires_at:1}]) {
    const c = controller();
    await assert.rejects(c.sandbox.showAuthorizedOpen(data));
    assert.equal(c.sandbox.sceneEl.classList.contains('is-open'), false);
    assert.equal(c.sandbox.passBtn.disabled, true);
  }
});

test('settled payment with server gate closed never claims the barrier opened', async () => {
  const c = controller();
  c.sandbox.fetch = async () => ({ok:true, json:async () => ({success:true, settled:true, gate_open:false, notice:'Authorization denied'})});
  await c.sandbox.handleExitSettlement('CASH', 'success');
  assert.equal(c.sandbox.sceneEl.classList.contains('is-open'), false);
  assert.equal(c.sandbox.passBtn.disabled, true);
  assert.equal(c.notice.textContent, 'Authorization denied');
});

test('payment success opens barrier and waits; repeated clicks do not submit twice', async () => {
  const c = controller();
  let calls = 0;
  c.sandbox.fetch = async () => {
    calls++;
    return {ok:true, json:async () => ({...permit(), success:true, settled:true})};
  };
  const settlement = c.sandbox.handleExitSettlement('CASH', 'success');
  await c.sandbox.handleExitSettlement('CASH', 'success');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  assert.equal(c.sandbox.passBtn.disabled, true);
  c.finish(); await settlement;
  assert.equal(c.sandbox.passBtn.disabled, false);
  assert.equal(c.sandbox.sceneEl.classList.contains('is-moving'), false);
});

test('response for an edited ticket cannot open a different ticket gate', async () => {
  const c = controller();
  let respond;
  c.sandbox.fetch = () => new Promise(resolve => {respond = resolve;});
  const request = c.sandbox.handleExitSettlement('CASH', 'success');
  c.sandbox.authorizationRevision++;
  respond({ok:true, json:async () => ({...permit(), success:true, settled:true})});
  await request;
  assert.equal(c.sandbox.sceneEl.classList.contains('is-open'), false);
});
