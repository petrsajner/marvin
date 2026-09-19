---
name: testing-a-running-program
description: Test a program you started - a game, a tool, anything with a window - without taking the screen away from the user. Covers watching and driving one window directly, and running an SDL or pygame program with no window at all so its logic can be checked quickly.
---

# Testing a Running Program

The user is working on this machine while you test. Two things follow from that:
the screen is not yours, and a plain `screenshot()` shows whatever is in front -
usually the user's browser, not the program you started. Both paths below avoid
that.

## Which path

| Question | Path |
|---|---|
| Does it look right? Does the user's own copy behave? | **Window path** below |
| Does the logic work? Does this input produce that state? | **Headless path** below |

The headless path is faster, needs no screen and cannot be disturbed. Use it for
anything that is really about behaviour rather than appearance.

## Window path - watch and drive one window

1. `list_windows` - find the title. Never assume the program is in front.
2. `screenshot(window="its title")` - photographs that window where it stands,
   even covered by something else. Coordinates in the image belong to the window,
   so a later `click` lands where the picture showed it.
3. `press_key(keys, window="its title")` - sends the key into that program
   without bringing it forward. Verified against a covered pygame window: enter,
   arrows, letters and `ctrl+s` all arrive, and the window in front receives
   nothing.
4. Verify with another `screenshot(window=...)`. Always. A key that was accepted
   by the queue is not the same as a key the program acted on.
5. **Only if step 3 does nothing**: `focus_window("its title")`, then press the
   key normally. Some programs read the keyboard directly rather than through
   window messages and can only be reached while in front - which takes the
   screen from the user, so it is the fallback, not the opening move.
6. A game that misses a tap needs a longer press, not a repeated one:
   `press_key("left", hold=0.3)`.

A minimised window has nothing to photograph; restore it with `focus_window`
first, or say that you need it open.

## Headless path - no window at all

SDL programs, which includes everything written with pygame, will run with no
window when the driver is set to `dummy`. Nothing appears on screen, rendering
happens in memory, and a frame can be written to a PNG that you then look at with
`view_image`.

```python
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"     # Before importing pygame.
os.environ["SDL_AUDIODRIVER"] = "dummy"     # Silence, and no audio device needed.
import pygame

pygame.init()
screen = pygame.display.set_mode((320, 240))   # Still required; it just has no window.

for step in range(60):                         # Step the loop yourself.
    update_game_state()
    draw(screen)
    pygame.display.flip()

pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
handle_events(pygame.event.get())              # Posted events are delivered normally.

pygame.image.save(screen, "frame.png")         # Then view_image("frame.png").
```

Run it through `shell`, with the interpreter that has pygame installed - the
project's own environment if it has one.

Rules that keep a headless test honest:

- **Step the loop; do not sleep.** `pygame.time.wait` and `clock.tick` turn a
  one-second test into a one-second wait for no benefit. Call the update function
  the number of times the test needs.
- **Post events instead of pressing keys.** `pygame.event.post` puts input into
  the program's own queue; there is no window for a real key to reach.
- **Assert on state, not on pixels,** wherever the state is reachable. A saved
  frame is for the questions state cannot answer.
- **Say which path produced a result.** A headless run proves the logic; it does
  not prove the window the user opens behaves the same way.

## Reporting

Say what you sent, what you saw, and by which path. "Posted enter to the game
window; the screenshot shows the score at 0 and the ship at the left edge" is a
result. "Pressed enter" is not.
