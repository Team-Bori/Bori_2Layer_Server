import unittest

from main import app


class OpenApiTests(unittest.TestCase):
    def test_swagger_lists_websocket_messages(self):
        schema = app.openapi()
        self.assertEqual(
            list(schema["paths"]),
            ["/ws/initConnect", "/ws/command", "/ws/report", "/ws/BoriException"],
        )
        self.assertIn("piSerial", schema["components"]["schemas"]["InitConnect"]["properties"])
        self.assertNotIn("pi_serial", schema["components"]["schemas"]["InitConnect"]["properties"])
        payload = schema["components"]["schemas"]["CommandPayload"]["properties"]
        self.assertIn("artifactUrl", payload)
        self.assertEqual(
            schema["components"]["schemas"]["BoriException"]["properties"]["code"]["enum"],
            ["UNKNOWN_PORT", "PORT_CLOSED", "OVERSIZE"],
        )
        self.assertEqual(
            set(schema["components"]["schemas"]["ReportPayload"]["properties"]),
            {"cpuPct", "memPct", "fps", "tempC", "powerW", "errorRate"},
        )
        example = schema["paths"]["/ws/report"]["post"]["requestBody"]["content"]["application/json"]["example"]
        self.assertIsNone(example["payload"]["fps"])
        self.assertFalse(app.swagger_ui_parameters["tryItOutEnabled"])


if __name__ == "__main__":
    unittest.main()
