from django.test import Client, TestCase


class HealthTests(TestCase):
    def test_health(self) -> None:
        response = Client().get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
