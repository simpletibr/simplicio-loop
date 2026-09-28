"""A standalone simplicio-cli / simplicio-mapper next to the single wheel corrupts it on uninstall."""
from simplicio_loop import stack_manifest as sm


def _pretend_installed(monkeypatch, present):
    real = sm._installed_version
    monkeypatch.setattr(
        sm, "_installed_version",
        lambda name: "0.26.34" if name in present else (None if name in sm.LEGACY_DISTRIBUTIONS else real(name)),
    )


def test_legacy_standalone_distribution_marks_the_stack_drifted(monkeypatch):
    _pretend_installed(monkeypatch, {"simplicio-mapper"})
    document = sm.stack_manifest()
    assert document["legacy_distributions"] == ["simplicio-mapper"]
    assert document["healthy"] is False
    assert "simplicio-mapper-legacy-standalone" in document["missing_or_drifted"]
    assert "pip uninstall -y simplicio-mapper" in document["legacy_remediation"]


def test_no_legacy_distribution_reports_an_empty_list(monkeypatch):
    _pretend_installed(monkeypatch, set())
    document = sm.stack_manifest()
    assert document["legacy_distributions"] == []
    assert document["legacy_remediation"] == ""
