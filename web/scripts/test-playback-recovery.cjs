const { stripTypeScriptTypes } = require('node:module');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = readFileSync('src/lib/listen.ts', 'utf8').replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
function setup() {
  let element; let timerId = 0;
  const timers = new Map(); const attempts = [];
  class Audio {
    constructor() { element = this; this.events = {}; this.currentTime = 0; this.paused = true; }
    addEventListener(k, fn) { this.events[k] = fn; }
    set src(v) { this.url = v; attempts.push(v); }
    getAttribute() { return this.url; }
    play() { this.paused = false; return Promise.resolve(); }
    pause() { this.paused = true; this.events.pause?.(); }
    load() {}
    removeAttribute() { this.url = ''; }
    fire(k) { this.error = k === 'error' ? {} : null; this.events[k]?.(); }
  }
  const store = { getItem: () => null, setItem() {}, removeItem() {} };
  const c = vm.createContext({ Audio, AbortController, console, performance, localStorage: store, sessionStorage: store,
    navigator: {}, window: { addEventListener() {} }, document: { addEventListener() {} },
    setInterval() {}, setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; }, clearTimeout(id) { timers.delete(id); },
    useSyncExternalStore() {}, api: { listen: () => new Promise(() => {}) },
    errorMessage: e => String(e), isAbort: () => false, listenStreamUrl: ref => ref, startDownload() {},
    hubEvents: { on() {} }, NATIVE_PLAYING_EVENT: 'native', canPlayAll: () => false, pauseNative() {}, webPlayerShown() {},
    listeningAccount: () => null, newEventId: () => 'id', newLaunch: () => ({}), playEvent() {}, routeContext: () => 'other',
  });
  vm.runInContext(stripTypeScriptTypes(source), c);
  const run = s => vm.runInContext(s, c);
  const tick = ms => { const entry = [...timers].find(([, t]) => t.ms === ms); assert.ok(entry, 'expected timer ' + ms); timers.delete(entry[0]); entry[1].fn(); };
  return { run, tick, attempts, fail() { element.fire('error'); }, good() { element.fire('playing'); } };
}
const tracks = "[{ref:'good', title:'G', artist:'A'}, {ref:'bad', title:'B', artist:'A'}, {ref:'next', title:'N', artist:'A'}]";
{
 const t = setup(); t.run(`listenAll(${tracks})`); t.good(); t.run('next()');
 t.fail(); t.fail(); t.tick(1000); t.fail(); t.tick(1000); t.fail(); t.tick(1000);
 assert.deepEqual(t.attempts, ['good', 'bad', 'bad', 'bad', 'next']);
 t.fail(); t.tick(1000); assert.equal(t.attempts.at(-1), 'good');
 t.fail(); t.tick(1000); assert.equal(t.run('getListenState().phase'), 'error');
 console.log('PASS: two retries, duplicate failure deduplication, next, last successful, bounded fallback');
}
{
 const t = setup(); t.run(`listenAll(${tracks})`); t.fail(); t.run('pause()');
 assert.throws(() => t.tick(1000)); assert.equal(t.run('getListenState().phase'), 'paused');
 console.log('PASS: user pause cancels scheduled retry');
}
{
 const t = setup(); t.run(`listenAll(${tracks})`); t.tick(30000); t.tick(1000);
 assert.deepEqual(t.attempts, ['good', 'good']);
 t.fail(); t.run('next()'); assert.throws(() => t.tick(1000));
 t.run('stopListening()'); assert.throws(() => t.tick(30000));
 console.log('PASS: stalled start timeout, manual next and stop cancel old recovery');
}
