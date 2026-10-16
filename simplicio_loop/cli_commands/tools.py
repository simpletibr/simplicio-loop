"""`ecc`, `deploy`, `agent-slots`, `generation-broker` and `hub-drain-plan`.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

import argparse



def add_ecc(sub):
    p_ecc = sub.add_parser("ecc", help="inspect the opt-in ECC advisory integration")
    ecc_sub = p_ecc.add_subparsers(dest="ecc_command", required=True)
    p_ecc_doctor = ecc_sub.add_parser("doctor", help="verify ECC provenance and safety policy")
    p_ecc_doctor.add_argument("--repo", default=".", help="repository root")
    p_ecc_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def add_deploy(sub):
    p_deploy = sub.add_parser(
        "deploy", help="plan a gated serverless deployment (dry-run unless --apply is explicit)"
    )
    p_deploy.add_argument("--repo", default=".")
    p_deploy.add_argument("--backend", choices=("modal", "daytona"), default="modal")
    p_deploy.add_argument("--environment", default="")
    p_deploy.add_argument("--image", default="")
    p_deploy.add_argument("--apply", action="store_true")
    p_deploy.add_argument("--action-gate", action="store_true")


def add_agent_slots(sub):
    p_slots = sub.add_parser("agent-slots", help="inspect and reclaim Loop-owned agent capacity")
    p_slots.add_argument("slot_args", nargs=argparse.REMAINDER,
                         help="pass-through args for the JSON-first agent slot registry")


def add_generation_broker(sub):
    p_generation_broker = sub.add_parser(
        "generation-broker", help="operate persisted generation bindings")
    p_generation_broker.add_argument("broker_args", nargs=argparse.REMAINDER)


def add_hub_drain_plan(sub):
    sub.add_parser(
        "hub-drain-plan",
        help="read-only PT-BR/EN GitHub drain intake; never executes the plan",
    )
