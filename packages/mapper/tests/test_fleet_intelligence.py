from __future__ import annotations

import unittest

from simplicio_mapper.fleet_intelligence import build_fleet
from simplicio_mapper.structural_graph import EdgeKind, NodeKind


class FleetIntelligenceTests(unittest.TestCase):
    def test_explicit_repositories_keep_identity_and_generation(self) -> None:
        fleet = build_fleet(
            {
                "frontend": [("client.py", "import requests\nrequests.get('/users')\n")],
                "api": [("routes.py", "@app.get('/users')\ndef users():\n    pass\n")],
            },
            generations={"frontend": "g-front", "api": "g-api"},
            roots={"frontend": "/workspace/front", "api": "/workspace/api"},
        )
        self.assertEqual([item.repository_id for item in fleet.repositories], ["api", "frontend"])
        self.assertEqual({item.generation_id for item in fleet.repositories}, {"g-front", "g-api"})
        self.assertTrue(all(row["repository"] in {"api", "frontend"} for row in fleet.query()))

    def test_unique_route_is_linked_across_repositories(self) -> None:
        fleet = build_fleet(
            {
                "client": [("client.py", "requests.get('/users')\n")],
                "api": [("routes.py", "@app.get('/users')\ndef users():\n    pass\n")],
            },
            generations={"client": "g1", "api": "g2"},
        )
        self.assertTrue(any(edge.kind == EdgeKind.HTTP_CALLS and edge.target_repo == "api" for edge in fleet.edges))

    def test_iac_becomes_resource_without_network_discovery(self) -> None:
        fleet = build_fleet(
            {"service": [("deployment.yaml", "kind: Deployment\nmetadata:\n  name: service\n")]},
            generations={"service": "g1"},
        )
        resources = fleet.query(kind=NodeKind.RESOURCE)
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["name"], "Deployment")


if __name__ == "__main__":
    unittest.main()
