// V-M-A11Y: resource errors are distinct from actual accessibility violations.
const test = require('node:test');
const assert = require('node:assert/strict');
const { preflight, errorCode, MIN_TMP_BYTES } = require('../tools/a11y_check.cjs');
test('bounded tmpfs refuses to launch Chromium with less than 64 MiB', () => {
  assert.throws(() => preflight({ tmp_free_bytes: MIN_TMP_BYTES - 1 }), { code: 'tmp_space_low' });
  assert.doesNotThrow(() => preflight({ tmp_free_bytes: MIN_TMP_BYTES }));
  assert.throws(() => preflight({}), { code: 'tmp_unavailable' });
});
test('low tmp explains a crash; ample tmp does not imply OOM', () => {
  assert.equal(errorCode(new Error('page.addScriptTag: Target crashed'), {tmp_free_bytes: 100}), 'tmp_space_low');
  assert.equal(errorCode(new Error('page.addScriptTag: Target crashed'), {tmp_free_bytes: MIN_TMP_BYTES}), 'browser_crashed');
  assert.equal(errorCode({name: 'TimeoutError'}, {}), 'browser_timeout');
  assert.equal(errorCode(new Error('secret diagnostic'), {}), 'browser_error');
});
