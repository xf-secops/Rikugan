"""Exploration mode: autonomous binary exploration → planning → patching → save.

Implements a four-phase agent flow:
  1. EXPLORE — agent autonomously maps the binary to understand the user's request
  2. PLAN   — agent synthesizes findings into a concrete modification plan
  3. EXECUTE — agent applies patches in-memory with verification
  4. SAVE   — user approves persisting changes to the file
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExplorationPhase(str, Enum):
    EXPLORE = "explore"
    PLAN = "plan"
    EXECUTE = "execute"
    SAVE = "save"


# ---------------------------------------------------------------------------
# Knowledge Base — structured accumulator of exploration findings
# ---------------------------------------------------------------------------

@dataclass
class FunctionInfo:
    """A function discovered during exploration."""
    address: int
    name: str
    summary: str = ""
    decompiled: str = ""
    relevance: str = "medium"  # low / medium / high


@dataclass
class StringRef:
    """A string reference found during exploration."""
    address: int
    value: str
    xref_functions: List[int] = field(default_factory=list)
    relevance: str = "medium"


@dataclass
class Finding:
    """A single exploration finding logged via the exploration_report pseudo-tool."""
    category: str  # function_purpose, data_structure, constant, hypothesis, string_ref, import_usage
    address: Optional[int]
    summary: str
    evidence: str = ""
    relevance: str = "medium"


@dataclass
class KnowledgeBase:
    """Accumulated knowledge from the exploration phase."""
    user_goal: str = ""
    relevant_functions: Dict[int, FunctionInfo] = field(default_factory=dict)
    relevant_strings: List[StringRef] = field(default_factory=list)
    relevant_imports: List[str] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    hypotheses: List[str] = field(default_factory=list)

    def add_finding(self, finding: Finding) -> None:
        self.findings.append(finding)
        # Auto-extract hypotheses
        if finding.category == "hypothesis":
            self.hypotheses.append(finding.summary)

    def add_function(self, info: FunctionInfo) -> None:
        self.relevant_functions[info.address] = info

    @property
    def has_minimum_for_planning(self) -> bool:
        """Check if the knowledge base has enough data to transition to planning."""
        return (
            len(self.relevant_functions) >= 1
            and len(self.hypotheses) >= 1
            and any(
                f.relevance == "high"
                for f in self.findings
                if f.category == "hypothesis"
            )
        )

    @property
    def planning_gap_description(self) -> str:
        """Describe what's missing for planning, for feedback to the agent."""
        gaps = []
        if len(self.relevant_functions) < 1:
            gaps.append("0 relevant functions (need ≥1)")
        if len(self.hypotheses) < 1:
            gaps.append("0 hypotheses (need ≥1)")
        elif not any(f.relevance == "high" for f in self.findings if f.category == "hypothesis"):
            gaps.append("0 high-relevance hypotheses (need ≥1 with relevance='high')")
        return "; ".join(gaps) if gaps else ""

    def to_summary(self) -> str:
        """Generate a text summary of accumulated knowledge for the planning prompt."""
        parts = [f"## Exploration Summary\n\nGoal: {self.user_goal}\n"]

        if self.relevant_functions:
            parts.append("### Relevant Functions")
            for addr, func in self.relevant_functions.items():
                rel = f" [{func.relevance}]" if func.relevance != "medium" else ""
                parts.append(f"- `0x{addr:x}` {func.name}: {func.summary}{rel}")

        if self.relevant_strings:
            parts.append("\n### Relevant Strings")
            for sref in self.relevant_strings:
                parts.append(f'- `0x{sref.address:x}`: "{sref.value}"')

        if self.relevant_imports:
            parts.append("\n### Relevant Imports")
            for imp in self.relevant_imports:
                parts.append(f"- {imp}")

        if self.hypotheses:
            parts.append("\n### Hypotheses")
            for i, hyp in enumerate(self.hypotheses, 1):
                parts.append(f"{i}. {hyp}")

        if self.findings:
            parts.append(f"\n### All Findings ({len(self.findings)} total)")
            for f in self.findings:
                addr_str = f"0x{f.address:x}" if f.address is not None else "N/A"
                parts.append(f"- [{f.category}] {addr_str}: {f.summary}")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Modification Plan — output of Phase 2
# ---------------------------------------------------------------------------

@dataclass
class PlannedChange:
    """A single planned modification to the binary."""
    index: int
    target_address: int
    current_behavior: str
    proposed_behavior: str
    patch_strategy: str
    risk_level: str = "low"  # low / medium / high


@dataclass
class ModificationPlan:
    """The complete modification plan generated in Phase 2."""
    changes: List[PlannedChange] = field(default_factory=list)
    rationale: str = ""
    verification_plan: str = ""


# ---------------------------------------------------------------------------
# Patch Record — tracking for Phase 3 (in-memory patches)
# ---------------------------------------------------------------------------

@dataclass
class PatchRecord:
    """Record of a single in-memory patch applied during Phase 3."""
    address: int
    original_bytes: bytes
    new_bytes: bytes
    description: str = ""
    verified: bool = False
    verification_result: str = ""
    change_index: int = 0  # links back to PlannedChange.index


@dataclass
class PatchSummary:
    """Summary of all patches for the save approval gate (Phase 4)."""
    patches: List[PatchRecord] = field(default_factory=list)
    total_bytes_modified: int = 0
    all_verified: bool = False
    target_file: str = ""

    def compute(self) -> None:
        """Recompute summary fields from patch list."""
        self.total_bytes_modified = sum(len(p.new_bytes) for p in self.patches)
        self.all_verified = all(p.verified for p in self.patches) if self.patches else False


# ---------------------------------------------------------------------------
# Exploration State — the full state machine
# ---------------------------------------------------------------------------

@dataclass
class ExplorationState:
    """Full state of the exploration mode across all phases."""
    phase: ExplorationPhase = ExplorationPhase.EXPLORE
    knowledge_base: KnowledgeBase = field(default_factory=KnowledgeBase)
    modification_plan: Optional[ModificationPlan] = None
    patches_applied: List[PatchRecord] = field(default_factory=list)
    explore_turns: int = 0
    execute_turns: int = 0
    total_turns: int = 0  # monotonic counter across all phases (for UI)
    max_explore_turns: int = 30
    max_execute_turns: int = 20
    explore_only: bool = False  # /explore mode — no patching

    def can_transition_to(self, target: ExplorationPhase) -> tuple:
        """Validate whether a phase transition is allowed.

        Returns (allowed: bool, reason: str).
        """
        if target == self.phase:
            return (False, f"Already in {self.phase.value} phase.")

        if target == ExplorationPhase.PLAN:
            if self.phase != ExplorationPhase.EXPLORE:
                return (False, "Can only transition to PLAN from EXPLORE phase.")
            if not self.knowledge_base.has_minimum_for_planning:
                gap = self.knowledge_base.planning_gap_description
                return (
                    False,
                    f"Not enough findings to plan. {gap}. Keep exploring."
                )
            return (True, "")

        if target == ExplorationPhase.EXECUTE:
            if self.phase != ExplorationPhase.PLAN:
                return (False, "Can only transition to EXECUTE from PLAN phase.")
            if self.modification_plan is None or not self.modification_plan.changes:
                return (False, "No modification plan with changes to execute.")
            return (True, "")

        if target == ExplorationPhase.SAVE:
            if self.phase != ExplorationPhase.EXECUTE:
                return (False, "Can only transition to SAVE from EXECUTE phase.")
            if not self.patches_applied:
                return (False, "No patches have been applied to save.")
            return (True, "")

        return (False, f"Unknown target phase: {target}")

    def transition_to(self, target: ExplorationPhase) -> None:
        """Transition to a new phase (assumes validation already passed)."""
        self.phase = target


# ---------------------------------------------------------------------------
# Prompts for each phase
# ---------------------------------------------------------------------------

EXPLORATION_SYSTEM_ADDENDUM = """\

## Exploration Mode — Active

You are in **exploration mode**, systematically investigating the binary to understand \
how to achieve the user's goal. You have access to all analysis tools.

### Pseudo-tools available:
- `exploration_report`: Log a structured finding (function purpose, data structure, \
constant, hypothesis, string reference, import usage). Call this whenever you discover \
something relevant.
- `phase_transition`: Request to move to the next phase. Call with \
`to_phase="plan"` when you have identified all locations that need to change.

### Exploration strategy:
1. **Orient** — Binary info, imports, exports, strings with goal-relevant keywords
2. **Search** — xrefs from strings/imports to find candidate functions
3. **Dive** — Decompile candidates, trace data flow, find exact constants/logic
4. **Hypothesize** — Form concrete hypotheses about what to change

### Rename as you go:
As you explore, **rename functions whose purpose you have confidently identified**. \
Use `rename_function` to replace generic names (sub_XXXX, FUN_XXXX) with descriptive \
ones. This makes subsequent analysis clearer for you and the user. \
Only rename when you are certain — if unsure, leave the original name and note your \
hypothesis in an `exploration_report` instead. Batch renames of local variables \
(`rename_multi_variables`) are also encouraged when decompiling a key function.

### Persist your findings:
Use `save_memory` to persist confirmed findings to RIKUGAN.md so future sessions \
start with context. Save function purposes, architecture notes, and data structures \
you've confidently identified. Do this as you go — don't wait until the end.

Log every significant finding with `exploration_report`. When you have enough \
understanding, call `phase_transition(to_phase="plan")`.
"""

PLAN_SYNTHESIS_PROMPT = """\
You are now in the **PLAN** phase. Based on your exploration findings below, create \
a concrete modification plan.

{knowledge_summary}

For each change, specify:
1. The exact address to modify
2. What the current code does at that address
3. What it should do after modification
4. The minimal patch strategy (which bytes/instructions to change)

Format as a numbered list of changes. After listing all changes, provide:
- **Rationale**: Why these changes achieve the user's goal
- **Verification**: How to verify correctness after patching

Do NOT use any tools. Output the plan as text only.
"""

EXECUTE_STEP_PROMPT = """\
You are in the **EXECUTE** phase. Apply the following patch:

**Change {index} of {total}**: {description}

Follow the Smart Patch workflow:
1. Read disassembly/decompilation at the target to confirm current state
2. Read current bytes at the target address (`read_bytes`) as backup — print the hex
3. Assemble and write new bytes using `execute_python`
4. NOP-pad any remaining bytes to preserve instruction alignment
5. Verify with `redecompile_function` — confirm the change is correct
6. Report the result with `exploration_report(category="patch_result")`

Include the original hex bytes and new hex bytes in your exploration_report \
so the save gate can track what changed.
"""

SAVE_PROMPT = """\
All patches have been applied and verified in-memory.

{patch_summary}

The user will now be asked whether to save these changes to the file. \
Do not take any further actions until the user decides.
"""
