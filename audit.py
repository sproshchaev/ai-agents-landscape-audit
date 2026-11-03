"""Сверка архитектурного репозитория с тем, что реально работает в компании.

Сначала проверяется сам репозиторий, как это делает обычный архитектурный валидатор.
Затем агенты собираются из фактических источников (MCP-конфиги команд и журнал LLM-шлюза)
и проверяются по шести ошибкам из статьи.

    python3 audit.py              # сводка, её же сверяет run.sh с expected.txt
    python3 audit.py --details    # плюс строка на каждого агента
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from generate import AUDIT_DATE

DATA = Path(__file__).parent / "data"
ZOMBIE_DAYS = 30
GATEWAY_PORT = 443
# учётка, которой нет в выгрузке: не сервисная и не отключённая, отсутствие данных — не соответствие
UNKNOWN_ACCOUNT = {"kind": "unknown", "enabled": "unknown"}


def load():
    repository = json.loads((DATA / "repository.json").read_text(encoding="utf-8"))
    mcp = [json.loads(p.read_text(encoding="utf-8"))
           for p in sorted((DATA / "runtime" / "mcp").glob("*.json"))]
    with open(DATA / "runtime" / "service_accounts.csv", encoding="utf-8") as f:
        accounts = {r["account"]: r for r in csv.DictReader(f)}
    with open(DATA / "runtime" / "llm_gateway.csv", encoding="utf-8") as f:
        log = list(csv.DictReader(f))
    return repository, mcp, accounts, log


def check_repository(repository):
    """То, что видит архитектор, глядя только в репозиторий."""
    apps = repository["applications"]
    allowed = set(repository["standards"]["integration_channels"])
    return {
        "apps": len(apps),
        "agents": sum(a["type"] == "ai-agent" for a in apps),
        "with_owner": sum(bool(a["business_owner"]) for a in apps),
        "integrations": len(repository["integrations"]),
        "by_standard": sum(i["channel"] in allowed for i in repository["integrations"]),
    }


def discover(mcp, log):
    """Агенты по фактическим следам: MCP-конфиг команды и вызовы через LLM-шлюз."""
    agents = {}
    for cfg in mcp:
        for a in cfg["agents"]:
            declared = {k: v for k, v in a.items() if k != "account"}
            agents[a["key"]] = {**declared, "team": cfg["team"], "source": "mcp", "last_call": "",
                                "accounts": {a["account"]}}
    for r in log:
        a = agents.get(r["agent"])
        if a is None:
            # в журнале шлюза команды нет, она берётся из ключа agt-<команда>-NN
            parts = r["agent"].split("-")
            a = agents[r["agent"]] = {"key": r["agent"], "team": parts[1] if len(parts) > 2 else "?",
                                      "capability": None, "servers": [], "source": "log",
                                      "last_call": "", "accounts": set()}
        # учётка из журнала может отличаться от заявленной в MCP-конфиге, сверяются все
        a["accounts"].add(r["account"])
        a["last_call"] = max(a["last_call"], r["date"])
    return agents


def via_gateway(url, gateway):
    """Шлюз определяется схемой, хостом и портом: тот же хост на другом порту — другой сервис."""
    try:
        port = url.port or GATEWAY_PORT
    except ValueError:
        return False
    return url.scheme == "https" and url.hostname == gateway and port == GATEWAY_PORT


def audit(repository, agents, accounts):
    apps = {a.get("runtime_key"): a for a in repository["applications"] if a.get("runtime_key")}
    hosts = {a["host"]: a["id"] for a in repository["applications"]}
    gateway = repository["standards"]["mcp_gateway"].lower()
    border = (AUDIT_DATE - timedelta(days=ZOMBIE_DAYS)).isoformat()

    # возможность берётся из записи репозитория, даже если тип у записи неверный
    teams_by_cap = defaultdict(set)
    for key, a in agents.items():
        if key in apps:
            a["capability"] = apps[key]["capability"]
        if a["capability"]:
            teams_by_cap[a["capability"]].add(a["team"])
    # возможное пересечение: одну бизнес-возможность закрывают агенты двух и более команд
    dup_caps = {c: sorted(t) for c, t in sorted(teams_by_cap.items()) if len(t) > 1}

    for key, a in agents.items():
        app = apps.get(key)
        # технический владелец из MCP-конфига бизнес-владельцем не считается
        owner = (app and app["business_owner"]) or a.get("business_owner")
        accs = [accounts.get(n, UNKNOWN_ACCOUNT) for n in a["accounts"] - {"", None}] or [UNKNOWN_ACCOUNT]
        # локальный MCP через stdio адреса не имеет и этой проверкой не покрывается
        direct = [u for u in (urlparse(s.get("url") or "") for s in a["servers"] if "command" not in s)
                  if not via_gateway(u, gateway)]
        # нет записи, запись с другим типом (агента не описывает) или заведён как AI-агент
        a["registration"] = "missing" if app is None else (
            "ai-agent" if app["type"] == "ai-agent" else "wrong_type")
        a["errors"] = {
            1: a["registration"] != "ai-agent",
            2: not owner,
            3: any(acc["kind"] != "service" for acc in accs),
            4: bool(direct),
            5: a["capability"] in dup_caps,
            # нет вызовов в журнале вовсе — активность неизвестна, это не то же, что «молчит»
            6: "" < a["last_call"] < border and any(acc["enabled"] != "no" for acc in accs),
        }
        a["direct_connections"] = len(direct)
        # тот же хост шлюза на чужом порту показывается с портом, иначе — системой из репозитория
        a["direct_targets"] = sorted({hosts.get(u.hostname, u.netloc) for u in direct})
    return dup_caps


def main():
    repository, mcp, accounts, log = load()
    rep = check_repository(repository)
    agents = discover(mcp, log)
    dup_caps = audit(repository, agents, accounts)
    total = len(agents)
    n = Counter(i for a in agents.values() for i, e in a["errors"].items() if e)
    src = Counter(a["source"] for a in agents.values())
    caps = {c["id"]: c["name"] for c in repository["capabilities"]}

    print("Архитектурный репозиторий (data/repository.json)")
    print(f"  приложений: {rep['apps']}, из них с типом ai-agent: {rep['agents']}")
    print(f"  с бизнес-владельцем: {rep['with_owner']} из {rep['apps']}")
    print(f"  интеграций по стандарту: {rep['by_standard']} из {rep['integrations']}")
    print()
    print("Фактические следы (data/runtime)")
    print(f"  агентов найдено: {total}, команд: {len({a['team'] for a in agents.values()})}")
    print(f"  из MCP-конфигов: {src['mcp']}, только из журнала LLM-шлюза: {src['log']}")
    print()
    reg = Counter(a["registration"] for a in agents.values())
    print(f"Ошибка 1. Агент не заведён как AI-агент: {n[1]} из {total}; "
          f"записи нет у {reg['missing']}, записаны с другим типом {reg['wrong_type']}")
    print(f"Ошибка 2. Нет бизнес-владельца: {n[2]} из {total}")
    print(f"Ошибка 3. Работает под учётной записью человека или неизвестной: {n[3]} из {total}")
    direct = [a for a in agents.values() if a["errors"][4]]
    targets = sorted({t for a in direct for t in a["direct_targets"]})
    print(f"Ошибка 4. MCP напрямую, мимо шлюза: {len(direct)} из {total}, "
          f"{sum(a['direct_connections'] for a in direct)} подключений к {len(targets)} системам")
    print(f"Ошибка 5. Возможное пересечение, одну возможность закрывают агенты разных команд: "
          f"возможностей {len(dup_caps)}, агентов в них {n[5]}")
    for c, teams in dup_caps.items():
        print(f"    {c} {caps.get(c, 'нет в репозитории')}: {', '.join(teams)}")
    print(f"Ошибка 6. Не работает больше {ZOMBIE_DAYS} дней, а учётка не отключена: {n[6]} из {total}")
    print()
    clean = sum(not any(a["errors"].values()) for a in agents.values())
    print(f"Хотя бы одна ошибка: {total - clean} из {total}, без ошибок: {clean}")

    if "--details" in sys.argv:
        print()
        print("агент                ошибки        последний вызов  прямые MCP")
        for key in sorted(agents):
            a = agents[key]
            errs = ",".join(str(i) for i, e in a["errors"].items() if e) or "-"
            print(f"{key:<20} {errs:<13} {a['last_call'] or '-':<16} "
                  f"{', '.join(a['direct_targets']) or '-'}")


if __name__ == "__main__":
    main()
