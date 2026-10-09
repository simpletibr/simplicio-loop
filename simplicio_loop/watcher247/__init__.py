"""24/7 watcher for simplicio-* repos.

Asyncio-native port of simplicio-loop-247.py. Runs only while the Simplicio MCP
subscription is active; baselines open issues on the first tick, then runs
headless turbo (OpenRouter) on each new issue (SIMPLICIO_247_CONCURRENCY at a
time, one per repo) and opens a PR. It does not merge. Stop with the STOP file.
"""
from __future__ import annotations
