"""Skill sync functions for resynchronizing installed skills after package upgrade.

These functions are used by operator_check.py when a package upgrade is detected,
to ensure that skills installed in ~/.claude/skills and other host surfaces are
updated to match the newly installed package version.

This module ships with the wheel and is importable from pip-installed contexts.
"""
import hashlib
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

# Explicit override keeps portable profiles and isolated installer tests honest;
# normal installs still use the platform's real user home.
HOME = (os.environ.get("SIMPLICIO_HOME") or os.environ.get("HOME")
        or os.path.expanduser("~"))

SKILLS = ["simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch"]


def compute_skill_digest(skill_name: str, skill_root: str = None) -> str:
    """Compute SHA256 digest of a skill directory to detect changes.
    
    Args:
        skill_name: Name of the skill (e.g., 'simplicio-loop')
        skill_root: Root directory containing .claude/skills (defaults to package root)
        
    Returns:
        Hex string of SHA256 digest, or empty string if skill not found
    """
    if skill_root is None:
        # When called from operator_check after a pip install, use the installed package location
        import simplicio_loop
        skill_root = os.path.dirname(os.path.dirname(simplicio_loop.__file__))
    
    skill_path = os.path.join(skill_root, ".claude", "skills", skill_name)
    
    if not os.path.isdir(skill_path):
        return ""
    
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(skill_path):
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "rb") as f:
                    h.update(f.read())
            except OSError:
                pass
    return h.hexdigest()


def get_installed_skill_hosts() -> dict:
    """Detect which hosts already have skills installed.
    
    Returns:
        Dictionary mapping host name to installation root directory
    """
    home = Path(HOME)
    hosts = {}
    
    if (home / ".claude" / "skills" / "simplicio-loop").is_dir():
        hosts["claude"] = str(home)
    if (home / ".cursor" / "skills" / "simplicio-loop").is_dir():
        hosts["cursor"] = str(home)
    if (home / ".codex" / "skills" / "simplicio-loop").is_dir():
        hosts["codex"] = str(home)
    if (home / ".grok" / "skills" / "simplicio-loop").is_dir():
        hosts["grok"] = str(home)
    if (home / ".vscode" / "simplicio-skills" / "simplicio-loop").is_dir():
        hosts["vscode"] = str(home / ".vscode" / "simplicio-skills")
    if (home / ".agents" / "skills" / "simplicio-loop").is_dir():
        hosts["agents"] = str(home)
    if (home / ".copilot" / "skills" / "simplicio-loop").is_dir():
        hosts["copilot"] = str(home)
    if (home / ".antigravity" / "skills" / "simplicio-loop").is_dir():
        hosts["antigravity"] = str(home)
    if (home / ".kiro" / "steering" / "simplicio-loop").is_dir():
        hosts["kiro"] = str(home)
    if (home / ".hermes" / "skills" / "simplicio-loop").is_dir():
        hosts["hermes"] = str(home)
    if (home / ".simplicio-loop" / "skills" / "simplicio-loop").is_dir():
        hosts["simplicio_agent"] = str(home)
    if (home / ".config" / "opencode" / "skills" / "simplicio-loop").is_dir():
        hosts["opencode"] = str(home)
    if (home / ".config" / "amp" / "skills" / "simplicio-loop").is_dir():
        hosts["amp"] = str(home)
    
    return hosts


def _copy_skills(target: str, skills_dst: str = None) -> None:
    """Copy skills from package source to target.
    
    Args:
        target: Base target directory  
        skills_dst: Specific skills destination directory (defaults to target/.claude/skills)
    """
    import simplicio_loop
    source_root = os.path.dirname(os.path.dirname(simplicio_loop.__file__))
    
    dst_root = skills_dst if skills_dst else os.path.join(target, ".claude", "skills")
    os.makedirs(dst_root, exist_ok=True)
    for s in SKILLS:
        src = os.path.join(source_root, ".claude", "skills", s)
        if not os.path.isdir(src):
            continue
        shutil.copytree(src, os.path.join(dst_root, s), dirs_exist_ok=True)


def compute_skill_path_digest(skill_path: str) -> str:
    """Compute SHA256 digest of a skill at an arbitrary path.
    
    Args:
        skill_path: Full path to the skill directory
        
    Returns:
        Hex string of SHA256 digest, or empty string if skill not found
    """
    if not os.path.isdir(skill_path):
        return ""
    
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(skill_path):
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "rb") as f:
                    h.update(f.read())
            except OSError:
                pass
    return h.hexdigest()


def resync_installed_skills(verbose: bool = False) -> dict:
    """Resync installed skills from the package source after an upgrade.
    
    Args:
        verbose: Whether to print status messages
        
    Returns:
        Dictionary with 'synced' list of hosts and 'errors' list of errors
    """
    hosts = get_installed_skill_hosts()
    report = {"synced": [], "errors": []}
    
    for host, target_base in hosts.items():
        try:
            if host == "vscode":
                skills_dst = target_base
            elif host == "grok":
                skills_dst = os.path.join(target_base, ".grok", "skills")
            elif host == "agents":
                skills_dst = os.path.join(target_base, ".agents", "skills")
            elif host == "kiro":
                skills_dst = os.path.join(target_base, ".kiro", "steering")
            elif host in ("simplicio_agent", "hermes"):
                skills_dst = os.path.join(target_base, ".simplicio-loop", "skills")
            elif host == "opencode":
                skills_dst = os.path.join(target_base, ".config", "opencode", "skills")
            elif host == "amp":
                skills_dst = os.path.join(target_base, ".config", "amp", "skills")
            else:
                skills_dst = os.path.join(target_base, "." + host, "skills")
            
            _copy_skills(target_base, skills_dst=skills_dst)
            report["synced"].append(host)
            if verbose:
                print("  resynced skills for %s -> %s" % (host, skills_dst))
        except Exception as exc:
            report["errors"].append({"host": host, "error": str(exc)})
            if verbose:
                print("  ! error resyncing %s: %s" % (host, exc))
    
    return report
