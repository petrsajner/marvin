# Marvin 1.20.0 - Marvin suggests your next step

## Highlights

- **Your next step is ready in the message field.** While a conversation goes
  on, the model keeps forming an idea of what you will most naturally ask it
  next: what you are working toward, what has been solved and what is still
  open. When the chat is idle and the message field is empty, that idea is
  there as grey text. Press **→** or **Tab** and it becomes your text, to edit
  or send as it is.
- **No extra request and no waiting.** The suggestion is part of the model's
  ordinary replies, so the GPU never works on it separately and nothing slows
  down.
- **Most useful in Development.** There the suggestions lean toward concrete
  follow-up: run or check what was built, fix what is still failing, continue
  with the next planned step, or commit finished work.
- **Yours to switch off.** **Settings > Behavior > Suggest the next step**
  turns it off; the message field then shows its usual placeholder.

## How it works

- **The suggestion grows with the conversation.** The model refines it with
  every reply, including the short progress updates during longer work, so a
  suggestion is ready the moment a task finishes. It is written the way you
  would type it, in your language.
- **Hidden from the conversation.** You never see the suggestion inside a
  reply, neither while it is being written nor afterwards; it only appears in
  the empty message field.
- **When the model offers none, the task's own state fills in.** In order:
  - a check that failed;
  - an unfinished step of the task plan;
  - the first of the next steps in the task's closing summary.
- **It never gets in your way.** The suggestion is shown only in an empty
  message field of an idle chat. Typing anything replaces it. Sending a message
  clears it, and the next task forms a new one. Without a suggestion, Tab moves
  the focus as before.
- Every model in Marvin can offer suggestions. How often and how well each one
  does it varies; when a model offers nothing, the message field simply shows
  its usual placeholder.

## Updating

- Conversations, projects, memories, skills and models stay in place. Nothing
  new is downloaded.
- **The first request in each existing conversation reads the whole
  conversation once more.** The model's instructions now ask for the
  suggestion, so the prompt it had already processed no longer matches. In a
  long conversation that first request takes noticeably longer; the following
  ones are as fast as before. Turning the suggestions off or on has the same
  one-time effect.
- When updating from 1.18 or earlier, Flash-Next's engine is still prepared on
  its first start, as described in the
  [1.19.0 release notes](RELEASE-NOTES-1.19.0.md).
