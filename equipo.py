#!/usr/bin/env python3
"""Equipo IA multiproyecto: un solo equipo instalado, varios proyectos configurados.

  python3 equipo.py proyectos                       Lista los proyectos y si su coordinador está en marcha
  python3 equipo.py panel [--puerto 8765]           Panel web local (http://127.0.0.1:8765)
  python3 equipo.py <proyecto> vigilar|una-vez|estado|parar|reanudar N|diagnostico|leccion …
  python3 equipo.py <proyecto> tablero ver|nueva|verificar …
  python3 equipo.py importar <nombre> --repo owner/repo [--repo owner/otro] [--descripcion "…"]
  python3 equipo.py nuevo <nombre> --repo nombre-repo [--repo otro] --stack python|vacio [--descripcion "…"]
  python3 equipo.py migrar                          Convierte la instalación de un proyecto (v3) en proyectos/ensayo
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
PROYECTOS = LAB / "proyectos"
EQUIPO_JSON = LAB / "equipo.json"
PLANTILLA = LAB / "repo-plantilla"
sys.path.insert(0, str(PLANTILLA / ".equipo-ia"))
import tablero_lib as T  # noqa: E402

os.environ.pop("EQUIPO_IA_PROYECTO", None)
import coordinador as C  # noqa: E402  (sin proyecto: solo utilidades)

NOMBRE_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
REPO_OK = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NUESTROS_WORKFLOWS = ("tablero-pr.yml", "mantenimiento.yml", "despliegue.yml", "aviso-critico.yml")
STACKS = ("python", "vacio")


# --------------------------------------------------------------------------- utilidades

def equipo_cfg() -> dict:
    if EQUIPO_JSON.exists():
        return json.loads(EQUIPO_JSON.read_text(encoding="utf-8"))
    base = json.loads((LAB / "config.example.json").read_text(encoding="utf-8"))
    return {k: v for k, v in base.items() if k in C.CLAVES_COMPARTIDAS}


def gh_bin() -> list[str]:
    g = equipo_cfg().get("gh_bin", ["gh"])
    return [g] if isinstance(g, str) else g


def gh(*args, stdin_text=None, comprobar=True, cwd=None) -> str:
    r = C.ejecutar(gh_bin() + list(args), cwd=cwd or LAB, timeout=300, stdin_text=stdin_text)
    if comprobar and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def git(*args, cwd: Path, comprobar=True) -> str:
    r = C.ejecutar(["git", *args], cwd=cwd, timeout=600)
    if comprobar and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def proyectos() -> list[str]:
    if not PROYECTOS.exists():
        return []
    return sorted(p.name for p in PROYECTOS.iterdir() if (p / "config.json").exists())


def plantilla_tablero() -> str | None:
    """owner/numero del tablero que sirve de plantilla: equipo.json → plantilla_tablero, o el de «ensayo»."""
    p = equipo_cfg().get("plantilla_tablero") or {}
    if not p.get("numero") and (PROYECTOS / "ensayo" / "config.json").exists():
        p = json.loads((PROYECTOS / "ensayo" / "config.json").read_text(encoding="utf-8")).get("tablero") or {}
    return f"{p['owner']}/{p['numero']}" if p.get("numero") else None


def cfg_proyecto(nombre: str) -> dict:
    cfg = json.loads((PROYECTOS / nombre / "config.json").read_text(encoding="utf-8"))
    return C.fusionar(equipo_cfg(), cfg)


def guardar_cfg_proyecto(nombre: str, cambios: dict) -> None:
    p = PROYECTOS / nombre / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg.update(cambios)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def env_proyecto(nombre: str) -> dict:
    return dict(os.environ, EQUIPO_IA_PROYECTO=nombre)


def script(nombre: str, archivo: str, *args, capturar=False, timeout=3600) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(LAB / archivo), *args]
    if capturar:
        return subprocess.run(cmd, cwd=LAB, env=env_proyecto(nombre), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    return subprocess.run(cmd, cwd=LAB, env=env_proyecto(nombre))


def coordinador_activo(nombre: str) -> int | None:
    lock = PROYECTOS / nombre / "estado" / "coordinador.lock"
    if not lock.exists():
        return None
    try:
        pid = int(json.loads(lock.read_text(encoding="utf-8") or "{}").get("pid", 0))
    except Exception:
        return None
    return pid if C.pid_vivo(pid) else None


def login() -> str:
    return gh("api", "user", "--jq", ".login").strip()


# --------------------------------------------------------------------------- detección en GitHub

def detectar_ci(repo: str) -> dict:
    """Workflows propios del repo y nombres de sus jobs en la rama por defecto (serán los checks requeridos)."""
    rama = json.loads(gh("api", f"repos/{repo}", "--jq", "{default_branch}"))["default_branch"]
    wfs = json.loads(gh("api", f"repos/{repo}/actions/workflows?per_page=100", comprobar=False) or "{}").get("workflows", [])
    propios = [w for w in wfs if Path(w["path"]).name not in NUESTROS_WORKFLOWS and w.get("state") == "active"]
    checks: list[str] = []
    if propios:
        runs = json.loads(gh("api", f"repos/{repo}/actions/runs?branch={rama}&per_page=20", comprobar=False) or "{}")
        vistos = set()
        for r in runs.get("workflow_runs", []):
            if Path(r.get("path", "")).name in NUESTROS_WORKFLOWS or r["workflow_id"] in vistos:
                continue
            vistos.add(r["workflow_id"])
            jobs = json.loads(gh("api", f"repos/{repo}/actions/runs/{r['id']}/jobs", comprobar=False) or "{}")
            checks += [j["name"] for j in jobs.get("jobs", []) if j["name"] not in checks]
    return {"rama": rama, "workflows": [w["path"] for w in propios], "checks": checks}


def archivos_bloqueo(clon: Path) -> list[str]:
    nombres = {"composer.lock", "package-lock.json", "requirements.txt", ".python-version"}
    salida = []
    for p in clon.rglob("*"):
        if p.name in nombres and "node_modules" not in p.parts and "vendor" not in p.parts and ".git" not in p.parts:
            salida.append(str(p.relative_to(clon)).replace("\\", "/"))
    return sorted(salida)


def dependabot_yml(clon: Path) -> str:
    bloques = []
    def directorios(patron):
        return sorted({"/" + str(p.parent.relative_to(clon)).replace("\\", "/").lstrip(".").strip("/")
                       for p in clon.rglob(patron) if "node_modules" not in p.parts and "vendor" not in p.parts})
    for eco, patron in (("composer", "composer.json"), ("npm", "package.json"), ("pip", "requirements.txt")):
        for d in directorios(patron):
            bloques.append(f"  - package-ecosystem: {eco}\n    directory: \"{d if d != '/' else '/'}\"\n"
                           f"    schedule:\n      interval: weekly\n    labels: [dependencias]")
    bloques.append("  - package-ecosystem: github-actions\n    directory: \"/\"\n    schedule:\n      interval: weekly\n"
                   "    labels: [dependencias]")
    return "version: 2\nupdates:\n" + "\n".join(bloques) + "\n"


# --------------------------------------------------------------------------- plantillas de stack (repos nuevos)

PRUEBAS_YML = {
    "python": """name: pruebas
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  pruebas:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m compileall -q .
      - run: python -m unittest discover -s tests -t . -v
""",
    "vacio": """name: pruebas
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  pruebas:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: test -f README.md && echo "Proyecto sin pruebas todavía: la primera tarea debería definirlas"
""",
}


def andamiaje(clon: Path, nombre: str, stack: str, descripcion: str, url_tablero: str) -> None:
    (clon / "README.md").write_text(f"# {nombre}\n\n{descripcion}\n\n> Proyecto gestionado por el Equipo IA. "
                                    f"Tablero: {url_tablero}\n", encoding="utf-8")
    (clon / ".gitignore").write_text("__pycache__/\n*.pyc\n.env\nnode_modules/\nvendor/\n", encoding="utf-8")
    (clon / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (clon / ".github" / "workflows" / "pruebas.yml").write_text(PRUEBAS_YML[stack], encoding="utf-8")
    if stack == "python":
        for d in ("src", "tests"):
            (clon / d).mkdir(exist_ok=True)
            (clon / d / "__init__.py").write_text("", encoding="utf-8")
        (clon / "tests" / "test_humo.py").write_text(
            "import unittest\n\n\nclass TestHumo(unittest.TestCase):\n    def test_arranca(self):\n"
            "        self.assertTrue(True)\n", encoding="utf-8")


# --------------------------------------------------------------------------- instalación en un repo

def copiar_instalacion(clon: Path, repo: str, tablero: dict, checks: list[str], workflow_pruebas: str | None,
                       crear_dependabot: bool) -> list[str]:
    avisos = []
    destino = clon / ".equipo-ia"
    destino.mkdir(exist_ok=True)
    for p in (PLANTILLA / ".equipo-ia").iterdir():
        if p.is_file() and p.suffix in (".py", ".md"):
            shutil.copy(p, destino / p.name)
    m = json.loads((PLANTILLA / ".equipo-ia" / "mantenimiento.json").read_text(encoding="utf-8"))
    m["repo"] = repo
    m["tablero"] = {k: tablero[k] for k in ("owner", "numero", "owner_tipo")}
    m["pruebas_requeridas"] = checks
    m["versiones"]["archivos"] = archivos_bloqueo(clon) or m["versiones"]["archivos"]
    if workflow_pruebas:
        m["deuda"]["workflow_pruebas"] = Path(workflow_pruebas).name
    (destino / "mantenimiento.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    wf = clon / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    for nombre in NUESTROS_WORKFLOWS:
        if (wf / nombre).exists() and (wf / nombre).read_text(encoding="utf-8") != \
                (PLANTILLA / ".github" / "workflows" / nombre).read_text(encoding="utf-8") and \
                "equipo-ia" not in (wf / nombre).read_text(encoding="utf-8"):
            avisos.append(f"{repo}: ya existe .github/workflows/{nombre} y no es nuestro; no lo toco")
            continue
        shutil.copy(PLANTILLA / ".github" / "workflows" / nombre, wf / nombre)
    if crear_dependabot:
        dep = clon / ".github" / "dependabot.yml"
        if dep.exists():
            avisos.append(f"{repo}: ya tiene .github/dependabot.yml; lo conservo")
        else:
            dep.write_text(dependabot_yml(clon), encoding="utf-8")
    (clon / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)
    shutil.copy(LAB / "plantillas" / "tarea-agente.yml", clon / ".github" / "ISSUE_TEMPLATE" / "tarea-agente.yml")
    return avisos


def preparar_github(repo: str, tablero: dict, simulado: bool) -> list[str]:
    """Etiquetas, variables, Dependabot y comprobación del secreto. Devuelve pendientes para Óscar."""
    pendientes = []
    colores = {"agent:claude": "D97757", "agent:local": "2B7A78", "mantenimiento": "5319E7", "simulado": "C5DEF5",
               "registro-mantenimiento": "BFDADC", "dependencias": "0366D6"}
    for etq, color in colores.items():
        gh("label", "create", etq, "--repo", repo, "--color", color, "--force", comprobar=False)
    if simulado:
        return pendientes
    gh("api", "-X", "PUT", f"repos/{repo}/vulnerability-alerts", comprobar=False)
    gh("variable", "set", "TABLERO_OWNER", "--repo", repo, "--body", tablero["owner"], comprobar=False)
    gh("variable", "set", "TABLERO_NUMERO", "--repo", repo, "--body", str(tablero["numero"]), comprobar=False)
    secretos = gh("api", f"repos/{repo}/actions/secrets", "--jq", ".secrets[].name", comprobar=False)
    if "TABLERO_TOKEN" not in secretos.split():
        pendientes.append(f"Guardar el secreto TABLERO_TOKEN en {repo}")
    return pendientes


def instalar_en_repo(repo: str, clon: Path, tablero: dict, checks: list[str], workflow_pruebas: str | None,
                     directo: bool, log, extra: dict | None = None) -> str | None:
    """Repo nuevo → commit directo en main. Repo con historia → rama y PR para que Óscar la revise."""
    rama_def = git("rev-parse", "--abbrev-ref", "HEAD", cwd=clon, comprobar=False) or "main"
    if not directo:
        git("fetch", "origin", cwd=clon)
        git("checkout", "-B", "equipo-ia/instalacion", f"origin/{rama_def}", cwd=clon)
    for ruta, texto in (extra or {}).items():
        (clon / ruta).parent.mkdir(parents=True, exist_ok=True)
        (clon / ruta).write_text(texto, encoding="utf-8")
    avisos = copiar_instalacion(clon, repo, tablero, checks, workflow_pruebas, crear_dependabot=True)
    for a in avisos:
        log("⚠ " + a)
    git("add", "-A", cwd=clon)
    if not git("status", "--porcelain", cwd=clon, comprobar=False):
        log(f"{repo}: la instalación ya estaba al día")
        if not directo:
            git("checkout", rama_def, cwd=clon, comprobar=False)
        return None
    git("commit", "-m", "Equipo IA: tablero, mantenimiento programado, Done/PRO y Dependabot", cwd=clon)
    if directo:
        git("push", "-u", "origin", "HEAD", cwd=clon)
        log(f"{repo}: instalación subida a {git('rev-parse', '--abbrev-ref', 'HEAD', cwd=clon)}")
        return None
    git("push", "-f", "-u", "origin", "equipo-ia/instalacion", cwd=clon)
    cuerpo = ("Instala el **Equipo IA** en este repositorio. No cambia código de la aplicación.\n\n"
              "- `.equipo-ia/`: mantenimiento semanal, sincronización Done/PRO y aviso crítico.\n"
              "- `.github/workflows/`: tablero-pr, mantenimiento, despliegue (simulado) y aviso-critico.\n"
              "- `.github/ISSUE_TEMPLATE/tarea-agente.yml` y `dependabot.yml` (si no existía).\n\n"
              f"Checks requeridos para pasar a Done: {', '.join(checks) or '(ninguno)'}.\n\n"
              "Revísala e intégrala cuando te parezca bien.")
    existente = json.loads(gh("pr", "list", "--repo", repo, "--head", "equipo-ia/instalacion", "--state", "open",
                              "--json", "url") or "[]")
    if existente:
        url = existente[0]["url"]
    else:
        url = gh("pr", "create", "--repo", repo, "--head", "equipo-ia/instalacion", "--base", rama_def,
                 "--title", "Equipo IA: instalación del tablero y el mantenimiento", "--body-file", "-",
                 stdin_text=cuerpo).strip()
    git("checkout", rama_def, cwd=clon, comprobar=False)
    log(f"{repo}: PR de instalación {url}")
    return url


# --------------------------------------------------------------------------- alta de proyectos

def crear_proyecto(nombre: str, repos: list[str], crear_repos: bool, stack: str, descripcion: str,
                   log=print) -> dict:
    if not NOMBRE_OK.match(nombre):
        raise ValueError("Nombre de proyecto: minúsculas, números y guiones (2-41 caracteres)")
    if (PROYECTOS / nombre / "config.json").exists():
        raise ValueError(f"Ya existe el proyecto {nombre}")
    if not repos:
        raise ValueError("Indica al menos un repositorio")
    if stack not in STACKS:
        raise ValueError(f"Stack desconocido: {stack}")
    ecfg = equipo_cfg()
    if not EQUIPO_JSON.exists():
        EQUIPO_JSON.write_text(json.dumps(ecfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    simulado = bool(ecfg.get("simular_actions"))
    yo = login()
    completos = [r if "/" in r else f"{yo}/{r}" for r in repos]
    for r in completos:
        if not REPO_OK.match(r):
            raise ValueError(f"Repositorio no válido: {r}")
    pd = PROYECTOS / nombre
    pd.mkdir(parents=True, exist_ok=True)
    log(f"Proyecto {nombre}: repos {', '.join(completos)}")

    if crear_repos:
        for r in completos:
            log(f"Creando repositorio privado {r}")
            gh("repo", "create", r, "--private", "--description", descripcion or nombre)

    principal = completos[0]
    clon = pd / "repo"
    if not (clon / ".git").exists():
        log(f"Clonando {principal}")
        git("clone", f"https://github.com/{principal}.git", str(clon), cwd=LAB)
    guardar_cfg_proyecto(nombre, {"repo": principal, "repos": completos, "descripcion": descripcion,
                                  "autor_autorizado": yo, "autores_autorizados": [yo], "clon_local": "repo",
                                  "fuente_cola": "tablero", "stack": stack})

    log("Creando el tablero del proyecto")
    plantilla = plantilla_tablero()
    log(f"Plantilla del tablero: {plantilla}" if plantilla else "Sin plantilla: habrá que crear las vistas a mano")
    r = script(nombre, "tablero.py", "crear", "--titulo", f"Equipo IA · {nombre}",
               *(["--plantilla", plantilla] if plantilla else []), capturar=True)
    if r.returncode != 0:
        raise RuntimeError("tablero.py crear: " + (r.stderr or r.stdout)[-500:])
    tablero = json.loads((pd / "config.json").read_text(encoding="utf-8"))["tablero"]
    log(f"Tablero: {tablero.get('url')}")

    pendientes, prs = [], []
    for repo in completos:
        if repo == principal:
            rclon = clon
        else:
            rclon = pd / "estado" / "repos" / repo.split("/")[1]
            if not (rclon / ".git").exists():
                rclon.parent.mkdir(parents=True, exist_ok=True)
                git("clone", "--depth", "50", f"https://github.com/{repo}.git", str(rclon), cwd=LAB)
        vacio = git("rev-parse", "--verify", "HEAD", cwd=rclon, comprobar=False) == ""
        if vacio:
            log(f"{repo}: vacío → andamiaje «{stack}»")
            git("checkout", "-B", "main", cwd=rclon)
            andamiaje(rclon, repo.split("/")[1], stack, descripcion, tablero.get("url", ""))
            ci = {"checks": ["pruebas"], "workflows": [".github/workflows/pruebas.yml"]}
        else:
            ci = detectar_ci(repo)
            if not ci["checks"] and ci["workflows"]:
                raise RuntimeError(f"{repo} tiene CI ({', '.join(ci['workflows'])}) pero aún no hay ejecuciones en "
                                   f"{ci['rama']}: espera a que termine la primera y repite el alta")
            if not ci["checks"]:
                log(f"{repo}: sin CI propia → la PR añade pruebas.yml «{stack}»")
                ci = {"checks": ["pruebas"], "workflows": [".github/workflows/pruebas.yml"],
                      "extra": {} if (rclon / ".github/workflows/pruebas.yml").exists()
                      else {".github/workflows/pruebas.yml": PRUEBAS_YML[stack]}}
            else:
                log(f"{repo}: CI detectada ({', '.join(ci['workflows'])}) → checks requeridos: {', '.join(ci['checks'])}")
        url = instalar_en_repo(repo, rclon, tablero, ci["checks"], (ci["workflows"] or [None])[0],
                               directo=vacio, log=log, extra=ci.get("extra"))
        if url:
            prs.append(url)
            pendientes.append(f"Revisar e integrar la PR de instalación: {url}")
        if repo == principal:
            guardar_cfg_proyecto(nombre, {"ci": {"checks": ci["checks"], "timeout_s": 2400, "intervalo_s": 20}})
            git("fetch", "origin", cwd=clon, comprobar=False)
            git("remote", "set-head", "origin", "--auto", cwd=clon, comprobar=False)
        pendientes += preparar_github(repo, tablero, simulado)

    if not plantilla:
        pendientes.append(f"Crear las vistas «Tablero» y «Planning» en {tablero.get('url')}")
    guardar_cfg_proyecto(nombre, {"instalacion": {"prs": prs, "pendientes": pendientes, "fecha": C.ahora()}})
    log("Hecho. Pendiente para Óscar:\n  - " + "\n  - ".join(pendientes))
    return {"nombre": nombre, "tablero": tablero.get("url"), "prs": prs, "pendientes": pendientes}


# --------------------------------------------------------------------------- migración v3 → v4

def migrar(nombre: str = "ensayo") -> None:
    viejo = LAB / "config.json"
    if not viejo.exists():
        sys.exit("No hay config.json de la v3 que migrar.")
    if C.LOCK_PATH.exists() and C.pid_vivo(int(json.loads(C.LOCK_PATH.read_text() or "{}").get("pid", 0))):
        sys.exit("Hay un coordinador en marcha: páralo antes de migrar.")
    pd = PROYECTOS / nombre
    if (pd / "config.json").exists():
        sys.exit(f"Ya existe proyectos/{nombre}.")
    cfg = json.loads(viejo.read_text(encoding="utf-8"))
    compartido = {k: v for k, v in cfg.items() if k in C.CLAVES_COMPARTIDAS}
    compartido["pruebas_comunes"] = {}
    propio = {k: v for k, v in cfg.items() if k not in C.CLAVES_COMPARTIDAS}
    propio.setdefault("repos", [propio.get("repo")])
    pd.mkdir(parents=True, exist_ok=True)
    viejo_estado, viejo_wt = (LAB / "estado").resolve(), (LAB / "worktrees").resolve()
    for d in ("estado", "worktrees", propio.get("clon_local", "repo")):
        if (LAB / d).exists():
            shutil.move(str(LAB / d), str(pd / d))
            print(f"movido {d} → proyectos/{nombre}/{d}")
    clon = pd / propio.get("clon_local", "repo")
    wts = [str(p) for p in (pd / "worktrees").glob("*")] if (pd / "worktrees").exists() else []
    if wts and (clon / ".git").exists():
        git("worktree", "repair", *wts, cwd=clon, comprobar=False)
    db = pd / "estado" / "registro.db"
    if db.exists():
        con = sqlite3.connect(str(db))
        con.execute("UPDATE tareas SET worktree = replace(worktree, ?, ?)", (str(viejo_wt), str((pd / "worktrees").resolve())))
        con.commit()
        con.close()
    if not EQUIPO_JSON.exists():
        EQUIPO_JSON.write_text(json.dumps(compartido, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (pd / "config.json").write_text(json.dumps(propio, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    viejo.rename(LAB / "config.json.v3.bak")
    print(f"Migrado a proyectos/{nombre}. Configuración compartida en equipo.json; copia de seguridad: config.json.v3.bak")
    print(f"Comprueba: python3 equipo.py {nombre} estado")


# --------------------------------------------------------------------------- CLI

COMANDOS_TABLERO = {"tablero"}
COMANDOS_ENSAYO = {"ensayo": "ensayo.py", "ensayo-tablero": "ensayo_tablero.py"}


def main() -> None:
    a = sys.argv[1:]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not a or a[0] in ("-h", "--help", "ayuda"):
        print(__doc__)
        return
    if a[0] == "proyectos":
        lista = proyectos()
        if not lista:
            print("No hay proyectos. Crea uno con `importar` o `nuevo`, o migra la v3 con `migrar`.")
        for p in lista:
            c = cfg_proyecto(p)
            pid = coordinador_activo(p)
            print(f"{p:22} {'● en marcha (PID ' + str(pid) + ')' if pid else '○ parado':24} "
                  f"{', '.join(c.get('repos') or [c.get('repo')])}  {(c.get('tablero') or {}).get('url', '')}")
        return
    if a[0] == "migrar":
        migrar(a[1] if len(a) > 1 else "ensayo")
        return
    if a[0] == "panel":
        import panel
        puerto = int(a[a.index("--puerto") + 1]) if "--puerto" in a else 8765
        panel.servir(puerto, abrir="--no-abrir" not in a)
        return
    if a[0] in ("importar", "nuevo"):
        import argparse
        ap = argparse.ArgumentParser(prog=f"equipo.py {a[0]}")
        ap.add_argument("nombre")
        ap.add_argument("--repo", action="append", required=True)
        ap.add_argument("--stack", default="vacio", choices=STACKS)
        ap.add_argument("--descripcion", default="")
        x = ap.parse_args(a[1:])
        crear_proyecto(x.nombre, x.repo, crear_repos=a[0] == "nuevo", stack=x.stack, descripcion=x.descripcion)
        return
    nombre, resto = a[0], a[1:]
    if nombre not in proyectos():
        sys.exit(f"No existe el proyecto «{nombre}». Proyectos: {', '.join(proyectos()) or '(ninguno)'}")
    if not resto:
        sys.exit("Falta el comando: vigilar, una-vez, estado, parar, reanudar N, tablero ver…")
    if resto[0] in COMANDOS_TABLERO:
        sys.exit(script(nombre, "tablero.py", *resto[1:]).returncode)
    if resto[0] in COMANDOS_ENSAYO:
        sys.exit(script(nombre, COMANDOS_ENSAYO[resto[0]], *resto[1:]).returncode)
    sys.exit(script(nombre, "coordinador.py", *resto).returncode)


if __name__ == "__main__":
    main()
