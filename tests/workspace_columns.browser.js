async (page) => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const left = page.getByRole('separator', { name: 'Navigation width' });
  const right = page.getByRole('separator', { name: 'Detail width' });
  const widths = () => page.evaluate(() => ({
    left: document.querySelector('.sidebar-region').getBoundingClientRect().width,
    right: document.querySelector('.detail').getBoundingClientRect().width,
    overflow: document.documentElement.scrollWidth > innerWidth,
    chats: document.querySelectorAll('.chat-list button:not(.older-chats)').length,
    fits: [...document.querySelectorAll('.chat-list button:not(.older-chats)')].every(b => {
      const button = b.getBoundingClientRect(), text = b.querySelector('span').getBoundingClientRect();
      return text.bottom <= button.bottom && text.top >= button.top;
    }),
  }));
  await page.setViewportSize({ width: 1440, height: 960 });
  await left.waitFor();
  let state = await widths();
  assert(state.left === 330 && state.right === 427.5, 'Default columns are not 50% wider');
  assert(state.chats === 20 && state.fits && !state.overflow, 'Initial chat list layout');
  await page.getByRole('button', { name: 'Show older (6)' }).click();
  assert((await widths()).chats === 26, 'Older conversations did not expand');
  await page.getByRole('button', { name: 'Show recent only' }).click();
  assert((await widths()).chats === 20, 'Conversation collapse failed');
  for (const [handle, dx] of [[left, 70], [right, -50]]) {
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + dx, box.y + 100, { steps: 10 });
    await page.mouse.up();
  }
  state = await widths();
  assert(state.left === 400 && state.right === 478 && !state.overflow, 'Dragging failed');
  await left.dblclick();
  assert((await widths()).left === 330, 'Double-click reset failed');
  await page.reload();
  await left.waitFor();
  state = await widths();
  assert(state.left === 330 && state.right === 427.5 && state.chats === 20, 'Reload must reset widths and pagination');
  for (const [width, height] of [[1920,1080],[1366,768],[1024,768],[720,450],[390,844]]) {
    await page.setViewportSize({ width, height });
    assert(!(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)), `Overflow at ${width}`);
    const prompt = await page.getByRole('textbox', { name: 'Message' }).boundingBox();
    assert(prompt.width > 100 && prompt.y + prompt.height <= height, `Prompt unavailable at ${width}`);
    await page.screenshot({ path: `output/playwright/columns-${width}.png` });
  }
  console.log('PASS: defaults, drag both columns, reset, 20/26 chat pagination, multiline titles, 5 viewports');
}
