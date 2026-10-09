"""Unit tests for benchmark_central_map.py pure helpers."""
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add scripts to path so we can import the benchmark module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Import the module (we'll test the pure functions)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "benchmark_central_map",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "benchmark_central_map.py")
)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_get_dir_size_empty():
    """Test get_dir_size on an empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        size = bench.get_dir_size(tmpdir)
        assert size == 0, f"Expected 0, got {size}"


def test_get_dir_size_with_files():
    """Test get_dir_size with actual files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a few test files
        test_file1 = os.path.join(tmpdir, "test1.txt")
        test_file2 = os.path.join(tmpdir, "test2.txt")
        
        content1 = "hello"
        content2 = "world123"
        
        with open(test_file1, "w") as f:
            f.write(content1)
        with open(test_file2, "w") as f:
            f.write(content2)
        
        size = bench.get_dir_size(tmpdir)
        expected = len(content1) + len(content2)
        assert size == expected, f"Expected {expected}, got {size}"


def test_get_dir_size_nonexistent():
    """Test get_dir_size on nonexistent directory."""
    size = bench.get_dir_size("/nonexistent/path/xyz")
    assert size == 0, f"Expected 0 for nonexistent path, got {size}"


def test_get_dir_size_nested():
    """Test get_dir_size with nested directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create nested structure
        subdir = os.path.join(tmpdir, "subdir")
        os.makedirs(subdir)
        
        test_file1 = os.path.join(tmpdir, "test1.txt")
        test_file2 = os.path.join(subdir, "test2.txt")
        
        content1 = "abc"
        content2 = "defghij"
        
        with open(test_file1, "w") as f:
            f.write(content1)
        with open(test_file2, "w") as f:
            f.write(content2)
        
        size = bench.get_dir_size(tmpdir)
        expected = len(content1) + len(content2)
        assert size == expected, f"Expected {expected}, got {size}"


def test_format_markdown_table_simple():
    """Test format_markdown_table with simple data."""
    before = {
        "per_worktree": [
            {"worktree": 0, "seconds": 1.5, "bytes": 100},
            {"worktree": 1, "seconds": 2.0, "bytes": 200}
        ],
        "total_bytes": 300,
        "git_simplicio_bytes": 0
    }
    
    after = {
        "per_worktree": [
            {"worktree": 0, "seconds": 1.2, "bytes": 80},
            {"worktree": 1, "seconds": 1.8, "bytes": 150}
        ],
        "central_bytes": 50,
        "total_bytes": 280
    }
    
    table = bench.format_markdown_table(before, after, 2)
    
    # Check that table contains expected markers
    assert "| Worktree |" in table, "Table header missing"
    assert "| 0 |" in table, "Worktree 0 row missing"
    assert "| 1 |" in table, "Worktree 1 row missing"
    assert "| **TOTAL** |" in table, "Totals row missing"
    assert "BEFORE=" in table, "Mean comparison missing"
    assert "central-map" not in table or "Central base" in table, "Central base info missing"


if __name__ == "__main__":
    # Run tests
    test_get_dir_size_empty()
    print("✓ test_get_dir_size_empty")
    
    test_get_dir_size_with_files()
    print("✓ test_get_dir_size_with_files")
    
    test_get_dir_size_nonexistent()
    print("✓ test_get_dir_size_nonexistent")
    
    test_get_dir_size_nested()
    print("✓ test_get_dir_size_nested")
    
    test_format_markdown_table_simple()
    print("✓ test_format_markdown_table_simple")
    
    print("\nAll tests passed!")
