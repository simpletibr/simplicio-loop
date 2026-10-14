'''Unit tests for the GitHub links and the git worktree rows of the coordination view (TDD red).

Each backlog item carries an ``issue`` and a ``pr`` link (None or ``{'number', 'url'}``) read from its ``github`` dict
or from its top-level fields. The payload also carries ``worktrees``: the rows of ``git worktree list --porcelain``
for the repository passed as ``repo``, each with its state, its cleanup hint and the backlog item it belongs to.
The worktree tests run real git in temporary repositories, including a real merge conflict; nothing is faked except
the subprocess timeout and the missing git binary, which cannot be produced reliably any other way.
'''
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from simplicio_loop.dashboard import coordination

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC).timestamp()
GIT = ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false']
ROW_KEYS = {'path', 'branch', 'head', 'item_id', 'state', 'cleanup', 'main'}


def _git(cwd, *args):
    return subprocess.run([*GIT, '-C', str(cwd), *args], capture_output=True, text=True, check=True, timeout=60)


def _commit(cwd, message):
    _git(cwd, 'add', '-A')
    _git(cwd, 'commit', '-q', '-m', message)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    (root / 'shared.txt').write_text('base\n', encoding='utf-8')
    _commit(root, 'base')
    return root.resolve()


def _add_worktree(repo, name, branch):
    path = (repo.parent / name).resolve()
    _git(repo, 'worktree', 'add', '-q', '-b', branch, str(path))
    return path


def _item(iid, status='ready', **extra):
    obj = {'kind': 'item', 'id': iid, 'goal': f'Goal {iid}', 'status': status, 'depends_on': [], 'priority': 100}
    obj.update(extra)
    return obj


def _write(tmp_path, *objs):
    path = tmp_path / 'backlog.jsonl'
    path.write_text(''.join(json.dumps(obj) + '\n' for obj in objs), encoding='utf-8')
    return path


def _view(tmp_path, repo, *objs):
    return coordination.build_coordination(_write(tmp_path, *objs), now=NOW, repo=repo)


def _link_item(tmp_path, **fields):
    return _view(tmp_path, None, _item('X', **fields))['items'][0]


def _row(payload, branch):
    rows = [row for row in payload['worktrees']['rows'] if row['branch'] == branch]
    assert len(rows) == 1, payload['worktrees']
    return rows[0]


# --- GitHub issue and PR links -------------------------------------------------------------------------------------


def test_a_github_dict_gives_issue_and_pr_links_with_urls_built_from_its_repo(tmp_path):
    item = _link_item(tmp_path, github={'repo': 'acme/widgets', 'issue': 12, 'pr': 34})
    assert item['issue'] == {'number': 12, 'url': 'https://github.com/acme/widgets/issues/12'}
    assert item['pr'] == {'number': 34, 'url': 'https://github.com/acme/widgets/pull/34'}


def test_digit_strings_are_accepted_as_link_numbers(tmp_path):
    item = _link_item(tmp_path, github={'repo': 'acme/widgets', 'issue': '7', 'pr': ' 8 '})
    assert item['issue'] == {'number': 7, 'url': 'https://github.com/acme/widgets/issues/7'}
    assert item['pr'] == {'number': 8, 'url': 'https://github.com/acme/widgets/pull/8'}


def test_top_level_numbers_are_used_when_there_is_no_github_dict(tmp_path):
    item = _link_item(tmp_path, issue=5, pr=6)
    assert item['issue'] == {'number': 5, 'url': None}
    assert item['pr'] == {'number': 6, 'url': None}


def test_top_level_numbers_with_a_github_repo_string_have_no_repo_to_build_from(tmp_path):
    item = _link_item(tmp_path, issue=5, github='acme/widgets#5')
    assert item['issue'] == {'number': 5, 'url': None}


def test_an_explicit_github_url_is_used_as_given(tmp_path):
    item = _link_item(tmp_path, github={'repo': 'acme/widgets', 'issue': 12},
                      issue_url='https://github.com/acme/other/issues/12')
    assert item['issue'] == {'number': 12, 'url': 'https://github.com/acme/other/issues/12'}


def test_an_explicit_pr_url_wins_over_the_built_url(tmp_path):
    item = _link_item(tmp_path, github={'repo': 'acme/widgets', 'pr': 34},
                      pr_url='https://github.com/acme/widgets/pull/34')
    assert item['pr'] == {'number': 34, 'url': 'https://github.com/acme/widgets/pull/34'}


@pytest.mark.parametrize('url', [
    'http://github.com/acme/widgets/issues/9',
    'https://github.com.evil.example/acme/widgets/issues/9',
    'https://example.com/acme/widgets/issues/9',
    'javascript:alert(1)',
    42,
])
def test_an_explicit_url_that_is_not_https_github_is_rejected(tmp_path, url):
    item = _link_item(tmp_path, github={'repo': 'acme/widgets', 'issue': 9}, issue_url=url)
    assert item['issue'] == {'number': 9, 'url': 'https://github.com/acme/widgets/issues/9'}


def test_a_rejected_explicit_url_without_a_repo_leaves_the_url_null(tmp_path):
    item = _link_item(tmp_path, issue=9, issue_url='http://github.com/acme/widgets/issues/9')
    assert item['issue'] == {'number': 9, 'url': None}


@pytest.mark.parametrize('value', [0, -3, 'abc', '', '-4', '1.5', True, None, 2.0])
def test_non_positive_or_non_numeric_link_numbers_give_a_null_link(tmp_path, value):
    item = _link_item(tmp_path, github={'repo': 'acme/widgets', 'issue': value, 'pr': value})
    assert item['issue'] is None
    assert item['pr'] is None


@pytest.mark.parametrize('repo_value', ['acme', 'acme/widgets/extra', 'acme widgets',
                                        'https://github.com/acme/widgets', '', None])
def test_a_repo_that_is_not_owner_slash_name_gives_a_null_url(tmp_path, repo_value):
    item = _link_item(tmp_path, github={'repo': repo_value, 'issue': 3})
    assert item['issue'] == {'number': 3, 'url': None}


def test_items_without_link_fields_have_null_issue_and_pr(tmp_path):
    item = _link_item(tmp_path)
    assert item['issue'] is None
    assert item['pr'] is None


def test_every_item_view_carries_the_issue_and_pr_keys(tmp_path):
    payload = _view(tmp_path, None, _item('A'), _item('B', github={'repo': 'acme/widgets', 'pr': 2}))
    assert all({'issue', 'pr'} <= set(item) for item in payload['items'])


# --- worktrees: unverified paths -----------------------------------------------------------------------------------


def test_no_repository_gives_unverified_worktrees_with_no_rows(tmp_path):
    payload = _view(tmp_path, None, _item('A'))
    assert payload['status'] == 'MEASURED'
    assert set(payload['worktrees']) == {'status', 'reason', 'rows'}
    assert payload['worktrees']['status'] == 'UNVERIFIED'
    assert payload['worktrees']['reason']
    assert payload['worktrees']['rows'] == []


def test_a_directory_that_is_not_a_repository_is_unverified(tmp_path):
    payload = _view(tmp_path, tmp_path / 'absent', _item('A'))
    assert payload['worktrees']['status'] == 'UNVERIFIED'
    assert payload['worktrees']['reason']
    assert payload['worktrees']['rows'] == []


def test_a_missing_git_binary_is_unverified(tmp_path, repo, monkeypatch):
    monkeypatch.setenv('PATH', str(tmp_path / 'no-bin'))
    payload = _view(tmp_path, repo, _item('A'))
    assert payload['worktrees']['status'] == 'UNVERIFIED'
    assert 'git' in payload['worktrees']['reason']
    assert payload['worktrees']['rows'] == []


def test_a_git_timeout_is_unverified_and_git_runs_with_a_five_second_limit_and_no_shell(tmp_path, repo, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(args, kwargs.get('timeout'))

    monkeypatch.setattr(coordination.subprocess, 'run', fake_run)
    payload = _view(tmp_path, repo, _item('A'))
    assert payload['worktrees']['status'] == 'UNVERIFIED'
    assert payload['worktrees']['rows'] == []
    args, kwargs = calls[0]
    assert args[0] == 'git'
    assert args[-3:] == ['worktree', 'list', '--porcelain']
    assert kwargs['timeout'] == 5
    assert kwargs.get('shell', False) is False


def test_an_unreadable_backlog_also_reports_unverified_worktrees(tmp_path, repo):
    payload = coordination.build_coordination(tmp_path / 'absent.jsonl', now=NOW, repo=repo)
    assert payload['status'] == 'UNVERIFIED'
    assert payload['worktrees']['status'] == 'UNVERIFIED'
    assert payload['worktrees']['reason']
    assert payload['worktrees']['rows'] == []


# --- worktrees: real git states ------------------------------------------------------------------------------------


def test_a_repository_with_no_extra_worktrees_lists_only_the_main_worktree_as_clean(tmp_path, repo):
    payload = _view(tmp_path, repo, _item('A'))
    assert payload['worktrees']['status'] == 'MEASURED'
    assert payload['worktrees']['reason'] is None
    assert len(payload['worktrees']['rows']) == 1
    row = payload['worktrees']['rows'][0]
    assert set(row) == ROW_KEYS
    assert (row['path'], row['branch'], row['main'], row['state'], row['cleanup']) == (str(repo), 'main', True,
                                                                                       'clean', 'none')


def test_the_main_worktree_is_the_first_row_and_linked_worktrees_are_not_main(tmp_path, repo):
    _add_worktree(repo, 'wt-main-check', 'feat-main-check')
    rows = _view(tmp_path, repo)['worktrees']['rows']
    assert [row['main'] for row in rows] == [True, False]
    assert rows[0]['path'] == str(repo)


def test_a_clean_linked_worktree_is_clean_with_no_cleanup(tmp_path, repo):
    _add_worktree(repo, 'wt-clean', 'feat-clean')
    assert _row(_view(tmp_path, repo), 'feat-clean')['state'] == 'clean'
    assert _row(_view(tmp_path, repo), 'feat-clean')['cleanup'] == 'none'


def test_an_untracked_file_makes_a_worktree_dirty(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-untracked', 'feat-untracked')
    (wt / 'notes.txt').write_text('scratch\n', encoding='utf-8')
    row = _row(_view(tmp_path, repo), 'feat-untracked')
    assert (row['state'], row['cleanup']) == ('dirty', 'none')


def test_a_modified_tracked_file_makes_a_worktree_dirty(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-modified', 'feat-modified')
    (wt / 'shared.txt').write_text('changed\n', encoding='utf-8')
    assert _row(_view(tmp_path, repo), 'feat-modified')['state'] == 'dirty'


def test_a_real_merge_conflict_is_reported_as_conflict_ahead_of_dirty(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-conflict', 'feat-conflict')
    (wt / 'shared.txt').write_text('feature side\n', encoding='utf-8')
    _commit(wt, 'feature edit')
    (repo / 'shared.txt').write_text('main side\n', encoding='utf-8')
    _commit(repo, 'main edit')
    merge = subprocess.run([*GIT, '-C', str(wt), 'merge', '--no-edit', 'main'], capture_output=True, text=True,
                           timeout=60, check=False)
    assert merge.returncode != 0, 'the merge must stop on a real conflict'
    status = _git(wt, 'status', '--porcelain').stdout
    assert any(line[:2] == 'UU' for line in status.splitlines()), status
    row = _row(_view(tmp_path, repo), 'feat-conflict')
    assert (row['state'], row['cleanup']) == ('conflict', 'none')


def test_a_locked_worktree_is_locked_with_locked_cleanup(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-locked', 'feat-locked')
    _git(repo, 'worktree', 'lock', str(wt))
    row = _row(_view(tmp_path, repo), 'feat-locked')
    assert (row['state'], row['cleanup']) == ('locked', 'locked')


def test_a_worktree_whose_directory_is_gone_is_prunable_with_pending_cleanup(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-gone', 'feat-gone')
    shutil.rmtree(wt)
    row = _row(_view(tmp_path, repo), 'feat-gone')
    assert (row['state'], row['cleanup']) == ('prunable', 'pending')


def test_a_worktree_whose_status_cannot_run_is_unknown(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-broken', 'feat-broken')
    index = Path(_git(wt, 'rev-parse', '--git-path', 'index').stdout.strip())
    (index if index.is_absolute() else wt / index).write_bytes(b'not a git index')
    row = _row(_view(tmp_path, repo), 'feat-broken')
    assert (row['state'], row['cleanup']) == ('unknown', 'none')


def test_a_detached_worktree_has_no_branch_and_a_seven_character_head(tmp_path, repo):
    path = (repo.parent / 'wt-detached').resolve()
    _git(repo, 'worktree', 'add', '-q', '--detach', str(path))
    head = _git(repo, 'rev-parse', 'HEAD').stdout.strip()
    rows = _view(tmp_path, repo)['worktrees']['rows']
    row = next(row for row in rows if row['path'] == str(path))
    assert row['branch'] is None
    assert row['head'] == head[:7]
    assert row['state'] == 'clean'


def test_a_branch_keeps_its_slashes_after_refs_heads_is_stripped(tmp_path, repo):
    _add_worktree(repo, 'wt-nested', 'feat/nested/deep')
    row = _row(_view(tmp_path, repo), 'feat/nested/deep')
    assert row['head'] == _git(repo, 'rev-parse', 'HEAD').stdout.strip()[:7]
    assert row['main'] is False


# --- worktrees: backlog item matching ------------------------------------------------------------------------------


def test_an_item_naming_the_worktree_path_owns_that_row(tmp_path, repo):
    wt = _add_worktree(repo, 'wt-by-path', 'feat-by-path')
    payload = _view(tmp_path, repo, _item('T-9', worktree=str(wt)))
    assert _row(payload, 'feat-by-path')['item_id'] == 'T-9'


def test_an_item_naming_the_branch_owns_that_row(tmp_path, repo):
    _add_worktree(repo, 'wt-by-branch', 'feat-by-branch')
    payload = _view(tmp_path, repo, _item('T-8', branch='feat-by-branch'))
    assert _row(payload, 'feat-by-branch')['item_id'] == 'T-8'


def test_a_detached_worktree_is_matched_only_by_its_path(tmp_path, repo):
    path = (repo.parent / 'wt-detached-match').resolve()
    _git(repo, 'worktree', 'add', '-q', '--detach', str(path))
    payload = _view(tmp_path, repo, _item('X', worktree=str(path)))
    row = next(row for row in payload['worktrees']['rows'] if row['path'] == str(path))
    assert row['item_id'] == 'X'


def test_an_explicit_match_wins_over_a_name_match(tmp_path, repo):
    _add_worktree(repo, 'wt-explicit', 'feat-A')
    payload = _view(tmp_path, repo, _item('A'), _item('Z', branch='feat-A'))
    assert _row(payload, 'feat-A')['item_id'] == 'Z'


def test_a_branch_segment_matches_the_item_id_and_the_longest_id_wins(tmp_path, repo):
    _add_worktree(repo, 'wt-longest', 'feat/task-12-fix')
    payload = _view(tmp_path, repo, _item('task'), _item('task-12'))
    assert _row(payload, 'feat/task-12-fix')['item_id'] == 'task-12'


def test_a_branch_segment_matches_a_whole_segment_only(tmp_path, repo):
    _add_worktree(repo, 'wt-partial', 'alpha-feature')
    payload = _view(tmp_path, repo, _item('alp'))
    assert _row(payload, 'alpha-feature')['item_id'] is None


def test_a_branch_segment_matches_an_item_id_separated_by_slashes(tmp_path, repo):
    _add_worktree(repo, 'wt-slash', 'chore/B/cleanup')
    assert _row(_view(tmp_path, repo, _item('B')), 'chore/B/cleanup')['item_id'] == 'B'


def test_a_worktree_with_no_matching_item_has_a_null_item_id(tmp_path, repo):
    _add_worktree(repo, 'wt-orphan', 'feat-orphan')
    assert _row(_view(tmp_path, repo, _item('A')), 'feat-orphan')['item_id'] is None
