import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop.skill_sync import (
    compute_skill_digest,
    get_installed_skill_hosts,
    resync_installed_skills,
    SKILLS,
)


@pytest.fixture
def fake_home(tmp_path):
    """Create a fake HOME directory with some installed skills."""
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def fake_repo(tmp_path):
    """Create a fake repository structure with skills."""
    repo = tmp_path / "repo"
    repo.mkdir()
    skills_dir = repo / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    
    # Create a fake simplicio-loop skill
    skill_dir = skills_dir / "simplicio-loop"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Simplicio Loop\n\nFake skill content v1")
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "host-operator-flow.md").write_text("# Host Rules")
    
    return repo


def test_compute_skill_digest_deterministic(fake_repo):
    """Test that computing digest twice yields the same result."""
    digest1 = compute_skill_digest("simplicio-loop", skill_root=str(fake_repo))
    digest2 = compute_skill_digest("simplicio-loop", skill_root=str(fake_repo))
    assert digest1 == digest2
    assert len(digest1) == 64  # SHA256 is 64 hex chars


def test_compute_skill_digest_changes_with_content(tmp_path):
    """Test that digest changes when skill content changes."""
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    skills1 = repo1 / ".claude" / "skills" / "simplicio-loop"
    skills1.mkdir(parents=True)
    (skills1 / "SKILL.md").write_text("Content v1")
    
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    skills2 = repo2 / ".claude" / "skills" / "simplicio-loop"
    skills2.mkdir(parents=True)
    (skills2 / "SKILL.md").write_text("Content v2")
    
    digest1 = compute_skill_digest("simplicio-loop", skill_root=str(repo1))
    digest2 = compute_skill_digest("simplicio-loop", skill_root=str(repo2))
    
    assert digest1 != digest2


def test_get_installed_skill_hosts_detects_claude(fake_home):
    """Test that get_installed_skill_hosts detects Claude installation."""
    # Create a fake Claude installation
    claude_skills = fake_home / ".claude" / "skills" / "simplicio-loop"
    claude_skills.mkdir(parents=True)
    (claude_skills / "SKILL.md").write_text("Skill content")
    
    # Mock the HOME variable in the module
    import simplicio_loop.skill_sync
    with mock.patch.object(simplicio_loop.skill_sync, 'HOME', str(fake_home)):
        hosts = get_installed_skill_hosts()
        assert "claude" in hosts
        assert hosts["claude"] == str(fake_home)


def test_get_installed_skill_hosts_detects_cursor(fake_home):
    """Test that get_installed_skill_hosts detects Cursor installation."""
    # Create a fake Cursor installation
    cursor_skills = fake_home / ".cursor" / "skills" / "simplicio-loop"
    cursor_skills.mkdir(parents=True)
    (cursor_skills / "SKILL.md").write_text("Skill content")
    
    # Mock the HOME variable in the module
    import simplicio_loop.skill_sync
    with mock.patch.object(simplicio_loop.skill_sync, 'HOME', str(fake_home)):
        hosts = get_installed_skill_hosts()
        assert "cursor" in hosts


def test_resync_installed_skills_updates_stale_skill(fake_home, fake_repo):
    """Test that resync_installed_skills updates an old installed skill."""
    # Create an old skill in Claude
    old_skill = fake_home / ".claude" / "skills" / "simplicio-loop"
    old_skill.mkdir(parents=True)
    (old_skill / "SKILL.md").write_text("Old content")
    
    # Mock both simplicio_loop module and HOME
    import simplicio_loop
    import simplicio_loop.skill_sync
    with mock.patch.object(simplicio_loop, '__file__', str(fake_repo / "simplicio_loop" / "__init__.py")), \
         mock.patch.object(simplicio_loop.skill_sync, 'HOME', str(fake_home)):
        # Call resync
        report = resync_installed_skills(verbose=False)
        
        # Verify the skill was synced
        assert "claude" in report["synced"]
        assert len(report["errors"]) == 0
        
        # Verify the skill was updated
        new_content = (old_skill / "SKILL.md").read_text()
        assert "Fake skill content v1" in new_content


def test_resync_reports_errors_gracefully(fake_home):
    """Test that resync handles errors gracefully."""
    # Create an installed skill (but not all the required infrastructure)
    skill = fake_home / ".claude" / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Skill")
    
    # Mock HOME to point to fake_home with no valid source
    import simplicio_loop.skill_sync
    with mock.patch.object(simplicio_loop.skill_sync, 'HOME', str(fake_home)):
        # Call resync - it should handle missing source gracefully
        report = resync_installed_skills(verbose=False)
        
        # The function should not crash, but may report errors or skip
        assert isinstance(report, dict)
        assert "synced" in report
        assert "errors" in report


def test_skill_sync_importable_from_installed_context():
    """Test that skill_sync module is importable from simplicio_loop package (pip-installed scenario).
    
    This test verifies that when operator_check.py (running from pip-installed code) tries to
    import simplicio_loop.skill_sync, it succeeds. This is the scenario when the package has been
    installed via pip and operator_check needs to call resync_installed_skills after an upgrade.
    """
    # Verify the module exists and has the expected functions
    try:
        from simplicio_loop.skill_sync import resync_installed_skills, compute_skill_digest, get_installed_skill_hosts
        assert callable(resync_installed_skills)
        assert callable(compute_skill_digest)
        assert callable(get_installed_skill_hosts)
    except ImportError as e:
        pytest.fail(f"Failed to import simplicio_loop.skill_sync: {e}")


def test_operator_check_can_call_resync():
    """Test that operator_check.py can successfully import and call resync_installed_skills.
    
    This simulates how operator_check.py (either from scripts/ or _bundle/) would call
    the resync function after a pip upgrade.
    """
    # Simulate the import that operator_check.py does after successful upgrade
    import simplicio_loop.skill_sync
    
    # Verify we can get the function
    fn = None
    try:
        from simplicio_loop.skill_sync import resync_installed_skills
        fn = resync_installed_skills
    except (ImportError, ModuleNotFoundError) as e:
        pytest.fail(f"operator_check import failed: {e}")
    
    # Verify the function is callable
    assert callable(fn)
    assert fn.__name__ == "resync_installed_skills"

def test_compute_skill_path_digest_for_arbitrary_paths():
    """Test that compute_skill_path_digest works on arbitrary skill paths.
    
    This is used by doctor.py to verify installed skills in different host locations.
    """
    from simplicio_loop.skill_sync import compute_skill_path_digest
    
    # Create a test skill at an arbitrary path
    tmp_path = Path(tempfile.mkdtemp())
    skill_path = tmp_path / "test-skill"
    skill_path.mkdir()
    (skill_path / "SKILL.md").write_text("Test skill content")
    (skill_path / "references").mkdir()
    (skill_path / "references" / "guide.md").write_text("Guide content")
    
    # Compute digest
    digest = compute_skill_path_digest(str(skill_path))
    
    # Verify it's a valid SHA256 digest
    assert digest
    assert len(digest) == 64  # SHA256 hex is 64 chars
    
    # Verify it changes when content changes
    (skill_path / "SKILL.md").write_text("Modified content")
    new_digest = compute_skill_path_digest(str(skill_path))
    assert new_digest != digest


def test_doctor_digest_computation_for_multiple_hosts(fake_home):
    """Test that digests are computed correctly for different host installation paths.
    
    Verifies that doctor.py can correctly detect stale skills for different hosts like
    claude, cursor, vscode, etc., where skills are installed in different directory structures.
    """
    from simplicio_loop.skill_sync import compute_skill_path_digest, get_installed_skill_hosts
    
    # Create skills at different host locations
    # Claude: ~/.claude/skills/simplicio-loop
    claude_skill = fake_home / ".claude" / "skills" / "simplicio-loop"
    claude_skill.mkdir(parents=True)
    (claude_skill / "SKILL.md").write_text("Claude version 1")
    
    # Cursor: ~/.cursor/skills/simplicio-loop
    cursor_skill = fake_home / ".cursor" / "skills" / "simplicio-loop"
    cursor_skill.mkdir(parents=True)
    (cursor_skill / "SKILL.md").write_text("Cursor version 1")
    
    # VS Code: ~/.vscode/simplicio-skills/simplicio-loop
    vscode_skill = fake_home / ".vscode" / "simplicio-skills" / "simplicio-loop"
    vscode_skill.mkdir(parents=True)
    (vscode_skill / "SKILL.md").write_text("VSCode version 1")
    
    # Mock HOME
    import simplicio_loop.skill_sync
    with mock.patch.object(simplicio_loop.skill_sync, 'HOME', str(fake_home)):
        # Verify all hosts are detected
        hosts = get_installed_skill_hosts()
        assert "claude" in hosts
        assert "cursor" in hosts
        assert "vscode" in hosts
        
        # Compute digests for each host
        digests = {}
        for host in ["claude", "cursor", "vscode"]:
            if host == "vscode":
                skill_dir = vscode_skill
            elif host == "cursor":
                skill_dir = cursor_skill
            else:
                skill_dir = claude_skill
            
            digest = compute_skill_path_digest(str(skill_dir))
            digests[host] = digest
            assert digest, f"Failed to compute digest for {host}"
            assert len(digest) == 64
        
        # Verify different hosts have different digests (different content)
        assert digests["claude"] != digests["cursor"]
        assert digests["claude"] != digests["vscode"]
        assert digests["cursor"] != digests["vscode"]

