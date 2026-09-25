"""Lightweight public facade for Simplicio Fast.

Importing the package exposes its version without eagerly loading mmap,
Runtime subprocess, workspace, navigation, or cache implementations. Public
symbols remain source-compatible and are loaded on first access.
"""

from __future__ import annotations

from importlib import import_module


__version__ = "2.0.35"

_EXPORTS = {
    "ArenaError": (".prism_arena", "ArenaError"),
    "EngineSelection": (".engine", "EngineSelection"),
    "EngineSelectionError": (".engine", "EngineSelectionError"),
    "Delta": (".delta", "Delta"),
    "DeltaError": (".delta", "DeltaError"),
    "GenerationId": (".workspace", "GenerationId"),
    "KnowledgeFacade": (".knowledge", "KnowledgeFacade"),
    "Manifest": (".workspace", "Manifest"),
    "NavigationBudget": (".navigation", "NavigationBudget"),
    "NavigationError": (".navigation", "NavigationError"),
    "NavigationIndex": (".navigation", "NavigationIndex"),
    "NavigationItem": (".navigation", "NavigationItem"),
    "NavigationPage": (".navigation", "NavigationPage"),
    "PrismArena": (".prism_arena", "PrismArena"),
    "PrismWorkDelta": (".prism_arena", "PrismWorkDelta"),
    "ProjectionEnvelope": (".projection", "ProjectionEnvelope"),
    "ProjectionError": (".projection", "ProjectionError"),
    "ProjectionStore": (".projection", "ProjectionStore"),
    "FederatedEdge": (".federation", "FederatedEdge"),
    "Federation": (".federation", "Federation"),
    "FederationError": (".federation", "FederationError"),
    "FederationMember": (".federation", "FederationMember"),
    "compile_federation": (".federation", "compile_federation"),
    "DiffRecord": (".semantic_diff", "DiffRecord"),
    "SemanticDiff": (".semantic_diff", "SemanticDiff"),
    "SemanticDiffError": (".semantic_diff", "SemanticDiffError"),
    "WhatIfOverlay": (".semantic_diff", "WhatIfOverlay"),
    "diff_generations": (".semantic_diff", "diff_generations"),
    "ValidationCache": (".validation_cache", "ValidationCache"),
    "ValidationCacheError": (".validation_cache", "ValidationCacheError"),
    "ValidationKey": (".validation_cache", "ValidationKey"),
    "ValidationResult": (".validation_cache", "ValidationResult"),
    "CapabilityCandidate": (".capability_ranking", "CapabilityCandidate"),
    "CapabilityRankingError": (".capability_ranking", "CapabilityRankingError"),
    "rank_capabilities": (".capability_ranking", "rank_capabilities"),
    "UniversalContextError": (".universal_context", "UniversalContextError"),
    "compile_context": (".universal_context", "compile_context"),
    "ContextAdapterError": (".context_adapters", "ContextAdapterError"),
    "adapt_code": (".context_adapters", "adapt_code"),
    "adapt_knowledge_result": (".context_adapters", "adapt_knowledge_result"),
    "adapt_operations_result": (".context_adapters", "adapt_operations_result"),
    "adapter_manifest": (".context_adapters", "adapter_manifest"),
    "compile_context_sources": (".context_adapters", "compile_context_sources"),
    "ContextSecurityError": (".context_security", "ContextSecurityError"),
    "security_manifest": (".context_security", "security_manifest"),
    "validate_context_packet": (".context_security", "validate_context_packet"),
    "OperationReceipt": (".operations_projection", "OperationReceipt"),
    "OperationsProjection": (".operations_projection", "OperationsProjection"),
    "OperationsProjectionError": (".operations_projection", "OperationsProjectionError"),
    "KnowledgeFact": (".knowledge_projection", "KnowledgeFact"),
    "KnowledgeProjection": (".knowledge_projection", "KnowledgeProjection"),
    "KnowledgeProjectionError": (".knowledge_projection", "KnowledgeProjectionError"),
    "ProjectionSDK": (".sdk", "ProjectionSDK"),
    "SDKError": (".sdk", "SDKError"),
    "CompatibilityDecision": (".compatibility", "CompatibilityDecision"),
    "CompatibilityError": (".compatibility", "CompatibilityError"),
    "compatibility_manifest": (".compatibility", "compatibility_manifest"),
    "evaluate_compatibility": (".compatibility", "evaluate_compatibility"),
    "RequestKey": (".pager", "RequestKey"),
    "SingleFlightCoordinator": (".pager", "SingleFlightCoordinator"),
    "SingleFlightError": (".pager", "SingleFlightError"),
    "SlotView": (".prism_arena", "SlotView"),
    "TaskOverlay": (".prism_arena", "TaskOverlay"),
    "WorkspaceStore": (".workspace", "WorkspaceStore"),
    "make_request_key": (".pager", "make_request_key"),
    "navigate": (".navigation", "navigate"),
    "select_engine": (".engine", "select_engine"),
}

__all__ = [*_EXPORTS, "__version__"]


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
