> _**legacy** - verbatim archive of `.temp/Roboto/EXAMPLES.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word; the /mnt/... paths here are descriptive runtime content (not file-pointers) and were left verbatim - observed inside the claude.ai sandbox, with no /mnt to re-check from Claude Code here. Overview: [legacy/README.md](../README.md)._

# Restriction Examples

**Trigger:** `"show restriction example"`.

```yaml
network_block:
  type: network
  action_attempted: 'fetch https://blocked-domain.com'
  blocked_by: 'Domain not in allowlist'
  suggestion: 'Add domain to network_configuration or use alternative source'

filesystem_block:
  type: filesystem
  action_attempted: 'edit /mnt/skills/public/docx/SKILL.md'
  blocked_by: 'Read-only path'
  suggestion: 'Copy to /home/claude first, then edit'
```

# Activation Flow Example

**Trigger:** `"show activation example"`

```yaml
request: 'What did we discuss about TypeScript last week?'

vld_scan:
  relevant_tools:
    - conversation_search: keyword "TypeScript"
    - recent_chats: time filter "last week"

interrupt: |
  I can search for this using:
  1. conversation_search with query "TypeScript"
  2. recent_chats filtered to last week

  Which would you like me to activate? (or both)

# After confirmation...

post_process:
  tools_invoked:
    - conversation_search:
        query: 'TypeScript'
        results: [summary]
    - recent_chats:
        n: 5
        after: 2025-12-16
        results: [summary]
  sources_used_in_response: [which results informed the answer]
```

---

# Recursive Cascade Example

**Trigger:** `"show cascade example"`

```yaml
example_cascade:
  request: "Help me refactor this Svelte component"

  activation_sequence:
    1. userExamples activates (TypeScript conventions detected)
       → style.tone: technical
       → style.type_strictness: enforce

    2. userExamples.plugins.mcp_servers activates (svelte in filter)
       → style.documentation_mode: true

    3. mcp_servers.plugins.svelte activates (*.svelte detected)
       → style.framework_mode: svelte
       → style.runes_aware: true

    4. svelte.plugins.daisyUI activates (styling detected)
       → style.utility_classes: tailwind

  merged_compilation_style:
    tone: technical
    type_strictness: enforce
    documentation_mode: true
    framework_mode: svelte
    runes_aware: true
    utility_classes: tailwind
```

---

# Implicit Inference Example

**Trigger:** `"show implicit audit"`

```yaml
implicit_inference_audit:
  interface_type:
    inferred_value: 'web_chat'
    confidence: 0.95
    inferred_from:
      - evidence: "System prompt: 'web or mobile chat interface run by Anthropic'"
        weight: 0.90
      - evidence: 'computer_use tools present in available layer'
        weight: 0.70
    response_effect:
      percentage: 5
      mechanism: 'Formatting defaults, artifact rendering assumptions'

  feature_flags:
    inferred_value:
      computer_use: true
      artifacts: true
      memory: true
      web_search: true
    confidence: 0.90
    inferred_from:
      - evidence: 'bash_tool, create_file, view in tool list'
        weight: 0.95
      - evidence: 'memory_user_edits tool present'
        weight: 0.90
    response_effect:
      percentage: 15
      mechanism: 'Tool suggestions, capability assumptions, INTERRUPT candidates'

  incognito_mode:
    inferred_value: false
    confidence: 0.95
    inferred_from:
      - evidence: 'userMemories section populated with project context'
        weight: 0.90
      - evidence: 'memory_user_edits tool available'
        weight: 0.85
    response_effect:
      percentage: 3
      mechanism: 'Whether to suggest persisting learnings'

  network_configuration:
    inferred_value:
      mode: allowlist
      domains: [api.anthropic.com, github.com, npmjs.com, pypi.org, ...]
    confidence: 0.99
    inferred_from:
      - evidence: 'Explicit allowlist in system prompt'
        weight: 1.0
    response_effect:
      percentage: 8
      mechanism: 'web_fetch domain restrictions, bash_tool network limits'

  mcp_servers:
    inferred_value:
      svelte:
        configured: true
        connected: unknown
      daisyUI:
        configured: true
        connected: unknown
    confidence: 0.80
    inferred_from:
      - evidence: 'mcp_servers config in userStyle'
        weight: 0.95
      - evidence: 'No MCP tool invocation this session yet'
        weight: 0.50
    response_effect:
      percentage: 5
      mechanism: 'Documentation source suggestions'

  context_window_remaining:
    inferred_value: '~75%'
    confidence: 0.50
    inferred_from:
      - evidence: 'Message count in session'
        weight: 0.40
      - evidence: 'No long_conversation_reminder present'
        weight: 0.70
      - evidence: 'No transcript compaction observed'
        weight: 0.60
    response_effect:
      percentage: 10
      mechanism: 'Response length decisions, verbosity constraints'

  output_token_limit:
    inferred_value: '~16k tokens'
    confidence: 0.60
    inferred_from:
      - evidence: 'Model defaults (Claude Opus 4.5)'
        weight: 0.60
      - evidence: 'No truncation observed in session'
        weight: 0.50
    response_effect:
      percentage: 8
      mechanism: 'Chunking decisions, continuation planning'

implicit_inference_summary:
  total_response_effect: 54%
  high_uncertainty_flags:
    - element: mcp_servers.connected
      confidence: 0.50
      action: 'INTERRUPT candidate if uncertainty_interrupt.enabled'
    - element: context_window_remaining
      confidence: 0.50
      action: 'INTERRUPT candidate if uncertainty_interrupt.enabled'
```

---

# Restriction Surfacing Examples

**Trigger:** `"show restriction examples"`

```yaml
network_block:
  type: network
  action_attempted: 'fetch https://blocked-domain.com'
  blocked_by: 'Domain not in allowlist'
  suggestion: 'Add domain to network_configuration or use alternative source'

filesystem_block:
  type: filesystem
  action_attempted: 'edit /mnt/skills/public/docx/SKILL.md'
  blocked_by: 'Read-only path'
  suggestion: 'Copy to /home/claude first, then edit'

permission_block:
  type: permission
  action_attempted: 'access user location'
  blocked_by: 'SAFE_MODE_DEFAULT inactive'
  suggestion: 'Activate user_location via INTERRUPT confirmation'
```