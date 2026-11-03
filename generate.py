"""Генератор синтетического ландшафта: архитектурный репозиторий и то, что реально работает.

Данные уже лежат в data/, запускать генератор не нужно. Он здесь, чтобы было видно,
как данные получены, и чтобы CI мог проверить, что они воспроизводятся байт в байт.

    python3 generate.py            # перезаписать data/
    python3 generate.py /tmp/out   # сгенерировать в другой каталог
"""

import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

SEED = 154
AUDIT_DATE = date(2026, 10, 31)
LOG_DAYS = 90
GATEWAY = "api-gw.corp.local"
CHANNELS = ["api-gateway", "esb", "event-bus"]

CAPABILITIES = [
    ("CAP-01", "Обработка обращений клиентов"),
    ("CAP-02", "Продажи и сделки"),
    ("CAP-03", "Счета и платежи"),
    ("CAP-04", "Закупки"),
    ("CAP-05", "Подбор персонала"),
    ("CAP-06", "Складская логистика"),
    ("CAP-07", "Маркетинговые кампании"),
    ("CAP-08", "Договорная работа"),
    ("CAP-09", "Поддержка ИТ-инфраструктуры"),
    ("CAP-10", "Отчётность и аналитика"),
    ("CAP-11", "Управление знаниями"),
    ("CAP-12", "Кадровое администрирование"),
]

# id, название, бизнес-возможность, бизнес-владелец (роль)
APPLICATIONS = [
    ("crm", "CRM", "CAP-02", "Директор по продажам"),
    ("contact-center", "Контакт-центр", "CAP-01", "Руководитель клиентского сервиса"),
    ("service-desk", "Service Desk", "CAP-09", "Руководитель ИТ-поддержки"),
    ("billing", "Биллинг", "CAP-03", "Финансовый директор"),
    ("erp-finance", "ERP, финансовый контур", "CAP-03", "Финансовый директор"),
    ("erp-procurement", "ERP, закупки", "CAP-04", "Директор по закупкам"),
    ("supplier-portal", "Портал поставщиков", "CAP-04", "Директор по закупкам"),
    ("wms", "Склад WMS", "CAP-06", "Директор по логистике"),
    ("tms", "Транспорт TMS", "CAP-06", "Директор по логистике"),
    ("ats", "Система подбора персонала", "CAP-05", "Директор по персоналу"),
    ("hr-core", "Кадровая система", "CAP-12", "Директор по персоналу"),
    ("hr-portal", "HR-портал", "CAP-12", "Директор по персоналу"),
    ("cdp", "Платформа клиентских данных", "CAP-07", "Директор по маркетингу"),
    ("email-campaigns", "Рассылки", "CAP-07", "Директор по маркетингу"),
    ("cms", "Сайт и CMS", "CAP-07", "Директор по маркетингу"),
    ("contracts", "Договорная система", "CAP-08", "Директор по правовым вопросам"),
    ("edo", "Электронный документооборот", "CAP-08", "Директор по правовым вопросам"),
    ("dwh", "Хранилище данных", "CAP-10", "Директор по данным"),
    ("bi", "BI-отчётность", "CAP-10", "Директор по данным"),
    ("wiki", "База знаний", "CAP-11", "Руководитель офиса цифровой трансформации"),
    ("monitoring", "Мониторинг", "CAP-09", "Руководитель ИТ-поддержки"),
    ("cmdb", "CMDB", "CAP-09", "Руководитель ИТ-поддержки"),
    ("iam", "Управление доступом", "CAP-09", "Руководитель ИТ-поддержки"),
    ("mail", "Корпоративная почта", "CAP-11", "Руководитель ИТ-поддержки"),
    ("pricing", "Ценообразование", "CAP-02", "Директор по продажам"),
    ("loyalty", "Программа лояльности", "CAP-07", "Директор по маркетингу"),
    ("payments", "Платёжный шлюз", "CAP-03", "Финансовый директор"),
    ("treasury", "Казначейство", "CAP-03", "Финансовый директор"),
    ("lms", "Обучение сотрудников", "CAP-05", "Директор по персоналу"),
    ("claims", "Претензии и возвраты", "CAP-01", "Руководитель клиентского сервиса"),
    ("tender", "Тендерная площадка", "CAP-04", "Директор по закупкам"),
    ("fleet", "Автопарк", "CAP-06", "Директор по логистике"),
]

# Четыре агента попали в репозиторий, но как обычные приложения
AGENTS_AS_APPS = [
    ("agt-support-01", "Бот первой линии поддержки", "CAP-01", "Руководитель клиентского сервиса"),
    ("agt-sales-01", "Помощник менеджера по продажам", "CAP-02", "Директор по продажам"),
    ("agt-hr-01", "Чат-бот кадровых вопросов", "CAP-12", None),
    ("agt-itops-01", "Ассистент дежурного инженера", "CAP-09", "Руководитель ИТ-поддержки"),
]

# команда, сколько у неё агентов, какие возможности она закрывает агентами
TEAMS = [
    ("support", 6, ["CAP-01", "CAP-11"]),
    ("sales", 5, ["CAP-02", "CAP-01", "CAP-10"]),
    ("finance", 4, ["CAP-03", "CAP-10"]),
    ("procurement", 3, ["CAP-04", "CAP-08"]),
    ("logistics", 3, ["CAP-06"]),
    ("hr", 4, ["CAP-05", "CAP-12", "CAP-11"]),
    ("marketing", 4, ["CAP-07", "CAP-10"]),
    ("legal", 2, ["CAP-08"]),
    ("itops", 3, ["CAP-09", "CAP-11"]),
]

# какие системы агент каждой возможности дёргает инструментами
TOOLS_BY_CAPABILITY = {}
for app_id, _, cap, _ in APPLICATIONS:
    TOOLS_BY_CAPABILITY.setdefault(cap, []).append(app_id)

PURPOSES = {
    "CAP-01": "ответы клиентам",
    "CAP-02": "подготовка коммерческих предложений",
    "CAP-03": "сверка счетов",
    "CAP-04": "разбор заявок на закупку",
    "CAP-05": "отбор резюме",
    "CAP-06": "планирование отгрузок",
    "CAP-07": "тексты рассылок",
    "CAP-08": "проверка договоров",
    "CAP-09": "разбор инцидентов",
    "CAP-10": "сводки для руководства",
    "CAP-11": "поиск по базе знаний",
    "CAP-12": "кадровые справки",
}


def host(app_id):
    return f"{app_id}.corp.local"


def build(rng):
    repo_apps = []
    for rows, is_agent in ((APPLICATIONS, False), (AGENTS_AS_APPS, True)):
        for app_id, name, cap, owner in rows:
            app = {"id": app_id, "name": name, "type": "application",
                   "capability": cap, "business_owner": owner, "host": host(app_id)}
            if is_agent:
                app["runtime_key"] = app_id
            repo_apps.append(app)

    integrations = []
    app_ids = [a[0] for a in APPLICATIONS]
    for i, src in enumerate(app_ids):
        for dst in rng.sample(app_ids[:i] + app_ids[i + 1:], rng.choice([1, 1, 2])):
            integrations.append({"from": src, "to": dst,
                                 "channel": rng.choice(CHANNELS)})

    repository = {
        "standards": {"integration_channels": CHANNELS,
                      "mcp_gateway": GATEWAY},
        "capabilities": [{"id": c, "name": n} for c, n in CAPABILITIES],
        "applications": repo_apps,
        "integrations": integrations,
    }

    registered = {key: cap for key, _, cap, _ in AGENTS_AS_APPS}
    mcp, accounts, log = {}, {}, []
    for team, count, caps in TEAMS:
        agents = []
        for n in range(1, count + 1):
            key = f"agt-{team}-{n:02d}"
            if key in registered:
                cap, owner = registered[key], None
            else:
                cap = rng.choice(caps)
                owner = "руководитель команды " + team if rng.random() < 0.4 else None
            human = rng.random() < 0.35
            account = f"user:{team}-{rng.randint(10, 99)}" if human else f"svc:{key}"
            # аргумент setdefault считается и для уже известной учётки: он тратит вызовы rng,
            # и без них data/ перестанет воспроизводиться байт в байт
            accounts.setdefault(account, {"account": account, "kind": "human" if human else "service",
                             "enabled": "yes", "scopes": ",".join(sorted(rng.sample(
                                 ["read:crm", "read:wiki", "write:tickets", "read:finance",
                                  "write:mail", "read:hr", "write:docs"], rng.randint(1, 3))))})

            zombie = rng.random() < 0.2
            last = AUDIT_DATE - timedelta(days=rng.randint(35, 80) if zombie else rng.randint(0, 6))
            first = last - timedelta(days=rng.randint(5, 40))
            day = max(first, AUDIT_DATE - timedelta(days=LOG_DAYS - 1))
            while day <= last:
                if rng.random() < 0.7 or day == last:
                    log.append({"date": day.isoformat(), "account": account, "agent": key,
                                "requests": rng.randint(3, 400)})
                day += timedelta(days=1)

            # примерно каждый девятый агент — скрипт без MCP, виден только в журнале шлюза
            if rng.random() < 0.11 and key not in registered:
                continue
            direct = rng.random() < 0.5
            servers = []
            tools = TOOLS_BY_CAPABILITY[cap]
            for app_id in sorted(rng.sample(tools, min(len(tools), rng.randint(1, 3)))):
                if direct and rng.random() < 0.8:
                    url = f"http://{host(app_id)}:{rng.choice([8080, 8443, 9000])}/mcp"
                else:
                    url = f"https://{GATEWAY}/{app_id}/mcp"
                servers.append({"name": app_id, "url": url})
            agent = {"key": key, "purpose": PURPOSES[cap], "capability": cap, "account": account}
            if owner:
                agent["owner"] = owner
            agent["servers"] = servers
            agents.append(agent)
        mcp[team] = {"team": team, "agents": agents}

    log.sort(key=lambda r: (r["date"], r["agent"]))
    return repository, mcp, sorted(accounts.values(), key=lambda r: r["account"]), log


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data"
    repository, mcp, accounts, log = build(random.Random(SEED))
    (out / "runtime" / "mcp").mkdir(parents=True, exist_ok=True)
    write_json(out / "repository.json", repository)
    for team, cfg in mcp.items():
        write_json(out / "runtime" / "mcp" / f"{team}.json", cfg)
    write_csv(out / "runtime" / "service_accounts.csv", accounts,
              ["account", "kind", "enabled", "scopes"])
    write_csv(out / "runtime" / "llm_gateway.csv", log, ["date", "account", "agent", "requests"])
    print(f"данные записаны в {out}")


if __name__ == "__main__":
    main()
