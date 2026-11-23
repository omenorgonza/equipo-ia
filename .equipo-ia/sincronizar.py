#!/usr/bin/env python3
"""Movimientos del tablero que dependen de hechos verificables en GitHub (corre en Actions).

  pr-cerrada --pr N
      PR integrada en la rama objetivo con pruebas verdes → sus issues pasan a Done.
      Integrada sin pruebas verdes o cerrada sin integrar → se marca Bloqueo y se queda en Testing / Review.
  produccion
      Lee el último despliegue CORRECTO del entorno configurado (Deployments API) y reconcilia:
        Done con el cambio incluido → PRO
        PRO cuyo cambio ya no está en producción (reversión) o sin despliegue que lo acredite
        (movimiento manual) → vuelve a Done con una nota.
Arrastrar una tarjeta nunca ejecuta un despliegue: ningún workflow se dispara por cambios del tablero.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import tablero_lib as T  # noqa: E402

RAIZ = AQUI.parent
CONFIG = json.loads((AQUI / "mantenimiento.json").read_text(encoding="utf-8"))
GH = json.loads(os.environ.get("EQUIPO_IA_GH_BIN", '["gh"]'))
REPO = os.environ.get("GITHUB_REPOSITORY") or CONFIG["repo"]
RUN_URL = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
           if os.environ.get("GITHUB_RUN_ID") else "(ejecución local)")


def gh(*args, stdin_text=None, comprobar=True) -> str:
    r = subprocess.run(GH + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       input=stdin_text, timeout=120)
    if comprobar and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:500]}")
    return r.stdout


def es_ancestro(commit: str, sha: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", commit, sha], cwd=RAIZ).returncode == 0


def tablero() -> T.Tablero:
    tb = CONFIG.get("tablero", {})
    owner = os.environ.get("TABLERO_OWNER") or tb.get("owner")
    numero = os.environ.get("TABLERO_NUMERO") or tb.get("numero")
    if not (owner and numero):
        sys.exit("Falta TABLERO_OWNER / TABLERO_NUMERO")
    return T.Tablero(owner, int(numero), tb.get("owner_tipo", "user"), GH)


def comentar(numero: int, texto: str) -> None:
    gh("issue", "comment", str(numero), "--repo", REPO, "--body-file", "-", stdin_text=texto)


def rama_por_defecto() -> str:
    return json.loads(gh("repo", "view", REPO, "--json", "defaultBranchRef"))["defaultBranchRef"]["name"]


def cmd_pr_cerrada(a) -> None:
    pr = json.loads(gh("pr", "view", str(a.pr), "--repo", REPO, "--json",
                       "number,url,state,mergedAt,baseRefName,mergeCommit,closingIssuesReferences,statusCheckRollup"))
    issues = [i["number"] for i in pr.get("closingIssuesReferences") or []]
    if not issues:
        print("La PR no cierra ninguna issue; nada que mover.")
        return
    t = tablero()
    objetivo = CONFIG.get("rama_objetivo") or rama_por_defecto()
    checks = pr.get("statusCheckRollup") or []
    requeridos = set(CONFIG.get("pruebas_requeridas", []))
    nombres_ok = {c.get("name") or c.get("context") for c in checks
                  if (c.get("conclusion") or c.get("state")) in ("SUCCESS", "NEUTRAL", "SKIPPED")}
    faltan = sorted(requeridos - nombres_ok)
    fallidos = [c.get("name") for c in checks if (c.get("conclusion") or c.get("state")) in ("FAILURE", "ERROR", "TIMED_OUT")]
    for n in issues:
        it = t.item_de_issue(REPO, n)
        if not it:
            print(f"#{n} no está en el tablero")
            continue
        if not pr.get("mergedAt"):
            t.poner_texto(it["item_id"], T.CAMPO_BLOQUEO, f"PR #{pr['number']} cerrada sin integrar")
            print(f"#{n}: PR cerrada sin integrar → Bloqueo")
        elif pr["baseRefName"] != objetivo:
            print(f"#{n}: PR integrada en {pr['baseRefName']}, no en {objetivo}: sigue en {it['estado']}")
        elif faltan or fallidos:
            t.poner_texto(it["item_id"], T.CAMPO_BLOQUEO,
                          f"PR #{pr['number']} integrada sin pruebas verdes (faltan {faltan}, fallidas {fallidos})")
            print(f"#{n}: integrada sin pruebas requeridas verdes → Bloqueo, sigue en {it['estado']}")
        else:
            t.mover(it["item_id"], T.DONE)
            t.poner_texto(it["item_id"], T.CAMPO_BLOQUEO, "")
            comentar(n, f"✅ Integrada en `{objetivo}` con la PR #{pr['number']} "
                        f"(commit `{pr['mergeCommit']['oid'][:10]}`) y pruebas verdes. ¡Buen trabajo, equipo! → Done")
            print(f"#{n} → Done")


def ultimo_despliegue_correcto(entorno: str) -> dict | None:
    for d in json.loads(gh("api", f"repos/{REPO}/deployments?environment={entorno}&per_page=50")):
        estados = json.loads(gh("api", f"repos/{REPO}/deployments/{d['id']}/statuses?per_page=10"))
        if estados and estados[0]["state"] == "success":
            return {**d, "simulado": "SIMULADO" in (d.get("description") or ""), "log_url": estados[0].get("log_url")}
    return None


def commit_de_issue(n: int) -> str | None:
    """Merge commit de la PR que cerró la issue."""
    datos = json.loads(gh("issue", "view", str(n), "--repo", REPO, "--json", "closedByPullRequestsReferences"))
    for ref in datos.get("closedByPullRequestsReferences") or []:
        pr = json.loads(gh("pr", "view", str(ref["number"]), "--repo", REPO, "--json", "mergeCommit,mergedAt"))
        if pr.get("mergedAt") and pr.get("mergeCommit"):
            return pr["mergeCommit"]["oid"]
    return None


def cmd_produccion(_a) -> None:
    entorno = CONFIG["produccion"]["entorno"]
    dep = ultimo_despliegue_correcto(entorno)
    t = tablero()
    movidos = []
    sha = dep["sha"] if dep else None
    etiqueta = f"{entorno}{' [SIMULADO]' if dep and dep['simulado'] else ''}"
    print(f"Producción ({etiqueta}): {sha or 'sin despliegue correcto'}")
    for it in t.items():
        if it["repo"].lower() != REPO.lower() or it["estado"] not in (T.DONE, T.PRO):
            continue
        commit = commit_de_issue(it["numero"])
        incluido = bool(sha and commit and es_ancestro(commit, sha))
        if it["estado"] == T.DONE and incluido:
            t.mover(it["item_id"], T.PRO)
            comentar(it["numero"], f"🚀 En producción ({etiqueta}): el despliegue {dep['id']} de `{sha[:10]}` "
                                   f"contiene `{commit[:10]}`. {RUN_URL}")
            movidos.append((it["numero"], "PRO"))
        elif it["estado"] == T.PRO and not incluido:
            motivo = ("el último despliegue correcto ya no contiene el cambio (reversión)" if sha and commit
                      else "no hay un despliegue correcto que acredite el cambio (movimiento manual)")
            destino = T.DONE if commit else T.REVIEW
            if not commit:
                motivo = "su PR no está integrada y ningún despliegue la contiene (movimiento manual)"
            t.mover(it["item_id"], destino)
            comentar(it["numero"], f"↩️ Vuelve a {destino}: {motivo}. Producción: `{(sha or '-')[:10]}`. {RUN_URL}")
            movidos.append((it["numero"], destino))
    print(json.dumps({"sha_produccion": sha, "movidos": movidos}, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"## Sincronización PRO\n\nProducción {etiqueta}: `{sha}`\n\nMovidos: {movidos}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("pr-cerrada")
    x.add_argument("--pr", type=int, required=True)
    x.set_defaults(f=cmd_pr_cerrada)
    sp.add_parser("produccion").set_defaults(f=cmd_produccion)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
