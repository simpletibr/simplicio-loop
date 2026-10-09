"""Automatic squad sizing: how many squads and workers may run AT THE SAME TIME, from demand and a measured machine.

DEFAULT ON in both entry points (`simplicio-loop squads plan`, the 24/7 watcher): the loop works out the number of squads
that delivers fastest without overloading the host. Pure and deterministic: every input (issues, probe, limits) is a
parameter, so a test injects a fake probe and never reads the real load.

* DEMAND  (`measure_demand`): the widest dependency level of the issues, after removing the issues that share a file path
  (two writers on one file cannot run together). A 6-issue linear chain has width 1 on any host.
* SUPPLY  (`supply`): workers the machine can carry, the smallest of four limits, each at least 1:
    cpu    floor(80% of cores)
    load   floor(80% of cores - max(load 1 min, load 5 min))   (headroom: no new worker on a busy host)
    memory floor((available - 512 MiB floor) / 1.25 GiB per worker)   ESTIMATE per worker
    disk   floor((free - 2 GiB floor) / 1 GiB per worker)             ESTIMATE per worker
  then the daily budget of the watcher (can be 0). A value the probe cannot measure gives 1 worker and
  `proof_kind: UNVERIFIED` with the reason: unknown is never unlimited.
* OVERRIDE: `--squads N` / `SIMPLICIO_SQUADS=N` (N >= 1) or an explicit worker count wins over the four machine limits;
  demand and the daily budget still cap it. `SIMPLICIO_PRISM_SLOTS` / `SIMPLICIO_LOOP_OPERATOR_WORKERS` count as an
  override only when they differ from the economy profile's own value (the profile exports them to every session).
* RESULT  (`recommend`): `total_workers` = min(demand, supply); `workers_per_squad` = min(4, total); `squads` =
  ceil(total / workers_per_squad). `limited_by` names the binding limit; `reasons` tells the user why.

Monotonic: more load, less memory, less disk or fewer cores never add a worker. `resize` shrinks at once between waves
and grows only after two calm samples in a row (one full wave).

Sizing only decides how many run at once. It never decides what may merge (squad gate, AUTO_MERGE, merge train, locks).
"""
from __future__ import annotations

import dataclasses
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, Union

from . import local_capacity

SCHEMA = "simplicio.squad-capacity/v1"
GIB = 1 << 30
MAX_WORKERS_PER_SQUAD = 4  # squads.DEFAULT_MAX_WORKERS; a test pins the two together (squads imports this module)
CPU_SHARE = (4, 5)  # use at most 80% of the cores, the rest is headroom for the OS, the coordinator and bursts
WORKER_MEMORY_BYTES = int(1.25 * GIB)  # ESTIMATE: economy_profile sizes an isolated agent at ~1.25 GiB
WORKER_DISK_BYTES = GIB  # ESTIMATE: one git worktree plus build and test output
MEMORY_FLOOR_BYTES = local_capacity.DEFAULT_MEMORY_FLOOR_BYTES
DISK_FLOOR_BYTES = local_capacity.DEFAULT_DISK_FLOOR_BYTES
SHARE_MAX_AGE_NS = 30 * 10**9  # a tick's sample is reused by later steps of the same tick only while this fresh
RECHECK_FAST_S = 30  # cpu, load and memory move fast
RECHECK_SLOW_S = 120
SQUADS_ENV = "SIMPLICIO_SQUADS"
WORKER_ENVS = ("SIMPLICIO_PRISM_SLOTS", "SIMPLICIO_LOOP_OPERATOR_WORKERS")
MACHINE_LIMITS = ("disk", "memory", "cpu", "load")  # tie order: the scarcest resource is named first
ESTIMATES = {"label": "ESTIMATE", "worker_memory_bytes": WORKER_MEMORY_BYTES, "worker_disk_bytes": WORKER_DISK_BYTES,
             "memory_floor_bytes": MEMORY_FLOOR_BYTES, "disk_floor_bytes": DISK_FLOOR_BYTES,
             "cpu_share": "%d/%d" % CPU_SHARE}
_PROBE_FIELDS = ("cpu_count", "load_average", "memory_available_bytes", "disk_free_bytes")


# ---------------------------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Probe:
    """MEASURED machine values; None = not measured (with the reason in `null_reasons`).

    `sample` is the raw `local_capacity.CapacitySample` the values came from, so the intake `resource_governor` point can
    reuse it instead of probing twice in one tick.
    """

    cpu_count: Optional[int] = None
    load_average: Optional[Tuple[float, float, float]] = None  # 1, 5 and 15 minutes
    memory_available_bytes: Optional[int] = None
    disk_free_bytes: Optional[int] = None
    observed_at_ns: int = 0
    null_reasons: Mapping[str, str] = field(default_factory=dict)
    sample: Any = field(default=None, compare=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_count": self.cpu_count,
            "load_average": list(self.load_average) if self.load_average is not None else None,
            "memory_available_bytes": self.memory_available_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "observed_at_ns": self.observed_at_ns,
            "null_reasons": dict(self.null_reasons),
        }


def parse_squads(value: Any) -> Optional[int]:
    """`auto` (or None) -> None; a positive integer -> that integer; anything else (0, -1, 1.5, text) -> ValueError."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "auto":
        return None
    text = str(value).strip()
    if isinstance(value, bool) or not text.isdigit() or int(text) < 1:
        raise ValueError("squads must be 'auto' or an integer >= 1, got %r" % (value,))
    return int(text)


def _positive_int(raw: Any) -> Optional[int]:
    text = str(raw).strip()
    return int(text) if text.isdigit() and int(text) >= 1 else None


@dataclass(frozen=True)
class Limits:
    """What the caller pins down. All None = fully automatic."""

    squads: Optional[int] = None  # explicit number of squads (--squads N / SIMPLICIO_SQUADS)
    workers: Optional[int] = None  # explicit number of workers (an env the user set)
    budget_left: Optional[int] = None  # what the daily budget still allows (watcher); 0 = spent
    max_workers_per_squad: int = MAX_WORKERS_PER_SQUAD
    override_source: str = ""  # shown in the reasons, e.g. "--squads" or "SIMPLICIO_PRISM_SLOTS"

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None, *, economy: Optional[Mapping[str, str]] = None,
                 extra_worker_envs: Sequence[str] = (), budget_left: Optional[int] = None,
                 max_workers_per_squad: int = MAX_WORKERS_PER_SQUAD, squads_option: Optional[str] = None) -> "Limits":
        """Overrides from the environment. `SIMPLICIO_SQUADS=0` (or any bad value) raises ValueError.

        `squads_option` is the explicit `--squads` flag ("auto" or N): when given it replaces SIMPLICIO_SQUADS.

        `SIMPLICIO_PRISM_SLOTS` and `SIMPLICIO_LOOP_OPERATOR_WORKERS` are an override only when they differ from the value
        the economy profile writes (`economy` = that profile's env; computed when not given): the profile exports them
        to every session, so taking them as an override would switch the load check off for everybody.
        `extra_worker_envs` (the watcher's SIMPLICIO_247_CONCURRENCY) are always explicit.
        """
        env = os.environ if environ is None else environ
        squads, squads_source = None, SQUADS_ENV
        raw = str(env.get(SQUADS_ENV, "")).strip() if squads_option is None else squads_option
        if squads_option is not None:
            squads_source = "--squads"
        if str(raw).strip():
            try:
                squads = parse_squads(raw)
            except ValueError as exc:
                raise ValueError("%s: %s" % (squads_source, exc)) from None
        explicit: Dict[str, int] = {}
        for name in extra_worker_envs:
            value = _positive_int(env.get(name, ""))
            if value is not None:
                explicit[name] = value
        profile: Optional[Mapping[str, str]] = economy
        for name in WORKER_ENVS:
            value = _positive_int(env.get(name, ""))
            if value is None:
                continue
            if profile is None:
                profile = _economy_env(env)
            if str(profile.get(name, "")).strip() != str(value):
                explicit[name] = value
        source = ""
        workers = None
        if explicit:
            source = min(explicit, key=lambda name: (explicit[name], name))
            workers = explicit[source]
        if squads is not None:
            source = squads_source
        return cls(squads=squads, workers=workers, budget_left=budget_left, max_workers_per_squad=max_workers_per_squad,
                   override_source=source)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def _economy_env(env: Mapping[str, str]) -> Mapping[str, str]:
    from . import economy_profile

    try:
        return economy_profile.economy_parallel_env(env=env)
    except Exception:  # noqa: BLE001  no profile value known: any set value then counts as the user's
        return {}


# ---------------------------------------------------------------------------------------------- probe


def _loadavg() -> Tuple[float, float, float]:
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        import psutil  # Windows has no os.getloadavg; psutil emulates it

        return psutil.getloadavg()


def _valid_load(value: Any) -> Optional[Tuple[float, float, float]]:
    try:
        one, five, fifteen = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) and x >= 0 for x in (one, five, fifteen)):
        return None
    return (one, five, fifteen)


def measure(root: Union[str, os.PathLike] = ".", *, probe_fn: Optional[Callable[..., Any]] = None,
            loadavg_fn: Optional[Callable[[], Any]] = None) -> Probe:
    """One MEASURED probe: `local_capacity.probe_local_capacity` (cores, memory, disk of `root`) plus the load average.

    The sample is taken with the same arguments as the watcher's resource_governor point (one worker, no reserve), so
    that point can reuse it (`shared_sample`). Nothing is estimated: a value that cannot be read stays None.
    """
    sample = (probe_fn or local_capacity.probe_local_capacity)(root, requested_workers=1, reserve_workers=0)
    reasons = {k: v for k, v in dict(sample.null_reasons).items() if k in _PROBE_FIELDS}
    try:
        load = _valid_load((loadavg_fn or _loadavg)())
    except Exception:  # noqa: BLE001  OSError, ImportError, AttributeError: no load signal on this host
        load = None
    if load is None:
        reasons["load_average"] = "getloadavg_unavailable"
    return Probe(
        cpu_count=sample.cpu_count, load_average=load, memory_available_bytes=sample.memory_available_bytes,
        disk_free_bytes=sample.disk_free_bytes, observed_at_ns=sample.observed_at_ns, null_reasons=reasons, sample=sample)


def shared_sample(probe: Optional[Probe], *, now_ns: Optional[int] = None, max_age_ns: int = SHARE_MAX_AGE_NS) -> Any:
    """The raw capacity sample of a tick's probe while it is fresh, else None (the caller then probes itself)."""
    if probe is None or probe.sample is None:
        return None
    age = (time.time_ns() if now_ns is None else now_ns) - probe.observed_at_ns
    return probe.sample if 0 <= age <= max_age_ns else None


# ---------------------------------------------------------------------------------------------- demand


@dataclass(frozen=True)
class Demand:
    issues: int
    width: int  # the most issues that can run at the same time
    levels: Tuple[int, ...]  # parallel width of each dependency level, conflicts removed
    conflicts: int  # pairs of same-level issues that share a file path

    def to_dict(self) -> Dict[str, Any]:
        return {"issues": self.issues, "width": self.width, "levels": list(self.levels), "depth": len(self.levels),
                "conflicts": self.conflicts}


def _independent(members: Sequence[int], paths: Mapping[int, set]) -> Tuple[int, int]:
    """(size of a greedy independent set, conflicting pairs) among `members`; two issues conflict when they share a path.

    Minimum-degree-first, smallest number on ties: deterministic, and never above the exact maximum (so it never
    over-allocates).
    """
    by_path: Dict[str, list] = {}
    for n in members:
        for p in paths[n]:
            by_path.setdefault(p, []).append(n)
    adjacent: Dict[int, set] = {n: set() for n in members}
    for group in by_path.values():
        for n in group:
            adjacent[n].update(group)
    for n in members:
        adjacent[n].discard(n)
    pairs = sum(len(a) for a in adjacent.values()) // 2
    remaining, picked = set(members), 0
    while remaining:
        n = min(remaining, key=lambda m: (len(adjacent[m] & remaining), m))
        picked += 1
        remaining -= adjacent[n] | {n}
    return picked, pairs


def measure_demand(issues: Sequence[Mapping[str, Any]]) -> Demand:
    """Parallel width of `issues`: dependency levels (`depends_on` and "depends on #N" in the body), conflicts removed.

    Raises `squads.SquadCycleError` for a dependency cycle, like `plan_squads`.
    """
    from . import squads  # lazy: squads imports this module

    rows = list(issues)
    deps = squads.dependencies(rows)
    if not deps:
        return Demand(0, 0, (), 0)
    order = squads._merge_order({n: set(d) for n, d in deps.items()})  # topological, raises SquadCycleError
    paths = {squads._number(i.get("number")): {squads._clean_path(p) for p in (i.get("paths") or []) if str(p).strip()}
             for i in rows}
    level: Dict[int, int] = {}
    for n in order:
        level[n] = 1 + max((level[d] for d in deps[n]), default=-1)
    members: Dict[int, list] = {}
    for n in order:
        members.setdefault(level[n], []).append(n)
    widths, conflicts = [], 0
    for depth in sorted(members):
        picked, pairs = _independent(members[depth], paths)
        widths.append(picked)
        conflicts += pairs
    return Demand(len(deps), max(widths), tuple(widths), conflicts)


# ---------------------------------------------------------------------------------------------- supply


@dataclass(frozen=True)
class Supply:
    workers: int  # what the machine (or the override) allows, before demand
    limited_by: str  # disk | memory | cpu | load | budget | override
    caps: Mapping[str, int]  # the four machine limits
    reasons: Tuple[str, ...]
    unverified: Mapping[str, str]


def _gib(value: float) -> str:
    return "%.2f GiB" % (value / GIB)


def supply(probe: Probe, limits: Optional[Limits] = None) -> Supply:
    """Workers the machine can carry: the smallest of cpu, load, memory and disk (each >= 1), then override and budget."""
    limits = limits or Limits()
    caps: Dict[str, int] = {}
    reasons, unverified = [], {}

    def unknown(name: str, label: str) -> None:
        unverified[name] = str(probe.null_reasons.get(name) or "not_measured")
        reasons.append("%s: not measured (%s) -> UNVERIFIED, conservative minimum of 1 worker" % (label, unverified[name]))

    cores = probe.cpu_count if probe.cpu_count and probe.cpu_count > 0 else None
    if cores is None:
        caps["cpu"] = 1
        unknown("cpu_count", "cpu")
    else:
        caps["cpu"] = max(1, cores * CPU_SHARE[0] // CPU_SHARE[1])
        reasons.append("cpu: %d core(s) x %d/%d = %d worker(s)" % (cores, CPU_SHARE[0], CPU_SHARE[1], caps["cpu"]))

    if probe.load_average is None:
        caps["load"] = 1
        unknown("load_average", "load")
    elif cores is None:
        caps["load"] = 1
        reasons.append("load: cannot be compared without the core count -> 1 worker")
    else:
        one, five, fifteen = probe.load_average
        busy = max(one, five)
        usable = cores * CPU_SHARE[0] / CPU_SHARE[1]
        caps["load"] = max(1, math.floor(usable - busy))
        reasons.append("load: 1/5/15 min %.2f/%.2f/%.2f; busy %.2f of %.1f usable cores -> %d worker(s)"
                       % (one, five, fifteen, busy, usable, caps["load"]))

    if probe.memory_available_bytes is None:
        caps["memory"] = 1
        unknown("memory_available_bytes", "memory")
    else:
        caps["memory"] = max(1, (probe.memory_available_bytes - MEMORY_FLOOR_BYTES) // WORKER_MEMORY_BYTES)
        reasons.append("memory: %s available, floor %s, %s per worker (ESTIMATE) -> %d worker(s)" % (
            _gib(probe.memory_available_bytes), _gib(MEMORY_FLOOR_BYTES), _gib(WORKER_MEMORY_BYTES), caps["memory"]))

    if probe.disk_free_bytes is None:
        caps["disk"] = 1
        unknown("disk_free_bytes", "disk")
    else:
        raw = (probe.disk_free_bytes - DISK_FLOOR_BYTES) // WORKER_DISK_BYTES
        caps["disk"] = max(1, raw)
        note = "; at or below the floor, the minimum of 1 applies and the disk is nearly full" if raw < 1 else ""
        reasons.append("disk: %s free, floor %s, %s per worker (ESTIMATE) -> %d worker(s)%s" % (
            _gib(probe.disk_free_bytes), _gib(DISK_FLOOR_BYTES), _gib(WORKER_DISK_BYTES), caps["disk"], note))

    machine = min(caps.values())
    machine_by = next(name for name in MACHINE_LIMITS if caps[name] == machine)
    if limits.squads is not None:
        workers, by = limits.squads * limits.max_workers_per_squad, "override"
        reasons.append("override: %d squad(s) set by %s wins over the machine limits, which allow %d worker(s) (limited by %s)"
                       % (limits.squads, limits.override_source or "the caller", machine, machine_by))
    elif limits.workers is not None:
        workers, by = limits.workers, "override"
        reasons.append("override: %d worker(s) set by %s wins over the machine limits, which allow %d worker(s) (limited by %s)"
                       % (limits.workers, limits.override_source or "the caller", machine, machine_by))
    else:
        workers, by = machine, machine_by
    if limits.budget_left is not None:
        reasons.append("budget: the daily cap still allows %d" % max(0, limits.budget_left))
        if limits.budget_left < workers:
            workers, by = max(0, limits.budget_left), "budget"
    return Supply(workers, by, dict(caps), tuple(reasons), unverified)


# ---------------------------------------------------------------------------------------------- result


@dataclass(frozen=True)
class CapacityPlan:
    """How many squads, and how many workers per squad, may run at the same time. JSON-serializable."""

    squads: int
    workers_per_squad: int  # the largest squad
    total_workers: int
    limited_by: str  # demand | cpu | load | memory | disk | budget | override
    proof_kind: str  # MEASURED, or UNVERIFIED when a probe value was missing
    recheck_after_s: int
    reasons: Tuple[str, ...]
    demand: Demand
    supply: Mapping[str, Any]
    probe: Probe
    limits: Limits
    unverified: Mapping[str, str]
    estimates: Mapping[str, Any] = field(default_factory=lambda: dict(ESTIMATES))
    calm_waves: int = 0  # consecutive samples that allowed at least the current size (growth gate of `resize`)
    schema: str = SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema, "squads": self.squads, "workers_per_squad": self.workers_per_squad,
            "total_workers": self.total_workers, "limited_by": self.limited_by, "proof_kind": self.proof_kind,
            "recheck_after_s": self.recheck_after_s, "reasons": list(self.reasons), "demand": self.demand.to_dict(),
            "supply": dict(self.supply), "probe": self.probe.to_dict(), "limits": self.limits.to_dict(),
            "unverified": dict(self.unverified), "estimates": dict(self.estimates), "calm_waves": self.calm_waves,
        }


def recommend(issues: Union[Sequence[Mapping[str, Any]], Demand], probe: Probe, limits: Optional[Limits] = None) -> CapacityPlan:
    """Squads and workers to run at once: min(demand, supply), with the reasons. `issues` may be a precomputed `Demand`."""
    limits = limits or Limits()
    demand = issues if isinstance(issues, Demand) else measure_demand(issues)
    sup = supply(probe, limits)
    width = demand.width
    if width == 0:
        total, by = 0, "demand"
    elif width < sup.workers or (width == sup.workers and sup.limited_by in MACHINE_LIMITS):
        total, by = width, "demand"
    else:
        total, by = sup.workers, sup.limited_by
    if total == 0:
        squads_n = per_squad = 0
    elif limits.squads is not None:
        squads_n = min(limits.squads, total)
        per_squad = math.ceil(total / squads_n)
    else:
        per_squad = min(limits.max_workers_per_squad, total)
        squads_n = math.ceil(total / per_squad)
    headline = "%d worker(s) in %d squad(s), up to %d per squad, limited by %s" % (total, squads_n, per_squad, by)
    demand_line = "demand: %d issue(s) in %d dependency level(s); the widest runs %d at once" % (
        demand.issues, len(demand.levels), width)
    if demand.conflicts:
        demand_line += " after counting %d shared-file conflict(s)" % demand.conflicts
    reasons = (headline, demand_line) + sup.reasons
    fast = by in ("cpu", "load", "memory") or bool(sup.unverified)
    return CapacityPlan(
        squads=squads_n, workers_per_squad=per_squad, total_workers=total, limited_by=by,
        proof_kind="UNVERIFIED" if sup.unverified else "MEASURED",
        recheck_after_s=RECHECK_FAST_S if fast else RECHECK_SLOW_S, reasons=reasons, demand=demand,
        supply={**sup.caps, "workers": sup.workers, "limited_by": sup.limited_by}, probe=probe, limits=limits,
        unverified=dict(sup.unverified))


def resize(plan: CapacityPlan, probe: Probe) -> CapacityPlan:
    """Re-size a plan between waves with a new probe: shrink at once, grow only after a calm wave.

    Calm = the new sample allows at least the current size. A sample that allows more only grows the plan when the
    previous boundary was calm too (the load stayed low for a full wave); otherwise the plan holds its size.
    """
    fresh = recommend(plan.demand, probe, plan.limits)
    before, after = plan.total_workers, fresh.total_workers
    kept = tuple(r for r in plan.reasons if not r.startswith("resize:"))
    if after < before:
        note = "resize: shrink %d -> %d worker(s) now (%s)" % (before, after, fresh.limited_by)
        return dataclasses.replace(fresh, calm_waves=0, reasons=(note,) + fresh.reasons)
    if after == before:
        return dataclasses.replace(fresh, calm_waves=plan.calm_waves + 1)
    if plan.calm_waves >= 1:
        note = "resize: grow %d -> %d worker(s) after a calm wave" % (before, after)
        return dataclasses.replace(fresh, calm_waves=0, reasons=(note,) + fresh.reasons)
    note = "resize: the machine allows %d worker(s) (now %d); growth waits for a calm wave" % (after, before)
    return dataclasses.replace(plan, probe=probe, calm_waves=plan.calm_waves + 1, reasons=kept + (note,))
