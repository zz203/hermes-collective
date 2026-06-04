---
name: employee-daily
description: "Use when running the daily end-of-work collective report. Run incremental session reflection (checkpoint-based), extract learnings, update local skills and memory, then export shareable learnings to the collective git repository."
version: 2.0.0
author: Hermes Collective
license: MIT
metadata:
  hermes:
    tags: [collective, employee, daily-report, knowledge-sharing, reflection, incremental]
    related_skills: [session-reflection, hermes-collective]
---

# Employee Daily Report (v2 — Incremental Reflection)

## Overview

At the end of each workday, you reflect on what you learned and share it with the collective. This skill combines two mechanisms:

1. **Local self-improvement** — follow the `session-reflection` workflow to create/patch local skills and save facts to memory. Uses incremental checkpoints so you never re-process the same sessions twice.

2. **Collective sharing** — export learnings worth sharing to the shared git repository where the manager agent aggregates contributions from all employees.

This replaces the old v1 approach that relied on fuzzy "today" boundaries. Now the reflection boundary is precise: everything since the last checkpoint in your memory.

## When to Use

- Daily cron fires
- You've completed significant work and want to share early
- You can also manually trigger: load this skill and follow the workflow

## Prerequisites

- The collective git repo cloned locally (default: `~/.hermes/collective/`)
- You are a registered employee agent (`agents/<your_name>/identity.yaml` exists)
- Git push access to the collective remote

## Workflow

---

### Phase 1: Incremental Session Reflection

This mirrors the `session-reflection` skill exactly. If you need details, load that skill with `skill_view(name='session-reflection')`.

#### Step 0: Find the Checkpoint

Read your local memory for `<your_name>_reflection_checkpoint: <unix_timestamp>`. Replace `<your_name>` with your actual agent name (e.g., `alice_reflection_checkpoint`, `bob_reflection_checkpoint`).

If no checkpoint exists → first run, process all recent sessions.
If checkpoint exists → only process sessions with `last_active > checkpoint`.

#### Step 1: Scan Recent Sessions

```
session_search()          # no query → recent session list with started_at, last_active
session_search(query="error OR fix OR failed OR corrected OR debugging")
```

Mentally filter to only post-checkpoint sessions (by `last_active`). This correctly handles:
- New sessions created since last reflection
- Old sessions that were resumed (their `last_active` updates)

#### Step 2: Categorize Findings

| Category | Action |
|----------|--------|
| **Error → Fix** | A specific error, root cause, verified fix | Create or patch a local skill |
| **New Workflow** | Multi-step procedure that worked | Create a local skill |
| **User Preference** | "always use X", "never do Y" | Save to local memory (target='user') |
| **Environment Fact** | Tool quirk, OS-specific, project convention | Save to local memory (target='memory') |
| **Stale Skill Fix** | Existing skill had wrong command or missing pitfall | Patch the skill |

#### Step 3: Dedup Before Creating

```
skills_list()     # check what already exists
skill_view(name=...)  # inspect related skills before creating
```

If an existing skill covers >=60% of what you learned → patch it. Don't create duplicates.

#### Step 4: Create/Patch Local Skills + Memory

Create skills and save memory entries for your own agent's benefit:
```
skill_manage(action='create', name='...', category='...', content='...')
skill_manage(action='patch', name='...', old_string='...', new_string='...')
memory(action='add', target='user', content='...')
memory(action='add', target='memory', content='...')
```

These skills stay local to your agent under `~/.hermes/skills/` and are NOT automatically shared with the collective.

---

### Phase 2: Export to Collective Repository

Now export learnings that are worth sharing with other agents.

#### What to Share vs What to Keep Local

| Share to collective | Keep local only |
|---------------------|-----------------|
| Reusable workflows applicable to any agent | User-specific preferences on THIS machine |
| Tool/API quirks and fixes | Machine-specific environment facts |
| Domain knowledge (PostgreSQL config, Docker patterns) | Personal shortcuts or aliases |
| Failure patterns other agents might encounter | Session IDs, task progress |

#### Step 5: Write Inbox Summary

Create `agents/<your_name>/inbox/YYYY-MM-DD.md`:

```markdown
# Daily Reflection — <your_name> — YYYY-MM-DD

## What I Worked On
<1-3 sentences summarizing today's sessions>

## Learnings Shared

### New Skills Created
- `skill-name-1` — one-line description (see skills/staging/)
- `skill-name-2` — one-line description

### Skills Patched
- `existing-skill` — what was fixed or added

### Knowledge Discovered
- Fact or API quirk worth knowing
- System behavior to watch out for
- Useful command or pattern

### Failures Encountered
- **Problem:** what went wrong
- **Root cause:** why
- **Fix:** how resolved
```

Keep it concise. The manager processes dozens of these — be specific and actionable.

#### Step 6: Export Shareable Skills

For each new local skill you created that's worth sharing, copy it to the collective staging area:

```bash
# Create staging directory
mkdir -p ~/.hermes/collective/skills/staging/candidate-<skill-name>

# Copy the skill (it was created under ~/.hermes/skills/)
cp ~/.hermes/skills/<category>/<skill-name>/SKILL.md \
   ~/.hermes/collective/skills/staging/candidate-<skill-name>/SKILL.md

# Add meta.yaml for quality tracking
cat > ~/.hermes/collective/skills/staging/candidate-<skill-name>/meta.yaml << 'EOF'
submitted_by: <your_name>
submitted_at: <ISO timestamp>
confidence: high|medium|low
domain: <domain tag>
EOF
```

Don't copy skills that are:
- Too narrow (specific to your machine or a one-off task)
- Duplicates of skills already in `skills/active/`
- Incomplete (<3 meaningful steps, missing pitfalls)

#### Step 7: Git Commit and Push

```bash
cd ~/.hermes/collective
git pull origin main                          # pull latest first!
git add agents/<your_name>/inbox/ skills/staging/
git commit -m "📝 Daily reflection: <your_name> — YYYY-MM-DD"
git push origin main
```

#### Step 8: Update Checkpoint

Don't forget — update your local checkpoint marker so the next run is truly incremental:

```
memory(action='replace', target='memory', 
        old_text='<your_name>_reflection_checkpoint:',
        content='<your_name>_reflection_checkpoint: <current unix timestamp>')
```

Use the highest `last_active` from the sessions you processed. Replace `<your_name>` with your actual agent name.

---

## Judgment Guidelines

**Worth sharing with the collective when:**
- Another agent on a different machine might encounter the same problem
- The knowledge is domain-specific and not obvious
- The workflow involves 3+ non-trivial steps
- The fix required >2 iterations to get right

**Keep local when:**
- It's about your specific machine, file paths, or personal config
- It's a user preference (these go to your memory, not collective skills)
- It's trivial (standard library API, common knowledge)

---

## Common Pitfalls

1. **Forgetting the checkpoint update.** If you skip Step 8, the next run re-processes the same sessions. Always update `<your_name>_reflection_checkpoint` as the LAST action.

2. **Using the wrong agent name in the checkpoint key.** If you're alice, use `alice_reflection_checkpoint`. If you're bob, use `bob_reflection_checkpoint`. Using the wrong name means another agent's checkpoint leaks into yours.

3. **Using started_at instead of last_active.** `session_search` returns both. `started_at` never changes — a session resumed 3 days later would be skipped. Always filter by `last_active`.

4. **Sharing too much.** Not every local skill belongs in the collective. Before exporting, ask: "Would an agent on a completely different machine find this useful?"

5. **Not pulling before pushing.** Your colleagues may have pushed since your last sync. Always `git pull` first.

6. **Duplicating skills already in staging.** Check `ls skills/staging/` before copying — another agent may have submitted something similar. If so, merge your insights into theirs.

7. **Saving transient state to memory.** "We were working on the auth module" is session state. "Auth module uses JWT RS256, keys at /etc/auth/" is durable knowledge.

8. **Reflection paralysis.** If only 1-2 clear learnings, save those and move on. Not every session produces shareable skills.

---

## Verification Checklist

- [ ] Checkpoint found in memory under `<your_name>_reflection_checkpoint` (or confirmed as first run)
- [ ] `session_search()` filtered to only post-checkpoint sessions (by `last_active`)
- [ ] Local skills created/patched via `skill_manage`
- [ ] Memory entries saved for durable facts
- [ ] Inbox summary written to `agents/<name>/inbox/YYYY-MM-DD.md`
- [ ] Shareable skills copied to `skills/staging/candidate-*/`
- [ ] `git pull` done before committing
- [ ] Commit pushed successfully
- [ ] `<your_name>_reflection_checkpoint` updated in memory
