> _**legacy** - verbatim archive of `.temp/Roboto/CONFIG.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word, unchanged. Overview: [legacy/README.md](../README.md)._

# Configs

Human-editable enforcement configurations stored externally.

# <userExamples>

## TypeScript Conventions

```yaml
example:
  name: 'TypeScript Conventions'
  type: code_style
```

```typescript
// INTERFACE: object shapes, entities, props, API contracts
// Prefix with 'I'
interface IUser { name: string; }
interface ICardProps { title: string; }

// TYPE: unions, functions, intersections, mapped types
type Status = "pending" | "approved" | "rejected";
type Handler = (event: Event) => void;
```

### General Patterns

- Prefer `const` arrow functions: `const fn = () => {}`
- Omit obvious type annotations; include only when they add functionality

### Naming Strategy

**Core principle**: Names should be contextually obvious within their scope.

**File-Scoped Exports**: Prefer short contextual names—consumers can alias if needed.

```typescript
// user.ts — PREFERRED
export interface IUser { name: string; }
export type Settings = { theme: string; }

// Consumer renames if needed:
import type { Settings as UserSettings } from './user';
```

**Local Scope Variables**: Prefer concise names when context makes meaning obvious.

```typescript
function processUser() {
  let active = true;  // Clear from function name
  let count = 0;
}
```

**Object Property Pattern**: Group related values into a const object.

```typescript
const settings = { maxRetries: 3, timeoutMs: 5000, enableCache: true };
```

# <documentation_sources>

External documentation accessible via web_fetch.

## Capability

```yaml
tools_available:
  web_fetch: true
  web_search: true
  mcp_invoke: false
```

## Sources

### Svelte

```yaml
svelte:
  status: VERIFIED

  endpoints:
    docs: https://svelte.dev/docs
    kit: https://svelte.dev/docs/kit
    tutorial: https://svelte.dev/tutorial
    runes: https://svelte.dev/docs/svelte/what-are-runes
    mcp_info: https://mcp.svelte.dev/mcp
    llms_txt: https://svelte.dev/docs/mcp/overview/llms.txt

  raw:
    svelte: https://raw.githubusercontent.com/sveltejs/svelte/main
    mcp: https://raw.githubusercontent.com/sveltejs/mcp/main

  triggers: [svelte, SvelteKit, runes, $state, $derived, $effect, $props, $bindable]
```

### daisyUI

```yaml
daisyUI:
  status: VERIFIED

  endpoints:
    docs: https://daisyui.com/docs
    components: https://daisyui.com/components
    themes: https://daisyui.com/docs/themes
    colors: https://daisyui.com/docs/colors
    config: https://daisyui.com/docs/config
    gitmcp: https://gitmcp.io/saadeghi/daisyui

  raw:
    repo: https://raw.githubusercontent.com/saadeghi/daisyui/master

  triggers: [daisyui, daisy component, daisy theme, daisyui button, daisyui modal]
```

## Activation

```yaml
config:
  enabled: true
  require_confirmation: true
  confirmation_template: 'Fetch {source} docs? [web_fetch]'
```

## Examples

```yaml
user_asks_svelte_mcp:
  trigger: 'what tools does svelte mcp provide'
  action: INTERRUPT → "Fetch Svelte MCP endpoint?"
  tool: web_fetch("https://mcp.svelte.dev/mcp")

user_asks_daisyui_via_gitmcp:
  trigger: 'get daisyui docs from gitmcp'
  action: INTERRUPT → "Fetch daisyUI via GitMCP?"
  tool: web_fetch("https://gitmcp.io/saadeghi/daisyui")

user_asks_runes:
  trigger: 'how do svelte runes work'
  action: INTERRUPT → "Fetch Svelte runes docs?"
  tool: web_fetch("https://svelte.dev/docs/svelte/what-are-runes")
```
