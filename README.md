# Rikugan (六眼)

A reverse-engineering agent for **IDA Pro** and **Binary Ninja** that integrates a multi-provider LLM directly into your analysis UI. This project was vibecoded together with my friend, Claude Code.


![alt text](assets/binja_showcase.png)


![alt text](assets/ida_showcase.png)

### One-line install

The quickest way to install. Auto-detects IDA Pro, Binary Ninja, or both.

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1 | iex
```

To install for a specific host only:

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash -s -- --ida
curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash -s -- --binja
```

```powershell
# Windows
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1))) -Target ida
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1))) -Target binja
```

## Is this another MCP client?

No, Rikugan is an ***agent*** built to live inside your RE host (**IDA Pro or Binary Ninja**). It does not consume an MCP server to interact with the host database; it has its own agentic loop, context management, its own role prompt (you can check it [here](rikugan/agent/system_prompt.py)), and an in-process tool orchestration layer.

The agent loop is a generator-based turn cycle: each user message kicks off a stream→execute→repeat pipeline where the LLM response is streamed token-by-token and tool calls are intercepted and dispatched.

The results are fed back as the next turn's context. It supports automatic error recovery, mid-run user questions, plan mode for multi-step workflows, and message queuing — all without leaving the disassembler.

The agent really ***lives*** and ***breathes*** reversing.

Advantages:

- No need to switch to an external MCP client such as Claude Code
- Assistant-first, not designed to do your job (unless you ask it to)
- Extensible to many LLM providers and local installations (Ollama)
- Quick to enable — just hit Ctrl+Shift+I and the chat will appear

Also, building agents is a fascinating area of study, especially when coding alongside them.


## Features

There are 60+ tools available to the agent, covering:

- Navigation
- Code reading (decompiler, disassembly)
- Cross-references
- Strings (list, filter)
- Annotations (retype, rename, comments)
- IL reading/writing (Binary Ninja's LLIL/MLIL/HLIL) — read IL at any level, modify expressions, force branches, NOP instructions, patch bytes, register pipeline transforms
- Scripting to extend its capabilities (Binary Ninja Python and IDAPython)
- Analysis profiles
  - Profiles let you define what data the LLM can access, restrict which tools it can use, and create custom rules and prompts — especially useful for private analysis and research.
- Reuse MCP servers and skills from Claude Code and OpenAI's Codex.

Tool details can be found in the [ARCHITECTURE.md](ARCHITECTURE.md) document. You can use these tools to do things like:

- "Explain this function"
- "Analyze this binary and tell me what it does"
- "Batch rename all functions in this binary"
- "Try to deobfuscate this function"

Depending on the complexity, the agent may invoke subagents to assist with the analysis. It will **always** ask your permission before running scripts and will never execute the target binary.


### Exploration

Exploration mode is directly inspired by how code agents work, but applied to binaries instead of source code.

|![alt text](assets/subagents_example_1.png)|
|:--:|
|Triggering exploration mode with /explore|

When you trigger it, the main orchestrator first orients itself — it reads imports, exports, strings, and key functions to build a map of what the binary is doing. 


|![alt text](assets/subagents_example_2.png)|
|:--:|
|Logging a high-relevance finding via exploration_report|

Then, instead of doing everything in a single context, it spawns subagents and delegates focused tasks to each one: "analyze this function", "trace this data structure", "figure out what this import cluster is doing".

|![alt text](assets/subagents_example_3.png)|
|:--:|
|Orchestrator spawning subagents in parallel to tackle the binary|

Subagents run in complete isolation from the parent session. They are essentially independent instances of Rikugan with a single task and zero prior knowledge. After finishing, each one reports its findings back to the orchestrator, which synthesizes everything and continues toward your goal.

This gives you deeper and faster analysis than a single agent pass, and keeps the main context window clean.

During exploration, it also renames functions when it has high confidence about what a function actually does.

### Natural Language Patches/modding (Experimental)

A binary is code, code is text, and LLMs are good at reading and writing text. Agentic coding works well for editing source — `/modify` does the same thing, but on the compiled binary.

`/modify make this maze game easy to me, make me pass thought the walls`

![alt text](assets/modify_example_01.png)

That's it. Rikugan runs exploration mode, builds context about the binary, and applies the patches. This can produce issues (segfaults, crashes), but you can feed those back and it will try to fix them.

|![alt text](assets/modify_example_02.png)|
|:--:|
|Discovered a function purpose|



|![alt text](assets/modify_example_03.png)|
|:--:|
|Present you the modification/patch plan|

Then it will proceed to the plan implementation state.

![alt text](assets/modify_example_04.png)

Done

![alt text](assets/maze_solve.gif)

### Memory

Rikugan is inspired by how Claude Code maintains its memory. Every important finding during a session is saved to `RIKUGAN.md` — a running synthesis of what was discovered across analysis sessions.

![alt text](assets/memory.png)

### Deobfuscation (Experimental, designed for Binary Ninja only)

The `/deobfuscation` skill activates plan mode — the agent reads the IL, figures out what the obfuscation is doing, and uses IL write primitives or byte patching to undo it.

IL read/write tools:
- **Read**: `get_il`, `get_cfg` (blocks, edges, dominators, loops), `track_variable_ssa` (def-use chains)
- **Write**: `il_replace_expr`, `il_set_condition`, `il_nop_expr`, `il_remove_block`, `patch_branch` / `write_bytes`, `install_il_workflow` (pipeline transforms)

The skill teaches the agent to recognize and remove:
- **Control Flow Flattening (CFF)** — dispatcher loops with state variable
- **Opaque Predicates** — always-true/false conditions (algebraic and call-based)
- **Mixed Boolean-Arithmetic (MBA)** — complex expressions that simplify to trivial operations
- **Junk Code / Dead Stores** — instructions that compute values never used

Runs in plan mode, so you can review the plan before the agent starts patching.

|![](assets/cff_remove_example.gif)|
|:--:|
|~3x speed of the workflow, original process took ~4:30 min

## Requirements

- IDA Pro 9.0+ with Hex-Rays decompiler or Binary Ninja (UI mode)
- Python 3.9+ (**see note below for IDA Pro**)
- At least one LLM provider
- Windows, macOS, or Linux

> **IDA Pro + Python > 3.10 warning:** IDA Pro's Qt/PySide6 binding (Shiboken) has a known Use-After-Free bug that can cause crashes when Python > 3.10 is used. The issue is triggered by Shiboken's `__import__` hook during Qt signal dispatch — Rikugan works around this by routing all `ida_*` imports through `importlib.import_module()` and installing a re-entrancy guard on `builtins.__import__`. That said, Python 3.10 is still the safest choice for IDA Pro. See the [upstream report](https://community.hex-rays.com/t/ida-9-3-b1-macos-arm64-uaf-crash/646) for details.


## Manual install

Clone this repository, then run the installer for your target host:

**IDA Pro (Linux / macOS):**
```bash
./install_ida.sh
```

**IDA Pro (Windows):**
```bat
install_ida.bat
```

**Binary Ninja (Linux / macOS):**
```bash
./install_binaryninja.sh
```

**Binary Ninja (Windows):**
```bat
install_binaryninja.bat
```

All scripts auto-detect the user directory for their host. If detection fails (or you have a non-standard setup), pass the path explicitly:

```bash
./install_ida.sh /path/to/ida/user/dir
install_ida.bat "C:\Users\you\AppData\Roaming\Hex-Rays\IDA Pro"
./install_binaryninja.sh /path/to/binaryninja/user/dir
install_binaryninja.bat "C:\Users\you\AppData\Roaming\Binary Ninja"
```

Installers create the plugin symlink, install dependencies, and set up host-specific config directories.

### Set your API key

Rikugan has a settings dialog to configure your model of choice. Open Rikugan → click Settings → paste your key.

- IDA config: `~/.idapro/rikugan/config.json` (Linux / macOS) · `%APPDATA%\Hex-Rays\IDA Pro\rikugan\config.json` (Windows)
- Binary Ninja config: `~/.binaryninja/rikugan/config.json` (Linux) · `~/Library/Application Support/Binary Ninja/rikugan/config.json` (macOS) · `%APPDATA%\Binary Ninja\rikugan\config.json` (Windows)

![alt text](assets/rikugan_settings.png)

**Anthropic OAuth:** If you have Claude Code installed and authenticated, Rikugan auto-detects the OAuth token from the macOS Keychain. On other platforms, paste your API key manually or run `claude setup-token`.

## Usage

### Open the panel

IDA Pro: press **Ctrl+Shift+I** or go to **Edit → Plugins → Rikugan**.

Binary Ninja: use **Tools → Rikugan → Open Panel** or click the icon on the sidebar.

### Multi-tab chat

Each tab is an independent conversation with its own message history and context. Use the **+** button to create a new tab, or close tabs you no longer need. Tabs are tied to the current file — opening a different database starts a fresh set of tabs, and returning to a file restores its saved conversations.

### Chat export

Right-click a tab or click the **Export** button to save a conversation as Markdown. Tool calls and results are formatted with language-appropriate syntax highlighting (`c` for decompiled code, `x86asm` for disassembly, `python` for scripts, etc.).

### Script approval

The `execute_python` tool always asks for your permission before running. You see the full Python code with syntax highlighting in a scrollable preview, and can **Allow** or **Deny** each execution. The agent can never run the target binary on your machine.

![alt text](assets/approval_example.png)

### Profiles

Profiles let you customize the agent to fit your analysis needs. They give you granular control over which data the LLM can read, restrict which tools it can use, and let you define custom rules to filter data.

![alt text](/assets/profile.png)

### Quick actions

IDA Pro exposes these under right-click menus.
Binary Ninja exposes equivalent commands under **Tools → Rikugan** and address-context command menus.

| Action | Description |
|--------|-------------|
| **Send to Rikugan** | Pre-fills the input with the current selection (Ctrl+Shift+A in IDA) |
| **Explain this** | Auto-explains the current function |
| **Rename with Rikugan** | Analyzes and renames with evidence |
| **Deobfuscate with Rikugan** | Systematic deobfuscation |
| **Find vulnerabilities** | Security audit |
| **Suggest types** | Infers types from usage patterns |
| **Annotate function** | Adds comments to decompiled code |
| **Clean microcode / IL** | Identifies and NOPs junk instructions |
| **Xref analysis** | Deep cross-reference tracing |

### Skills

Skills are reusable analysis workflows. Type `/` in the input area to see available skills with autocomplete.

Create custom skills in:

- IDA (Linux / macOS): `~/.idapro/rikugan/skills/<slug>/SKILL.md`
- IDA (Windows): `%APPDATA%\Hex-Rays\IDA Pro\rikugan\skills\<slug>\SKILL.md`
- Binary Ninja (Linux): `~/.binaryninja/rikugan/skills/<slug>/SKILL.md`
- Binary Ninja (macOS): `~/Library/Application Support/Binary Ninja/rikugan/skills/<slug>/SKILL.md`
- Binary Ninja (Windows): `%APPDATA%\Binary Ninja\rikugan\skills\<slug>\SKILL.md`

Each skill lives in its own subdirectory.

```
# IDA Pro
~/.idapro/rikugan/skills/                                        # Linux / macOS
%APPDATA%\Hex-Rays\IDA Pro\rikugan\skills\                       # Windows

# Binary Ninja
~/.binaryninja/rikugan/skills/                                   # Linux
~/Library/Application Support/Binary Ninja/rikugan/skills/       # macOS
%APPDATA%\Binary Ninja\rikugan\skills\                           # Windows
  my-skill/
    SKILL.md            # required — frontmatter + prompt body
    references/         # optional — .md files appended to the prompt
      api-notes.md
```

Skill format:
```markdown
---
name: My Custom Skill
description: What it does in one line
tags: [analysis, custom]
allowed_tools: [decompile_function, rename_function]
---
Task: <instruction for the agent>

## Approach
...
```

The `allowed_tools` field is optional — when set, the agent can only use those tools while the skill is active.

### Supported agents

Rikugan supports pre-built skills from Claude Code and Codex. Go to Settings → Skills tab and choose which ones to enable.

![alt text](/assets/skills_settings.png)


### MCP Servers

Connect external MCP servers to extend Rikugan with additional tools. Create the config file at:

- IDA (Linux / macOS): `~/.idapro/rikugan/mcp.json`
- IDA (Windows): `%APPDATA%\Hex-Rays\IDA Pro\rikugan\mcp.json`
- Binary Ninja (Linux): `~/.binaryninja/rikugan/mcp.json`
- Binary Ninja (macOS): `~/Library/Application Support/Binary Ninja/rikugan/mcp.json`
- Binary Ninja (Windows): `%APPDATA%\Binary Ninja\rikugan\mcp.json`

```json
{
  "mcpServers": {
    "binary-ninja": {
      "command": "python",
      "args": ["-m", "binaryninja_mcp"],
      "env": {},
      "enabled": true
    }
  }
}
```

MCP servers are started when the plugin loads. Their tools appear alongside built-in ones with the prefix `mcp_<server>_<tool>` — the agent sees them in the tool list and can call them like any other tool. Set `"enabled": false` to keep a server configured without starting it.

### Supported agents

Similar to skills, Rikugan also supports pre-configured MCP servers from Claude Code and Codex in Settings → MCP tab.



## Tools

50 tools are shared across both hosts with identical interfaces. IDA adds 6 host-specific microcode tools; Binary Ninja adds 13 host-specific IL tools for reading, analyzing, and transforming its intermediate language.

### Shared tools (50)

| Category | Tools |
|----------|-------|
| **Navigation** | `get_cursor_position` `get_current_function` `jump_to` `get_name_at` `get_address_of` |
| **Functions** | `list_functions` `get_function_info` `search_functions` |
| **Strings** | `list_strings` `search_strings` `get_string_at` |
| **Database** | `list_segments` `list_imports` `list_exports` `get_binary_info` `read_bytes` |
| **Disassembly** | `read_disassembly` `read_function_disassembly` `get_instruction_info` |
| **Decompiler** | `decompile_function` `get_pseudocode` `get_decompiler_variables` |
| **Xrefs** | `xrefs_to` `xrefs_from` `function_xrefs` |
| **Annotations** | `rename_function` `rename_variable` `set_comment` `set_function_comment` `rename_address` `set_type` |
| **Types** | `create_struct` `modify_struct` `get_struct_info` `list_structs` `create_enum` `modify_enum` `get_enum_info` `list_enums` `create_typedef` `apply_struct_to_address` `apply_type_to_variable` `set_function_prototype` `import_c_header` `suggest_struct_from_accesses` `propagate_type` `get_type_libraries` `import_type_from_library` |
| **Scripting** | `execute_python` — requires user approval before each execution |

### IDA-only tools (6)

| Category | Tools |
|----------|-------|
| **Microcode** | `get_microcode` `get_microcode_block` `nop_microcode` `install_microcode_optimizer` `remove_microcode_optimizer` `list_microcode_optimizers` |

Uses Hex-Rays MMAT maturity levels. Includes `redecompile_function` to refresh output after microcode patches.

### Binary Ninja-only tools (13)

| Category | Tools |
|----------|-------|
| **IL Core** | `get_il` `get_il_block` `nop_instructions` `redecompile_function` |
| **IL Analysis** | `get_cfg` `track_variable_ssa` |
| **IL Transform** | `il_replace_expr` `il_set_condition` `il_nop_expr` `il_remove_block` `patch_branch` `write_bytes` `install_il_workflow` |

Read IL at any level (LLIL, MLIL, HLIL), inspect CFG structure and SSA def-use chains, then modify: replace expressions, force conditions, NOP instructions, remove blocks, patch branches at byte level, or register custom Python transforms in the analysis pipeline.


## Recommended Providers

Rikugan supports Anthropic, OpenAI, Google Gemini, MiniMax, Ollama, and any OpenAI-compatible endpoint. Below is a summary of what has been tested in practice.

### Tested Providers

| Provider | Notes |
|----------|-------|
| **Claude Opus 4.6** | Best overall for deep reasoning and complex reverse-engineering tasks. Expensive via API — recommend using your Claude Pro/Max plan with OAuth instead. |
| **Claude Sonnet 4.6** | Good performance at lower cost. Handles complex tasks well. Also better used through a Claude plan than via API to avoid rate limits. Both Anthropic models use **prompt caching** to reduce token spend, but API rate limits hit faster than plan limits. |
| **MiniMax M2.5 / M2.5 Highspeed** | Excellent performance at significantly lower cost. In local tests performed on par with Opus 4.6. Very generous usage limits and high TPM (tokens per minute). Uses the Anthropic-compatible API (`api.minimax.io/anthropic`). Recommended if you want top-tier results without the API bill. |
| **Gemini 2.5 / 3 / 3.1 Pro** | Solid results overall. Hallucinates more than Anthropic/MiniMax models but can solve many tasks effectively. |
| **Kimi 2.5** | Strong coding skills, but lacks the deterministic and logical approach that complex reverse-engineering tasks require. |
| **LLAMA 70B (local via Ollama)** | Interesting analysis results but not production-ready for RE tasks. |
| **GPT 120B OSS (local)** | Similar to LLAMA 70B — lacks reasoning depth. |

### Needs more testing

- GPT-5.3 Codex
- GPT-5.2

### Context window usage display

The context bar shows how much of the model's context window is currently in use. A few things to keep in mind:

**Why the percentage can decrease during a long agentic run:**
Rikugan automatically truncates old tool results to save context space — results older than 8 messages are cut to 500 characters. If the agent makes many tool calls in a single turn, earlier results get progressively trimmed, so the token count sent to the API on the next inner call may genuinely be smaller than the previous one. A drop in the percentage means the context manager reclaimed space, not that something went wrong.

**Why Anthropic numbers are more accurate than other providers:**
Claude uses [prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching). The API reports three separate token buckets: fresh input tokens, cache-read tokens, and cache-creation tokens. Rikugan adds all three to compute the true context window usage, so the displayed percentage reflects the actual context occupancy — not just the uncached portion, which would otherwise appear to drop dramatically on cache hits.


# Conclusion

If you'd asked me last year what I thought about AI doing reverse engineering, I'd probably have said something like "Nah, impossible — it hallucinates, and reverse engineering is not something as simple as writing code." But this year I completely changed my mind when I saw what was achievable. AI is not the ChatGPT from 2023 anymore; it's something entirely different.

For that reason, I decided to invest this year in researching this topic. It's amazing what we can build with agentic coding — it's surreal how quickly I'm learning topics that I simply "didn't have time" to study before.

Rikugan is just one of many projects I've built in the last three months. The first version was built in a single night. Within two days it already supported both IDA and Binary Ninja. Within three days, it was essentially what you see here, with only minor tweaks since.

This is a work in progress with many areas for improvement. I took care to ensure this wouldn't be another AI slop project, but I'm certain there is still room to grow. I hope you use it for good. If you find bugs, have suggestions, or want quality-of-life improvements, please open an issue.

That's all — thanks.
