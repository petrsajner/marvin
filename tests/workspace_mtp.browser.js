// Run against tests/serve_workspace_fixture.py, never personal settings.
async (page) => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const errors = [];
  const onError = error => errors.push(error.message);
  const stateUrl = new URL('/api/state', page.url()).href;
  page.on('pageerror', onError);
  try {
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Advanced', exact: true }).click();
    await dialog.getByRole('combobox', { name: 'Model', exact: true }).selectOption('q5');
    const cache = dialog.getByRole('combobox', { name: 'KV cache profile', exact: true });
    await cache.selectOption('q8_0');
    const toggle = dialog.getByRole('button', { name: 'Speculative decoding (MTP)', exact: true });
    const enabled = dialog.locator('button.positive').filter({ hasText: 'Speculative decoding (MTP)' });
    const profile = async () => (await (await page.request.get(stateUrl)).json()).preferences.kv_cache_modes.q5;
    assert(!(await cache.locator('option').allTextContents()).some(text => text.includes('MTP')), 'Base-profile menu contains MTP entries');
    if (await enabled.count()) {
      await toggle.click();
      await enabled.waitFor({ state: 'hidden' });
    }
    await toggle.click();
    await enabled.waitFor();
    assert(await profile() === 'q8_0_mtp', 'Advanced toggle did not enable MTP');
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/settings') && response.request().method() === 'PATCH' && response.ok()),
      cache.selectOption('q8_0_128k'),
    ]);
    assert(await profile() === 'q8_0_128k_mtp', 'Changing context lost the MTP selection');
    await cache.selectOption('f16');
    await enabled.waitFor({ state: 'hidden' });
    assert(await toggle.isDisabled(), 'Unsupported cache profile offers MTP');
    assert(await profile() === 'f16', 'Unsupported cache profile did not remove MTP');
    await cache.selectOption('q8_0');
    await toggle.waitFor({ state: 'visible' });
    await dialog.getByRole('button', { name: 'Simple', exact: true }).click();
    await cache.waitFor({ state: 'hidden' });
    await toggle.click();
    await enabled.waitFor();
    assert(await profile() === 'q8_0_mtp', 'Simple toggle did not enable MTP');
    await toggle.click();
    await enabled.waitFor({ state: 'hidden' });
    assert(await profile() === 'q8_0', 'Simple toggle did not disable MTP');
    await page.screenshot({ path: 'output/playwright/mtp-settings.png' });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    assert(errors.length === 0, 'MTP settings crashed: ' + errors.join('; '));
    console.log('PASS: MTP toggles in Simple and Advanced, context pairing and unsupported cache profiles');
  } finally {
    page.off('pageerror', onError);
  }
}
