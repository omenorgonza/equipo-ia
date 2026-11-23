#!/usr/bin/env python3
"""Instalación en GitHub y ensayos de aceptación del tablero y el mantenimiento.

  instalar-github   Sube workflows + .equipo-ia al repo del piloto, activa Dependabot y fija variables.
  prioridad         P0 en Backlog y P1/P2 en To Do (mismo agente): sale P1 antes que P2; P0 intacta.
  bloqueo           P1 bloqueada y P2 elegible: se ejecuta P2; P1 conserva la causa.
  reinicio          Caída tras reservar y tras crear la PR: sin duplicar ejecución, rama, PR ni tarjeta.
  aviso-duplicado   Mismo aviso simulado dos veces: una propuesta; evidencia nueva la actualiza; nadie la ejecuta.
  aviso-critico     Destinatario, canal y configuración + recorrido con aviso simulado.
  remoto            Workflow con el coordinador parado: crea/actualiza la propuesta y deja registro;
                    al volver, el coordinador recoge lo que Óscar autorice.
  pro               Despliegue fallido, correcto, movimiento manual y reversión.
  todos             Todo en orden.

En modo real (por defecto) los pasos de GitHub Actions se disparan con `gh workflow run` y se espera
su resultado. Con `"simular_actions": true` en config.json (pruebas sin red) se ejecutan los mismos
scripts en local contra el GitHub simulado.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB / "repo-plantilla" / ".equipo-ia"))
import tablero_lib as T  # noqa: E402
import coordinador as C  # noqa: E402
import ensayo as E  # noqa: E402

RES = C.ESTADO / "ensayo-tablero.json"


def anotar(clave: str, tipo: str, ok: bool, evidencia: str) -> None:
    """tipo: verificado | simulado | pendiente."""
    r = json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else {}
    r[clave] = {"tipo": tipo, "ok": ok, "evidencia": evidencia, "cuando": C.ahora()}
    C.ESTADO.mkdir(parents=True, exist_ok=True)
    RES.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{'OK   ' if ok else 'FALLO'} [{tipo}] {clave}: {evidencia}")


def cfg_y_tablero():
    cfg = C.cargar_config()
    tb = cfg["tablero"]
    return cfg, T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), cfg["gh_bin"])


def gh(cfg, *args, stdin_text=None, comprobar=True) -> str:
    r = C.ejecutar(cfg["gh_bin"] + list(args), cwd=LAB, timeout=300, stdin_text=stdin_text)
    if comprobar and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def tarea(cfg, t, titulo, agente, estado, prioridad, archivo, bloqueo="") -> int:
    base = C.Git(cfg).rama_por_defecto()
    cuerpo = E.cuerpo(f"Crea el archivo {archivo} con el título '# Hecho por el equipo'. Nada más.", agente, base,
                      "_No response_", archivo, f"- Existe {archivo} con el título indicado", "docs-tarea")
    n = E.crear_issue(cfg, titulo, agente, cuerpo)
    nodo = json.loads(gh(cfg, "issue", "view", str(n), "--repo", cfg["repo"], "--json", "id"))["id"]
    item = t.anadir(nodo)
    t.mover(item, estado)
    t.poner_opcion(item, T.CAMPO_PRIORIDAD, T.prioridad_por_codigo(prioridad))
    if bloqueo:
        t.poner_texto(item, T.CAMPO_BLOQUEO, bloqueo)
    # quitar `ready` que añade crear_issue: en modo tablero el estado vive solo en el tablero
    gh(cfg, "issue", "edit", str(n), "--repo", cfg["repo"], "--remove-label", "ready", comprobar=False)
    return n


def item(t, cfg, n) -> dict:
    return t.item_de_issue(cfg["repo"], n) or {}


def coord(*args) -> str:
    return E.coord(*args, comprobar=False)


# --------------------------------------------------------------------------- Actions (real o local)

def accion(cfg, workflow: str, script: list[str], inputs: dict | None = None, env_extra: dict | None = None) -> str:
    """Ejecuta un paso de Actions: en real dispara el workflow y espera; en simulado corre el script."""
    if cfg.get("simular_actions"):
        clon = (C.PD / cfg["clon_local"]).resolve()
        env = dict(os.environ, GITHUB_REPOSITORY=cfg["repo"], EQUIPO_IA_GH_BIN=json.dumps(C.resolver_bin(cfg["gh_bin"])),
                   TABLERO_OWNER=cfg["tablero"]["owner"], TABLERO_NUMERO=str(cfg["tablero"]["numero"]),
                   EQUIPO_IA_SALIDA=str(C.ESTADO / "resumen-mantenimiento.json"), **(env_extra or {}))
        r = C.ejecutar(["{python}", str(clon / ".equipo-ia" / script[0]), *script[1:]], cwd=clon, timeout=600, env=env)
        print((r.stdout + r.stderr)[-2500:])
        return f"local:{script[0]} código {r.returncode}"
    antes = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    args = ["workflow", "run", workflow, "--repo", cfg["repo"]]
    for k, v in (inputs or {}).items():
        args += ["-f", f"{k}={v}"]
    gh(cfg, *args)
    run = None
    for _ in range(60):
        time.sleep(5)
        runs = json.loads(gh(cfg, "run", "list", "--repo", cfg["repo"], "--workflow", workflow, "--limit", "5",
                             "--json", "databaseId,createdAt,url,status,conclusion,event"))
        nuevos = [r for r in runs if r["createdAt"] >= antes and r["event"] == "workflow_dispatch"]
        if nuevos:
            run = nuevos[0]
            break
    if not run:
        raise RuntimeError(f"No aparece la ejecución de {workflow}")
    C.ejecutar(cfg["gh_bin"] + ["run", "watch", str(run["databaseId"]), "--repo", cfg["repo"]], timeout=1800)
    fin = json.loads(gh(cfg, "run", "view", str(run["databaseId"]), "--repo", cfg["repo"], "--json", "conclusion,url"))
    print(f"{workflow}: {fin['conclusion']} {fin['url']}")
    return f"{fin['url']} ({fin['conclusion']})"


# --------------------------------------------------------------------------- instalación

def cmd_instalar_github(_a) -> None:
    cfg = C.cargar_config()
    clon = (C.PD / cfg["clon_local"]).resolve()
    origen = LAB / "repo-plantilla"
    for p in origen.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            destino = clon / p.relative_to(origen)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(p, destino)
    mj = clon / ".equipo-ia" / "mantenimiento.json"
    m = json.loads(mj.read_text(encoding="utf-8"))
    m["repo"] = cfg["repo"]
    m["tablero"] = {k: cfg["tablero"][k] for k in ("owner", "numero", "owner_tipo")}
    mj.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.copy(LAB / "plantillas" / "tarea-agente.yml", clon / ".github" / "ISSUE_TEMPLATE" / "tarea-agente.yml")
    git = lambda *x, **k: E.git(cfg, *x, **k)  # noqa: E731
    git("checkout", C.Git(cfg).rama_por_defecto())
    git("pull", "--ff-only", comprobar=False)
    git("add", "-A")
    if git("status", "--porcelain"):
        git("commit", "-m", "Tablero, mantenimiento programado, Done/PRO y Dependabot")
        git("push")
    if not cfg.get("simular_actions"):
        gh(cfg, "api", "-X", "PUT", f"repos/{cfg['repo']}/vulnerability-alerts", comprobar=False)
        gh(cfg, "api", "-X", "PUT", f"repos/{cfg['repo']}/automated-security-fixes", comprobar=False)
        gh(cfg, "variable", "set", "TABLERO_OWNER", "--repo", cfg["repo"], "--body", cfg["tablero"]["owner"])
        gh(cfg, "variable", "set", "TABLERO_NUMERO", "--repo", cfg["repo"], "--body", str(cfg["tablero"]["numero"]))
        secretos = gh(cfg, "secret", "list", "--repo", cfg["repo"], comprobar=False)
        if "TABLERO_TOKEN" not in secretos:
            print("\nFALTA el secreto TABLERO_TOKEN (token clásico con scopes `repo` y `project`):\n"
                  f"  gh secret set TABLERO_TOKEN --repo {cfg['repo']}\n")
    p = C.PD / "config.json"
    c = json.loads(p.read_text(encoding="utf-8"))
    c["pruebas"]["docs-tarea"] = ["{python}", "-c", "import glob,sys; sys.exit(0 if glob.glob('docs/*.md') else 1)"]
    c.setdefault("autores_autorizados", [c.get("autor_autorizado", "")])
    p.write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Instalado en GitHub: workflows pruebas, tablero-pr, tablero-issue, mantenimiento, despliegue, aviso-critico; dependabot.yml.")


# --------------------------------------------------------------------------- ensayos

def cmd_prioridad(_a) -> None:
    cfg, t = cfg_y_tablero()
    p2 = tarea(cfg, t, "Prioridad P2 (más antigua)", "local", T.TODO, "P2", "docs/prio-p2.md")
    p1 = tarea(cfg, t, "Prioridad P1", "local", T.TODO, "P1", "docs/prio-p1.md")
    p0 = tarea(cfg, t, "Prioridad P0 en Backlog", "local", T.BACKLOG, "P0", "docs/prio-p0.md")
    coord("una-vez")
    e1, e2, e0 = item(t, cfg, p1)["estado"], item(t, cfg, p2)["estado"], item(t, cfg, p0)["estado"]
    paso1 = e1 == T.REVIEW and e2 == T.TODO and e0 == T.BACKLOG
    coord("una-vez")
    e2b, e0b = item(t, cfg, p2)["estado"], item(t, cfg, p0)["estado"]
    tocada = C.obtener(C.db(), cfg["repo"], p0) is not None
    anotar("prioridad", "verificado" if not cfg.get("simular_actions") else "simulado",
           paso1 and e2b == T.REVIEW and e0b == T.BACKLOG and not tocada,
           f"1.ª pasada: P1 #{p1}={e1}, P2 #{p2}={e2}, P0 #{p0}={e0}; 2.ª: P2={e2b}, P0={e0b}; P0 en registro={tocada}")


def cmd_issue_al_tablero(_a) -> None:
    """Issue creada fuera del tablero → tablero-issue.yml la pone en Planning con su prioridad; si ya está colocada, no la toca."""
    cfg, t = cfg_y_tablero()
    cuerpo = "Issue creada sin pasar por el tablero (móvil u otra sesión)."
    suelta = int(gh(cfg, "issue", "create", "--repo", cfg["repo"], "--title", "Issue suelta (al tablero)",
                    "--label", "prioridad:p1", "--body-file", "-", stdin_text=cuerpo).strip().rstrip("/").split("/")[-1])
    colocada = tarea(cfg, t, "Issue ya colocada en To Do", "local", T.TODO, "P3", "docs/colocada.md")
    simulado = bool(cfg.get("simular_actions"))
    if simulado:
        for n in (suelta, colocada):
            accion(cfg, "tablero-issue.yml", ["sincronizar.py", "issue-abierta", "--issue", str(n), "--espera", "0"])
    for _ in range(1 if simulado else 24):  # en real, el workflow se dispara solo al abrir la issue
        a = item(t, cfg, suelta)
        if a.get("estado"):
            break
        time.sleep(5)
    a, b = item(t, cfg, suelta), item(t, cfg, colocada)
    anotar("issue-al-tablero", "simulado" if simulado else "verificado",
           a.get("estado") == T.PLANNING and a.get("prioridad") == "P1 alta" and b.get("estado") == T.TODO,
           f"suelta #{suelta}: {a.get('estado')}/{a.get('prioridad')}; colocada #{colocada}: {b.get('estado')}")


def cmd_bloqueo(_a) -> None:
    cfg, t = cfg_y_tablero()
    p1 = tarea(cfg, t, "P1 bloqueada", "local", T.TODO, "P1", "docs/bloq-p1.md",
               bloqueo="Esperando credenciales del entorno de pruebas (ensayo)")
    p2 = tarea(cfg, t, "P2 elegible", "local", T.TODO, "P2", "docs/bloq-p2.md")
    coord("una-vez")
    i1, i2 = item(t, cfg, p1), item(t, cfg, p2)
    anotar("bloqueo", "verificado" if not cfg.get("simular_actions") else "simulado",
           i2["estado"] == T.REVIEW and i1["estado"] == T.TODO and "credenciales" in i1["bloqueo"],
           f"P2 #{p2}={i2['estado']}; P1 #{p1}={i1['estado']} bloqueo='{i1['bloqueo']}'")


def cmd_reinicio(_a) -> None:
    cfg, t = cfg_y_tablero()
    n = tarea(cfg, t, "Reinicio tras reservar y tras PR", "local", T.TODO, "P1", "docs/reinicio.md")
    coord("una-vez", "--detener-tras", "reservada")
    tras_reserva = (item(t, cfg, n)["estado"], C.obtener(C.db(), cfg["repo"], n)["estado"])
    coord("una-vez", "--detener-tras", "pr")
    tras_pr = (item(t, cfg, n)["estado"], C.obtener(C.db(), cfg["repo"], n)["paso"])
    coord("una-vez")
    coord("una-vez")
    f = C.obtener(C.db(), cfg["repo"], n)
    ramas, prs = E.contar(cfg, n)
    tarjetas = sum(1 for it in t.items() if it["numero"] == n and it["repo"].lower() == cfg["repo"].lower())
    ejecuciones = len(list((C.LOGS / f"issue-{n}").glob("*-agente-*.log")))
    ok = ramas == 1 and prs == 1 and tarjetas == 1 and ejecuciones == 1 and item(t, cfg, n)["estado"] == T.REVIEW
    anotar("reinicio", "verificado" if not cfg.get("simular_actions") else "simulado", ok,
           f"#{n}: tras reservar (tablero, registro)={tras_reserva}; tras PR={tras_pr}; final={f['estado']}; "
           f"ramas={ramas} PR={prs} tarjetas={tarjetas} ejecuciones del agente={ejecuciones}")


def propuesta_simulada(cfg) -> dict | None:
    issues = json.loads(gh(cfg, "issue", "list", "--repo", cfg["repo"], "--label", "mantenimiento", "--state", "all",
                           "--limit", "200", "--json", "number,body,title"))
    return next((i for i in issues if "GHSA-SIMU-0000-0001" in (i["body"] or "")), None)


def cmd_aviso_duplicado(_a) -> None:
    cfg, t = cfg_y_tablero()
    tipo = "simulado"
    r1 = accion(cfg, "mantenimiento.yml", ["mantenimiento.py", "--simulacion", "aviso"], {"simulacion": "aviso"})
    previa = propuesta_simulada(cfg)  # tras la 1.ª ejecución: a partir de aquí, nada debe comentarse
    base_coment = len(json.loads(gh(cfg, "issue", "view", str(previa["number"]), "--repo", cfg["repo"], "--json",
                                    "comments"))["comments"]) if previa else 0
    r2 = accion(cfg, "mantenimiento.yml", ["mantenimiento.py", "--simulacion", "aviso"], {"simulacion": "aviso"})
    p = propuesta_simulada(cfg)
    if not p:
        anotar("aviso-duplicado", tipo, False, f"no se creó la propuesta ({r1})")
        return
    n = p["number"]
    total = sum(1 for i in json.loads(gh(cfg, "issue", "list", "--repo", cfg["repo"], "--label", "mantenimiento",
                                         "--state", "all", "--limit", "200", "--json", "body"))
                if "GHSA-SIMU-0000-0001" in (i["body"] or ""))
    vista = json.loads(gh(cfg, "issue", "view", str(n), "--repo", cfg["repo"], "--json", "body,comments"))
    comentarios_1 = len(vista.get("comments", [])) - base_coment
    it = item(t, cfg, n)
    # Óscar escribe una nota y sube la prioridad: deben conservarse
    cuerpo = vista["body"].replace("_(se conservan en cada actualización)_", "Nota de Óscar: revisar con el TL el lunes.")
    gh(cfg, "issue", "edit", str(n), "--repo", cfg["repo"], "--body-file", "-", stdin_text=cuerpo)
    t.poner_opcion(it["item_id"], T.CAMPO_PRIORIDAD, "P1 alta")
    r3 = accion(cfg, "mantenimiento.yml", ["mantenimiento.py", "--simulacion", "aviso-modificado"],
                {"simulacion": "aviso-modificado"})
    vista2 = json.loads(gh(cfg, "issue", "view", str(n), "--repo", cfg["repo"], "--json", "body,comments"))
    it2 = item(t, cfg, n)
    coord("una-vez")
    sin_agente = C.obtener(C.db(), cfg["repo"], n) is None and item(t, cfg, n)["estado"] == T.PLANNING
    ok = (total == 1 and it["estado"] == T.PLANNING and comentarios_1 == 0 and "1.0.2" in vista2["body"]
          and "Nota de Óscar" in vista2["body"] and len(vista2.get("comments", [])) - base_coment == 1
          and it2["prioridad"] == "P1 alta" and it2["estado"] == T.PLANNING and sin_agente)
    anotar("aviso-duplicado", tipo, ok,
           f"propuesta #{n}: {total} issue(s) con la clave; tras 2 ejecuciones idénticas comentarios={comentarios_1}; "
           f"evidencia nueva → cuerpo con 1.0.2={'1.0.2' in vista2['body']}, nota conservada={'Nota de Óscar' in vista2['body']}, "
           f"comentarios nuevos={len(vista2.get('comments', [])) - base_coment}, prioridad={it2['prioridad']}, estado={it2['estado']}; "
           f"ningún agente la tomó={sin_agente}. Ejecuciones: {r1} · {r2} · {r3}")


def cmd_aviso_critico(_a) -> None:
    cfg, _t = cfg_y_tablero()
    r = accion(cfg, "aviso-critico.yml", ["aviso_critico.py"], env_extra={"DESTINATARIO": cfg["tablero"]["owner"]})
    issues = json.loads(gh(cfg, "issue", "list", "--repo", cfg["repo"], "--label", "simulado", "--state", "all",
                           "--limit", "20", "--json", "number,title"))
    avisos = [i for i in issues if "Aviso crítico de prueba" in i["title"]]
    anotar("aviso-critico-recorrido", "simulado", bool(avisos),
           f"aviso simulado #{avisos[0]['number'] if avisos else '-'} asignado a {cfg['tablero']['owner']}; {r}")
    anotar("aviso-critico-dependabot-real", "pendiente", True,
           "La notificación real de Dependabot llega cuando GitHub detecte la alerta de requests==2.31.0; "
           "confirma su recepción (correo/web) y anótalo en el aviso simulado")


def cmd_remoto(_a) -> None:
    cfg, t = cfg_y_tablero()
    parado = not C.LOCK_PATH.exists()
    r = accion(cfg, "mantenimiento.yml", ["mantenimiento.py", "--simulacion", "aviso"], {"simulacion": "aviso"})
    reg = json.loads(gh(cfg, "issue", "list", "--repo", cfg["repo"], "--label", "registro-mantenimiento", "--state", "all",
                        "--limit", "1", "--json", "number,body"))
    p = propuesta_simulada(cfg)
    # El TL completa la parte ejecutable y Óscar autoriza (To Do)
    vista = json.loads(gh(cfg, "issue", "view", str(p["number"]), "--repo", cfg["repo"], "--json", "body"))["body"]
    ejecutable = vista.split("## Para pasar a To Do")[0] + "## Para pasar a To Do (completado por el TL)\n\n" + E.cuerpo(
        "Crea el archivo docs/mantenimiento-simulado.md con el título '# Hecho por el equipo'. Nada más.", "local",
        C.Git(cfg).rama_por_defecto(), "_No response_", "docs/mantenimiento-simulado.md", "- Existe el archivo", "docs-tarea")
    gh(cfg, "issue", "edit", str(p["number"]), "--repo", cfg["repo"], "--body-file", "-", stdin_text=ejecutable)
    gh(cfg, "issue", "edit", str(p["number"]), "--repo", cfg["repo"], "--add-label", "agent:local")
    t.mover(item(t, cfg, p["number"])["item_id"], T.TODO)
    coord("una-vez")
    estado = item(t, cfg, p["number"])["estado"]
    ultima = ""
    if reg:
        ultima = next((l for l in reg[0]["body"].splitlines() if l.startswith("- Última ejecución correcta")), "")
    anotar("remoto-pc-parado", "simulado" if cfg.get("simular_actions") else "verificado",
           parado and bool(reg) and estado == T.REVIEW,
           f"coordinador parado durante el workflow={parado}; registro #{reg[0]['number'] if reg else '-'} «{ultima}»; "
           f"propuesta #{p['number']} autorizada → {estado}; {r}")


def cmd_pro(a) -> None:
    cfg, t = cfg_y_tablero()
    con = C.db()
    candidatas = [f for f in con.execute("SELECT * FROM tareas WHERE repo=? AND estado='revision' ORDER BY issue",
                                         (cfg["repo"],))]
    if len(candidatas) < 2:
        sys.exit("Necesito dos issues en Testing / Review con PR (ejecuta antes `prioridad`).")
    fa, fb = candidatas[0], candidatas[1]
    if not cfg.get("simular_actions"):
        if not a.si:
            input(f"Se integrarán en main las PR {fa['pr_url']} (y más tarde {fb['pr_url']}) del repo de ENSAYO. Intro para seguir…")
        gh(cfg, "pr", "merge", str(fa["pr_numero"]), "--repo", cfg["repo"], "--merge")
        time.sleep(30)  # tablero-pr.yml mueve a Done
    else:
        simular_merge(cfg, fa)
        accion(cfg, "tablero-pr.yml", ["sincronizar.py", "pr-cerrada", "--pr", str(fa["pr_numero"])])
    done_a = item(t, cfg, fa["issue"])["estado"]
    r_fallo = desplegar(cfg, "failure")
    tras_fallo = item(t, cfg, fa["issue"])["estado"]
    r_ok = desplegar(cfg, "success")
    tras_ok = item(t, cfg, fa["issue"])["estado"]
    # Movimiento manual: B (no integrada ni desplegada) arrastrada a PRO → no despliega y vuelve a Testing / Review
    t.mover(item(t, cfg, fb["issue"])["item_id"], T.PRO)
    despliegues_antes = n_despliegues(cfg)
    r_rec = accion(cfg, "mantenimiento.yml", ["sincronizar.py", "produccion"], {"simulacion": "ninguna"})
    manual = item(t, cfg, fb["issue"])["estado"]
    despliegues_despues = n_despliegues(cfg)
    ok = (done_a == T.DONE and tras_fallo == T.DONE and tras_ok == T.PRO and manual == T.REVIEW
          and despliegues_despues == despliegues_antes)
    anotar("pro", "simulado", ok,
           f"#{fa['issue']}: integrada → {done_a}; despliegue fallido → {tras_fallo}; correcto → {tras_ok}. "
           f"#{fb['issue']} arrastrada a PRO a mano → {manual}; despliegues lanzados por el arrastre="
           f"{despliegues_despues - despliegues_antes}. Ejecuciones: {r_fallo} · {r_ok} · {r_rec}")
    if cfg.get("simular_actions"):
        # Reversión: se despliega un SHA anterior al cambio → vuelve a Done
        base = C.Git(cfg).run("rev-parse", f"{fa['commit_base']}")
        registrar_despliegue(cfg, base, "success")
        accion(cfg, "despliegue.yml", ["sincronizar.py", "produccion"])
        anotar("pro-reversion", "simulado", item(t, cfg, fa["issue"])["estado"] == T.DONE,
               f"despliegue correcto de {base[:10]} (anterior al cambio) → #{fa['issue']} vuelve a "
               f"{item(t, cfg, fa['issue'])['estado']}")
    anotar("pro-real", "pendiente", True, "El piloto no tiene producción: conectar el despliegue real cuando exista")


def n_despliegues(cfg) -> int:
    if cfg.get("simular_actions"):
        return len(json.load(open(os.environ["FAKE_GH_STATE"]))["deployments"])
    return len(json.loads(gh(cfg, "api", f"repos/{cfg['repo']}/deployments?per_page=100")))


def desplegar(cfg, resultado: str) -> str:
    if cfg.get("simular_actions"):
        sha = C.Git(cfg).run("rev-parse", "origin/" + C.Git(cfg).rama_por_defecto())
        registrar_despliegue(cfg, sha, resultado)
        return accion(cfg, "despliegue.yml", ["sincronizar.py", "produccion"])
    return accion(cfg, "despliegue.yml", [], {"ref": C.Git(cfg).rama_por_defecto(), "resultado": resultado})


# --- solo para el GitHub simulado: lo que en real hacen GitHub y despliegue.yml
def registrar_despliegue(cfg, sha: str, resultado: str) -> None:
    st = os.environ["FAKE_GH_STATE"]
    s = json.load(open(st))
    s["deployments"].append({"id": len(s["deployments"]) + 100, "sha": sha, "environment": "produccion-simulada",
                             "description": "SIMULADO: no hay producción real", "statuses": ["in_progress", resultado]})
    json.dump(s, open(st, "w"), indent=1)


def simular_merge(cfg, f) -> None:
    git = lambda *x, **k: E.git(cfg, *x, **k)  # noqa: E731
    base = C.Git(cfg).rama_por_defecto()
    git("fetch", "origin")
    git("checkout", base)
    git("merge", "--ff-only", f"origin/{base}", comprobar=False)
    git("merge", "--no-ff", "--no-edit", f"origin/{f['rama']}")
    git("push", "origin", base)
    sha = git("rev-parse", "HEAD")
    st = os.environ["FAKE_GH_STATE"]
    s = json.load(open(st))
    for p in s["prs"]:
        if p["number"] == f["pr_numero"]:
            p.update(merged=True, state="MERGED", merge_oid=sha, checks=[{"name": "pruebas", "conclusion": "SUCCESS"}])
    json.dump(s, open(st, "w"), indent=1)


def cmd_todos(a) -> None:
    for fn in (cmd_prioridad, cmd_issue_al_tablero, cmd_bloqueo, cmd_reinicio, cmd_aviso_duplicado, cmd_aviso_critico, cmd_remoto, cmd_pro):
        fn(a)
    print("\nResumen:")
    for k, v in json.loads(RES.read_text(encoding="utf-8")).items():
        print(f"  {'OK   ' if v['ok'] else 'FALLO'} {v['tipo']:11} {k}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    for nombre, fn in [("instalar-github", cmd_instalar_github), ("prioridad", cmd_prioridad),
                       ("issue-al-tablero", cmd_issue_al_tablero), ("bloqueo", cmd_bloqueo),
                       ("reinicio", cmd_reinicio), ("aviso-duplicado", cmd_aviso_duplicado),
                       ("aviso-critico", cmd_aviso_critico), ("remoto", cmd_remoto), ("pro", cmd_pro), ("todos", cmd_todos)]:
        x = sp.add_parser(nombre)
        x.add_argument("--si", action="store_true", help="No pedir confirmación antes de integrar PR de ensayo")
        x.set_defaults(f=fn)
    a = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a.f(a)


if __name__ == "__main__":
    main()
