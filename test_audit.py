"""Пограничные случаи проверок, которых нет в синтетических данных.

    python3 -m unittest test_audit.py
"""

import unittest

from urllib.parse import urlparse

from audit import audit, discover, via_gateway

REPOSITORY = {
    "standards": {"integration_channels": ["api-gateway"], "mcp_gateway": "api-gw.corp.local"},
    "applications": [{"id": "crm", "host": "crm.corp.local", "capability": "CAP-02",
                      "business_owner": "Директор по продажам", "type": "application"}],
}
ACCOUNTS = {"svc:agt-sales-01": {"kind": "service", "enabled": "yes"},
            "user:sales-10": {"kind": "human", "enabled": "yes"}}
GW = "https://api-gw.corp.local/crm/mcp"


def run(servers=None, account="svc:agt-sales-01", log_account=None, last_call="2026-10-30",
        app_type=None, **fields):
    """last_call=None — агента нет в журнале шлюза, app_type — тип его записи в репозитории."""
    mcp = [{"team": "sales", "agents": [{"key": "agt-sales-01", "capability": "CAP-02",
                                         "account": account,
                                         "servers": [{"name": "crm", "url": GW}]
                                         if servers is None else servers, **fields}]}]
    log = [] if last_call is None else [
        {"date": last_call, "account": log_account or account, "agent": "agt-sales-01"}]
    repo = REPOSITORY if app_type is None else {**REPOSITORY, "applications": [
        *REPOSITORY["applications"],
        {"id": "agt-sales-01", "host": "agt-sales-01.corp.local", "capability": "CAP-02",
         "business_owner": "Директор по продажам", "type": app_type,
         "runtime_key": "agt-sales-01"}]}
    agents = discover(mcp, log)
    audit(repo, agents, ACCOUNTS)
    return agents["agt-sales-01"]["errors"]


class AuditEdgeCases(unittest.TestCase):
    def test_clean_service_account_has_no_error_3(self):
        self.assertFalse(run()[3])

    def test_human_account_seen_only_in_gateway_log(self):
        self.assertTrue(run(log_account="user:sales-10")[3])

    def test_unknown_account_is_not_treated_as_service(self):
        self.assertTrue(run(account="svc:unknown")[3])

    def test_via_gateway(self):
        cases = [(GW, True), ("https://api-gw.corp.local:443/crm/mcp", True),
                 ("https://api-gw.corp.local:8443/crm/mcp", False),
                 ("http://api-gw.corp.local/crm/mcp", False),
                 ("https://api-gw.corp.local:44a/crm/mcp", False),
                 ("http://crm.corp.local:8080/mcp", False)]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(via_gateway(urlparse(url), "api-gw.corp.local"), expected)

    def test_agent_without_servers_has_no_error_4(self):
        self.assertFalse(run(servers=[])[4])

    def test_silent_agent_with_unknown_account_is_zombie(self):
        self.assertTrue(run(account="svc:unknown", last_call="2026-08-01")[6])

    def test_active_agent_is_not_zombie(self):
        self.assertFalse(run()[6])

    def test_gateway_url_is_not_direct(self):
        self.assertFalse(run()[4])

    def test_agent_registered_as_application_is_error_1(self):
        errors = run(app_type="application")
        self.assertTrue(errors[1])
        self.assertFalse(errors[2])

    def test_agent_registered_as_ai_agent_is_not_error_1(self):
        self.assertFalse(any(run(app_type="ai-agent").values()))

    def test_agent_without_gateway_calls_is_not_zombie(self):
        self.assertFalse(run(last_call=None)[6])

    def test_stdio_server_is_skipped_not_crash(self):
        self.assertFalse(run(servers=[{"name": "local", "command": "mcp-files"}])[4])

    def test_remote_server_without_url_is_direct(self):
        self.assertTrue(run(servers=[{"name": "crm", "url": ""}])[4])

    def test_technical_owner_is_not_business_owner(self):
        self.assertTrue(run(technical_owner="руководитель команды sales")[2])

    def test_business_owner_from_mcp_config_counts(self):
        self.assertFalse(run(business_owner="Директор по продажам",
                             technical_owner="руководитель команды sales")[2])

    def test_gateway_host_on_other_port_is_direct(self):
        self.assertTrue(run(servers=[{"name": "crm",
                                      "url": "https://api-gw.corp.local:8443/crm/mcp"}])[4])


if __name__ == "__main__":
    unittest.main()
