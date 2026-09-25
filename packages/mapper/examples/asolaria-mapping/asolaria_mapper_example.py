#!/usr/bin/env python3
"""
Example: Asolaria Geometric & Hyper-Dimensional Mapping

Demonstrates the core concepts from Algorithms of Asolaria + HYPER-BECHS
applied to simplicio-mapper's repo mapping functionality.

Key concepts:
1. Tagging Discipline (MEASURED/CANON/OPERATOR/UNVERIFIED)
2. Addressing Geometry (REALMATHPOS, FNV-1a64, sha16)
3. BEHCS Encoding Tiers (256/1024/HyperBEHCS)
4. Brown-Hilbert Addressing
"""

import hashlib
import json
import struct
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


# =============================================================================
# 1. Tagging Discipline
# =============================================================================

class ProofLevel(Enum):
    """Asolaria tagging discipline — every mapped item gets exactly one."""
    MEASURED = "MEASURED"       # Executed/verified against real system
    CANON = "CANON"             # Doctrine/README states (source referenced)
    OPERATOR = "OPERATOR"       # Operator provided exact number (provenance tracked)
    UNVERIFIED = "UNVERIFIED"   # Detected but not confirmed


class MappedItem:
    """A single mapped entity with Asolaria tagging."""
    
    def __init__(
        self,
        name: str,
        kind: str,  # "module", "function", "class", "file"
        proof: ProofLevel,
        source: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        self.name = name
        self.kind = kind
        self.proof = proof
        self.source = source
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "proof": self.proof.value,
            "source": self.source,
            **self.metadata,
        }


# =============================================================================
# 2. Addressing Geometry (Classes A-B from Asolaria)
# =============================================================================

class REALMATHPOS:
    """Real Mathematical Position: file:line:col addressing.
    
    Classe A from Algorithms of Asolaria.
    Replaces flat paths with geometric coordinates.
    """
    
    def __init__(self, file_path: str, line: int, col: int):
        self.file_path = file_path
        self.line = line
        self.col = col
    
    @classmethod
    def from_path(cls, path: str) -> "REALMATHPOS":
        """Create position from a bare path (line=0, col=0 = file root)."""
        return cls(path, 0, 0)
    
    def advance(self, delta_line: int = 0, delta_col: int = 0) -> "REALMATHPOS":
        """Return a new position offset from this one."""
        return REALMATHPOS(self.file_path, self.line + delta_line, self.col + delta_col)
    
    def __str__(self) -> str:
        return f"{self.file_path}:{self.line}:{self.col}"
    
    def __repr__(self) -> str:
        return f"REALMATHPOS({self.file_path}:{self.line}:{self.col})"


class FNV1a64:
    """FNV-1a 64-bit hash — fast non-crypto hash for module lookup.
    
    Classe A from Algorithms of Asolaria.
    Used for O(1) directory walk replacement.
    """
    
    _OFFSET_BASIS = 0xCBF29CE484222325
    _FNV_PRIME = 0x100000001B3
    
    @classmethod
    def hash(cls, data: Union[str, bytes]) -> int:
        if isinstance(data, str):
            data = data.encode("utf-8")
        h = cls._OFFSET_BASIS
        for byte in data:
            h ^= byte
            h = (h * cls._FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
        return h
    
    @classmethod
    def hash_path(cls, path: Path) -> str:
        """Hash a file path for O(1) lookup key."""
        return f"fnv:{cls.hash(str(path)):016x}"


def sha16(data: Union[str, bytes]) -> str:
    """16-byte truncated SHA-256 — canonical module identity.
    
    Classe A: shorter than full SHA-256, enough for module-level dedup.
    Collision probability for <10^6 modules: essentially zero.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:32]  # 16 bytes = 32 hex chars


# =============================================================================
# 3. BEHCS Encoding Tiers (Classe B)
# =============================================================================

class BEHCSEncoder:
    """BEHCS encoding with 3 tiers.
    
    Classe B from Algorithms of Asolaria.
    Hyper-dimensional addressing space:
    - Tier 256:   256^60 ≈ 10^144  (small repos)
    - Tier 1024:  1024^60 ≈ 10^180 (medium projects)
    - Tier Hyper: 1024^256 ≈ 10^768 (monorepos)
    """
    
    def __init__(self, tier: str = "1024"):
        self.tier = tier
        if tier == "256":
            self.base = 256
            self.width = 60
        elif tier == "1024":
            self.base = 1024
            self.width = 60
        elif tier == "hyper":
            self.base = 1024
            self.width = 256
        else:
            raise ValueError(f"Unknown tier: {tier}")
    
    def encode(self, *values: int) -> List[int]:
        """Encode values into BEHCS address space.
        
        Each value is mapped to the tier's coordinate space.
        """
        encoded = []
        for v in values:
            # Clamp to addressable range
            clamped = min(max(v, 0), self.base - 1)
            encoded.append(clamped)
        # Pad to width
        while len(encoded) < self.width:
            encoded.append(0)
        return encoded[:self.width]
    
    def decode(self, address: List[int]) -> Tuple[int, ...]:
        """Trim trailing zeros and return non-zero coordinates."""
        trimmed = [x for x in reversed(address)]
        while trimmed and trimmed[0] == 0:
            trimmed.pop(0)
        return tuple(reversed(trimmed))
    
    def to_json_compat(self, address: List[int]) -> str:
        """Serialize to compact string."""
        return f"BEHCS-{self.tier}:{'-'.join(str(x) for x in address[:8])}..."


# =============================================================================
# 4. Brown-Hilbert Addressing (Classe C)
# =============================================================================

class BrownHilbertAddress:
    """port.port.port addressing for nested module hierarchies.
    
    Classe C from Algorithms of Asolaria.
    Uses Sidon sets for collision-avoidance in hierarchical namespaces.
    """
    
    def __init__(self, *ports: int):
        if len(ports) < 2:
            raise ValueError("Brown-Hilbert requires at least 2 ports")
        self.ports = list(ports)
    
    @classmethod
    def from_module_path(cls, module_path: str) -> "BrownHilbertAddress":
        """Map a dotted Python module path to Brown-Hilbert address.
        
        Example: 'simplicio_mapper.mapping.geometry'
        → BrownHilbertAddress(1, 3, 7, 13)  # primes from Sidon set
        """
        parts = module_path.split(".")
        # Use Sidon-related prime mapping for each depth level
        sidon_primes = [2, 3, 7, 13, 23, 41, 73, 127, 199, 307, 461, 673, 967]
        ports = []
        for i, part in enumerate(parts):
            if i < len(sidon_primes):
                # Simple hash: position × prime_of_depth
                h = FNV1a64.hash(part)
                ports.append((h % sidon_primes[i]) + 1)
            else:
                ports.append(FNV1a64.hash(part) % 256)
        return cls(*ports)
    
    def parent(self) -> Optional["BrownHilbertAddress"]:
        """Return parent address (drop last port)."""
        if len(self.ports) <= 2:
            return None
        return BrownHilbertAddress(*self.ports[:-1])
    
    def __str__(self) -> str:
        return ".".join(str(p) for p in self.ports)
    
    def to_json(self) -> Dict:
        return {
            "type": "Brown-Hilbert",
            "ports": self.ports,
            "address": str(self),
        }


# =============================================================================
# Example: Full Mapper Pipeline
# =============================================================================

class AsolariaMapper:
    """Complete mapper pipeline with Asolaria geometric addressing."""
    
    def __init__(self, repo_root: Path, tier: str = "1024"):
        self.repo_root = repo_root
        self.encoder = BEHCSEncoder(tier)
        self.modules: Dict[str, Dict] = {}
    
    def map_module(self, module_path: str, file_path: Path, line_count: int) -> Dict:
        """Map a single module with full Asolaria addressing."""
        
        # Compute addresses
        rel_path = str(file_path.relative_to(self.repo_root))
        pos = REALMATHPOS(rel_path, 0, 0)
        fnv_key = FNV1a64.hash_path(file_path)
        content_hash = sha16(file_path.read_bytes() if file_path.exists() else b"")
        bh_addr = BrownHilbertAddress.from_module_path(module_path)
        
        # BEHCS encoding of module dimensions
        dims = self.encoder.encode(len(module_path), line_count, len(rel_path))
        
        entry = {
            "module": module_path,
            "address": str(pos),
            "fnv_key": fnv_key,
            "sha16": content_hash,
            "brown_hilbert": str(bh_addr),
            "behcs_address": self.encoder.to_json_compat(dims),
            "proof": ProofLevel.MEASURED.value,
            "lines": line_count,
        }
        
        self.modules[module_path] = entry
        return entry
    
    def map_repository(self) -> Dict:
        """Map all Python modules in the repository."""
        for pyfile in sorted(self.repo_root.rglob("*.py")):
            if "site-packages" in str(pyfile) or ".venv" in str(pyfile):
                continue
            rel = pyfile.relative_to(self.repo_root)
            module_path = str(rel.with_suffix("")).replace("/", ".")
            lines = len(pyfile.read_bytes().split(b"\n"))
            self.map_module(module_path, pyfile, lines)
        
        return {
            "repo": self.repo_root.name,
            "tier": self.encoder.tier,
            "module_count": len(self.modules),
            "modules": self.modules,
        }


if __name__ == "__main__":
    print("=== Asolaria Geometric Mapping Example ===\n")
    
    # 1. Tagging Demo
    print("1. Tagging Discipline:")
    items = [
        MappedItem("parse_module", "function", ProofLevel.MEASURED, "executed: test_parse.py"),
        MappedItem("AddressingGeometry", "class", ProofLevel.CANON, "YOOL_TUPLE_HAMT.md"),
        MappedItem("schema_v3", "module", ProofLevel.UNVERIFIED),
    ]
    for item in items:
        print(f"   {item.proof.value:12s}  {item.name}")
    print()
    
    # 2. Addressing Demo
    print("2. Addressing Geometry:")
    pos = REALMATHPOS("simplicio_mapper/mapping.py", 42, 8)
    print(f"   REALMATHPOS:  {pos}")
    
    fnv = FNV1a64.hash_path(Path("simplicio_mapper/mapping.py"))
    print(f"   FNV-1a64:     {fnv}")
    
    sh16 = sha16("class AsolariaMapper")
    print(f"   sha16:        {sh16}")
    print()
    
    # 3. BEHCS Demo
    print("3. BEHCS Encoding:")
    for tier in ["256", "1024", "hyper"]:
        enc = BEHCSEncoder(tier)
        addr = enc.encode(42, 100, 7, 2026)
        print(f"   BEHCS-{tier:6s}: {enc.to_json_compat(addr)}  (space: ~10^{{{enc.width * (enc.base.bit_length() - 1) // 3}}})")
    print()
    
    # 4. Brown-Hilbert Demo
    print("4. Brown-Hilbert Addressing:")
    for path in ["simplicio_mapper.mapping.geometry", "simplicio_mapper.cli.main", "simplicio.utils"]:
        bh = BrownHilbertAddress.from_module_path(path)
        print(f"   {path:45s} → {bh}")
    print()
    
    # 5. Full Mapper Pipeline
    print("5. Full Mapper Pipeline (on repo root):")
    mapper = AsolariaMapper(Path(__file__).parent.parent)
    result = mapper.map_repository()
    print(f"   Modules mapped: {result['module_count']}")
    print(f"   Tier: {result['tier']}")
    for name, entry in list(result['modules'].items())[:5]:
        print(f"     {entry['proof']:10s} {name:40s} bh={entry['brown_hilbert']}")
    print()
    
    print("=== Example Complete ===")
