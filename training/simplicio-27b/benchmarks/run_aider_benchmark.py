# Official 2026 Aider Code Editing Benchmark Runner for Simplicio 27B
import os
import re
import ast
import sys
import json
import tempfile
import subprocess
from typing import List, Dict, Tuple

def load_instances() -> List[Dict]:
    data_path = os.path.join(os.path.dirname(__file__), "aider_instances.json")
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_surgical_diff(patch_content: str) -> List[Tuple[str, str]]:
    pattern = r"<<<< SEARCH\s*\n(.*?)\n====\s*\n(.*?)\n>>>> REPLACE"
    return re.findall(pattern, patch_content, re.DOTALL)

def evaluate_patch(initial: str, search_c: str, replace_c: str, test_code: str, fname: str) -> Dict:
    res = {"search_matched": False, "ast_valid": False, "test_passed": False}
    c_init = initial.replace("\r\n", "\n").strip()
    c_search = search_c.replace("\r\n", "\n").strip()
    if c_search in c_init:
        res["search_matched"] = True
        patched = c_init.replace(c_search, replace_c.strip())
        try:
            ast.parse(patched)
            res["ast_valid"] = True
        except SyntaxError:
            return res
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, fname), "w", encoding="utf-8") as sf:
                sf.write(patched)
            t_path = os.path.join(tmpdir, "test_" + fname)
            with open(t_path, "w", encoding="utf-8") as tf:
                tf.write(test_code)
            p = subprocess.run([sys.executable, "-m", "pytest", t_path, "-q"], cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                res["test_passed"] = True
    return res

def main():
    cases = load_instances()
    print("=" * 80)
    print("🚀 OFFICIAL 2026 AIDER CODE EDITING BENCHMARK (SIMPLICIO 27B HARNESS)")
    print("Evaluating Exercism testbed with atomic diff editing and pytest execution.")
    print("=" * 80)
    print(f"Loaded {len(cases)} official benchmark instances:")
    for c in cases:
        print(f"  - [{c['instance_id']}] Target: {c['file']}")
    print("\nReady for model inference and evaluation.")

if __name__ == "__main__":
    main()
