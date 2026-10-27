> _**legacy** - verbatim archive of `.temp/Roboto/PARAMS.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word, unchanged. Overview: [legacy/README.md](../README.md)._

# Tool Parameters

**Trigger:** `"show tool params"`, `"param details"`

## conversation_search

```yaml
parameters:
  query:
    type: string
    required: true
    description: 'Keywords to search'
  max_results:
    type: integer
    required: false
    default: 5
    range: 1-10
```

## recent_chats

```yaml
parameters:
  n:
    type: integer
    required: false
    default: 3
    range: 1-20
  sort_order:
    type: string
    required: false
    default: 'desc'
    options: ['asc', 'desc']
  before:
    type: datetime
    required: false
    description: 'Filter chats before this time (ISO format)'
  after:
    type: datetime
    required: false
    description: 'Filter chats after this time (ISO format)'
```

## web_search

```yaml
parameters:
  query:
    type: string
    required: true
    description: 'Search query'
```

## web_fetch

```yaml
parameters:
  url:
    type: string
    required: true
  allowed_domains:
    type: array[string]
    required: false
  blocked_domains:
    type: array[string]
    required: false
  text_content_token_limit:
    type: integer
    required: false
```

## bash_tool

```yaml
parameters:
  command:
    type: string
    required: true
  description:
    type: string
    required: true
```

## view

```yaml
parameters:
  path:
    type: string
    required: true
  description:
    type: string
    required: true
  view_range:
    type: array[integer, integer]
    required: false
    description: '[start_line, end_line]'
```

## create_file

```yaml
parameters:
  description:
    type: string
    required: true
    order: 1
  path:
    type: string
    required: true
    order: 2
  file_text:
    type: string
    required: true
    order: 3
```

## str_replace

```yaml
parameters:
  path:
    type: string
    required: true
  old_str:
    type: string
    required: true
  new_str:
    type: string
    required: false
    default: ''
  description:
    type: string
    required: true
```

## present_files

```yaml
parameters:
  filepaths:
    type: array[string]
    required: true
    min_items: 1
```

## memory_user_edits

```yaml
parameters:
  command:
    type: string
    required: true
    options: ['view', 'add', 'remove', 'replace']
  control:
    type: string
    required: false
    max_length: 500
    description: "For 'add': content to add"
  line_number:
    type: integer
    required: false
    min: 1
    description: "For 'remove'/'replace': line to modify"
  replacement:
    type: string
    required: false
    max_length: 500
    description: "For 'replace': new content"
```