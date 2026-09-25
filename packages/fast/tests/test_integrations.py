from __future__ import annotations

import unittest
from unittest.mock import patch

from simplicio_fast.integrations import integration_status


class IntegrationStatusTest(unittest.TestCase):
    @staticmethod
    def _status(
        available: dict[str, str], version: str = "0.18.6"
    ) -> dict[str, object]:
        def executable(*names: str) -> str | None:
            return next((available[name] for name in names if name in available), None)

        def distribution(name: str) -> str | None:
            return {"simplicio-mapper": "0.26.11", "simplicio-cli": version}.get(name)

        with (
            patch(
                "simplicio_fast.integrations._distribution_version",
                side_effect=distribution,
            ),
            patch("simplicio_fast.integrations._executable", side_effect=executable),
        ):
            return integration_status()

    def test_prefers_current_dev_cli_action_binary(self) -> None:
        status = self._status(
            {
                "simplicio-mapper": "mapper.exe",
                "simplicio-dev-cli": "dev-cli.cmd",
                "simplicio-cli": "legacy-cli.exe",
            }
        )
        self.assertTrue(status["integrated_ready"])
        self.assertEqual("dev-cli.cmd", status["dev_cli"]["executable"])

    def test_falls_back_to_legacy_cli_name(self) -> None:
        status = self._status(
            {"simplicio-mapper": "mapper.exe", "simplicio-cli": "legacy-cli.exe"}
        )
        self.assertTrue(status["integrated_ready"])
        self.assertEqual("legacy-cli.exe", status["dev_cli"]["executable"])

    def test_below_minimum_dev_cli_remains_fail_closed(self) -> None:
        status = self._status(
            {"simplicio-mapper": "mapper.exe", "simplicio-dev-cli": "dev-cli.cmd"},
            version="0.16.2",
        )
        self.assertFalse(status["integrated_ready"])
        self.assertFalse(status["dev_cli"]["compatible"])
        self.assertEqual("0.18.6", status["dev_cli"]["minimum"])


if __name__ == "__main__":
    unittest.main()
