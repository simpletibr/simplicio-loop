/*
 * Pure filesystem walkers for the `.specs/sprints/` and `.skills/` layout.
 * No `vscode` imports here on purpose — keeps the module unit-testable via
 * plain `node --test` without spinning a VS Code host.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

export type TaskStatus = 'todo' | 'doing' | 'done';

export interface Sprint {
  id: string;            // sprint-01
  dir: string;           // absolute path to sprint dir
  status?: TaskStatus;   // parsed from SPRINT.md frontmatter, optional
  tasks: TaskFile[];
}

export interface TaskFile {
  file: string;          // absolute path
  basename: string;      // 01-example.task.md
  title: string;         // first `# Heading` from the file
  status: TaskStatus;
}

const FRONTMATTER_STATUS_RE = /^status:\s*([a-z]+)/im;

export function readFirstHeading(text: string): string {
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    const m = line.match(/^#\s+(.+)\s*$/);
    if (m) return m[1].trim();
  }
  return '';
}

export function readStatus(text: string): TaskStatus {
  const m = text.match(FRONTMATTER_STATUS_RE);
  if (!m) return 'todo';
  const value = m[1].toLowerCase();
  if (value === 'doing' || value === 'in_progress' || value === 'wip') return 'doing';
  if (value === 'done' || value === 'completed') return 'done';
  return 'todo';
}

export function listSprints(specsRoot: string): Sprint[] {
  const sprintsDir = path.join(specsRoot, 'sprints');
  if (!fs.existsSync(sprintsDir)) return [];
  const entries = fs.readdirSync(sprintsDir, { withFileTypes: true });
  const out: Sprint[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    if (!/^sprint-\d+/i.test(entry.name)) continue;
    const sprintDir = path.join(sprintsDir, entry.name);
    const sprintFile = path.join(sprintDir, 'SPRINT.md');
    const sprintText = safeRead(sprintFile);
    const sprintStatus = sprintText ? readStatus(sprintText) : undefined;
    const taskFiles = fs.readdirSync(sprintDir)
      .filter((f) => f.endsWith('.task.md'))
      .sort()
      .map((basename) => {
        const file = path.join(sprintDir, basename);
        const text = safeRead(file);
        return {
          file,
          basename,
          title: readFirstHeading(text) || basename,
          status: readStatus(text),
        };
      });
    out.push({ id: entry.name, dir: sprintDir, status: sprintStatus, tasks: taskFiles });
  }
  out.sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  return out;
}

export function statusIcon(status: TaskStatus): string {
  switch (status) {
    case 'done':  return '$(pass)';
    case 'doing': return '$(sync)';
    default:      return '$(circle-large-outline)';
  }
}

export function statusLabel(status: TaskStatus): string {
  switch (status) {
    case 'done':  return 'done';
    case 'doing': return 'doing';
    default:      return 'todo';
  }
}

function safeRead(p: string): string {
  try { return fs.readFileSync(p, 'utf8'); } catch { return ''; }
}
