// Run against tests/serve_workspace_fixture.py with Playwright CLI run-code.
async (page) => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const url = new URL('/', page.url()).href;
  const stateUrl = new URL('/api/state', url).href;
  const errors = [];
  const onError = error => errors.push(error.message);
  page.on('pageerror', onError);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  try {
    await page.route(stateUrl, async route => {
      await gate;
      await route.continue();
    });
    await page.goto(url);
    await page.locator('.startup').waitFor({ timeout: 5000 });
    assert(await page.locator('.startup').innerText().then(text => text.includes('Loading workspace')), 'Missing loading message');
    assert(errors.length === 0, 'Startup crashed: ' + errors.join('; '));
    await page.screenshot({ path: 'output/playwright/startup-loading.png' });
    release();
    await page.locator('.workspace').waitFor();
    await page.getByRole('textbox', { name: 'Chat title', exact: true }).waitFor();
    await page.unrouteAll({ behavior: 'wait' });

    await page.route(stateUrl, route => route.fulfill({
      status: 503, json: { detail: 'Workspace service is temporarily unavailable' },
    }));
    await page.reload();
    await page.locator('.startup').filter({ hasText: 'Workspace service is temporarily unavailable' }).waitFor();
    await page.screenshot({ path: 'output/playwright/startup-error.png' });
    await page.unrouteAll({ behavior: 'wait' });

    await page.reload();
    await page.locator('.workspace').waitFor();
    await page.getByRole('textbox', { name: 'Chat title', exact: true }).waitFor();
    assert(errors.length === 0, 'Startup crashed: ' + errors.join('; '));
    await page.screenshot({ path: 'output/playwright/startup-ready.png' });
    console.log('PASS: initial render, delayed workspace state, visible API failure and successful reload without JavaScript errors');
  } finally {
    release();
    await page.unrouteAll({ behavior: 'wait' });
    page.off('pageerror', onError);
  }
}
