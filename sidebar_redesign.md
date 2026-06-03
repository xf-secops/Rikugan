# Rikugan Chat Sidebar And Workspace Redesign Brief

## Summary

The current Rikugan chat/session UI is still visually uncomfortable and inconsistent after several implementation attempts. The goal is to redesign the chat workspace so it feels like a calm, native, agentic reverse-engineering tool inside both IDA Pro and Binary Ninja.

The user wants the UI to resemble the provided reference image: a lean chat/session sidebar on the left, a readable agent conversation area in the center, and a quiet composer at the bottom. The design should feel closer to VS Code Codex/Cursor-style agent panels than a raw Qt form.

This brief is for a design-focused implementation agent. Do not push changes. Do not commit unless explicitly requested.

## What The User Wants

- A polished chat-session management UI for both IDA and Binary Ninja.
- Multiple chats/threads that can run in parallel.
- Clear per-chat state: running, queued, awaiting approval, cancelled, error.
- Ability to create, switch, fork, export, and delete chats.
- A sidebar that looks quiet, compact, useful, and native to the host.
- A chat workspace that is comfortable in both dark and light themes.
- No hardcoded black text on dark surfaces.
- No giant white chat canvas inside dark mode.
- No pure black assistant bubbles or composer input.
- No raw/newline `QListWidgetItem` text duplication.
- No confusing `"New Chat"` title shown as if it is a real existing conversation.
- Bottom composer should be aligned with the chat column, not the sidebar.
- Bottom composer should only expose primary actions: `Send` and conditional `Stop`/`Queue`.
- Secondary actions should not be a noisy vertical rail.
- Settings/tools should be reachable but not visually dominant.

## Current Problems Seen By User

The latest UI still looks bad, especially in IDA:

- Dark mode can show a huge light/white chat canvas while the host dock is dark.
- Assistant response content can sit in an overly black/deep box.
- Composer input can be too black or mismatched with the chat surface.
- Some text appears hardcoded black and becomes unreadable on dark surfaces.
- Light mode can become harsh and not comfortable.
- Sidebar is functional but still visually rough:
  - Button styling is too blocky.
  - Typography and spacing are not refined enough.
  - Row selected/hover states do not feel native or calm.
  - It still does not match the reference image closely enough.
- The overall layout still feels like pieces bolted together rather than one integrated agent panel.

## Reference Direction

The reference image shows:

- A left sidebar titled `Chats`.
- Search at the top.
- Compact chat rows:
  - title
  - metadata line, such as `2 threads`, `1 change`, age, or status
  - optional badge, such as `Awaiting Approval`
  - selected row has a calm highlighted background
- Tiny toolbar affordances, not large primary buttons.
- Main chat content is readable and centered in the available workspace.
- Agent response is not a giant card stack; it feels like a work surface.
- Tool-call status is visible but quiet.
- The composer is a low-noise bar at the bottom.

Approximate layout:

```text
+-----------------------------+------------------------------------------+
| Chats                       +|                                          |
| [search chats............]   | Agent conversation / work transcript      |
|                              |                                          |
| > BackgroundAutomation       |   User request bubble                     |
|   2 threads                  |                                          |
|                              |   Rikugan response                        |
| > Authentication Methods...  |   - concise result text                   |
|   1 thread                   |   - tool call summaries                   |
|                              |   - approval/cancel/error states          |
| * Rename key-exchange...     |                                          |
|   2 threads - 1 change       |                                          |
|   [Awaiting Approval]        |                                          |
|                              |------------------------------------------|
|                              | > input field                         Send|
+-----------------------------+------------------------------------------+
```

## Existing Implementation Context

Important files:

- `rikugan/ui/panel_core.py`
  - Owns the main panel layout.
  - Contains `ChatThreadList` and `ChatThreadRow`.
  - Owns chat switching, create/fork/delete/export callbacks.
  - Builds composer action buttons.

- `rikugan/ui/chat_view.py`
  - Scrollable message area.
  - Uses `QScrollArea#chat_scroll` and `QWidget#chat_container`.
  - Needs explicit styling so host Qt does not fill the viewport with an unintended palette role.

- `rikugan/ui/message_widgets.py`
  - User/assistant/error/queued/question/tool-like message widgets.
  - Still needs a coherent semantic color model across all message types.

- `rikugan/ui/input_area.py`
  - Composer text editor.
  - Needs to align visually with chat surface and support light/dark readability.

- `rikugan/ui/markdown.py`
  - Markdown-to-Qt HTML renderer.
  - Code/link/list/heading colors must match assistant bubble colors.

- `rikugan/ui/styles.py`
  - Central style helpers.
  - Recent attempts added palette helpers, but the result is still visually wrong.
  - A design-focused pass should simplify and stabilize this instead of layering more ad hoc blends.

## Implementation History / Attempts

Recent work attempted:

- Added `ChatThreadRow` custom row widgets.
- Cleared backing `QListWidgetItem` text to avoid duplicate visible row text.
- Added a sidebar component with header, search, action toolbar, and row widgets.
- Removed the bottom vertical rail of `New`, `Export`, `Settings`, `Tools`.
- Moved composer under the chat column so it does not span the sidebar.
- Added per-chat running/queued/approval/error/cancelled statuses.
- Added palette-aware helper functions and tests.
- Tried to fix assistant/input colors by deriving surfaces from host palettes.
- Tried to explicitly style `chat_scroll` and `chat_container`.

Despite this, the visual result is still unacceptable to the user.

## Design Requirements

### Sidebar

Use a calm host-native sidebar:

- Width around 240-320 px, resizable through splitter.
- Header:
  - `Chats` label.
  - Small new-chat affordance, ideally icon-like or tiny text button.
- Search directly under header.
- Small toolbar for secondary actions:
  - New
  - Fork
  - Export
  - Delete
  - Settings only if there is no better top-level place
- Toolbar should not look like chunky web buttons.
- Rows must be custom widgets:
  - one title line
  - one muted metadata line
  - optional badge
  - no duplicated fallback item text
  - fixed row height or stable min height
  - text elision for long titles
  - selected and hover states must be visible but subtle
- Row status should be obvious:
  - Running
  - Queued
  - Awaiting Approval
  - Cancelled
  - Error
- Delete/fork/export must target the selected chat.
- Clicking rows must switch active chat reliably.

### Main Chat Workspace

The chat workspace should feel integrated with the host:

- In dark mode:
  - no white chat canvas
  - no hard black message/input panels
  - text should be light enough to read
  - surfaces should be near host dark gray, with gentle elevation
- In light mode:
  - no overly dark assistant boxes
  - text should be dark enough to read
  - surfaces should be light neutral, not pure white everywhere
- Message bubbles:
  - user messages visually distinct but not neon
  - assistant messages calm and readable
  - error/cancelled states use existing error color language
  - queued messages visible but quiet
- Markdown:
  - bullets, numbered lists, bold text, inline code, fenced code, and links must be readable
  - code blocks should not look pasted from a dark theme when in light mode
- Tool call/approval widgets must not introduce hardcoded black/white conflicts.

### Composer

The composer should be lean:

- Input dominates the width.
- Buttons:
  - `Send`
  - `Stop` only when running
  - `Queue` state only if message will queue during active run
- No bottom vertical rail for secondary actions.
- Placeholder text should be readable in dark and light themes.
- Border/focus state should be subtle and consistent.
- Composer should align with main chat column, not with sidebar.

### Theme Strategy

Do not trust arbitrary child widget palettes. IDA and Qt can report conflicting palette roles:

- `Window` may represent the dock.
- `Base` may become white inside text/scroll widgets even in dark mode.
- Child widget palettes can be black or white while the surrounding panel is not.

Recommended strategy:

- Define a small semantic color system for Rikugan chat:
  - `panel`
  - `sidebar`
  - `chat_canvas`
  - `assistant_bg`
  - `user_bg`
  - `input_bg`
  - `tool_bg`
  - `text`
  - `muted`
  - `border`
  - `accent`
  - `danger`
- Derive these from a stable source:
  - ideally the main `RikuganPanelCore` or chat page palette
  - use `Window` as the baseline for panel/chat surfaces
  - avoid using `Base` as the primary chat background source
- Apply explicit styles to:
  - chat scroll viewport
  - chat container
  - assistant/user/message widgets
  - input area
  - Markdown generated HTML
  - sidebar rows and search field

## Behavioral Requirements

- Existing multi-chat behavior must remain:
  - create chat
  - switch chat
  - fork chat
  - delete chat
  - export chat
  - run chats in parallel
  - per-chat queue and approval status
- New chat should create a fresh independent chat without asking to clear context.
- Cancelled runs should appear in history as a visible `Cancelled by user` style message.
- Session restore/settings behavior should not regress.
- Shared UI must work in both IDA and Binary Ninja.

## Acceptance Criteria

IDA dark mode:

- Chat canvas is dark/neutral, not white.
- Assistant response area is not pure black and not a giant harsh card.
- Composer input is readable and not pure black.
- No black text appears on dark surfaces.
- Sidebar rows, search, and toolbar are readable.

IDA light mode:

- Chat canvas is light/neutral and not harsh.
- Assistant responses are light with readable dark text.
- Markdown code/link/list text is readable.
- Sidebar remains compact and pleasant.

Binary Ninja:

- Shared UI still renders correctly.
- Sidebar and chat layout remain usable.
- No IDA-specific hacks break Binja.

Interaction:

- Clicking a sidebar row switches chats.
- Status badges update without overlapping title/detail.
- `Send`, `Stop`, and `Queue` states work.
- Delete/fork/export affect the selected chat only.

## Suggested Test Coverage

Add or keep tests for:

- Custom sidebar row does not leave visible `QListWidgetItem` fallback text.
- Row status badges render once.
- Row filtering uses stored title/detail, not item text.
- Chat view stylesheet explicitly styles `QScrollArea#chat_scroll` and `QWidget#chat_container`.
- Dark palette with white `Base` does not create white chat canvas.
- Light palette with dark text creates readable light assistant/input surfaces.
- Dark palette with black text role gets repaired.
- Markdown generated styles are readable in both themes.
- Composer exposes only `Send` and `Stop`/`Queue`.

Regression commands:

```powershell
py -3 -m pytest tests -q
py -3 -m ruff check <modified files>
py -3 -m py_compile <modified ui files>
git diff --check
```

## Notes For The Next Agent

- The user is frustrated with incremental color tweaks. Prefer a coherent design pass.
- Do not just add more blend constants without first defining semantic roles.
- Avoid hardcoded black/white except as blend targets inside helpers.
- If a host palette is unreliable, explicitly style the local chat workspace.
- The UI should feel calm, useful, and native, not flashy.
- No push. No commit unless the user asks.
