#!/usr/bin/env python3
"""Ensayo del circuito completo (fases 3 y 4 de la hoja de ruta).

  preparar-repo     Crea (con --crear) o reutiliza el repo privado, sube el commit inicial,
                    la plantilla de issue y las etiquetas; actualiza config.json.
  crear-issues      Publica las dos issues del piloto desde el mismo commit base.
  caida-tras-push   Procesa la cola deteniéndose tras subir las ramas y luego reanuda.
  unicidad          Repite `una-vez` dos veces y comprueba una rama y una PR por issue.
  integrar          Rama temporal con ambas entregas: verde, fallo deliberado, revertir, verde.
  ollama-caida      Tarea local con Ollama detenido: bloqueo, sin relevo de pago, reanudación.
  completo          Todo lo anterior en orden (pide confirmación para parar/arrancar Ollama).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import coordinador as C

LAB = C.LAB
RESULTADOS = C.ESTADO / "ensayo-resultados.json"


def resultados() -> dict:
    return json.loads(RESULTADOS.read_text(encoding="utf-8")) if RESULTADOS.exists() else {}


def anotar(clave: str, ok: bool, detalle: str, segundos: float | None = None) -> None:
    r = resultados()
    r[clave] = {"ok": ok, "detalle": detalle, "segundos": segundos, "cuando": C.ahora()}
    C.ESTADO.mkdir(parents=True, exist_ok=True)
    RESULTADOS.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{'OK  ' if ok else 'FALLO'} {clave}: {detalle}" + (f" ({segundos}s)" if segundos else ""))


def coord(*args: str, comprobar=True) -> str:
    r = C.ejecutar(["{python}", str(LAB / "coordinador.py"), *args], cwd=LAB, timeout=3600)
    salida = (r.stdout or "") + (r.stderr or "")
    print(salida.rstrip())
    if comprobar and r.returncode != 0:
        sys.exit(f"coordinador.py {' '.join(args)} terminó con código {r.returncode}")
    return salida


def git(cfg, *args, cwd=None, comprobar=True) -> str:
    return C.Git(cfg).run(*args, cwd=cwd, comprobar=comprobar)


# --------------------------------------------------------------------------- repo

ARCHIVOS_INICIALES = {
    "README.md": "# Repositorio de ensayo del equipo IA\n\nVer docs/contrato-puntos.md.\n",
    ".gitignore": "__pycache__/\n*.pyc\n",
    "src/__init__.py": "",
    "tests/__init__.py": "",
}


def cmd_preparar_repo(a) -> None:
    cfg_path = C.PD / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    gh = cfg.get("gh_bin", ["gh"])
    if isinstance(gh, str):
        gh = [gh]
    login = C.ejecutar(gh + ["api", "user", "--jq", ".login"], timeout=60).stdout.strip()
    if not login:
        sys.exit("No hay sesión en gh. Ejecuta `gh auth login`.")
    owner = a.owner or login
    nombre = f"{owner}/{a.nombre}"
    url = a.remoto
    if not url:
        v = C.ejecutar(gh + ["repo", "view", nombre, "--json", "url,isPrivate,viewerPermission"], timeout=60)
        if v.returncode != 0:
            if not a.crear:
                sys.exit(f"{nombre} no existe. Confirma nombre y destino y repite con --crear.")
            r = C.ejecutar(gh + ["repo", "create", nombre, "--private",
                                 "--description", "Ensayo del equipo IA local (equipo-ia-lab)"], timeout=120)
            if r.returncode != 0:
                sys.exit(r.stderr)
            v = C.ejecutar(gh + ["repo", "view", nombre, "--json", "url,isPrivate,viewerPermission"], timeout=60)
        info = json.loads(v.stdout)
        if not info.get("isPrivate"):
            sys.exit(f"{nombre} no es privado; el ensayo exige un repositorio privado.")
        url = info["url"] + ".git"
    clon = C.PD / cfg.get("clon_local", "repo")
    if not (clon / ".git").exists():
        r = C.ejecutar(["git", "clone", url, str(clon)], cwd=LAB, timeout=300)
        if r.returncode != 0:
            sys.exit(r.stderr)
    cfg["repo"], cfg["autor_autorizado"] = nombre, login
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cfg = C.cargar_config()
    vacio = git(cfg, "rev-parse", "--verify", "HEAD", comprobar=False) == ""
    if vacio:
        for ruta, texto in ARCHIVOS_INICIALES.items():
            p = clon / ruta
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(texto, encoding="utf-8")
        (clon / "docs").mkdir(exist_ok=True)
        shutil.copy(LAB / "plantillas" / "contrato-puntos.md", clon / "docs" / "contrato-puntos.md")
        (clon / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)
        shutil.copy(LAB / "plantillas" / "tarea-agente.yml", clon / ".github" / "ISSUE_TEMPLATE" / "tarea-agente.yml")
        git(cfg, "checkout", "-B", "main")
        git(cfg, "add", "-A")
        git(cfg, "commit", "-m", "Commit inicial: contrato, plantilla de issue y estructura")
        git(cfg, "push", "-u", "origin", "main")
    git(cfg, "fetch", "origin")
    git(cfg, "remote", "set-head", "origin", "--auto", comprobar=False)
    rama = C.Git(cfg).rama_por_defecto()
    colores = {"agent:claude": "D97757", "agent:local": "2B7A78", "ready": "0E8A16",
               "running": "FBCA04", "review": "1D76DB", "blocked": "B60205"}
    for etq, color in colores.items():
        C.ejecutar(gh + ["label", "create", etq, "--repo", nombre, "--color", color, "--force"], timeout=60)
    anotar("preparar-repo", True, f"{nombre} privado, rama por defecto {rama}, cuenta {login}, clon {clon}")


# --------------------------------------------------------------------------- issues

def cuerpo(objetivo, agente, base, commit, archivos, criterios, prueba, deps="ninguna") -> str:
    return (f"### Objetivo\n\n{objetivo}\n\n### Agente\n\n{agente}\n\n### Rama base\n\n{base}\n\n"
            f"### Commit base\n\n{commit}\n\n### Archivos permitidos\n\n{archivos}\n\n"
            f"### Criterios de aceptación\n\n{criterios}\n\n### Comando de prueba\n\n{prueba}\n\n"
            f"### Dependencias\n\n{deps}\n")


def crear_issue(cfg, titulo: str, agente: str, texto: str) -> int:
    gh = C.GH(cfg)
    out = gh.run("issue", "create", "--repo", cfg["repo"], "--title", titulo, "--label", "ready",
                 "--label", cfg["agentes"][agente]["etiqueta"], "--body-file", "-", stdin_text=texto)
    n = int(out.strip().rstrip("/").split("/")[-1])
    if cfg.get("fuente_cola", "etiquetas") == "etiquetas" and not cfg.get("simular_actions"):
        for _ in range(30):  # GitHub tarda unos segundos en mostrarla al filtrar por etiqueta
            if any(i["number"] == n for i in gh.issues_ready()):
                break
            time.sleep(2)
    return n


def cmd_crear_issues(_a) -> None:
    cfg = C.cargar_config()
    git(cfg, "fetch", "origin")
    base = C.Git(cfg).rama_por_defecto()
    commit = git(cfg, "rev-parse", f"origin/{base}")
    contrato = (LAB / "plantillas" / "contrato-puntos.md").read_text(encoding="utf-8")
    impl = crear_issue(cfg, "Implementar sumar_puntos", "claude", cuerpo(
        "Implementa la función descrita en el contrato.\n\n" + contrato, "claude", base, commit, "src/puntos.py",
        "- `sumar_puntos([1, 2, 3]) == 6`\n- `sumar_puntos([]) == 0`\n- Negativos → `ValueError` con 'negativo'\n- No crees pruebas",
        "import-src"))
    tests = crear_issue(cfg, "Pruebas de sumar_puntos", "local", cuerpo(
        "Escribe las pruebas unittest del contrato. NO implementes la función.\n\n" + contrato, "local", base, commit,
        "tests/test_puntos.py",
        "- Tres métodos de prueba: suma normal, cero, valores negativos (assertRaises ValueError)\n"
        "- Importa `from src.puntos import sumar_puntos`\n- Solo modifica tests/test_puntos.py",
        "sintaxis-tests"))
    r = resultados()
    r["issues"] = {"impl": impl, "tests": tests, "commit_base": commit}
    RESULTADOS.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    anotar("crear-issues", True, f"#{impl} (claude, src/) y #{tests} (local, tests/) desde {commit[:10]}")


def issues_piloto() -> tuple[int, int]:
    r = resultados().get("issues")
    if not r:
        sys.exit("Primero ejecuta: python ensayo.py crear-issues")
    return r["impl"], r["tests"]


# --------------------------------------------------------------------------- comprobaciones

def cmd_caida_tras_push(_a) -> None:
    cfg = C.cargar_config()
    impl, tests = issues_piloto()
    t0 = time.time()
    coord("una-vez", "--detener-tras", "push")
    con = C.db()
    tras = {n: dict(C.obtener(con, cfg["repo"], n) or {}) for n in (impl, tests)}
    detenidas = [n for n, f in tras.items() if f.get("estado") == "en_curso" and f.get("paso") == "push"]
    print(f"Tras la caída simulada: { {n: (f.get('estado'), f.get('paso')) for n, f in tras.items()} }")
    coord("una-vez")
    fin = {n: dict(C.obtener(con, cfg["repo"], n) or {}) for n in (impl, tests)}
    ok = all(f.get("estado") == "revision" and f.get("pr_url") for f in fin.values())
    anotar("caida-tras-push", ok and bool(detenidas),
           f"detenidas tras push: {detenidas}; después: { {n: (f.get('estado'), f.get('pr_url')) for n, f in fin.items()} }"
           + ("" if ok else " — revisa `python coordinador.py estado`"),
           round(time.time() - t0, 1))


def contar(cfg, issue: int) -> tuple[int, int]:
    con = C.db()
    f = C.obtener(con, cfg["repo"], issue)
    rama = f["rama"]
    prs = json.loads(C.GH(cfg).run("pr", "list", "--repo", cfg["repo"], "--head", rama, "--state", "all",
                                   "--json", "number"))
    ramas = [l for l in git(cfg, "ls-remote", "--heads", "origin", f"agente/*/issue-{issue}").splitlines() if l.strip()]
    return len(ramas), len(prs)


def cmd_unicidad(_a) -> None:
    cfg = C.cargar_config()
    impl, tests = issues_piloto()
    coord("una-vez")
    coord("una-vez")
    coord("reanudar", str(impl), "--desde", "push")
    coord("una-vez")
    cuentas = {n: contar(cfg, n) for n in (impl, tests)}
    ok = all(c == (1, 1) for c in cuentas.values())
    anotar("unicidad", ok, f"(ramas remotas, PR) por issue tras 3 ejecuciones + reanudación forzada: {cuentas}")


def cmd_integrar(_a) -> None:
    cfg = C.cargar_config()
    impl, tests = issues_piloto()
    con = C.db()
    fi, ft = C.obtener(con, cfg["repo"], impl), C.obtener(con, cfg["repo"], tests)
    if not (fi and ft and fi["paso"] == "review" and ft["paso"] == "review"):
        sys.exit("Las dos issues deben estar en review antes de integrar.")
    t0 = time.time()
    git(cfg, "fetch", "origin")
    wt = C.WORKTREES / f"integracion-{time.strftime('%Y%m%d-%H%M%S')}"
    rama = f"ensayo/integracion-{impl}-{tests}-{int(time.time())}"
    git(cfg, "worktree", "add", "-b", rama, str(wt), fi["commit_base"])
    for f in (fi, ft):
        git(cfg, "merge", "--no-ff", "--no-edit", f"origin/{f['rama']}", cwd=wt)
    unit = C.expandir(cfg["pruebas"]["unit"])

    def correr():
        r = C.ejecutar(unit, cwd=wt, timeout=cfg["timeout_pruebas_s"])
        salida = (r.stdout or "") + (r.stderr or "")
        n = salida.count(" ... ok")
        return r.returncode, n, salida

    c1, n1, s1 = correr()
    print(s1)
    archivo = wt / "src" / "puntos.py"
    archivo.write_text(archivo.read_text(encoding="utf-8") +
                       "\n\n# FALLO DELIBERADO DEL ENSAYO\n_original = sumar_puntos\n"
                       "def sumar_puntos(puntos):\n    return _original(puntos) + 1\n", encoding="utf-8")
    c2, _, s2 = correr()
    print(s2)
    git(cfg, "checkout", "--", "src/puntos.py", cwd=wt)
    limpio = git(cfg, "status", "--porcelain", cwd=wt) == ""
    c3, n3, _ = correr()
    ok = c1 == 0 and n1 >= 3 and c2 != 0 and c3 == 0 and limpio
    anotar("integrar", ok, f"rama local {rama} en {wt}: verde={c1 == 0} ({n1} ok), fallo deliberado detectado={c2 != 0}, "
                           f"revertido limpio={limpio}, verde otra vez={c3 == 0} ({n3} ok)", round(time.time() - t0, 1))


def cmd_ollama_caida(a) -> None:
    cfg = C.cargar_config()
    if not a.no_interactivo:
        input("Detén Ollama (icono de la bandeja → Quit Ollama, o `taskkill /IM ollama.exe /F` y "
              "`taskkill /IM \"ollama app.exe\" /F`) y pulsa Intro…")
    ok, _ = C.ollama_disponible(cfg)
    if ok:
        sys.exit("Ollama sigue respondiendo; detenlo antes de continuar.")
    git(cfg, "fetch", "origin")
    base = C.Git(cfg).rama_por_defecto()
    n = crear_issue(cfg, "Notas del ensayo (prueba con Ollama caído)", "local", cuerpo(
        "Crea docs/notas-ensayo.md con un título '# Notas del ensayo' y una línea que diga que la tarea se "
        "completó tras recuperar Ollama.", "local", base, "_No response_", "docs/notas-ensayo.md",
        "- El archivo existe con el título indicado", "docs-notas"))
    t0 = time.time()
    coord("una-vez")
    con = C.db()
    f = dict(C.obtener(con, cfg["repo"], n))
    logs = list((C.LOGS / f"issue-{n}").glob("*")) if (C.LOGS / f"issue-{n}").exists() else []
    sin_relevo = not any("agente-claude" in p.name for p in logs) and f.get("agente") == "local"
    bloqueo_ok = f.get("estado") == "bloqueada" and "Ollama" in (f.get("causa") or "")
    anotar("ollama-caida-bloqueo", bloqueo_ok and sin_relevo,
           f"#{n}: estado={f.get('estado')} causa={f.get('causa')!r}; sin relevo de pago={sin_relevo}")
    if not a.no_interactivo:
        input("Arranca Ollama de nuevo (menú Inicio → Ollama, o `ollama serve` en otra terminal) y pulsa Intro…")
    for _ in range(30):
        if C.ollama_disponible(cfg)[0]:
            break
        time.sleep(2)
    coord("reanudar", str(n))
    coord("una-vez")
    f = dict(C.obtener(C.db(), cfg["repo"], n))
    anotar("ollama-caida-reanudacion", f.get("estado") == "revision" and bool(f.get("pr_url")),
           f"#{n}: estado={f.get('estado')} PR={f.get('pr_url')}", round(time.time() - t0, 1))


def cmd_completo(a) -> None:
    cmd_crear_issues(a)
    cmd_caida_tras_push(a)
    cmd_unicidad(a)
    cmd_integrar(a)
    cmd_ollama_caida(a)
    print("\nResumen:")
    for k, v in resultados().items():
        if isinstance(v, dict) and "ok" in v:
            print(f"  {'OK   ' if v['ok'] else 'FALLO'} {k}: {v['detalle']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("preparar-repo")
    x.add_argument("--nombre", default="equipo-ia-lab-ensayo")
    x.add_argument("--owner", help="Propietario (por defecto, tu cuenta de gh)")
    x.add_argument("--crear", action="store_true", help="Crear el repo privado si no existe (requiere tu confirmación)")
    x.add_argument("--remoto", help="URL de un remoto existente (solo pruebas)")
    x.set_defaults(f=cmd_preparar_repo)
    for nombre, fn in [("crear-issues", cmd_crear_issues), ("caida-tras-push", cmd_caida_tras_push),
                       ("unicidad", cmd_unicidad), ("integrar", cmd_integrar)]:
        sp.add_parser(nombre).set_defaults(f=fn)
    for nombre, fn in [("ollama-caida", cmd_ollama_caida), ("completo", cmd_completo)]:
        x = sp.add_parser(nombre)
        x.add_argument("--no-interactivo", action="store_true")
        x.set_defaults(f=fn)
    a = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a.f(a)


if __name__ == "__main__":
    main()
