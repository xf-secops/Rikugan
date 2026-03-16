"""Research mode: explore a binary and produce Obsidian-style markdown notes."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...core.logging import log_error, log_info
from ...core.types import Message, Role
from ..exploration_mode import ExplorationState, KnowledgeBase
from ..subagent import SubagentRunner
from ..turn import TurnEvent
from .phase_tracker import ModePhaseTracker
from .turn_helpers import execute_single_turn

if TYPE_CHECKING:
    from ..loop import AgentLoop


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ResearchNote:
    """A single research note written to disk."""

    genre: str
    title: str
    slug: str
    path: str
    content: str
    related_notes: list[str] = field(default_factory=list)
    reviewed: bool = False
    review_passed: bool = False


@dataclass
class ResearchState:
    """State for a research mode session."""

    notes_dir: str
    notes_written: list[ResearchNote] = field(default_factory=list)
    knowledge_base: KnowledgeBase = field(default_factory=KnowledgeBase)
    explore_turns: int = 0
    max_explore_turns: int = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert a title to a filesystem-safe slug."""
    # Normalize unicode, lowercase, replace spaces/special chars with hyphens
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-") or "untitled"


def _ensure_dir(path: str) -> None:
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


def _preview_lines(content: str, n: int = 2) -> str:
    """Return the first *n* non-empty lines as a preview."""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    return " | ".join(lines[:n])


# ---------------------------------------------------------------------------
# System prompt addendum for research mode
# ---------------------------------------------------------------------------

RESEARCH_SYSTEM_ADDENDUM = """\

## Research Mode — Active

You are in **research mode**. The user's request is about **the binary currently \
loaded in the analysis tool** — NOT about you, your workflow, or your instructions. \
Your job is to use analysis tools to investigate the binary and answer the user's \
question about it.

**START by calling analysis tools** (get_binary_info, list_imports, list_strings, \
search_functions, decompile_function, etc.) to investigate the binary. Do NOT \
describe your own process or capabilities — just start analyzing.

### CRITICAL — Log every finding with `exploration_report`:
You **MUST** call `exploration_report` whenever you discover something relevant \
about the binary: a function's purpose, a data structure, a constant, a hypothesis, \
a string reference, or an import usage. This is how your findings are tracked. \
**Every decompilation, every xref trace, every string search that reveals \
something useful → call `exploration_report` immediately.**

### Pseudo-tools available:
- `exploration_report`: Log a structured finding (function_purpose, data_structure, \
  constant, hypothesis, string_ref, import_usage, general). **Call this for every \
  significant discovery.** Set relevance to "high" for key findings.
- `research_note`: Write an Obsidian-compatible markdown note to the `notes/` folder.
- `spawn_subagent`: Delegate research-heavy subtasks to isolated subagents.
- `save_memory`: Persist confirmed findings to RIKUGAN.md for future sessions.

### Exploration strategy (applied to the binary):
1. **Orient** — get_binary_info, list_imports, list_exports, search strings
2. **Search** — xrefs from strings/imports to find candidate functions in the binary
3. **Dive** — Decompile candidates, trace data flow, find exact logic
4. **Log** — Call `exploration_report` for EVERY significant finding
5. **Rename** — Rename functions you've confidently identified in the binary

### Rename as you go:
As you explore, **rename functions whose purpose you have confidently identified**. \
Use `rename_function` to replace generic names (sub_XXXX, FUN_XXXX) with descriptive \
ones. Batch renames of local variables (`rename_multi_variables`) are also encouraged \
when decompiling a key function.

### Persist your findings:
Use `save_memory` to persist confirmed findings to RIKUGAN.md so future sessions \
start with context. Do this as you go — don't wait until the end.

Log every significant finding with `exploration_report`. Keep exploring the binary \
until you have thoroughly investigated the user's goal.
"""

NOTE_WRITING_PROMPT = """\
[SYSTEM] Exploration phase complete. Now write your findings as Obsidian-compatible \
research notes using the `research_note` tool.

**You MUST call `research_note` for each major topic you discovered.** Do NOT just \
write text — use the `research_note` tool to save notes to disk.

Review everything you analyzed above — every function you decompiled, every string \
you found, every xref you traced. Organize these into research notes by topic.

Each note should be a well-structured markdown document with:
- A `## Summary` section
- `> Addresses:` blockquote with relevant hex addresses
- `> Genre:` with `#tag`
- `> Related:` with `[[wiki-links]]` to other notes
- `## Key Functions` table (Address | Name | Purpose)
- `## Detailed Analysis` with evidence (decompiled snippets, observations)
- `## Open Questions` for unresolved items
- `## See Also` with `[[wiki-links]]`
- Mermaid diagrams for call flows where appropriate

Write **one `research_note` call per topic**. Cover ALL significant findings \
from your analysis. Use `[[wiki-links]]` between notes to build a connected \
knowledge graph.

{knowledge_summary}

Now call `research_note` for each topic. Do NOT output text — only call `research_note`.
"""

# ---------------------------------------------------------------------------
# Note writing and review pipeline
# ---------------------------------------------------------------------------


def write_and_review_note(
    state: ResearchState,
    genre: str,
    title: str,
    content: str,
    related_notes: list[str],
    runner_factory: Callable[[], SubagentRunner],
) -> Generator[TurnEvent, None, ResearchNote]:
    """Write a research note, review it, and rephrase/rewrite as needed.

    Returns the final ResearchNote.
    """
    slug = _slugify(title)
    genre_dir = os.path.join(state.notes_dir, _slugify(genre))
    _ensure_dir(genre_dir)
    note_path = os.path.join(genre_dir, f"{slug}.md")

    # Write draft
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content)

    note = ResearchNote(
        genre=genre,
        title=title,
        slug=slug,
        path=note_path,
        content=content,
        related_notes=related_notes,
    )

    # ── Step 1: REVIEW (silent, zero-context, tool-verified) ──
    # The reviewer has NO prior exploration context — only the note and
    # binary analysis tools.  All subagent UI output is suppressed.
    runner = runner_factory()
    review_prompt = (
        f"You are an independent reviewer. You have ZERO prior context about "
        f"this binary — the ONLY information you have is the note below. "
        f"Your job is to fact-check it against the actual binary.\n\n"
        f"**USE YOUR TOOLS** to verify every claim:\n"
        f"- `decompile_function` or `fetch_disassembly` to check that "
        f"functions at cited addresses actually exist and do what the note claims\n"
        f"- `search_functions_by_name` to verify function names are real\n"
        f"- `list_imports` / `list_strings` to verify import/string claims\n"
        f"- `get_xrefs_to` to verify cross-reference claims\n\n"
        f"Do NOT trust the note at face value. Verify, then respond.\n\n"
        f"---\n\n# {title}\n\n{content}\n\n---\n\n"
        f"After verifying with tools, reply starting with PASS or FAIL.\n"
        f"List each claim you verified and whether it checked out. "
        f"For FAIL, list specific errors with correct values from the binary."
    )

    try:
        review_result = yield from runner.run_task(review_prompt, max_turns=8, silent=True)
        note.reviewed = True
        passed = review_result.strip().upper().startswith("PASS")

        yield TurnEvent.research_note_reviewed(title, passed, review_result[:200])

        # ── Step 2: REWRITE if needed (silent, tool-verified) ──
        current_content = content
        if passed:
            # Rephrase — polish the note (text-only, no tools needed)
            rephrase_runner = runner_factory()
            rephrase_prompt = (
                f"Rewrite this research note for a human reverse engineer. "
                f"Preserve all technical details, addresses, and cross-links "
                f"(`[[...]]`). Improve clarity, add section structure, fix "
                f"formatting. Return the complete rewritten note — nothing else.\n\n"
                f"# {title}\n\n{content}"
            )
            rephrased = yield from rephrase_runner.run_task(rephrase_prompt, max_turns=3, silent=True)
            if rephrased.strip():
                current_content = rephrased
        else:
            # Rewrite — fix errors using tools to look up correct info
            rewrite_runner = runner_factory()
            rewrite_prompt = (
                f"This research note was reviewed and rejected. The reviewer "
                f"used binary analysis tools to independently verify claims "
                f"and found errors.\n\n"
                f"**Review feedback:**\n{review_result}\n\n"
                f"**Original note:**\n\n# {title}\n\n{content}\n\n"
                f"Rewrite the note addressing the feedback. **USE YOUR TOOLS** "
                f"(decompile_function, fetch_disassembly, search_functions_by_name, "
                f"etc.) to look up the correct addresses, function names, and "
                f"behavior. Fix all errors identified by the reviewer. "
                f"Preserve `[[wiki-links]]` and Obsidian formatting. "
                f"Return the complete corrected note — nothing else."
            )
            rewritten = yield from rewrite_runner.run_task(rewrite_prompt, max_turns=8, silent=True)
            if rewritten.strip():
                current_content = rewritten

        # ── Step 3: ORCHESTRATOR DOUBLECHECK (silent, zero-context) ──
        # A final independent verifier with fresh context confirms
        # the rewritten note is accurate before we commit it.
        orchestrator = runner_factory()
        doublecheck_prompt = (
            f"You are a final quality gate for a research note. You have ZERO "
            f"prior context. **USE YOUR TOOLS** to spot-check the key claims "
            f"in this note — verify at least the 3 most important addresses "
            f"or function references against the actual binary.\n\n"
            f"---\n\n{current_content}\n\n---\n\n"
            f"Reply with APPROVED if the note is accurate, or REJECTED with "
            f"a brief list of remaining errors. Be concise."
        )
        doublecheck_result = yield from orchestrator.run_task(doublecheck_prompt, max_turns=6, silent=True)

        approved = doublecheck_result.strip().upper().startswith("APPROVED")
        note.review_passed = approved
        note.content = current_content
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(current_content)

        if not approved:
            log_info(f"Research note '{title}' not approved by orchestrator: {doublecheck_result[:120]}")

    except Exception as e:
        log_error(f"Research note review pipeline failed for '{title}': {e}")
        # Note was already written as draft — keep it

    state.notes_written.append(note)

    preview = _preview_lines(note.content)
    yield TurnEvent.research_note_saved(
        title=title,
        genre=genre,
        path=note_path,
        preview=preview,
        review_passed=note.review_passed,
    )

    return note


# ---------------------------------------------------------------------------
# Index generation
# ---------------------------------------------------------------------------


def _generate_index(state: ResearchState, binary_name: str, goal: str) -> str:
    """Generate notes/index.md — an Obsidian Map of Content."""
    lines = [
        "# Research Index\n",
        f"> Binary: `{binary_name}` | Goal: {goal}\n",
    ]

    # Group notes by genre
    by_genre: dict[str, list[ResearchNote]] = {}
    for note in state.notes_written:
        by_genre.setdefault(note.genre, []).append(note)

    for genre in sorted(by_genre):
        lines.append(f"\n## {genre.replace('-', ' ').title()}\n")
        for note in by_genre[genre]:
            status = "" if note.review_passed else " (needs review)"
            lines.append(f"- [[{note.slug}]] — {note.title}{status}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main mode runner
# ---------------------------------------------------------------------------


def _run_note_writing_phase(
    loop: AgentLoop,
    research_state: ResearchState,
    system_prompt: str,
    tools_schema: list,
    max_turns: int = 15,
) -> Generator[TurnEvent, None, None]:
    """Phase 2: run turns where the agent writes research_note calls.

    Injects the KB summary and a strong prompt telling the agent to write
    notes via the research_note tool. Continues until the agent produces
    a text-only response (no tool calls) or hits the turn limit.
    """
    knowledge_summary = research_state.knowledge_base.to_summary()
    note_prompt = NOTE_WRITING_PROMPT.format(knowledge_summary=knowledge_summary)
    loop.session.add_message(Message(role=Role.USER, content=note_prompt))

    research_system = system_prompt + RESEARCH_SYSTEM_ADDENDUM

    for turn in range(max_turns):
        loop._check_cancelled()
        yield TurnEvent.turn_start(turn + 1000)  # offset to distinguish from explore turns

        result = yield from execute_single_turn(loop, research_system, tools_schema)

        if not result.ok:
            return

        yield TurnEvent.turn_end(turn + 1000)

        if not result.has_tool_calls:
            # Agent is done writing notes
            break

        # If agent wrote notes but also has more to say, continue
        loop._maybe_inject_error_hint()


def run_research_mode(
    loop: AgentLoop,
    user_message: str,
    system_prompt: str,
    tools_schema: list,
) -> Generator[TurnEvent, None, None]:
    """Run the agent in research mode: explore, then write notes.

    Uses :class:`ModePhaseTracker` so that on cancel + resume the pipeline
    skips to the phase that was interrupted.  The conversation history has
    all prior tool calls/results — the LLM picks up where it left off.
    """
    tracker = ModePhaseTracker(loop, phases=["explore", "document", "index"])

    # Determine notes directory — next to the binary/IDB
    idb_dir = ""
    if loop.session.idb_path:
        idb_dir = os.path.dirname(loop.session.idb_path)
    if not idb_dir:
        idb_dir = os.getcwd()

    notes_dir = os.path.join(idb_dir, "notes")
    _ensure_dir(notes_dir)

    research_state = ResearchState(
        notes_dir=notes_dir,
        max_explore_turns=loop.config.exploration_turn_limit,
    )
    research_state.knowledge_base.user_goal = user_message
    loop._research_state = research_state

    # Also set up exploration state so exploration_report calls are handled
    explore_state = ExplorationState(explore_only=True)
    explore_state.max_explore_turns = research_state.max_explore_turns
    explore_state.knowledge_base.user_goal = user_message
    loop._exploration_state = explore_state

    research_system = system_prompt + RESEARCH_SYSTEM_ADDENDUM
    log_info(f"Research mode started: goal={user_message[:80]!r}, resuming={tracker.is_resuming}")

    # ------------------------------------------------------------------
    # Phase 1: EXPLORE
    # ------------------------------------------------------------------
    # Exploration gets all tools EXCEPT research_note — prevents the LLM
    # from writing notes during exploration (that's the document phase's job).
    explore_tools = [t for t in tools_schema if t.get("function", {}).get("name") != "research_note"]

    if tracker.should_run("explore"):
        tracker.enter("explore")
        if not tracker.is_continuing("explore"):
            yield TurnEvent.exploration_phase_change("", "explore", f"Starting research: {user_message[:60]}")

        from .exploration import _run_phase1_inline

        yield from _run_phase1_inline(loop, explore_state, research_system, explore_tools, explore_only=True)

        # Merge exploration KB into research state
        research_state.knowledge_base = explore_state.knowledge_base
        research_state.knowledge_base.user_goal = user_message

        # Check if exploration actually ran (agent made tool calls).
        if explore_state.explore_turns < 2:
            log_info("Research mode: exploration ended too early, skipping note-writing")
            loop._research_state = None
            loop._clear_exploration_state()
            tracker.complete()
            return

    # ------------------------------------------------------------------
    # Phase 2: WRITE NOTES
    # ------------------------------------------------------------------
    if tracker.should_run("document"):
        tracker.enter("document")
        log_info("Research mode: entering note-writing phase")
        if not tracker.is_continuing("document"):
            yield TurnEvent.exploration_phase_change("explore", "document", "Exploration complete. Writing research notes...")

        yield from _run_note_writing_phase(loop, research_state, system_prompt, tools_schema)

    # ------------------------------------------------------------------
    # Phase 3: Generate index
    # ------------------------------------------------------------------
    tracker.enter("index")
    binary_name = os.path.basename(loop.session.idb_path) if loop.session.idb_path else "unknown"

    if research_state.notes_written:
        index_content = _generate_index(research_state, binary_name, user_message)
        index_path = os.path.join(notes_dir, "index.md")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_content)
        log_info(f"Research mode: index written to {index_path}")

        yield TurnEvent.research_note_saved(
            title="Research Index",
            genre="index",
            path=index_path,
            preview=f"{len(research_state.notes_written)} notes indexed",
            review_passed=True,
        )

    # Final summary message
    note_count = len(research_state.notes_written)
    summary_msg = f"Research complete. {note_count} note(s) written to `{notes_dir}/`.\n\n"
    if research_state.notes_written:
        summary_msg += "### Notes Written\n"
        for note in research_state.notes_written:
            status = "passed" if note.review_passed else "needs review"
            summary_msg += f"- **{note.title}** ({note.genre}) — {status}\n"
        summary_msg += f"\nOpen `{notes_dir}/` in Obsidian to browse the knowledge vault."

    loop.session.add_message(Message(role=Role.USER, content=f"[SYSTEM] {summary_msg}"))
    yield TurnEvent.text_done(summary_msg)

    log_info(f"Research mode finished: {note_count} notes")
    tracker.complete()
    loop._research_state = None
    loop._clear_exploration_state()
