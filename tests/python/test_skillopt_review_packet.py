from __future__ import annotations

import hashlib
import json
import subprocess
import sys

from bench.run_scratch_live_gate import load_skillopt_review_evidence
from bench.run_skillopt_review_packet import (
    build_review_packet,
    load_candidate_goals,
    main,
    write_reports,
)


def _write_skill(root, slug, *, review_required=True):
    review_line = "    review_required: true" if review_required else "    review_required: false"
    path = root / slug / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {slug}",
                "description: generated test skill",
                "auto_generated:",
                "  by: skill-opt",
                "  date: 2026-05-31",
                "  source_goal: Build an audit workflow",
                "  planner_model: test-planner",
                review_line,
                "---",
                "",
                f"# {slug}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_skillopt_review_packet_collects_only_review_gated_skills(tmp_path):
    skills_root = tmp_path / ".skills"
    _write_skill(skills_root, "generated-one")
    _write_skill(skills_root, "already-reviewed", review_required=False)
    manual_path = skills_root / "manual-review" / "SKILL.md"
    manual_path.parent.mkdir()
    manual_path.write_text(
        "\n".join(
            [
                "---",
                "name: manual-review",
                "review_required: true",
                "---",
                "",
                "# manual-review",
                "",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_review_packet(skills_root=skills_root)

    assert packet["benchmark"] == "skillopt-review-packet"
    assert packet["summary"]["review_gated_skills"] == 1
    assert packet["summary"]["release_ready"] is False
    assert packet["reviews"][0]["skill"] == "generated-one"
    assert packet["reviews"][0]["approved"] is None
    assert packet["reviews"][0]["reviewer"] == ""
    assert len(packet["reviews"][0]["sha256"]) == 64
    assert (
        packet["reviews"][0]["sha256"]
        == hashlib.sha256(
            (skills_root / "generated-one" / "SKILL.md").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
    )


def test_skillopt_review_packet_pending_rows_do_not_pass_live_gate(tmp_path):
    skills_root = tmp_path / ".skills"
    _write_skill(skills_root, "generated-one")
    packet = build_review_packet(skills_root=skills_root)
    json_path = tmp_path / "packet.json"
    md_path = tmp_path / "packet.md"

    write_reports(packet, json_path, md_path)
    normalized = load_skillopt_review_evidence(json_path)

    assert normalized["total_reviews"] == 0
    assert normalized["invalid_reviews"] == 1
    assert normalized["gate_passed"] is False
    assert "SkillOpt Human Review Packet" in md_path.read_text(encoding="utf-8")


def test_skillopt_review_packet_main_writes_reports(tmp_path):
    skills_root = tmp_path / ".skills"
    _write_skill(skills_root, "generated-one")
    json_path = tmp_path / "out.json"
    md_path = tmp_path / "out.md"

    rc = main(
        [
            "--skills-root",
            str(skills_root),
            "--json-output",
            str(json_path),
            "--md-output",
            str(md_path),
            "--quiet",
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["summary"]["pending_reviews"] == 1
    assert "generated-one" in md_path.read_text(encoding="utf-8")


def test_skillopt_review_packet_loads_candidate_goals_from_text_and_json(tmp_path):
    text_path = tmp_path / "goals.txt"
    text_path.write_text(
        "# comments are ignored\nGenerate pytest fixtures\n\nGenerate SQL migrations\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "goals.json"
    json_path.write_text(json.dumps({"goals": ["Generate Playwright flows"]}), encoding="utf-8")

    assert load_candidate_goals(text_path) == [
        "Generate pytest fixtures",
        "Generate SQL migrations",
    ]
    assert load_candidate_goals(json_path) == ["Generate Playwright flows"]


def test_skillopt_review_packet_main_can_generate_pending_candidate(
    tmp_path,
    monkeypatch,
):
    from simplicio.scratch import skill_opt

    skills_root = tmp_path / ".skills"
    json_path = tmp_path / "out.json"
    md_path = tmp_path / "out.md"

    def fake_generate_skill_doc(description, skills_root=None, planner_model=None):
        assert description == "Generate pytest fixtures"
        assert planner_model == "test-planner"
        return (
            "generated-pytest-fixtures",
            "\n".join(
                [
                    "---",
                    "name: generated-pytest-fixtures",
                    "description: generated test skill",
                    "auto_generated:",
                    "  by: skill-opt",
                    "  date: 2026-05-31",
                    "  source_goal: Generate pytest fixtures",
                    "  planner_model: test-planner",
                    "  review_required: true",
                    "---",
                    "",
                    "# generated-pytest-fixtures",
                    "",
                ]
            ),
        )

    monkeypatch.setattr(skill_opt, "generate_skill_doc", fake_generate_skill_doc)

    rc = main(
        [
            "--skills-root",
            str(skills_root),
            "--candidate-goal",
            "Generate pytest fixtures",
            "--description",
            "",
            "--planner",
            "test-planner",
            "--json-output",
            str(json_path),
            "--md-output",
            str(md_path),
            "--quiet",
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["summary"]["pending_reviews"] == 1
    assert payload["reviews"][0]["skill"] == "generated-pytest-fixtures"
    assert payload["reviews"][0]["approved"] is None
    assert payload["reviews"][0]["reviewer"] == ""


def test_skillopt_review_packet_main_records_candidate_generation_failures(
    tmp_path,
    monkeypatch,
):
    from simplicio.scratch import skill_opt

    skills_root = tmp_path / ".skills"
    json_path = tmp_path / "out.json"
    md_path = tmp_path / "out.md"

    def fake_install_skill_from_description(
        description,
        *,
        skills_root=None,
        planner_model=None,
    ):
        if description == "bad candidate":
            raise RuntimeError("planner unavailable")
        assert planner_model == "test-planner"
        return _write_skill(skills_root, "generated-good")

    monkeypatch.setattr(
        skill_opt,
        "install_skill_from_description",
        fake_install_skill_from_description,
    )

    rc = main(
        [
            "--skills-root",
            str(skills_root),
            "--candidate-goal",
            "good candidate",
            "--candidate-goal",
            "bad candidate",
            "--planner",
            "test-planner",
            "--json-output",
            str(json_path),
            "--md-output",
            str(md_path),
            "--quiet",
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["summary"]["pending_reviews"] == 1
    assert payload["summary"]["candidate_generation_failures"] == 1
    assert payload["generation_failures"][0]["description"] == "bad candidate"
    assert "planner unavailable" in payload["generation_failures"][0]["error"]


def test_skillopt_review_packet_script_can_import_repo_package(tmp_path):
    json_path = tmp_path / "out.json"
    md_path = tmp_path / "out.md"

    completed = subprocess.run(
        [
            sys.executable,
            "bench/run_skillopt_review_packet.py",
            "--skills-root",
            str(tmp_path / ".skills"),
            "--json-output",
            str(json_path),
            "--md-output",
            str(md_path),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["benchmark"] == ("skillopt-review-packet")


def test_versioned_skillopt_review_packet_has_pending_candidates() -> None:
    packet = json.loads(open("bench/results_skillopt_review_packet.json", encoding="utf-8").read())

    assert packet["summary"]["pending_reviews"] >= 10
    assert packet["summary"]["human_review_complete"] is False
    assert packet["summary"]["release_ready"] is False
    for row in packet["reviews"]:
        assert row["reviewer"] == ""
        assert row["approved"] is None
        assert row["reviewed_at"] == ""
        assert row["path"].startswith("bench/skillopt_pending_skills/")
        with open(row["path"], "rb") as artifact:
            assert row["sha256"] == hashlib.sha256(artifact.read().replace(b"\r\n", b"\n")).hexdigest()
