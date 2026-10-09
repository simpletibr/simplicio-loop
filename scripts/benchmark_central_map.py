#!/usr/bin/env python3
"""
Benchmark harness for central-map vs per-worktree full mapping.

Compares OLD (per-worktree full mapping) with NEW (central base + overlay).
Reports only MEASURED numbers: disk bytes and wall seconds.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
import argparse
import random
import stat
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional


def get_tool_info() -> Dict[str, Any]:
    """Get path and version of simplicio-mapper."""
    try:
        path = shutil.which("simplicio-mapper")
        if not path:
            return {"error": "simplicio-mapper not found on PATH"}
        
        version_out = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        version = version_out.stdout.strip() if version_out.returncode == 0 else version_out.stderr.strip()
        
        return {
            "path": path,
            "version": version
        }
    except Exception as e:
        return {"error": str(e)}


def get_dir_size(path: str) -> int:
    """Calculate total size of a directory (sum of file sizes via lstat, no symlink following)."""
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for fname in files:
                try:
                    fpath = os.path.join(root, fname)
                    stat_info = os.lstat(fpath)
                    total += stat_info.st_size
                except (OSError, FileNotFoundError):
                    pass
    except (OSError, FileNotFoundError):
        pass
    return total


def sh(*args, cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command."""
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check
    )


def generate_synthetic_repo(
    dst: str,
    nfiles: int,
    nwt: int,
    nfuncs: int,
    nedits: int
) -> Tuple[str, str]:
    """
    Generate synthetic repository with N files, K worktrees.
    Returns (main_clone_path, origin_path).
    """
    os.makedirs(dst, exist_ok=True)
    origin = os.path.join(dst, "origin.git")
    main = os.path.join(dst, "main")
    
    # Create bare origin
    sh("git", "init", "-q", "--bare", "-b", "main", origin)
    
    # Clone origin
    sh("git", "clone", "-q", origin, main)
    
    # Configure git user
    sh("git", "config", "user.email", "t@t", cwd=main)
    sh("git", "config", "user.name", "t", cwd=main)
    
    # Generate N python files
    rnd = random.Random(7)
    for i in range(nfiles):
        pkg_dir = os.path.join(main, f"pkg{i % 20}")
        os.makedirs(pkg_dir, exist_ok=True)
        
        funcs = []
        for j in range(nfuncs):
            r_val = rnd.randint(0, 99)
            funcs.append(f"def func_{i}_{j}(x):\n    return x + {r_val}\n")
        
        body = "\n".join(funcs)
        mod_file = os.path.join(pkg_dir, f"mod{i}.py")
        with open(mod_file, "w") as f:
            f.write("import os\n\n" + body)
    
    # Create README
    with open(os.path.join(main, "README.md"), "w") as f:
        f.write("# synthetic\n")
    
    # Commit and push
    sh("git", "add", "-A", cwd=main)
    sh("git", "commit", "-q", "-m", "init", cwd=main)
    sh("git", "push", "-q", "origin", "main", cwd=main)
    sh("git", "remote", "set-head", "origin", "main", cwd=main)
    
    # Create K linked worktrees
    for k in range(nwt):
        wt_path = os.path.join(dst, f"wt{k}")
        sh("git", "worktree", "add", "-q", "-b", f"wt{k}", wt_path, cwd=main)
    
    return main, origin


def apply_worktree_edits(wt_path: str, nedits: int) -> None:
    """Apply E uncommitted edits: rewrite E different existing files, add 1 untracked, delete 1 tracked."""
    # List all .py files
    py_files = []
    for root, dirs, files in os.walk(wt_path):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    
    # Edit E files
    rnd = random.Random(7)
    for i in range(min(nedits, len(py_files))):
        fpath = py_files[i]
        with open(fpath, "w") as f:
            f.write(f"# edited {i}\ndef new_func(x):\n    return x + {rnd.randint(0, 99)}\n")
    
    # Add 1 untracked file
    untracked_file = os.path.join(wt_path, "untracked.txt")
    with open(untracked_file, "w") as f:
        f.write("untracked content\n")
    
    # Delete 1 tracked file (if any exist)
    if py_files:
        sh("git", "rm", "-f", py_files[-1], cwd=wt_path, check=False)


def run_before_mode(
    repo_base: str,
    main_clone: str,
    nwt: int,
    timeout_sec: int = 1800
) -> Dict[str, Any]:
    """Run BEFORE mode: per-worktree full mapping."""
    result = {
        "status": "ok",
        "per_worktree": [],
        "total_bytes": 0,
        "git_simplicio_bytes": 0
    }
    
    try:
        for k in range(nwt):
            wt_path = os.path.join(repo_base, f"wt{k}")
            
            # Time the mapper call
            start = time.time()
            proc = subprocess.run(
                ["simplicio-mapper", "index", wt_path, "--json"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                timeout=timeout_sec
            )
            elapsed = time.time() - start
            
            if proc.returncode != 0:
                result["status"] = "failed"
                result["error"] = f"worktree {k}: {proc.stderr}"
                return result
            
            # Measure bytes under .simplicio-loop
            simplicio_dir = os.path.join(wt_path, ".simplicio-loop")
            wt_bytes = get_dir_size(simplicio_dir) if os.path.exists(simplicio_dir) else 0
            
            result["per_worktree"].append({
                "worktree": k,
                "seconds": round(elapsed, 3),
                "bytes": wt_bytes
            })
            result["total_bytes"] += wt_bytes
        
        # Measure .git/simplicio in main clone (should be ~0 for BEFORE)
        git_simplicio = os.path.join(main_clone, ".git", "simplicio")
        result["git_simplicio_bytes"] = get_dir_size(git_simplicio) if os.path.exists(git_simplicio) else 0
        
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
    
    return result


def run_after_mode(
    repo_base: str,
    main_clone: str,
    nwt: int,
    timeout_sec: int = 1800
) -> Dict[str, Any]:
    """Run AFTER mode: central base + overlay."""
    result = {
        "status": "ok",
        "base_build_seconds": 0.0,
        "per_worktree": [],
        "central_bytes": 0,
        "total_bytes": 0
    }
    
    try:
        for k in range(nwt):
            wt_path = os.path.join(repo_base, f"wt{k}")
            
            # Time the mapper call
            start = time.time()
            proc = subprocess.run(
                ["simplicio-mapper", "canonical", "overlay", wt_path, "--json"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                timeout=timeout_sec
            )
            elapsed = time.time() - start
            
            if proc.returncode != 0:
                result["status"] = "failed"
                result["error"] = f"worktree {k}: {proc.stderr}"
                return result
            
            # Parse JSON receipt
            try:
                receipt = json.loads(proc.stdout)
            except json.JSONDecodeError:
                result["status"] = "failed"
                result["error"] = f"worktree {k}: invalid JSON receipt"
                return result
            
            # Record base_build_seconds from first worktree
            if k == 0:
                result["base_build_seconds"] = round(elapsed, 3)  # worktree 0 pays the one-time base build
            
            # Measure bytes under .simplicio-loop
            simplicio_dir = os.path.join(wt_path, ".simplicio-loop")
            wt_bytes = get_dir_size(simplicio_dir) if os.path.exists(simplicio_dir) else 0
            
            wt_entry = {
                "worktree": k,
                "seconds": round(elapsed, 3),
                "bytes": wt_bytes,
                "receipt": receipt
            }
            
            # Add fallback reason if present
            if receipt.get("status") == "fallback":
                wt_entry["fallback_reason"] = receipt.get("fallback_reason", "unknown")
            
            result["per_worktree"].append(wt_entry)
            result["total_bytes"] += wt_bytes
        
        # Measure .git/simplicio in main clone (central base)
        git_simplicio = os.path.join(main_clone, ".git", "simplicio")
        result["central_bytes"] = get_dir_size(git_simplicio) if os.path.exists(git_simplicio) else 0
        result["total_bytes"] += result["central_bytes"]
        
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
    
    return result


def format_markdown_table(before: Dict[str, Any], after: Dict[str, Any], nwt: int) -> str:
    """Format results as markdown table."""
    lines = []
    lines.append("| Worktree | BEFORE (sec) | BEFORE (bytes) | AFTER (sec) | AFTER (bytes) |")
    lines.append("|----------|--------------|----------------|-------------|---------------|")
    
    for k in range(nwt):
        wt_before = before["per_worktree"][k] if k < len(before["per_worktree"]) else None
        wt_after = after["per_worktree"][k] if k < len(after["per_worktree"]) else None
        
        before_sec = wt_before["seconds"] if wt_before else "-"
        before_bytes = wt_before["bytes"] if wt_before else "-"
        after_sec = wt_after["seconds"] if wt_after else "-"
        after_bytes = wt_after["bytes"] if wt_after else "-"
        
        lines.append(f"| {k} | {before_sec} | {before_bytes} | {after_sec} | {after_bytes} |")
    
    # Totals row
    total_before_bytes = before.get("total_bytes", 0)
    total_after_bytes = after.get("total_bytes", 0)
    lines.append(f"| **TOTAL** | - | {total_before_bytes} | - | {total_after_bytes} |")
    
    # Compute 2nd..K-th worktree mean
    if nwt > 1:
        before_times = [w["seconds"] for w in before["per_worktree"][1:]]
        after_times = [w["seconds"] for w in after["per_worktree"][1:]]
        
        mean_before = sum(before_times) / len(before_times) if before_times else 0
        mean_after = sum(after_times) / len(after_times) if after_times else 0
        ratio = mean_after / mean_before if mean_before > 0 else 0
        
        lines.append("")
        lines.append(f"Mean seconds (worktrees 1..{nwt-1}): BEFORE={mean_before:.3f}, AFTER={mean_after:.3f}, ratio={ratio:.2f}x")
    
    # Central base info
    lines.append("")
    lines.append(f"Central base bytes (.git/simplicio): {after.get('central_bytes', 0)}")
    lines.append(f"Total disk BEFORE: {total_before_bytes} bytes")
    lines.append(f"Total disk AFTER: {total_after_bytes} bytes ({after.get('central_bytes', 0)} central + worktrees)")
    
    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark central-map vs per-worktree full mapping"
    )
    parser.add_argument("--files", type=int, default=3000, help="Number of files (default 3000)")
    parser.add_argument("--worktrees", type=int, default=5, help="Number of worktrees (default 5)")
    parser.add_argument("--funcs", type=int, default=25, help="Functions per file (default 25)")
    parser.add_argument("--edits", type=int, default=3, help="Modified files per worktree (default 3)")
    parser.add_argument("--dir", type=str, help="Work directory (default: /tmp/t28-bench-<pid>)")
    parser.add_argument("--mode", choices=["before", "after", "both"], default="both")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--keep", action="store_true", help="Keep work directory")
    
    args = parser.parse_args()
    
    # Validate args
    if args.files < 1 or args.worktrees < 1 or args.funcs < 1 or args.edits < 0:
        print("Error: invalid argument values", file=sys.stderr)
        return 2
    
    # Determine work directory
    if args.dir:
        if not args.dir.startswith("/tmp"):
            print("Error: --dir must be under /tmp", file=sys.stderr)
            return 2
        work_dir = args.dir
        should_remove = False
    else:
        work_dir = f"/tmp/t28-bench-{os.getpid()}"
        should_remove = True
    
    # Result structure
    final_result = {
        "schema": "simplicio.central-map-benchmark/v1",
        "params": {
            "files": args.files,
            "worktrees": args.worktrees,
            "funcs": args.funcs,
            "edits": args.edits
        },
        "tool": get_tool_info(),
        "before": None,
        "after": None,
        "comparison": {},
        "notes": []
    }
    
    # Add system notes
    try:
        load = os.getloadavg()
        final_result["notes"].append(f"load average: {load[0]:.1f}, {load[1]:.1f}, {load[2]:.1f}")
    except Exception:
        pass
    
    final_result["notes"].append(f"Python: {sys.version.split()[0]}")
    final_result["notes"].append(f"N={args.files}, K={args.worktrees}, F={args.funcs}")
    
    try:
        # Run BEFORE mode if needed
        if args.mode in ("before", "both"):
            repo_base_before = os.path.join(work_dir, "before")
            print(f"Generating synthetic repo ({args.files} files, {args.worktrees} worktrees)...", file=sys.stderr)
            main_before, _ = generate_synthetic_repo(
                repo_base_before,
                args.files,
                args.worktrees,
                args.funcs,
                args.edits
            )
            
            # Apply edits to all worktrees
            for k in range(args.worktrees):
                wt_path = os.path.join(repo_base_before, f"wt{k}")
                apply_worktree_edits(wt_path, args.edits)
            
            print(f"Running BEFORE mode...", file=sys.stderr)
            final_result["before"] = run_before_mode(repo_base_before, main_before, args.worktrees)
            if final_result["before"]["status"] != "ok":
                print(f"BEFORE mode failed: {final_result['before'].get('error', 'unknown')}", file=sys.stderr)
                if not args.keep and should_remove:
                    shutil.rmtree(work_dir, ignore_errors=True)
                if args.json:
                    print(json.dumps(final_result, indent=2))
                return 1
        
        # Run AFTER mode if needed (use a FRESH copy of the repo)
        if args.mode in ("after", "both"):
            repo_base_after = os.path.join(work_dir, "after")
            print(f"Generating synthetic repo ({args.files} files, {args.worktrees} worktrees)...", file=sys.stderr)
            main_after, _ = generate_synthetic_repo(
                repo_base_after,
                args.files,
                args.worktrees,
                args.funcs,
                args.edits
            )
            
            # Apply edits to all worktrees
            for k in range(args.worktrees):
                wt_path = os.path.join(repo_base_after, f"wt{k}")
                apply_worktree_edits(wt_path, args.edits)
            
            print(f"Running AFTER mode...", file=sys.stderr)
            final_result["after"] = run_after_mode(repo_base_after, main_after, args.worktrees)
            if final_result["after"]["status"] != "ok":
                print(f"AFTER mode failed: {final_result['after'].get('error', 'unknown')}", file=sys.stderr)
                if not args.keep and should_remove:
                    shutil.rmtree(work_dir, ignore_errors=True)
                if args.json:
                    print(json.dumps(final_result, indent=2))
                return 1
            
            # Check for fallback
            for wt_entry in final_result["after"]["per_worktree"]:
                if "fallback_reason" in wt_entry:
                    final_result["notes"].append(f"fallback in wt{wt_entry['worktree']}: {wt_entry['fallback_reason']}")
        
        # Compute comparison
        if final_result["before"] and final_result["after"]:
            rest_before = [w["seconds"] for w in final_result["before"]["per_worktree"][1:]]
            rest_after = [w["seconds"] for w in final_result["after"]["per_worktree"][1:]]
            mean_before = sum(rest_before) / len(rest_before) if rest_before else None
            mean_after = sum(rest_after) / len(rest_after) if rest_after else None
            final_result["comparison"] = {
                "total_bytes_before": final_result["before"].get("total_bytes", 0),
                "total_bytes_after": final_result["after"].get("total_bytes", 0),
                "central_bytes": final_result["after"].get("central_bytes", 0),
                "mean_seconds_worktrees_2_to_k_before": mean_before,
                "mean_seconds_worktrees_2_to_k_after": mean_after,
                "mean_seconds_ratio_after_over_before": (
                    mean_after / mean_before if mean_before and mean_after is not None else None
                ),
            }

        # Print markdown table if not JSON
        if args.mode == "both" and final_result["before"] and final_result["after"]:
            if not args.json:
                print("\n" + format_markdown_table(final_result["before"], final_result["after"], args.worktrees))
        
        # Print JSON
        if args.json:
            print(json.dumps(final_result, indent=2))
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        final_result["error"] = str(e)
        if args.json:
            print(json.dumps(final_result, indent=2))
        if not args.keep and should_remove:
            shutil.rmtree(work_dir, ignore_errors=True)
        return 1
    
    finally:
        # Clean up work directory if requested
        if not args.keep and should_remove and os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
            except Exception as e:
                print(f"Warning: failed to remove {work_dir}: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
