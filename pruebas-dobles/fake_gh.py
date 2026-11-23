#!/usr/bin/env python3
"""Doble de `gh` (REST + GraphQL de Projects v2) para probar sin GitHub. Estado en FAKE_GH_STATE.

Admite varios repos y varios proyectos. La CI se simula por repo con s["ci"][repo] = "success" | "failure".
Los repos nuevos se crean como bare en FAKE_GH_REMOTOS/<nombre>.git y git los alcanza con url.insteadOf.
"""
import base64, json, os, re, subprocess, sys

ST = os.environ["FAKE_GH_STATE"]
LOGIN = os.environ.get("FAKE_GH_LOGIN", "oscar")
ESTADO_OPC = ["Backlog", "Planning", "To Do", "Doing", "Testing / Review", "Done", "PRO"]
PRIO_OPC = ["P0 urgente", "P1 alta", "P2 normal", "P3 baja"]


def load():
    s = json.load(open(ST)) if os.path.exists(ST) else {}
    for k, v in {"issues": {}, "prs": [], "n": {}, "calls": [], "projects": {}, "deployments": [], "alerts": [],
                 "runs": [], "default_branch": "main", "seq": 0, "clock": 0, "ci": {}, "repos": {},
                 "workflows": {}, "secrets": {}, "issue_ids": {}}.items():
        s.setdefault(k, v)
    return s


def save(s):
    json.dump(s, open(ST, "w"), indent=1)


def opt(args, name, multi=False):
    vals = [args[i + 1] for i, a in enumerate(args) if a == name and i + 1 < len(args)]
    return vals if multi else (vals[0] if vals else None)


def body(args):
    bf = opt(args, "--body-file")
    return sys.stdin.read() if bf == "-" else (open(bf).read() if bf else opt(args, "--body") or "")


def repo_de(args):
    return opt(args, "--repo") or os.environ.get("FAKE_GH_REPO", "oscar/equipo-ia-lab-ensayo")


def nuevo_id(s, pref):
    s["seq"] += 1
    return f"{pref}_{s['seq']}"


def ahora(s):
    s["clock"] += 1
    return f"2026-11-22T10:{s['clock'] // 60:02d}:{s['clock'] % 60:02d}Z"


def siguiente(s, repo):
    s["n"][repo] = s["n"].get(repo, 0) + 1
    return s["n"][repo]


def clave(repo, n):
    return f"{repo}#{n}"


def issue_json(s, i):
    return {"id": i["id"], "number": i["number"], "title": i["title"], "body": i["body"], "state": i["state"],
            "labels": [{"name": l} for l in i["labels"]], "author": {"login": i["author"]}, "createdAt": i["createdAt"],
            "comments": [{"body": c} for c in i.get("comments", [])],
            "closedByPullRequestsReferences": [{"number": p["number"]} for p in s["prs"]
                                               if p["repo"] == i["repo"] and i["number"] in p.get("closes", []) and p.get("merged")]}


def remoto(repo):
    return os.path.join(os.environ.get("FAKE_GH_REMOTOS", "/tmp"), repo.split("/")[1] + ".git")


def head_sha(repo, rama):
    r = subprocess.run(["git", "ls-remote", remoto(repo), f"refs/heads/{rama}"], capture_output=True, text=True)
    return r.stdout.split()[0] if r.stdout.strip() else None


def checks(s, p):
    estado = s["ci"].get(p["repo"])
    if not estado:
        return p.get("checks", [])
    return [{"name": n, "status": "COMPLETED", "conclusion": estado.upper(),
             "detailsUrl": f"https://github.com/{p['repo']}/actions/runs/77/job/1"}
            for n in s["workflows"].get(p["repo"], {}).get("checks", ["tests"])]


def campos_proyecto():
    return [{"id": "F_Status", "name": "Status", "dataType": "SINGLE_SELECT", "options": []},
            {"id": "F_Estado", "name": "Estado", "dataType": "SINGLE_SELECT", "options": [{"id": "O_" + o, "name": o} for o in ESTADO_OPC]},
            {"id": "F_Prioridad", "name": "Prioridad", "dataType": "SINGLE_SELECT", "options": [{"id": "O_" + o, "name": o} for o in PRIO_OPC]},
            {"id": "F_Bloqueo", "name": "Bloqueo", "dataType": "TEXT"}]


def vista_json(v):
    """Vista guardada en el estado → ProjectV2View. `agrupar` (lista de nombres de campo) simula Column by."""
    return {"name": v["name"], "layout": v["layout"],
            "verticalGroupByFields": {"nodes": [{"name": n} for n in v.get("agrupar", [])]}}


def graphql(s, a):
    q = next((x[6:] for x in opt(a, "-f", True) if x.startswith("query=")), "")
    v = {}
    for k in ("-f", "-F"):
        for val in opt(a, k, True):
            if not val.startswith("query="):
                kk, vv = val.split("=", 1)
                v[kk] = vv
    if "projectV2(number" in q:
        raiz = "organization" if "organization(" in q else "user"
        p = s["projects"].get(str(v["numero"]))
        ok = p and p["owner"] == v["owner"]
        return {raiz: {"projectV2": {"id": f"PVT_{v['numero']}"} if ok else None}}
    p = s["projects"][(v.get("id") or v.get("p")).split("_")[1]]
    if "fields(first" in q:
        return {"node": {"title": p["title"], "url": p["url"], "public": False,
                         "fields": {"nodes": campos_proyecto()}, "views": {"nodes": [vista_json(x) for x in p.get("views", [])]}}}
    if "items(first" in q:
        nodes = []
        for iid, it in p["items"].items():
            fvs = [{("text" if n == "Bloqueo" else "name"): val, "field": {"name": n}}
                   for n, val in it["fields"].items() if val not in (None, "")]
            iss = s["issues"].get(it.get("issue", ""))
            contenido = {} if not iss else {
                "id": iss["id"], "number": iss["number"], "title": iss["title"], "body": iss["body"],
                "createdAt": iss["createdAt"], "state": iss["state"], "url": f"https://github.com/{iss['repo']}/issues/{iss['number']}",
                "author": {"login": iss["author"]}, "repository": {"nameWithOwner": iss["repo"]},
                "labels": {"nodes": [{"name": l} for l in iss["labels"]]}}
            nodes.append({"id": iid, "fieldValues": {"nodes": fvs}, "content": contenido})
        return {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}
    if "updateProjectV2ItemFieldValue" in q:
        campo = v["f"].split("_", 1)[1]
        valor = v["o"].split("_", 1)[1] if "o" in v else v["t"]
        if campo == "Estado" and os.environ.get("FAKE_GH_FALLA_MOVER") == valor:
            print("HTTP 502: fallo simulado al escribir Estado", file=sys.stderr)
            sys.exit(1)
        p["items"][v["i"]]["fields"][campo] = valor
        return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": v["i"]}}}
    if "clearProjectV2ItemFieldValue" in q:
        p["items"][v["i"]]["fields"][v["f"].split("_", 1)[1]] = None
        return {"clearProjectV2ItemFieldValue": {"projectV2Item": {"id": v["i"]}}}
    if "addProjectV2ItemById" in q:
        k = s["issue_ids"][v["c"]]
        for iid, it in p["items"].items():
            if it.get("issue") == k:
                return {"addProjectV2ItemById": {"item": {"id": iid}}}
        iid = nuevo_id(s, "PVTI")
        p["items"][iid] = {"issue": k, "fields": {}}
        return {"addProjectV2ItemById": {"item": {"id": iid}}}
    if "addProjectV2DraftIssue" in q:
        iid = nuevo_id(s, "PVTI")
        p["items"][iid] = {"draft": True, "fields": {}}
        return {"addProjectV2DraftIssue": {"projectItem": {"id": iid}}}
    if "deleteProjectV2Item" in q:
        p["items"].pop(v["i"], None)
        return {"deleteProjectV2Item": {"deletedItemId": v["i"]}}
    raise SystemExit("graphql no soportado: " + q[:80])


def api(s, a):
    posicionales, i = [], 1
    while i < len(a):
        if a[i] in ("-X", "-f", "-F", "--jq", "--input"):
            i += 2
            continue
        if not a[i].startswith("-"):
            posicionales.append(a[i])
        i += 1
    ruta = posicionales[0]
    metodo = opt(a, "-X") or "GET"
    if ruta == "graphql":
        return {"data": graphql(s, a)}
    if ruta == "user":
        return {"login": LOGIN}
    m = re.match(r"repos/([^/]+/[^/?]+)/?(.*)", ruta)
    repo, sub = m.group(1), m.group(2)
    if sub == "":
        return {"full_name": repo, "default_branch": s["repos"].get(repo, {}).get("rama", "main"), "private": True}
    if sub == "readme":
        texto = s["repos"].get(repo, {}).get("readme") or (
            f"# {repo}\n\nProyecto de prueba con una descripción suficientemente larga para el panel.\n\n> Estado: en pruebas.\n")
        return {"content": base64.b64encode(texto.encode()).decode(), "html_url": f"https://github.com/{repo}#readme"}
    if sub.startswith("dependabot/alerts"):
        if os.environ.get("FAKE_GH_ALERTS_ERROR"):
            print("HTTP 403: Resource not accessible", file=sys.stderr); sys.exit(1)
        return [x for x in s["alerts"] if x.get("repo", repo) == repo]
    if sub.startswith("deployments/") and "statuses" in sub:
        did = int(sub.split("/")[1])
        d = next(x for x in s["deployments"] if x["id"] == did)
        return [{"state": st, "log_url": "https://simulado"} for st in reversed(d["statuses"])]
    if sub.startswith("deployments?"):
        env = re.search(r"environment=([^&]+)", sub).group(1)
        return [d for d in reversed(s["deployments"]) if d["environment"] == env]
    if sub.startswith("actions/workflows?"):
        w = s["workflows"].get(repo)
        return {"workflows": [{"id": 1, "name": "Backend Tests", "path": w["path"], "state": "active"}] if w else []}
    if sub.startswith("actions/workflows/"):
        return {"workflow_runs": s["runs"]}
    if sub.startswith("actions/runs?"):
        w = s["workflows"].get(repo)
        if not w:
            return {"workflow_runs": []}
        return {"workflow_runs": [{"id": 77, "workflow_id": 1, "path": w["path"], "name": "Backend Tests",
                                   "status": "completed", "conclusion": w.get("main", "success"),
                                   "html_url": f"https://github.com/{repo}/actions/runs/77", "updated_at": "2026-11-22T10:00:00Z"}]}
    if re.match(r"actions/runs/\d+/jobs", sub):
        return {"jobs": [{"name": n} for n in s["workflows"].get(repo, {}).get("checks", [])]}
    if sub.startswith("actions/secrets"):
        return {"secrets": [{"name": n} for n in s["secrets"].get(repo, [])]}
    if sub.startswith("vulnerability-alerts"):
        if metodo == "PUT":
            return None
        print("HTTP/2.0 204 No Content"); return None
    if "/permission" in sub:
        return {"permission": "admin"}
    raise SystemExit("api no soportada: " + ruta)


def jq(out, expr):
    if expr == ".id":
        return out["id"]
    if expr == ".login":
        return out["login"]
    if expr == ".secrets[].name":
        return "\n".join(x["name"] for x in out["secrets"])
    if expr == "{default_branch}":
        return json.dumps({"default_branch": out["default_branch"]})
    return json.dumps(out)


a = sys.argv[1:]
import fcntl
_cerrojo = open(ST + ".lock", "w")
fcntl.flock(_cerrojo, fcntl.LOCK_EX)  # el panel consulta en paralelo: serializa el acceso al estado
s = load()
s["calls"].append(" ".join(a[:3]))
out, texto = None, None
if a[:1] == ["api"]:
    out = api(s, a)
    if opt(a, "--jq") and out is not None:
        texto, out = jq(out, opt(a, "--jq")), None
elif a[:2] == ["auth", "status"]:
    texto = f"github.com\n  ✓ Logged in to github.com account {LOGIN}\n  - Token scopes: 'project', 'repo'"
elif a[:2] in (["label", "create"], ["variable", "set"], ["project", "field-create"]):
    pass
elif a[:2] == ["project", "link"]:
    s["projects"][a[2]].setdefault("links", []).append(opt(a, "--repo"))
elif a[:2] == ["repo", "view"]:
    if "defaultBranchRef" in (opt(a, "--json") or ""):
        out = {"defaultBranchRef": {"name": s["default_branch"]}}
    else:
        sys.exit(1)
elif a[:2] == ["repo", "create"]:
    repo = a[2]
    subprocess.run(["git", "init", "-q", "--bare", remoto(repo)], check=True)
    subprocess.run(["git", "config", "--global", f"url.{remoto(repo)}.insteadOf", f"https://github.com/{repo}.git"], check=True)
    s["repos"][repo] = {"rama": "main", "readme": f"# {repo}\n\n{opt(a, '--description')} — creado desde el panel del equipo.\n"}
elif a[:2] == ["repo", "list"]:
    out = [{"nameWithOwner": r, "description": "", "isPrivate": True, "pushedAt": ""} for r in s["repos"]]
elif a[:2] == ["project", "list"]:
    out = {"projects": list(s["projects"].values())}
elif a[:2] == ["project", "create"]:
    n = str(len(s["projects"]) + 1)
    s["projects"][n] = {"number": int(n), "title": opt(a, "--title"),
                        "owner": LOGIN if opt(a, "--owner") == "@me" else opt(a, "--owner"),
                        "url": f"https://github.com/users/{LOGIN}/projects/{n}", "items": {},
                        "views": [{"name": "View 1", "layout": "TABLE_LAYOUT"}]}
    out = {k: s["projects"][n][k] for k in ("number", "title", "url")}
elif a[:2] == ["project", "copy"]:
    origen = s["projects"][a[2]]
    n = str(len(s["projects"]) + 1)
    s["projects"][n] = {"number": int(n), "title": opt(a, "--title"),
                        "owner": LOGIN if opt(a, "--target-owner") == "@me" else opt(a, "--target-owner"),
                        "url": f"https://github.com/users/{LOGIN}/projects/{n}", "items": {},
                        "views": list(origen.get("views", [])), "copiado_de": a[2]}
    out = {k: s["projects"][n][k] for k in ("number", "title", "url")}
elif a[:2] == ["issue", "create"]:
    repo = repo_de(a)
    n = siguiente(s, repo)
    k = clave(repo, n)
    s["seq"] += 1
    iid = f"I_{s['seq']}"
    s["issue_ids"][iid] = k
    s["issues"][k] = {"id": iid, "repo": repo, "number": n, "title": opt(a, "--title"), "body": body(a), "state": "OPEN",
                      "labels": opt(a, "--label", True), "assignees": opt(a, "--assignee", True),
                      "author": os.environ.get("FAKE_GH_AUTHOR", LOGIN), "comments": [], "createdAt": ahora(s)}
    texto = f"https://github.com/{repo}/issues/{n}"
elif a[:2] == ["issue", "list"]:
    repo, lab, st = repo_de(a), opt(a, "--label"), (opt(a, "--state") or "open").upper()
    out = [issue_json(s, i) for i in s["issues"].values()
           if i["repo"] == repo and (st == "ALL" or i["state"] == st) and (not lab or lab in i["labels"])]
elif a[:2] == ["issue", "view"]:
    out = issue_json(s, s["issues"][clave(repo_de(a), int(a[2]))])
elif a[:2] == ["issue", "edit"]:
    i = s["issues"][clave(repo_de(a), int(a[2]))]
    for l in opt(a, "--remove-label", True):
        i["labels"].remove(l)
    for l in opt(a, "--add-label", True):
        if l not in i["labels"]:
            i["labels"].append(l)
    if opt(a, "--body-file"):
        i["body"] = body(a)
elif a[:2] == ["issue", "comment"]:
    s["issues"][clave(repo_de(a), int(a[2]))]["comments"].append(body(a))
elif a[:2] == ["pr", "list"]:
    repo, h, autor, st = repo_de(a), opt(a, "--head"), opt(a, "--author"), (opt(a, "--state") or "open").upper()
    out = [{"number": p["number"], "url": p["url"], "state": p["state"], "title": p["title"],
            "createdAt": "2026-11-01T00:00:00Z", "statusCheckRollup": checks(s, p)} for p in s["prs"]
           if p["repo"] == repo and (not h or p["head"] == h) and (not autor or p.get("author") == autor)
           and (st == "ALL" or p["state"] == st)]
elif a[:2] == ["pr", "view"]:
    ref = a[2]
    p = next(p for p in s["prs"] if p["url"] == ref or (str(p["number"]) == ref and p["repo"] == repo_de(a)))
    out = {"number": p["number"], "url": p["url"], "state": p["state"], "baseRefName": p["base"],
           "isDraft": p.get("draft", False), "headRefOid": head_sha(p["repo"], p["head"]),
           "mergedAt": "2026-11-22T12:00:00Z" if p.get("merged") else None,
           "mergeCommit": {"oid": p["merge_oid"]} if p.get("merged") else None,
           "closingIssuesReferences": [{"number": n} for n in p.get("closes", [])],
           "statusCheckRollup": checks(s, p)}
elif a[:2] == ["pr", "create"]:
    repo = repo_de(a)
    n = siguiente(s, repo)
    b = body(a)
    s["prs"].append({"repo": repo, "number": n, "url": f"https://github.com/{repo}/pull/{n}", "state": "OPEN",
                     "head": opt(a, "--head"), "base": opt(a, "--base"), "title": opt(a, "--title"), "body": b,
                     "draft": "--draft" in a, "closes": [int(x) for x in re.findall(r"Closes #(\d+)", b)]})
    texto = s["prs"][-1]["url"]
elif a[:2] in (["pr", "edit"], ["pr", "ready"]):
    for p in s["prs"]:
        if str(p["number"]) == a[2] and p["repo"] == repo_de(a):
            if a[1] == "edit":
                p["body"] = body(a)
            else:
                p["draft"] = False
elif a[:2] == ["run", "view"] and "--log-failed" in a:
    texto = "tests\tRun phpunit\tFAILURES!\ntests\tRun phpunit\tBudgetTest::testLimite: Failed asserting that 90 is 100."
else:
    print("fake gh: no soportado", a, file=sys.stderr)
    sys.exit(2)
save(s)
if texto is not None:
    print(texto)
elif out is not None:
    print(json.dumps(out))
