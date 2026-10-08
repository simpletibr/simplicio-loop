import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Add scripts to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from install_lib import (
    compute_skill_digest,
    get_installed_skill_hosts,
    resync_installed_skills,
    copy_skills,
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
    import install_lib
    with mock.patch.object(install_lib, 'HOME', str(fake_home)):
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
    import install_lib
    with mock.patch.object(install_lib, 'HOME', str(fake_home)):
        hosts = get_installed_skill_hosts()
        assert "cursor" in hosts


def test_resync_installed_skills_updates_stale_skill(fake_home, fake_repo):
    """Test that resync_installed_skills updates an old installed skill."""
    # Create an old skill in Claude
    old_skill = fake_home / ".claude" / "skills" / "simplicio-loop"
    old_skill.mkdir(parents=True)
    (old_skill / "SKILL.md").write_text("Old content")
    
    # Mock both SOURCE and HOME
    import install_lib
    with mock.patch.object(install_lib, 'SOURCE', str(fake_repo)), \
         mock.patch.object(install_lib, 'HOME', str(fake_home)):
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
    import install_lib
    with mock.patch.object(install_lib, 'HOME', str(fake_home)):
        # Call resync - it should handle missing source gracefully
        report = resync_installed_skills(verbose=False)
        
        # The function should not crash, but may report errors or skip
        assert isinstance(report, dict)
        assert "synced" in report
        assert "errors" in report
