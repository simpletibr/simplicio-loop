/*
 * VS Code entry point. Wires the TreeView + commands and delegates filesystem
 * work to ./scan.ts (which has no `vscode` dependency and is unit-tested).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { listSprints, type Sprint, type TaskFile, statusLabel } from './scan';

class SprintsProvider implements vscode.TreeDataProvider<TreeNode> {
  private readonly emitter = new vscode.EventEmitter<TreeNode | void>();
  readonly onDidChangeTreeData = this.emitter.event;

  constructor(private readonly workspaceRoot: string) {}

  refresh(): void { this.emitter.fire(); }

  getTreeItem(element: TreeNode): vscode.TreeItem { return element; }

  getChildren(element?: TreeNode): TreeNode[] {
    const specsRoot = path.join(this.workspaceRoot, getSpecsRoot());
    if (!element) {
      return listSprints(specsRoot).map((s) => new SprintNode(s));
    }
    if (element instanceof SprintNode) {
      return element.sprint.tasks.map((t) => new TaskNode(t));
    }
    return [];
  }
}

class SprintNode extends vscode.TreeItem {
  constructor(public readonly sprint: Sprint) {
    super(sprint.id, vscode.TreeItemCollapsibleState.Expanded);
    this.description = sprint.status ? statusLabel(sprint.status) : `${sprint.tasks.length} task(s)`;
    this.iconPath = new vscode.ThemeIcon('milestone');
    this.contextValue = 'sprint';
    this.resourceUri = vscode.Uri.file(sprint.dir);
  }
}

class TaskNode extends vscode.TreeItem {
  constructor(public readonly task: TaskFile) {
    super(task.title, vscode.TreeItemCollapsibleState.None);
    this.description = `${statusLabel(task.status)} · ${task.basename}`;
    this.iconPath = iconForStatus(task.status);
    this.contextValue = 'task';
    this.resourceUri = vscode.Uri.file(task.file);
    this.command = {
      command: 'vscode.open',
      title: 'Open task',
      arguments: [this.resourceUri],
    };
  }
}

type TreeNode = SprintNode | TaskNode;

function iconForStatus(status: string): vscode.ThemeIcon {
  if (status === 'done')  return new vscode.ThemeIcon('pass');
  if (status === 'doing') return new vscode.ThemeIcon('sync');
  return new vscode.ThemeIcon('circle-large-outline');
}

function getSpecsRoot(): string {
  return vscode.workspace.getConfiguration('lpm').get<string>('specsRoot', '.specs');
}

function getWorkspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

export function activate(context: vscode.ExtensionContext): void {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) return;

  const provider = new SprintsProvider(workspaceRoot);
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('lpmSprints', provider),
    vscode.commands.registerCommand('lpm.refresh', () => provider.refresh()),
    vscode.commands.registerCommand('lpm.openCurrentTask', () => openCurrentTask(workspaceRoot)),
    vscode.commands.registerCommand('lpm.createAdr', () => createAdr(workspaceRoot)),
    vscode.commands.registerCommand('lpm.runInit', () => runInitHandoff(workspaceRoot)),
  );

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  refreshStatusBar(statusBar, workspaceRoot);
  statusBar.command = 'lpm.openCurrentTask';
  context.subscriptions.push(statusBar);

  const watcher = vscode.workspace.createFileSystemWatcher('**/.specs/sprints/**');
  watcher.onDidChange(() => { provider.refresh(); refreshStatusBar(statusBar, workspaceRoot); });
  watcher.onDidCreate(() => { provider.refresh(); refreshStatusBar(statusBar, workspaceRoot); });
  watcher.onDidDelete(() => { provider.refresh(); refreshStatusBar(statusBar, workspaceRoot); });
  context.subscriptions.push(watcher);
}

export function deactivate(): void { /* nothing to clean up */ }

function refreshStatusBar(statusBar: vscode.StatusBarItem, workspaceRoot: string): void {
  const sprints = listSprints(path.join(workspaceRoot, getSpecsRoot()));
  const active = sprints.find((s) => s.status === 'doing') ?? sprints[sprints.length - 1];
  if (!active) {
    statusBar.hide();
    return;
  }
  const doing = active.tasks.find((t) => t.status === 'doing');
  if (doing) {
    statusBar.text = `$(rocket) ${active.id} · ${doing.basename}`;
    statusBar.tooltip = `LLM Project Mapper · current task: ${doing.title}`;
  } else {
    statusBar.text = `$(rocket) ${active.id}`;
    statusBar.tooltip = `LLM Project Mapper · sprint ${active.id}`;
  }
  statusBar.show();
}

async function openCurrentTask(workspaceRoot: string): Promise<void> {
  const sprints = listSprints(path.join(workspaceRoot, getSpecsRoot()));
  if (!sprints.length) {
    vscode.window.showInformationMessage('No sprint folders found under .specs/sprints/.');
    return;
  }
  const active = sprints.find((s) => s.status === 'doing') ?? sprints[sprints.length - 1];
  const doing = active.tasks.find((t) => t.status === 'doing') ?? active.tasks[0];
  if (!doing) {
    vscode.window.showInformationMessage(`Sprint ${active.id} has no task files.`);
    return;
  }
  const doc = await vscode.workspace.openTextDocument(doing.file);
  await vscode.window.showTextDocument(doc);
}

async function createAdr(workspaceRoot: string): Promise<void> {
  const archDir = path.join(workspaceRoot, getSpecsRoot(), 'architecture');
  const templatePath = path.join(archDir, 'ADR-template.md');
  if (!fs.existsSync(templatePath)) {
    vscode.window.showErrorMessage('ADR-template.md not found under .specs/architecture/.');
    return;
  }
  const slug = await vscode.window.showInputBox({
    prompt: 'Short slug for the new ADR (kebab-case)',
    placeHolder: 'switch-cache-to-redis',
    validateInput: (v) => /^[a-z0-9][a-z0-9-]*$/.test(v) ? null : 'Use kebab-case: lowercase letters, digits, hyphens.',
  });
  if (!slug) return;
  const existing = fs.readdirSync(archDir)
    .filter((f) => /^ADR-(\d+)/.test(f))
    .map((f) => parseInt(f.match(/^ADR-(\d+)/)![1], 10))
    .sort((a, b) => a - b);
  const nextNum = (existing[existing.length - 1] ?? 0) + 1;
  const fileName = `ADR-${String(nextNum).padStart(3, '0')}-${slug}.md`;
  const destPath = path.join(archDir, fileName);
  fs.copyFileSync(templatePath, destPath);
  const doc = await vscode.workspace.openTextDocument(destPath);
  await vscode.window.showTextDocument(doc);
}

async function runInitHandoff(workspaceRoot: string): Promise<void> {
  const cli = vscode.workspace.getConfiguration('lpm').get<string>('defaultCli', 'claude');
  const initPath = path.join(workspaceRoot, 'INIT.md');
  if (!fs.existsSync(initPath)) {
    vscode.window.showErrorMessage('INIT.md not found at workspace root.');
    return;
  }
  const terminal = vscode.window.createTerminal({ name: 'LLM Project Mapper · INIT', cwd: workspaceRoot });
  const cmd = cli === 'skip'
    ? `echo 'Skipped — open INIT.md manually'`
    : `${cli} "$(cat INIT.md)"`;
  terminal.show();
  terminal.sendText(cmd);
}
