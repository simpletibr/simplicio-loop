"""Test for issue 1674: ensure issue 1674 models are properly registered.

The model catalog must list models that are actually available through their respective CLIs.
This test validates that the replacement models for gpt-6-luna and grok-4.5 are correctly configured.
"""

import pytest
from simplicio_loop import model_roles


class TestIssue1674Models:
    """Verify that codex execution and grok execution models are in the catalog and work."""

    def test_codex_execution_model_is_available(self):
        """codex/execution should resolve to an available model."""
        result = model_roles.resolve('codex', 'execution')
        # The new model that replaces gpt-6-luna
        assert result['model'] == 'gpt-5.6-luna'
        assert result['effort'] == 'high'

    def test_grok_execution_model_is_available(self):
        """grok/execution should resolve to an available model."""
        result = model_roles.resolve('grok', 'execution')
        # The new model that replaces grok-4.5
        assert result['model'] == 'grok-4.7'
        assert result['effort'] == 'high'

    def test_codex_execution_can_be_resolved_to_role(self):
        """codex execution model should map back to execution role."""
        result = model_roles.role_of('gpt-5.6-luna')
        assert result is not None
        assert result['role'] == 'execution'

    def test_grok_execution_can_be_resolved_to_role(self):
        """grok execution model should map back correctly."""
        # grok-4.7 is used for planning, coordination, and execution
        # role_of() returns the first match found, which is planning
        result = model_roles.role_of('grok-4.7')
        assert result is not None
        # grok-4.7 is used by multiple roles, so just verify it's in there
        assert result['role'] in ('planning', 'coordination', 'execution')
