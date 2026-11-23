#!/usr/bin/env python3
"""Aviso crítico: comprueba destinatario, canal y configuración; y ensaya el recorrido con un aviso SIMULADO.

El aviso inmediato real lo envía GitHub (Dependabot) a Óscar desde su detección, según sus ajustes de
notificaciones. Este script NO lo sustituye: comprueba que está activado y ensaya un aviso simulado que
llega como notificación de GitHub (issue creada por github-actions[bot] y asignada a Óscar).

Entorno: GH_TOKEN = GITHUB_TOKEN (para que la notificación venga de otra identidad) y
         ADMIN_TOKEN = token de Óscar (solo lectura de la configuración de seguridad).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.environ["GITHUB_REPOSITORY"]
DESTINATARIO = os.environ["DESTINATARIO"]
GH = json.loads(os.environ.get("EQUIPO_IA_GH_BIN", '["gh"]'))


def gh(*args, token=None, stdin_text=None):
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    return subprocess.run(GH + list(args), capture_output=True, text=True, env=env, input=stdin_text, timeout=120)


def main() -> None:
    admin = os.environ.get("ADMIN_TOKEN")
    filas = []
    r = gh("api", f"repos/{REPO}/vulnerability-alerts", "-i", token=admin)
    filas.append(("Dependabot alerts activado en el repo", "204" in (r.stdout.splitlines() or [""])[0],
                  "GET repos/{repo}/vulnerability-alerts → 204"))
    r = gh("api", f"repos/{REPO}/collaborators/{DESTINATARIO}/permission", token=admin)
    permiso = json.loads(r.stdout).get("permission") if r.returncode == 0 else f"error: {r.stderr.strip()[:120]}"
    filas.append((f"Destinatario {DESTINATARIO} con permiso para ver alertas", permiso in ("admin", "maintain", "write"),
                  f"permiso={permiso} (las alertas Dependabot se notifican a admins y a quien tenga acceso a ellas)"))
    filas.append(("Canal", None, "Notificaciones de GitHub de la cuenta (web y/o email). Revísalo en "
                                 "https://github.com/settings/notifications → «Dependabot alerts»: no se puede leer por API"))
    cuerpo = (f"## [SIMULADO] Aviso crítico de prueba\n\nEsto es un **ensayo**: no hay ninguna vulnerabilidad real.\n\n"
              f"- Destinatario: @{DESTINATARIO}\n- Canal: notificación de GitHub por asignación (y email si lo tienes activado)\n"
              f"- Diferencia con un aviso real: el real lo envía **Dependabot** con asunto «[{REPO}] … security alert» "
              f"y enlaza a Security → Dependabot; este lo crea **github-actions[bot]** con la etiqueta `simulado`.\n\n"
              "Cuando lo recibas, ciérralo con un comentario «recibido por <canal>» para dejar la evidencia.")
    r = gh("issue", "create", "--repo", REPO, "--title", "[SIMULADO] Aviso crítico de prueba",
           "--label", "simulado", "--assignee", DESTINATARIO, "--body-file", "-", stdin_text=cuerpo)
    filas.append(("Aviso simulado enviado", r.returncode == 0, r.stdout.strip() or r.stderr.strip()[:200]))
    salida = "\n".join(f"| {k} | {'✅' if ok else ('—' if ok is None else '❌')} | {d} |" for k, ok, d in filas)
    texto = f"## Aviso crítico: verificación\n\n| Comprobación | OK | Detalle |\n|---|---|---|\n{salida}\n"
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(texto)
    sys.exit(0 if all(ok is not False for _, ok, _ in filas) else 1)


if __name__ == "__main__":
    main()
