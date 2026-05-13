# Shared Skills Directory

`skills/` is the shared skill source for this workspace. Keep reusable agent
skills here, then expose the same directory to Claude, Codex, and Cursor with
symlinks. This avoids maintaining separate copies under each agent directory.

## Current Layout

As inspected in `/home/ecs-user/dt_workspace`:

- `skills/` is the real directory and an independent git repository.
- `skills` remote: `git@github.com:sstonehu/skills.git`.
- `.claude/skills -> /home/ecs-user/dt_workspace/skills`.
- `.codex/skills -> ../skills`.
- `.cursor/skills -> ../skills`.
- `dural_trade/.cursor/skills` is a real local directory, not a symlink. Treat
  it as a legacy/project-local Cursor skill surface unless it is deliberately
  replaced with a symlink.

Prefer relative symlinks for new machines because absolute paths break when the
workspace is restored under a different home directory.

## Restore On A New Dev Server

Run these commands from the workspace root, for example
`/home/ecs-user/dt_workspace`.

```bash
git clone git@github.com:sstonehu/skills.git skills

mkdir -p .claude .codex .cursor
ln -sfnT ../skills .claude/skills
ln -sfnT ../skills .codex/skills
ln -sfnT ../skills .cursor/skills
```

If the workspace already has `skills/`, update it instead:

```bash
git -C skills pull --ff-only
```

If a destination such as `.cursor/skills` already exists as a real directory,
back it up before creating the symlink:

```bash
mv .cursor/skills ".cursor/skills.backup.$(date +%Y%m%d%H%M%S)"
ln -sfnT ../skills .cursor/skills
```

For sub-repositories that need their own Cursor skill mount, create the link
from that repo's `.cursor` directory back to the workspace-level `skills/`.
Example for `dural_trade`:

```bash
mkdir -p dural_trade/.cursor
ln -sfnT ../../skills dural_trade/.cursor/skills
```

Only do this after confirming any existing project-local Cursor skills have
been migrated or intentionally discarded.

## Verify The Mounts

```bash
ls -ld skills .claude/skills .codex/skills .cursor/skills
readlink -f .claude/skills .codex/skills .cursor/skills
find -L .claude/skills -maxdepth 2 -name SKILL.md -print
git -C skills status --short
```

Expected result:

- Every agent skill path resolves to the same workspace `skills/` directory.
- `find -L ... -name SKILL.md` lists the shared skill definitions.
- `git -C skills status --short` is clean unless you are actively editing
  shared skills.

## Adding Or Updating Skills

- Edit the source under `skills/`, not under `.claude/skills`,
  `.codex/skills`, or `.cursor/skills`. Those paths should be symlinks.
- Prefer the portable skill shape `skills/<skill-name>/SKILL.md`.
- Include frontmatter with at least `name` and `description`.
- Keep helper scripts, templates, and checklists inside the same skill folder.
- Use paths that work from the workspace root, or clearly document when a script
  must be run from a specific repository.
- Preserve executable bits for scripts that are invoked directly.
- Commit shared skill changes inside the `skills/` repo.

Legacy flat markdown skills such as `debug-issue.md`, `explore-codebase.md`,
`refactor-safely.md`, and `review-changes.md` still exist. Prefer the
`<skill-name>/SKILL.md` layout for new shared skills unless an agent integration
specifically requires a flat file.

## Migration Checklist

1. Clone or restore the workspace repositories.
2. Clone or update `skills/` from `git@github.com:sstonehu/skills.git`.
3. Recreate `.claude/skills`, `.codex/skills`, and `.cursor/skills` as symlinks
   to the workspace `skills/` directory.
4. For repo-local Cursor mounts, replace real directories only after migrating
   any unique local skills.
5. Restore workspace-local plugin directories and `.agents/plugins/marketplace.json`.
6. Reinstall global agent plugins such as `caveman`, `oh-my-codex`, and
   `oh-my-claudecode` as described below.
7. Restore agent settings such as `.claude/settings.json`, `.mcp.json`, and any
   project-local settings required by the target machine. Keep API keys and
   auth tokens in machine-local secret/config files; do not commit them.
8. Run the verification commands above.
9. Restart Claude, Codex, or Cursor so they rescan the mounted skills and
   plugins.

## Ownership Rule

`skills/` is the source of truth. Agent-specific directories should only expose
it. If a skill is useful to more than one agent, move it into `skills/` first
and then let the symlinks make it visible everywhere.

## Workspace Plugins

The workspace also uses plugins outside this `skills/` repo. Restore plugins
after restoring `skills/`, because some plugin surfaces add their own skills,
hooks, prompts, agents, and runtime state.

### Workspace-local Codex plugins

The local Codex plugin marketplace is:

- `.agents/plugins/marketplace.json`

It currently advertises:

- `dt-mev-skills`
  - Source: `plugins/dt-mev-skills`
  - Manifest: `plugins/dt-mev-skills/.codex-plugin/plugin.json`
  - Policy: `INSTALLED_BY_DEFAULT`
  - Purpose: DT/MEV replay analysis, DEX integration review, workspace triage
- `caveman`
  - Source: `.codex-plugins/caveman`
  - Manifest: `.codex-plugins/caveman/.codex-plugin/plugin.json`
  - Policy: `AVAILABLE`
  - Purpose: terse communication and compression skills

Preserve these directories when migrating the workspace:

```bash
.agents/plugins/marketplace.json
.codex-plugins/caveman/
plugins/dt-mev-skills/
```

Verify after migration:

```bash
sed -n '1,220p' .agents/plugins/marketplace.json
sed -n '1,120p' .codex-plugins/caveman/.codex-plugin/plugin.json
sed -n '1,120p' plugins/dt-mev-skills/.codex-plugin/plugin.json
```

### Shared Caveman plugin

`caveman` is installed in multiple surfaces:

- Workspace-local Codex plugin: `.codex-plugins/caveman`
- Claude plugin marketplace/cache:
  - Marketplace: `~/.claude/plugins/marketplaces/caveman`
  - Installed plugin id: `caveman@caveman`
  - Current commit observed: `ef6050c5e1848b6880ff47c32ade1a608a64f85e`
- Generic agent skills:
  - `~/.agents/skills/caveman`
  - `~/.agents/skills/compress`
  - `~/.agents/skills/find-skills`

To restore the Claude-side plugin from a fresh machine, run these inside Claude
Code:

```text
/plugin marketplace add https://github.com/JuliusBrussee/caveman
/plugin install caveman
```

Then verify:

```bash
test -f ~/.claude/plugins/installed_plugins.json
test -d ~/.claude/plugins/marketplaces/caveman
test -f ~/.agents/skills/caveman/SKILL.md
```

### Codex-only plugins and OMX

Codex currently has:

- Codex CLI: `codex-cli 0.128.0`
- Official curated plugin: `superpowers@openai-curated`
  - Enabled in `~/.codex/config.toml`:
    - `[plugins."superpowers@openai-curated"]`
    - `enabled = true`
  - Cached plugin version observed: `superpowers` `5.1.0`
- oh-my-codex / OMX:
  - Global npm package: `oh-my-codex@0.14.3`
  - CLI check: `omx --version`
  - Install state: `~/.codex/.omx/install-state.json`
  - Hooks: `~/.codex/hooks.json`
  - Installed surfaces: `~/.codex/AGENTS.md`, `~/.codex/skills/`,
    `~/.codex/prompts/`, `~/.codex/agents/`
  - Workspace runtime state: `.omx/`

Restore Codex/OMX on a new machine:

```bash
npm install -g @openai/codex@0.128.0
npm install -g oh-my-codex@0.14.3
omx setup
```

Then restore or reapply the local `~/.codex/config.toml` settings needed for
this workspace, especially trusted project entries, MCP servers, model provider
settings, and:

```toml
[plugins."superpowers@openai-curated"]
enabled = true
```

Verify:

```bash
codex --version
omx --version
test -f ~/.codex/hooks.json
test -f ~/.codex/AGENTS.md
find ~/.codex/skills -maxdepth 2 -name SKILL.md | sort
```

If OMX behavior is missing after migration, run:

```bash
omx doctor
omx setup
```

### Claude-only plugins and OMC

Claude Code currently has:

- Claude Code CLI: `2.1.133`
- `oh-my-claudecode@omc`
  - Marketplace repo: `Yeachan-Heo/oh-my-claudecode`
  - Current project plugin version observed: `4.13.6`
  - Current git commit observed: `aacde3e19c40e891479e22fb30e6169a8782d7e4`
  - Installed plugin cache:
    - `~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.6`
    - `~/.claude/plugins/cache/omc/oh-my-claudecode/aacde3e19c40`
  - Marketplace clone:
    - `~/.claude/plugins/marketplaces/oh-my-claudecode`
  - Workspace runtime state:
    - `.omc/`
- Project enablement:
  - `.claude/settings.json` contains
    `"enabledPlugins": { "oh-my-claudecode@omc": true }`

Restore Claude/OMC on a new machine:

```bash
npm install -g @anthropic-ai/claude-code@2.1.133
```

Then run these inside Claude Code:

```text
/plugin marketplace add https://github.com/Yeachan-Heo/oh-my-claudecode
/plugin install oh-my-claudecode
```

Verify:

```bash
claude --version
test -f ~/.claude/plugins/installed_plugins.json
test -d ~/.claude/plugins/marketplaces/oh-my-claudecode
test -d ~/.claude/plugins/cache/omc/oh-my-claudecode
```

Do not treat `.omx/` or `.omc/` as the plugin installation itself. They are
workspace runtime state. Copy them only if you intentionally want to preserve
session state, notes, wiki, or project memory.
