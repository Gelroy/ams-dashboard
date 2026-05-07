from django.test import Client, TestCase


class HealthEndpointTest(TestCase):
    def test_health(self):
        r = Client().get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})
