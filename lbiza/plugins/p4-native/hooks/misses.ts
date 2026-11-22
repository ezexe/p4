// p4-native's misses: the situations in which a session does by hand what a native feature of this host does, each
// with the feature to name. Six rows have a miss seen live behind them, and say so under `seen`. The others are
// written from the record `weighed.json`: one for each slash command and tool a p4 plugin uses that a session can
// also do by hand, with the by-hand way under `hand`. A used row of the record names the rows that watch it, or
// says in one line why none does. register.ts checks the rows where a tool call has run and where a turn ends, and
// hands one line of context that names the feature, once for each situation in a session. Nothing here starts a
// process or asks a model: a row is a pattern over a call's own input or a turn's own answer. A row checked at a
// call has an option of the plugin, off by default, with which register.ts refuses the by-hand call before it runs.

// One situation. `seen` is the miss as it was seen live, and `hand` the by-hand way of a row written from the
// record, so a row has one of the two. `native` holds the keys of the record the row watches, `names` the tools the
// line names, of which one must answer in the session for the line to be handed, and `at` where it is checked:
// after a tool call or at a turn's end.
export type Miss = {
  id: string
  seen?: string
  hand?: string
  native: readonly string[]
  names: readonly string[]
  line: string
  at: 'call' | 'end'
}

// The tools a row is read off or names.
export const TERMINAL = 'mcp__terminal__run_in_terminal'
export const OWN_TOOL = 'mcp__p4-native__native'
const EVENTS = 'mcp__ccd_session_mgmt__list_events'
const SEARCH = 'mcp__ccd_session_mgmt__search_session_transcripts'
const EXPORT = 'mcp__ccd_session_mgmt__export_transcript'
const STATE = 'mcp__ccd_session_mgmt__get_session'
const USAGE = 'mcp__ccd_session_mgmt__get_usage'
const SESSIONS = 'mcp__ccd_session_mgmt__list_sessions'
const SEND = 'mcp__ccd_session_mgmt__send_message'
const STOP_SESSION = 'mcp__ccd_session_mgmt__stop_session'
const START = 'mcp__ccd_session__start_session'
const STOP_TAB = 'mcp__terminal__stop_terminal_tab'
const READ_TAB = 'mcp__terminal__read_terminal'
const DISCARD = 'mcp__ccd_host__discard_kept_worktree'
const STORAGE = 'mcp__ccd_host__get_storage_usage'
const LIFETIME = 'mcp__p4-temportal__lifetime'
// The app's task list and its box at a turn's end, which a call of either shows is in use.
export const PLAN = 'mcp__ccd_turn__update_plan'
export const WRAP_UP = 'mcp__ccd_turn__wrap_up'
// The tools that read another session, of which a line names those that answer here.
export const READERS = [EVENTS, SEARCH, EXPORT, STATE, USAGE] as const
// The tools `atCall` reads a miss off, which are the ones a refusal can stop.
export const READ_OFF = new Set(['Bash', 'PowerShell', 'Read', 'Grep', 'Glob', 'Edit', 'Write', 'WebFetch', 'Agent', 'TaskCreate', 'TodoWrite'])

// The option of the plugin's `userConfig` that refuses a row's by-hand call: `refuse_` and the row's id, spelled
// with underscores, since a key of `userConfig` takes letters, digits and underscores.
export function optionOf(id: string): string {
  return `refuse_${id.replaceAll('-', '_')}`
}

// The tools whose call can show a miss, or tells the module what the session has already done.
export const WATCHED = new Set([
  'Bash',
  'PowerShell',
  'Read',
  'Grep',
  'Glob',
  'Edit',
  'Write',
  'WebFetch',
  'Agent',
  'TaskCreate',
  'TodoWrite',
  'ToolSearch',
  'AskUserQuestion',
  WRAP_UP,
  TERMINAL,
  'SendMessage',
  'CronCreate',
  'ScheduleWakeup',
])

export const MISSES: readonly Miss[] = [
  {
    id: 'worker-with-no-exit-notice',
    seen: 'A `claude -p` worker was started in a Terminal tab with no notice asked for its exit, seen on 2026-11-19.',
    native: ['SendMessage'],
    names: ['SendMessage'],
    line:
      'p4-native: a `claude -p` worker was started in a Terminal tab and no notice was asked for its exit. ' +
      '`SendMessage` with `notify_when_idle` set to true, to that session, gives one notice when it goes idle or exits.',
    at: 'end',
  },
  {
    id: 'turn-ended-with-a-worker-out',
    seen: 'A session with workers out ended its turn with nothing set to wake it, seen on 2026-11-19.',
    native: ['CronCreate'],
    names: ['CronCreate'],
    line:
      'p4-native: this turn ended with a worker out and nothing set to wake the session. `CronCreate` schedules a ' +
      'prompt that looks in on the worker.',
    at: 'end',
  },
  {
    id: 'gh-run-polled-in-a-loop',
    seen: 'A shell loop polled `gh run list` and slept between the polls, seen on 2026-11-19.',
    native: [],
    names: [],
    line:
      'p4-native: this command polls `gh run` and sleeps. `gh run watch <run id> --exit-status` ends by itself when ' +
      'the run does, so run it once with `run_in_background` and wait for its notice.',
    at: 'call',
  },
  {
    id: 'gh-run-list-short-commit',
    seen: '`gh run list --commit` was given a short commit hash and listed nothing, seen on 2026-11-19.',
    native: [],
    names: [],
    line:
      'p4-native: `gh run list --commit` takes the full 40 characters of a commit hash, and a short one matches no ' +
      'run. `git rev-parse <short hash>` prints the full one.',
    at: 'call',
  },
  {
    id: 'transcript-read-from-disk',
    seen: "A session read another session's transcript file from disk, seen on 2026-11-19.",
    native: [
      'mcp__ccd_session_mgmt__list_events',
      'mcp__ccd_session_mgmt__search_session_transcripts',
      'mcp__ccd_session_mgmt__export_transcript',
      'mcp__ccd_session_mgmt__get_session',
      'mcp__ccd_session_mgmt__get_usage',
    ],
    names: READERS,
    line:
      "p4-native: this reads another session's transcript file from disk. The desktop app's own tools read a " +
      'session: {names}. `list_events` can answer a session at work with almost nothing, which the probe ' +
      '`list-events-of-a-session-at-work` watches.',
    at: 'call',
  },
  {
    id: 'host-limit-from-memory',
    seen: 'A limit of the host was stated from memory, seen on 2026-11-19.',
    native: [],
    names: [OWN_TOOL],
    line:
      "p4-native: the turn's answer states a limit of this host. What was measured here is in the capability map " +
      'and the probes, so call `mcp__p4-native__native` with `map` or `probes` before stating one.',
    at: 'end',
  },
  {
    id: 'file-read-by-a-shell',
    hand: 'A shell command prints one file with `cat`, `head`, `tail`, `less`, `more`, `type` or `Get-Content`.',
    native: ['Read'],
    names: ['Read'],
    line:
      'p4-native: this shell command prints a file. `Read` reads a file with line numbers, a part of it by `offset` ' +
      'and `limit`, and images, PDFs and notebooks too.',
    at: 'call',
  },
  {
    id: 'files-found-by-a-shell',
    hand: 'A shell command lists files by name with `find`, `ls -R`, `dir /s` or `Get-ChildItem -Recurse`.',
    native: ['Glob'],
    names: ['Glob'],
    line: 'p4-native: this shell command finds files by name. `Glob` matches a pattern such as `src/**/*.ts` and needs no shell.',
    at: 'call',
  },
  {
    id: 'text-searched-by-a-shell',
    hand: 'A shell command searches file contents with `grep`, `rg`, `findstr` or `Select-String` at the head of a pipeline.',
    native: ['Grep'],
    names: ['Grep'],
    line:
      'p4-native: this shell command searches file contents. `Grep` is the same search with ripgrep, filtered by ' +
      '`glob` or `type`, and it answers matching lines, files or counts.',
    at: 'call',
  },
  {
    id: 'file-edited-by-a-shell',
    hand: 'A shell command changes a file in place with `sed -i`, `perl -pi`, `awk -i inplace` or `-replace` piped to `Set-Content`.',
    native: ['Edit'],
    names: ['Edit'],
    line:
      'p4-native: this shell command changes a file in place. `Edit` replaces an exact string in a file, fails where ' +
      'the string is not there, and shows ezexe the change.',
    at: 'call',
  },
  {
    id: 'file-written-by-a-shell',
    hand: 'A shell command writes text into a file with `echo` or `printf` and a redirect, a heredoc, `Set-Content` or `Add-Content`.',
    native: ['Write'],
    names: ['Write'],
    line: 'p4-native: this shell command writes text into a file. `Write` writes a file whole, with no quoting of the shell in the way.',
    at: 'call',
  },
  {
    id: 'notebook-edited-as-a-file',
    hand: 'An `Edit` or `Write` call changes a Jupyter notebook as a text file.',
    native: ['NotebookEdit'],
    names: ['NotebookEdit'],
    line: 'p4-native: this changes a Jupyter notebook as text. `NotebookEdit` replaces, inserts or deletes one cell and keeps the file a notebook.',
    at: 'call',
  },
  {
    id: 'powershell-run-from-bash',
    hand: 'A `Bash` call runs `powershell` or `pwsh` with a command of its own.',
    native: ['PowerShell'],
    names: ['PowerShell'],
    line: 'p4-native: this Bash call starts PowerShell. The tool `PowerShell` runs the command itself, with no second layer of quoting.',
    at: 'call',
  },
  {
    id: 'bash-run-from-powershell',
    hand: 'A `PowerShell` call runs `bash`, `sh` or `wsl` with a command of its own.',
    native: ['Bash'],
    names: ['Bash'],
    line: 'p4-native: this PowerShell call starts a POSIX shell. The tool `Bash` runs the command itself, with no second layer of quoting.',
    at: 'call',
  },
  {
    id: 'page-fetched-by-a-shell',
    hand: 'A shell command gets a public web page with `curl`, `wget`, `Invoke-WebRequest` or `Invoke-RestMethod`.',
    native: ['WebFetch'],
    names: ['WebFetch'],
    line: 'p4-native: this shell command gets a web page. `WebFetch` fetches a URL and answers a question about what the page holds.',
    at: 'call',
  },
  {
    id: 'search-engine-fetched',
    hand: "A shell command or a `WebFetch` call gets a search engine's results page.",
    native: ['WebSearch'],
    names: ['WebSearch'],
    line: "p4-native: this gets a search engine's results page. `WebSearch` searches the web and answers the results with their links.",
    at: 'call',
  },
  {
    id: 'claude-run-in-a-shell',
    hand: 'A `Bash` or `PowerShell` call starts a scripted Claude Code run with `claude -p`.',
    native: ['Agent', 'mcp__ccd_session__start_session'],
    names: ['Agent', START],
    line:
      'p4-native: this shell command starts a scripted Claude Code run. A worker whose result comes back by itself ' +
      'is started by {names}.',
    at: 'call',
  },
  {
    id: 'claude-runs-fanned-out-in-a-shell',
    hand: 'A shell command starts several scripted Claude Code runs, in a loop or side by side.',
    native: ['Workflow'],
    names: ['Workflow'],
    line:
      'p4-native: this shell command starts several scripted Claude Code runs. `Workflow` runs a script that starts ' +
      'the agents, in parallel or in stages, and gives one notice when all are done, once ezexe asked for a workflow.',
    at: 'call',
  },
  {
    id: 'session-messaged-in-a-shell',
    hand: 'A shell command sends a prompt into a session that exists, with `claude --resume` or `--continue` and `-p`.',
    native: ['mcp__ccd_session_mgmt__send_message'],
    names: [SEND, 'SendMessage'],
    line: 'p4-native: this shell command sends a prompt into a session that exists. A message reaches a session by {names}.',
    at: 'call',
  },
  {
    id: 'session-resumed-in-a-shell',
    hand: 'A shell command resumes or forks a session with `claude --resume`, `--continue` or `--fork-session`.',
    native: ['/resume', '/fork'],
    names: [],
    line:
      'p4-native: this shell command resumes or forks a Claude Code session. `/resume` opens an earlier session and ' +
      '`/fork` branches this one, each for ezexe to type.',
    at: 'call',
  },
  {
    id: 'page-opened-from-a-shell',
    hand: 'A shell command opens an HTML file in a browser with `start`, `open`, `xdg-open` or `Invoke-Item`.',
    native: ['Artifact'],
    names: ['Artifact'],
    line: 'p4-native: this shell command opens an HTML file for ezexe. `Artifact` publishes a page ezexe opens, keeps and shares.',
    at: 'call',
  },
  {
    id: 'sessions-found-by-their-processes',
    hand: "A shell command lists the machine's processes and picks out Claude Code's.",
    native: ['ListAgents', 'mcp__ccd_session_mgmt__list_sessions', '/list-agents'],
    names: ['ListAgents', SESSIONS],
    line: "p4-native: this shell command looks for Claude Code's sessions among the processes. The sessions and agents are listed by {names}.",
    at: 'call',
  },
  {
    id: 'notification-raised-from-a-shell',
    hand: 'A shell command raises a notification of the system or rings its bell.',
    native: ['PushNotification'],
    names: ['PushNotification'],
    line:
      'p4-native: this shell command raises a notification. `PushNotification` notifies ezexe on the desktop and, ' +
      'with Remote Control connected, on the phone.',
    at: 'call',
  },
  {
    id: 'long-sleep-in-a-shell',
    hand: 'A shell command sleeps for a minute or longer.',
    native: ['ScheduleWakeup'],
    names: ['ScheduleWakeup'],
    line:
      'p4-native: this shell command sleeps for a minute or longer. A command run with `run_in_background` gives a ' +
      'notice at its exit, and `ScheduleWakeup` wakes a session in a `/loop` after a delay.',
    at: 'call',
  },
  {
    id: 'loop-with-a-sleep-in-a-shell',
    hand: 'A shell loop runs a step again and again with a sleep between.',
    native: ['/loop'],
    names: ['Skill'],
    line:
      'p4-native: this shell loop repeats a step on an interval. `/loop` runs a prompt or a command on an interval ' +
      'in the session, and a session starts it by the `Skill` tool.',
    at: 'call',
  },
  {
    id: 'skill-read-as-a-file',
    hand: "A `Read` call or a shell command prints a skill's `SKILL.md`.",
    native: ['Skill'],
    names: ['Skill'],
    line:
      "p4-native: this reads a skill's `SKILL.md` as a file. The `Skill` tool loads a listed skill with its own " +
      'folder and arguments, and a skill is read as a file only to change it.',
    at: 'call',
  },
  {
    id: 'process-killed-in-a-shell',
    hand: 'A shell command stops a process with `kill`, `pkill`, `taskkill` or `Stop-Process`.',
    native: ['TaskStop', 'mcp__terminal__stop_terminal_tab', 'mcp__ccd_session_mgmt__stop_session'],
    names: ['TaskStop', STOP_TAB, STOP_SESSION],
    line:
      'p4-native: this shell command stops a process. A background task, a Terminal tab and a session are each ' +
      'stopped by a tool of their own: {names}.',
    at: 'call',
  },
  {
    id: 'backup-copy-made-by-hand',
    hand: 'A shell command copies a file to a `.bak`, `.orig`, `.old` or `.backup` beside it.',
    native: ['/rewind', 'Checkpoints'],
    names: [],
    line:
      'p4-native: this shell command makes a backup copy of a file. Claude Code checkpoints a file before each edit ' +
      'of its own tools, and `/rewind` brings one back, for ezexe to type.',
    at: 'call',
  },
  {
    id: 'worktree-removed-in-a-shell',
    hand: 'A shell command removes a git worktree, or a folder under `.claude/worktrees`.',
    native: ['mcp__ccd_host__discard_kept_worktree', 'mcp__ccd_host__clean_up_worktrees'],
    names: [DISCARD, 'mcp__ccd_host__clean_up_worktrees'],
    line: "p4-native: this shell command removes a worktree. The desktop app removes its sessions' worktrees by {names}.",
    at: 'call',
  },
  {
    id: 'store-measured-in-a-shell',
    hand: 'A shell command adds up the size of a `.claude` folder with `du` or `Measure-Object`.',
    native: ['mcp__ccd_host__get_storage_usage'],
    names: [STORAGE],
    line: "p4-native: this shell command measures a `.claude` folder. {names} answers what Claude Code's files take on this machine.",
    at: 'call',
  },
  {
    id: 'transcript-copied-by-hand',
    hand: "A shell command copies this session's own transcript file.",
    native: ['/export'],
    names: [],
    line: "p4-native: this shell command copies this session's transcript file. `/export` writes the conversation to a file, for ezexe to type.",
    at: 'call',
  },
  {
    id: 'transcript-measured-by-hand',
    hand: "A shell command measures this session's own transcript file to tell how full the conversation is.",
    native: ['/context'],
    names: [],
    line:
      "p4-native: this shell command measures this session's transcript file. `/context` says how full the " +
      'conversation is and what fills it, for ezexe to type.',
    at: 'call',
  },
  {
    id: 'model-set-by-hand',
    hand: 'An edit of a settings file sets `model` or `effortLevel`, or a shell command sets `ANTHROPIC_MODEL`.',
    native: ['/model'],
    names: [],
    line:
      "p4-native: this sets a session's model or effort in a settings file or a variable. `/model` changes the model " +
      'of the session at once, and it is ezexe\'s to change.',
    at: 'call',
  },
  {
    id: 'store-file-removed-by-hand',
    hand: "A shell command deletes a file of the project's `.claude/p4` store, or an edit changes its `expires.json`.",
    native: ['/lifetime'],
    names: [LIFETIME],
    line:
      "p4-native: this changes the store's files by hand. {names} sets, lists and clears lifetimes, and its sweep " +
      'deletes what is due.',
    at: 'call',
  },
  {
    id: 'plugin-files-changed-by-hand',
    hand: "A shell command or an edit changes the installed plugins' files under `.claude/plugins`.",
    native: ['/plugin', '/reload-plugins'],
    names: [],
    line:
      'p4-native: this changes the installed plugins\' files by hand. `/plugin` installs and updates a plugin, and ' +
      '`/reload-plugins` loads a change in a running session, each for ezexe to type.',
    at: 'call',
  },
  {
    id: 'release-notes-fetched-by-hand',
    hand: "A shell command or a `WebFetch` call gets Claude Code's changelog or its package page.",
    native: ['/release-notes'],
    names: [],
    line: "p4-native: this gets Claude Code's changelog from the web. `/release-notes` prints what changed in this build, for ezexe to type.",
    at: 'call',
  },
  {
    id: 'review-handed-to-an-agent',
    hand: 'An `Agent` call asks a subagent to review a code change.',
    native: ['/code-review', '/review'],
    names: ['Skill'],
    line:
      'p4-native: this hands a code review to a subagent. The bundled skill `code-review` reviews a diff, a branch ' +
      'or a pull request at an effort level, and a session runs it by the `Skill` tool.',
    at: 'call',
  },
  {
    id: 'task-list-kept-by-another-tool',
    hand: "A `TaskCreate` or `TodoWrite` call keeps a task list in a session of the desktop app.",
    native: ['mcp__ccd_turn__update_plan'],
    names: [PLAN],
    line: 'p4-native: this keeps a task list the desktop app does not show. {names} is the list the app shows under the latest message.',
    at: 'call',
  },
  {
    id: 'question-asked-in-prose',
    hand: "A turn's answer ends with a question and its choices written out as a list.",
    native: ['AskUserQuestion', 'mcp__ccd_turn__wrap_up'],
    names: ['AskUserQuestion', WRAP_UP],
    line: "p4-native: the turn's answer ends with a question and its choices in prose. A question with choices is put to ezexe as buttons by {names}.",
    at: 'end',
  },
  {
    id: 'tool-said-missing-with-no-search',
    hand: "A turn's answer says the session has no tool for a thing, in a session that never searched its deferred tools.",
    native: ['ToolSearch'],
    names: ['ToolSearch'],
    line:
      "p4-native: the turn's answer says a tool is missing, and this session never called `ToolSearch`. A tool " +
      'listed by name alone is loaded by `ToolSearch` before it can be called.',
    at: 'end',
  },
  {
    id: 'context-said-full',
    hand: "A turn's answer says the conversation is long or tells ezexe to start a new one.",
    native: ['/compact'],
    names: [],
    line:
      "p4-native: the turn's answer says the conversation is long. `/compact` keeps the session going on a summary, " +
      'and Claude Code compacts by itself before the context is full.',
    at: 'end',
  },
  {
    id: 'terminal-output-asked-of-ezexe',
    hand: "A turn's answer asks ezexe to paste what a terminal printed.",
    native: ['mcp__terminal__read_terminal'],
    names: [READ_TAB],
    line: "p4-native: the turn's answer asks ezexe to paste what a terminal printed. {names} reads what is on screen in ezexe's Terminal panel.",
    at: 'end',
  },
  {
    id: 'command-handed-to-ezexe',
    hand: "A turn's answer tells ezexe to run a command in a terminal.",
    native: ['mcp__terminal__run_in_terminal'],
    names: [TERMINAL],
    line:
      "p4-native: the turn's answer tells ezexe to run a command in a terminal. {names} starts a command in " +
      "ezexe's Terminal panel, where ezexe named what may run there.",
    at: 'end',
  },
]

// A command line that starts a scripted Claude Code run.
const WORKER = /\bclaude(?:\.exe)?\b[^|;&\n]*\s(?:-p|--print)(?:\s|$)/
// One that resumes, continues or forks a session, and what makes a command start several runs.
const RESUMES = /\bclaude(?:\.exe)?\b[^|;&\n]*\s(?:--resume|-r|--continue|-c|--fork-session)(?:[\s=]|$)/
const FANS = /\b(?:for|while|until|foreach|xargs|parallel)\b|ForEach-Object/
// A command line that runs one script file, whose path is the first group.
const SCRIPT = /^\s*(?:[&.]|sh|bash|pwsh|powershell)\s+['"]?([^'"]+\.(?:ps1|sh))['"]?\s*$/
// A polled `gh run`, a wait between polls, and a short hash handed to `--commit`.
const GH_RUN = /\bgh\s+run\s+(?:list|view)\b/
const WAITS = /\b(?:sleep|Start-Sleep)\b/
const SHORT = /\bgh\s+run\s+list\b[^|;&\n]*--commit[=\s]+['"]?([0-9a-fA-F]{4,39})['"]?(?![0-9a-fA-F])/
// A transcript file of Claude Code, as its path is spelled on either system.
const TRANSCRIPT = /[\\/]\.claude[\\/]projects[\\/][^\s"'|;]*\.jsonl/
// A sentence that says the host cannot do a thing.
const HOST = '(?:desktop app|claude code|this host|this session|the harness|a headless (?:run|session)|a scripted run)'
const CANNOT = "(?:cannot|can't|can not|does not support|doesn't support|is not available|isn't available|has no way|has no tool|there is no way)"
const LIMIT = new RegExp(`\\b${HOST}\\b[^.\\n]{0,80}\\b${CANNOT}|${CANNOT}[^.\\n]{0,80}\\b${HOST}\\b`, 'i')

// What stands at the head of a pipeline, each read off the first stage alone: a file printed, files found by name,
// contents searched, text written by a redirect, and a page opened.
const PRINTS = /^(?:cat|head|tail|less|more|Get-Content|gc)\b((?:\s+-{1,2}[A-Za-z][\w-]*|\s+-?\d+)*)\s+(?!-)[^\s<>]+(?:\s+-{1,2}[A-Za-z][\w-]*(?:\s+\d+)?)*$/i
const TYPES = /^type\s+(?!-)[^\s<>]+$/i
const FINDS = /^(?:find\s+\S.*\s-(?:i?name|type|i?path)\b|ls\s+-\w*R|dir\s+\/s\b|(?:Get-ChildItem|gci|ls|dir)\b.*\s-Recurse\b)/i
const ACTS = /\s-(?:exec|execdir|delete|ok)\b/
const SEARCHES = /^(?:grep|egrep|fgrep|rg|ag|ack|findstr|Select-String|sls)\b/i
const ECHOES = /^(?:echo|printf|Write-Output)\b[^>]*>{1,2}\s*(?!&|\/dev\/null|\$null|nul\b)\S/i
const OPENS = /^(?:start|open|xdg-open|explorer(?:\.exe)?|Invoke-Item|ii|Start-Process|cmd\s+\/c\s+start)\b.*\.html?\b/i
const KILLS = /^(?:sudo\s+)?(?:xargs\s+(?:-\S+\s+)*)?(?:kill|pkill|killall|taskkill|Stop-Process|spps)\b/i
// What is read off a whole command line.
const EDITS = /\bsed\b[^|;&\n]*\s-[a-zA-Z]*i(?:\b|\.)|\bperl\s+-[a-zA-Z]*p[a-zA-Z]*i|\bawk\s+-i\s+inplace\b|-replace\b[^|\n]*\|\s*(?:Set-Content|sc)\b/
const HEREDOC = /\bcat\s*(?:>{1,2}\s*\S+\s*)?<<-?\s*['"]?\w+['"]?(?:\s*>{1,2}\s*\S+)?|\b(?:Set-Content|Add-Content)\b/i
const INTO_A_FILE = />{1,2}\s*[^&\s]|\b(?:Set-Content|Add-Content)\b/i
const POWERSHELL = /\b(?:powershell|pwsh)(?:\.exe)?\s+-/i
const POSIX = /\b(?:bash|sh|zsh)(?:\.exe)?\s+(?:-\w+\s+)*-\w*c\b|\bwsl(?:\.exe)?\s+[^-\s]/i
const FETCHES = /\b(?:curl|wget|Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b[^|;&\n]*\bhttps?:\/\/([^\s/'":]+)/i
const LOCAL = /^(?:localhost|127\.|0\.0\.0\.0|\[::1\]|.*\.localhost$|.*\.test$)/i
const SENDS = /\s-(?:X|d|F|T|o|O)\b|\s--(?:request|data|data-\w+|form|output|upload-file|remote-name)\b|\s-(?:Method|Body|OutFile|InFile)\b/
const ENGINE = /https?:\/\/(?:www\.)?(?:google\.[a-z.]+\/search|bing\.com\/search|(?:html\.)?duckduckgo\.com\/(?:html\/?)?\?|search\.brave\.com\/search|[a-z.]*yahoo\.com\/search)/i
const PROCESSES = /\b(?:tasklist|Get-Process|gps|ps|pgrep|wmic\s+process|Get-CimInstance\s+Win32_Process)\b[^\n]*\bclaude\b/i
const NOTIFIES = /\bnotify-send\b|\bterminal-notifier\b|display\s+notification|New-BurntToastNotification|\[console\]::beep|\bmsg(?:\.exe)?\s+\*|ToastNotificationManager/i
const SLEEPS = /\b(?:sleep|Start-Sleep)\s+(?:-(?:s|Seconds)\s+)?(\d+)([smh]?)\b|\btimeout\s+\/t\s+(\d+)/i
const LOOPS = /\b(?:while|until|for)\b[\s\S]*\b(?:sleep|Start-Sleep)\b/i
const SKILL_FILE = /[\\/]skills[\\/][^\\/\s"']+[\\/]SKILL\.md\b/i
const PRINTER = /\b(?:cat|head|tail|less|more|type|Get-Content|gc)\b/i
const BACKUP = /\b(?:cp|copy|Copy-Item|cpi)\b[^|;&\n]*\.(?:bak|orig|backup|old|save)\b/i
const COPIES = /\b(?:cp|copy|Copy-Item|cpi)\b/i
const MEASURES = /\b(?:wc|stat|du|Get-Item|Measure-Object)\b|\bls\s+-\w*l/i
const WORKTREE = /\bgit\b[^|;&\n]*\bworktree\s+(?:remove|prune)\b|\b(?:rm|Remove-Item|ri|rmdir|rd)\b[^|;&\n]*[\\/]\.claude[\\/]worktrees[\\/]/i
const STORE_SIZE = /\bdu\b[^|;&\n]*\.claude\b|\.claude\b[^\n]*\bMeasure-Object\b/i
const SETTINGS = /[\\/]\.claude[\\/]settings(?:\.local)?\.json$/i
const MODEL_KEY = /"(?:model|effortLevel)"\s*:/
const MODEL_VAR = /(?:\bexport\s+|\$env:|\bset\s+)ANTHROPIC_MODEL\s*=/i
const STORE_REMOVED = /\b(?:rm|del|Remove-Item|ri|rmdir|rd)\b[^|;&\n]*\.claude[\\/]p4[\\/]/i
const EXPIRES = /[\\/]\.claude[\\/]p4[\\/]temportal[\\/]expires\.json$/i
const PLUGIN_FILES = /[\\/]\.claude[\\/]plugins[\\/](?:cache|marketplaces|installed_plugins\.json|known_marketplaces\.json)/i
const MOVES = /\b(?:cp|mv|rm|rsync|robocopy|xcopy|Copy-Item|Move-Item|Remove-Item|sed)\b|>{1,2}/i
const CHANGELOG = /claude-code[\\/\w.-]*\/(?:CHANGELOG(?:\.md)?|releases)\b|\bnpm\s+(?:view|info|show)\s+@anthropic-ai\/claude-code\b/i
const REVIEW = /\bcode[- ]review\b|\breview\s+(?:the|this|my|these|our|a)\s+(?:code|diff|change|changes|commit|commits|branch|pr|pull request|patch)\b/i
// What is read off a turn's answer.
const CHOICE = /^\s*(?:[-*]\s+)?(?:\*\*)?(?:\(?[A-Da-d1-4][).:]|Option\s+[A-D1-4]\b)/
const NO_TOOL =
  /\b(?:do not|don't|does not|doesn't) have (?:access to )?(?:a|an|any|the|that)\b[^.\n]{0,60}\btool\b|\bno (?:such )?tool (?:named|called|for|to|that)\b|\btool\b[^.\n]{0,40}\b(?:is not|isn't) (?:available|loaded)\b/i
const FULL =
  /\b(?:context(?: window)?|conversation)\b[^.\n]{0,40}\b(?:is|has grown|has become)\s+(?:getting\s+|almost\s+|nearly\s+|now\s+|too\s+|very\s+)?(?:long|full|large)\b|\b(?:start|open|begin)\s+a\s+(?:new|fresh)\s+(?:session|conversation|chat)\b|\brunning\s+(?:low\s+on|out\s+of)\s+context\b/i
const PASTE = /\b(?:paste|share|send|copy|show)\b[^.?\n]{0,40}\b(?:output|errors?|logs?|what (?:it|the terminal) (?:says|printed|shows))\b/i
const RUN_IT = /\b(?:run|execute|type|enter|paste)\b[^.\n]{0,60}\b(?:in|into)\s+(?:your|a|the)\s+(?:own\s+)?(?:terminal|shell|powershell|command prompt|console)\b/i

// A minute, in the seconds a sleep is counted in.
const LONG = 60

function text(input: Record<string, unknown>, key: string): string {
  const value = input[key]

  return typeof value === 'string' ? value : ''
}

// The stages of a command line: each part between `&&`, `||`, `;`, a line end and `|`, trimmed. `heads` keeps the
// first stage of each pipeline alone, where a command reads a file and takes nothing from another.
function stages(command: string, isHeadOnly: boolean): string[] {
  return command
    .split(/&&|\|\||;|\n/)
    .flatMap(part => (isHeadOnly ? [part.split('|')[0] ?? ''] : part.split('|')))
    .map(stage => stage.trim())
    .filter(stage => stage !== '')
}

// How many seconds a command line sleeps for, at most, and 0 where it sleeps for none.
function slept(command: string): number {
  const found = SLEEPS.exec(command)
  if (found === null) return 0
  const count = Number(found[1] ?? found[3] ?? 0)
  const unit = found[2] === 'h' ? 3600 : found[2] === 'm' ? 60 : 1

  return count * unit
}

// Whether a line or a script's text starts a scripted Claude Code run.
export function isWorker(source: string): boolean {
  return WORKER.test(source)
}

// The script file a Terminal command runs, and nothing for a line that runs none.
export function scriptOf(command: string): string | undefined {
  return SCRIPT.exec(command)?.[1]
}

// Whether a call asks for a notice of another session's exit, and whether it sets something that wakes this one.
export function isNotice(tool: string, input: Record<string, unknown>): boolean {
  return tool === 'SendMessage' && input.notify_when_idle === true
}

export function isWake(tool: string, input: Record<string, unknown>): boolean {
  return tool === 'CronCreate' || tool === 'ScheduleWakeup' || isNotice(tool, input)
}

// The misses a shell command shows, by id. `isBash` tells the two shell tools apart, and `own` is this session's id.
function ofShell(command: string, isBash: boolean, own: string): string[] {
  const out: string[] = []
  const heads = stages(command, true)
  const every = stages(command, false)
  const file = TRANSCRIPT.exec(command)?.[0]
  const isOwn = file !== undefined && own !== '' && file.includes(own)

  const isPolled = GH_RUN.test(command) && WAITS.test(command)
  if (isPolled) out.push('gh-run-polled-in-a-loop')
  if (SHORT.test(command)) out.push('gh-run-list-short-commit')
  if (file !== undefined && !isOwn) out.push('transcript-read-from-disk')
  if (isOwn && COPIES.test(command)) out.push('transcript-copied-by-hand')
  else if (isOwn && MEASURES.test(command)) out.push('transcript-measured-by-hand')

  const isSkill = SKILL_FILE.test(command) && PRINTER.test(command)
  if (isSkill) out.push('skill-read-as-a-file')
  else if (file === undefined && heads.some(head => PRINTS.test(head) || (!isBash && TYPES.test(head)))) out.push('file-read-by-a-shell')
  if (heads.some(head => FINDS.test(head) && !ACTS.test(head))) out.push('files-found-by-a-shell')
  if (heads.some(head => SEARCHES.test(head))) out.push('text-searched-by-a-shell')
  const isEdited = EDITS.test(command)
  if (isEdited) out.push('file-edited-by-a-shell')
  else if (heads.some(head => ECHOES.test(head)) || (HEREDOC.test(command) && INTO_A_FILE.test(command))) out.push('file-written-by-a-shell')

  if (isBash && POWERSHELL.test(command)) out.push('powershell-run-from-bash')
  if (!isBash && POSIX.test(command)) out.push('bash-run-from-powershell')

  const host = FETCHES.exec(command)?.[1]
  if (ENGINE.test(command)) out.push('search-engine-fetched')
  else if (CHANGELOG.test(command)) out.push('release-notes-fetched-by-hand')
  else if (host !== undefined && !LOCAL.test(host) && !SENDS.test(command)) out.push('page-fetched-by-a-shell')

  if (RESUMES.test(command)) out.push(WORKER.test(command) ? 'session-messaged-in-a-shell' : 'session-resumed-in-a-shell')
  else if (WORKER.test(command)) {
    const runs = command.match(new RegExp(WORKER.source, 'g'))?.length ?? 0
    out.push(runs > 1 || FANS.test(command) ? 'claude-runs-fanned-out-in-a-shell' : 'claude-run-in-a-shell')
  }

  if (heads.some(head => OPENS.test(head))) out.push('page-opened-from-a-shell')
  if (PROCESSES.test(command)) out.push('sessions-found-by-their-processes')
  if (NOTIFIES.test(command)) out.push('notification-raised-from-a-shell')
  if (!isPolled && LOOPS.test(command)) out.push('loop-with-a-sleep-in-a-shell')
  else if (!isPolled && slept(command) >= LONG) out.push('long-sleep-in-a-shell')
  if (every.some(stage => KILLS.test(stage))) out.push('process-killed-in-a-shell')
  if (BACKUP.test(command)) out.push('backup-copy-made-by-hand')
  if (WORKTREE.test(command)) out.push('worktree-removed-in-a-shell')
  if (STORE_SIZE.test(command)) out.push('store-measured-in-a-shell')
  if (MODEL_VAR.test(command)) out.push('model-set-by-hand')
  if (STORE_REMOVED.test(command)) out.push('store-file-removed-by-hand')
  if (PLUGIN_FILES.test(command) && MOVES.test(command)) out.push('plugin-files-changed-by-hand')

  return out
}

// The misses one call shows, by id. `own` is this session's id, whose transcript file is its own to read.
export function atCall(tool: string, input: Record<string, unknown>, own: string): string[] {
  if (tool === 'Bash' || tool === 'PowerShell') return ofShell(text(input, 'command'), tool === 'Bash', own)
  const out: string[] = []
  const path = text(input, 'file_path')
  const read = [path, text(input, 'path'), text(input, 'pattern')].join('\n')
  const file = TRANSCRIPT.exec(read)?.[0]
  if (file !== undefined && (own === '' || !file.includes(own))) out.push('transcript-read-from-disk')
  if (tool === 'Read' && SKILL_FILE.test(path)) out.push('skill-read-as-a-file')
  if (tool === 'Edit' || tool === 'Write') {
    const written = `${text(input, 'new_string')}\n${text(input, 'content')}`
    if (/\.ipynb$/i.test(path)) out.push('notebook-edited-as-a-file')
    if (SETTINGS.test(path) && MODEL_KEY.test(written)) out.push('model-set-by-hand')
    if (EXPIRES.test(path)) out.push('store-file-removed-by-hand')
    if (PLUGIN_FILES.test(path)) out.push('plugin-files-changed-by-hand')
  }
  if (tool === 'WebFetch') {
    const url = text(input, 'url')
    if (ENGINE.test(url)) out.push('search-engine-fetched')
    else if (CHANGELOG.test(url)) out.push('release-notes-fetched-by-hand')
  }
  if (tool === 'Agent' && REVIEW.test(`${text(input, 'description')}\n${text(input, 'prompt')}`)) out.push('review-handed-to-an-agent')
  if (tool === 'TaskCreate' || tool === 'TodoWrite') out.push('task-list-kept-by-another-tool')

  return out
}

// What a session's own calls showed by a turn's end: a worker out, a notice asked for its exit, something set that
// wakes the session, the plugin's own tool or command asked, the deferred tools searched, and, in this turn, a
// question put to ezexe by a tool.
export type AtEnd = {
  isWorkerOut: boolean
  isNoticed: boolean
  isWoken: boolean
  hasAsked: boolean
  hasSearched: boolean
  isPut: boolean
}

// Whether an answer ends with a question whose choices are written out as a list of two or more.
function asksInProse(answer: string): boolean {
  const lines = answer.trim().split('\n')
  if (!lines.slice(-6).some(line => /\?\s*$/.test(line))) return false

  return lines.filter(line => CHOICE.test(line)).length > 1
}

// The misses a turn's end shows, by id: a worker out with no notice asked, that and nothing else set to wake the
// session, an answer that states a limit of the host in a session that never asked the plugin, and an answer that
// does by hand what a tool of the session does.
export function atEnd(state: AtEnd, answer: string): string[] {
  const out: string[] = []
  if (state.isWorkerOut && !state.isNoticed) out.push('worker-with-no-exit-notice')
  if (state.isWorkerOut && !state.isNoticed && !state.isWoken) out.push('turn-ended-with-a-worker-out')
  if (!state.hasAsked && LIMIT.test(answer)) out.push('host-limit-from-memory')
  if (!state.isPut && asksInProse(answer)) out.push('question-asked-in-prose')
  if (!state.hasSearched && NO_TOOL.test(answer)) out.push('tool-said-missing-with-no-search')
  if (FULL.test(answer)) out.push('context-said-full')
  if (PASTE.test(answer)) out.push('terminal-output-asked-of-ezexe')
  if (RUN_IT.test(answer)) out.push('command-handed-to-ezexe')

  return out
}
