async (page) => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  let phase = 'idle', started = Date.now() / 1000, release;
  const gate = new Promise(resolve => { release = resolve; });
  const state = () => ({ status: phase === 'ready' ? 'running' : 'down', model: 'q5', vram: '12 / 32 GB', switch: {
    status: phase, phase: phase === 'starting' ? 'loading' : phase, command: 'start', target: 'q5', started_at: started,
  } });
  await page.route('**/api/runtime', route => route.fulfill({ json: state() }));
  await page.route('**/api/runtime/start', async route => {
    phase = 'starting'; started = Date.now() / 1000;
    await gate;
    await route.fulfill({ json: { ok: true, switch: state().switch } });
  });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole('button', { name: 'start', exact: true }).click();
  assert(await page.getByRole('button', { name: 'start', exact: true }).getAttribute('aria-busy') === 'true', 'No immediate Start feedback');
  assert(await page.locator('.model-progress.running').count() === 1, 'Missing startup progress');
  assert(await page.locator('.activity-feedback.pending').count() === 1, 'No pending request feedback');
  release();
  await page.waitForFunction(() => document.querySelector('.model-progress')?.textContent.includes('Načítám model'));
  const animation = await page.getByRole('button', { name: 'start', exact: true }).evaluate(el => getComputedStyle(el).animationName);
  assert(animation.includes('action-breathe'), 'Start does not pulse');
  assert(!(await page.getByRole('button', { name: 'stop', exact: true }).isDisabled()), 'Stop unavailable during load');
  await page.screenshot({ path: 'output/playwright/feedback-model-start.png' });
  phase = 'ready';
  await page.evaluate(() => window.dispatchEvent(new Event('marvin-runtime-refresh')));
  await page.getByText('Model je připravený', { exact: true }).waitFor();
  assert(!(await page.getByRole('button', { name: 'start', exact: true }).isDisabled()), 'Start did not reset after load');
  await page.route('**/api/runtime/start', route => route.fulfill({ status: 500, json: { detail: 'Test load failed' } }));
  await page.getByRole('button', { name: 'start', exact: true }).click();
  await page.locator('.toast').filter({ hasText: 'Test load failed' }).waitFor();
  assert(await page.locator('.activity-feedback.failed').count() === 1, 'Failure not reflected in action feedback');
  await page.getByRole('dialog').getByRole('button', { name: 'Zavřít', exact: true }).click();
  let saved;
  const saveGate = new Promise(resolve => { saved = resolve; });
  await page.route('**/api/settings', async route => { await saveGate; await route.continue(); });
  await page.getByRole('combobox', { name: 'Myšlení', exact: true }).selectOption('medium');
  await page.locator('.activity-feedback.pending').filter({ hasText: 'Ukládání nastavení' }).waitFor();
  saved();
  await page.locator('.activity-feedback.accepted').waitFor();
  await page.unrouteAll({ behavior: 'wait' });
  console.log('PASS: immediate Start, slow response, loading pulse, Stop availability, ready, failure, settings save acknowledgement');
}
