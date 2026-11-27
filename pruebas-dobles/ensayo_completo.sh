#!/usr/bin/env bash
# Ensayo completo del equipo contra el GitHub simulado (sin red ni credenciales).
# Lo usa la CI del repo equipo-ia como juez de cada PR. Uso: bash pruebas-dobles/ensayo_completo.sh [/tmp/sim]
set -euo pipefail
S=${1:-/tmp/sim-ci}
ORIG=$(cd "$(dirname "$0")/.." && pwd)
FALLOS=0
ok()   { echo "OK    $*"; }
mal()  { echo "FALLO $*"; FALLOS=$((FALLOS + 1)); }

rm -rf "$S" "$S".*
mkdir -p "$(dirname "$S")"
# Configuración de git aislada: los remotos simulados (url.insteadOf) no se mezclan con otras simulaciones.
export GIT_CONFIG_GLOBAL="$S.gitconfig"
: > "$GIT_CONFIG_GLOBAL"
git config --global user.email "ci@equipo-ia.local"
git config --global user.name "Equipo IA CI"
git config --global init.defaultBranch main

echo "== 1. Montar el laboratorio simulado (piloto v3: issues, caída tras push, migración a tablero)"
bash "$ORIG/pruebas-dobles/montar_simulacion.sh" "$S" > "$S.montaje.log" 2>&1 || { cat "$S.montaje.log"; exit 1; }
cd "$S/lab"
# shellcheck disable=SC1091
. "$S/env.sh"
mkdir -p "$S/remotos"; export FAKE_GH_REMOTOS="$S/remotos"

echo "== 2. Ensayos de aceptación del tablero"
python3 ensayo_tablero.py todos > "$S.tablero.log" 2>&1 || true
grep -E "^  (OK|FALLO)" "$S.tablero.log" || { tail -40 "$S.tablero.log"; mal "ensayo_tablero no terminó"; }
grep -qE "^  FALLO" "$S.tablero.log" && mal "algún ensayo del tablero falló" || ok "ensayos del tablero"

echo "== 3. Multiproyecto: migrar, crear proyecto nuevo con CI"
python3 equipo.py migrar > /dev/null && [ -f proyectos/ensayo/config.json ] && ok "migración a proyectos/ensayo" || mal "migración"
python3 equipo.py ensayo estado > /dev/null && ok "ensayo sigue operativo tras migrar" || mal "ensayo tras migrar"
python3 equipo.py nuevo demo --repo demo-app --stack python --descripcion "Proyecto de prueba de la CI" > "$S.nuevo.log" 2>&1 \
  && ok "nuevo proyecto con andamiaje" || { tail -20 "$S.nuevo.log"; mal "nuevo proyecto"; }
python3 -c "import json;c=json.load(open('proyectos/demo/config.json'));assert c['ci']['checks']==['pruebas'];assert c['fuente_cola']=='tablero'" \
  && ok "config del proyecto nuevo" || mal "config del proyecto nuevo"
python3 -c "
import json; import equipo as E
c=json.load(open('proyectos/demo/config.json')); e=json.load(open('proyectos/ensayo/config.json'))
assert c.get('color') in E.PALETA and e.get('color') in E.PALETA, (c.get('color'), e.get('color'))
assert c['color'] != e['color'], 'dos proyectos con el mismo color por defecto'
h=open('panel.html').read(); assert len(E.PALETA) == 8 and all('.c-'+x in h for x in E.PALETA)" \
  && ok "color por defecto de los proyectos (paleta de 8)" || mal "color por defecto"
python3 -c "
import json,os; s=json.load(open(os.environ['FAKE_GH_STATE']))
p=[p for p in s['projects'].values() if p['title']=='Equipo IA · demo'][0]
assert p.get('copiado_de'), 'el tablero no se copió de la plantilla'" && ok "tablero copiado de la plantilla" || mal "plantilla del tablero"

echo "== 4. CI del proyecto como juez: rojo → bloqueo con log → reintento → verde"
python3 - <<'PY'
import json, os
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
s["workflows"]["oscar/demo-app"] = {"path": ".github/workflows/pruebas.yml", "checks": ["pruebas"], "main": "success"}
s["ci"]["oscar/demo-app"] = "failure"
json.dump(s, open(st, "w"))
c = json.load(open("proyectos/demo/config.json")); c["ci"]["intervalo_s"] = 1; c["ci"]["timeout_s"] = 60
json.dump(c, open("proyectos/demo/config.json", "w"), indent=2)
PY
N=$(python3 equipo.py demo tablero nueva "Tarea de CI" --agente local --objetivo "Crea el archivo docs/ci.md con un título." \
  --archivo "docs/ci.md" --criterio "existe docs/ci.md" --prueba ci --todo | sed -n 's/^#\([0-9]*\) creada.*/\1/p')
[ -n "$N" ] && ok "tarea creada (#$N)" || mal "no se creó la tarea"
python3 equipo.py demo una-vez > "$S.ci1.log" 2>&1 || true
grep -q "CI en rojo" "$S.ci1.log" && ok "CI en rojo bloquea la tarea" || { cat "$S.ci1.log"; mal "CI en rojo"; }
N="$N" python3 - <<'PY'
import json, os
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
s["ci"]["oscar/demo-app"] = "success"
# Marca la descripción actual de la PR abierta de la tarea: el reproceso debe sustituirla.
for p in s["prs"]:
    if p["repo"] == "oscar/demo-app" and p["state"] == "OPEN" and p["head"].endswith(f"/issue-{os.environ['N']}"):
        p["body"] = "DESCRIPCION-ANTERIOR\n" + p.get("body", "")
s["calls"] = []
json.dump(s, open(st, "w"))
PY
python3 equipo.py demo reanudar "$N" --desde agente > /dev/null
python3 equipo.py demo una-vez > "$S.ci2.log" 2>&1 || true
grep -q "CI en verde" "$S.ci2.log" && ok "reintento con el log de la CI y CI en verde" || { cat "$S.ci2.log"; mal "CI en verde"; }
N="$N" python3 - <<'PY' && ok "descripción de la PR abierta actualizada por PATCH REST" || mal "descripción de la PR no actualizada"
import json, os
s = json.load(open(os.environ["FAKE_GH_STATE"]))
prs = [p for p in s["prs"] if p["repo"] == "oscar/demo-app" and p["state"] == "OPEN"
       and p["head"].endswith(f"/issue-{os.environ['N']}")]
assert len(prs) == 1, f"se esperaba una sola PR abierta de la tarea: {prs}"
b = prs[0]["body"]
assert "DESCRIPCION-ANTERIOR" not in b, "la descripción no cambió"
assert f"Closes #{os.environ['N']}" in b and "CI del proyecto" in b, b
assert "api -X PATCH" in s["calls"], s["calls"]
assert not any(c.startswith("pr edit") for c in s["calls"]), s["calls"]
PY
grep -q '"pr", "edit"' "$ORIG/coordinador.py" && mal "coordinador.py aún usa gh pr edit" || ok "coordinador.py no usa gh pr edit"
grep -q "la CI del proyecto falló" "proyectos/demo/estado/prompts/issue-$N.md" && ok "el agente recibió el log del fallo" || mal "log de CI en el prompt"

REM="$FAKE_GH_REMOTOS/demo-app.git"
subir_a() {  # subir_a <rama> <archivo> <texto>: otra persona sube un commit directamente a GitHub
  local d; d=$(mktemp -d "$S.clon.XXXXXX")
  git clone -q --branch "$1" "$REM" "$d/c"
  mkdir -p "$(dirname "$d/c/$2")"; printf '%s\n' "$3" > "$d/c/$2"
  git -C "$d/c" add -A && git -C "$d/c" commit -qm "Commit ajeno: $2" && git -C "$d/c" push -q origin "$1"
  rm -rf "$d"
}
nueva_tarea_ci() {  # nueva_tarea_ci <archivo> → número de la issue
  python3 equipo.py demo tablero nueva "Tarea $1" --agente local --objetivo "Crea el archivo $1 con un título." \
    --archivo "$1" --criterio "existe $1" --prueba ci --todo | sed -n 's/^#\([0-9]*\) creada.*/\1/p'
}
reiniciar_llamadas() {
  python3 -c "
import json,os; st=os.environ['FAKE_GH_STATE']; s=json.load(open(st)); s['calls']=[]; json.dump(s, open(st,'w'))"
}

echo "== 4 ter. PR con conflictos con la base: bloqueo inmediato → reintento desde la base actualizada → verde"
N1=$(nueva_tarea_ci docs/conflicto.md)
[ -n "$N1" ] && ok "tarea con conflicto creada (#$N1)" || mal "no se creó la tarea con conflicto"
python3 equipo.py demo una-vez --detener-tras worktree > "$S.conf0.log" 2>&1 || true
subir_a main docs/conflicto.md "# Versión que llegó antes a main"   # main avanza y choca con lo que hará el agente
reiniciar_llamadas
python3 equipo.py demo una-vez > "$S.conf1.log" 2>&1 || true
grep -q "PR con conflictos con main" "$S.conf1.log" && ! grep -q "no terminó a tiempo" "$S.conf1.log" \
  && ok "PR con conflictos bloqueada sin esperar al timeout" || { cat "$S.conf1.log"; mal "PR con conflictos no bloqueada"; }
N1="$N1" python3 - <<'PY' && ok "bloqueo en menos de dos consultas, con causa, archivos y recuperación" || mal "bloqueo por conflictos incompleto"
import json, os
n = os.environ["N1"]; s = json.load(open(os.environ["FAKE_GH_STATE"]))
pr = [p for p in s["prs"] if p["repo"] == "oscar/demo-app" and p["head"].endswith(f"/issue-{n}")][0]
vistas = [c for c in s["calls"] if c == f"pr view {pr['number']}"]
assert 1 <= len(vistas) < 2, s["calls"]
p = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
it = [it for it in p["items"].values() if s["issues"].get(it.get("issue", ""), {}).get("number") == int(n)][0]
b = it["fields"].get("Bloqueo") or ""
assert "PR con conflictos con main" in b and "docs/conflicto.md" in b and f"reanudar {n} --desde agente" in b, b
assert "Reintentar con el agente" in b, b
PY
python3 equipo.py demo reanudar "$N1" --desde agente > /dev/null
python3 equipo.py demo una-vez > "$S.conf2.log" 2>&1 || true
grep -q "CI en verde" "$S.conf2.log" && ok "reintento tras conflictos y CI en verde" || { cat "$S.conf2.log"; mal "reintento tras conflictos"; }
grep -q "conflictos con \`main\`" "proyectos/demo/estado/prompts/issue-$N1.md" \
  && grep -A1 "^Archivos en conflicto:" "proyectos/demo/estado/prompts/issue-$N1.md" | grep -q "^- docs/conflicto.md" \
  && ok "el agente recibió los archivos en conflicto" || mal "archivos en conflicto en el prompt"
git -C "$REM" merge-base --is-ancestor main "agente/local/issue-$N1" \
  && ok "la rama de la PR parte de main actualizada" || mal "la rama no parte de main actualizada"

echo "== 4 quater. Commits ajenos en la rama de la PR: cuenta la CI del HEAD remoto; reanudar --desde ci trae la rama"
N2=$(nueva_tarea_ci docs/ajeno.md)
[ -n "$N2" ] && ok "tarea con commit ajeno creada (#$N2)" || mal "no se creó la tarea con commit ajeno"
python3 equipo.py demo una-vez --detener-tras pr > "$S.ajeno0.log" 2>&1 || true
N2="$N2" python3 - <<'PY'
import json, os
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
for p in s["prs"]:
    if p["repo"] == "oscar/demo-app" and p["head"].endswith(f"/issue-{os.environ['N2']}"):
        p["commit_ajeno"] = True  # fake_gh lo sube a la rama en la primera consulta de la espera de la CI
json.dump(s, open(st, "w"))
PY
python3 equipo.py demo una-vez > "$S.ajeno1.log" 2>&1 || true
grep -q "commits nuevos" "$S.ajeno1.log" && grep -q "CI en verde" "$S.ajeno1.log" \
  && ok "commit ajeno durante la espera: cuenta su CI (verde → revisión)" || { cat "$S.ajeno1.log"; mal "commit ajeno durante la espera"; }
N2="$N2" python3 - <<'PY' && ok "la CI contada es la del commit ajeno" || mal "no se registró la CI del commit ajeno"
import json, os
s = json.load(open(os.environ["FAKE_GH_STATE"]))
pr = [p for p in s["prs"] if p["repo"] == "oscar/demo-app" and p["head"].endswith(f"/issue-{os.environ['N2']}")][0]
assert pr.get("commits_ajenos") and not pr["draft"], pr
PY
subir_a "agente/local/issue-$N2" docs/ajeno.md "# Retoque del TL"
python3 equipo.py demo reanudar "$N2" --desde ci > /dev/null
python3 equipo.py demo una-vez > "$S.ajeno2.log" 2>&1 || true
grep -q "CI en verde" "$S.ajeno2.log" && ok "reanudar --desde ci y CI en verde" || { cat "$S.ajeno2.log"; mal "reanudar --desde ci"; }
[ "$(git -C "proyectos/demo/worktrees/issue-$N2" rev-parse HEAD)" = "$(git -C "$REM" rev-parse "agente/local/issue-$N2")" ] \
  && grep -q "Retoque del TL" "proyectos/demo/worktrees/issue-$N2/docs/ajeno.md" \
  && ok "reanudar --desde ci trajo la rama remota al worktree" || mal "el worktree no tiene la rama remota"

echo "== 4 quinquies. Revisión entre agentes: rondas, corrección, escalado al senior, rondas agotadas y antes_de_pr"
mkdir -p "$S.revlib"
cat > "$S.revlib/revlib.py" <<'PY'
# Estado simulado de la tarea NR del proyecto demo: issue, PR, comentarios de la PR y campos de su tarjeta.
import json, os
n = int(os.environ["NR"])
s = json.load(open(os.environ["FAKE_GH_STATE"]))
clave = f"oscar/demo-app#{n}"
issue = s["issues"][clave]
prs = [p for p in s["prs"] if p["repo"] == "oscar/demo-app" and p["head"].endswith(f"/issue-{n}")]
pr = prs[0] if prs else {}
com = pr.get("comments", [])
tablero = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
campos = [it["fields"] for it in tablero["items"].values() if it.get("issue") == clave][0]
def lecciones(agente):
    p = f"lecciones/{agente}.md"
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""
PY
nueva_rev() {  # nueva_rev <nombre> <agente> <guion> <prueba> → número de la issue (el guion lo lee fake_agente como revisor)
  python3 equipo.py demo tablero nueva "Revisión $1" --agente "$2" \
    --objetivo "Crea el archivo docs/$1.md con un título. [REV:$3]" \
    --archivo "docs/$1.md" --criterio "existe docs/$1.md" --prueba "$4" --todo | sed -n 's/^#\([0-9]*\) creada.*/\1/p'
}
comprobar_rev() {  # comprobar_rev <issue> <mensaje> (script de python por stdin); usar siempre con `|| …` (set -e)
  if NR="$1" PYTHONPATH="$S.revlib" python3 -; then ok "$2"; else mal "$2"; return 1; fi
}

N=$(nueva_rev rev-ok local ok ci)
python3 equipo.py demo una-vez > "$S.rev-ok.log" 2>&1 || true
comprobar_rev "$N" "aprobada en 2 rondas, registradas en la PR (comentarios y descripción)" <<'PY' || cat "$S.rev-ok.log"
from revlib import *
assert campos["Estado"] == "Testing / Review", campos
assert len(com) == 2 and "Revisión 1/2 · revisor: claude" in com[0] and "Revisión 2/2 · revisor: claude" in com[1], com
b = pr["body"]
assert b.count("### Revisión entre agentes") == 1 and "aprobada** tras 2 rondas" in b and "Revisión 2/2 · revisor: claude" in b, b
assert not pr["draft"], "la PR sigue en borrador"
p = open(f"proyectos/demo/estado/prompts/issue-{n}-revision-1.md", encoding="utf-8").read()
for x in ("existe docs/rev-ok.md", "Hecho por el equipo", "CI del proyecto en verde", "LECCIONES del autor (local)", "SOLO LECTURA"):
    assert x in p, (x, p)
PY

N=$(nueva_rev rev-corrige local corrige ci)
python3 equipo.py demo una-vez > "$S.rev-corrige.log" 2>&1 || true
comprobar_rev "$N" "bloqueante en la ronda 1 → corrige el autor, CI otra vez y ronda 2 aprobada" <<'PY' || cat "$S.rev-corrige.log"
from revlib import *
assert campos["Estado"] == "Testing / Review" and issue["labels"] == ["agent:local"], (campos, issue["labels"])
assert len(com) == 2 and "1 bloqueante(s)" in com[0] and "aprobada" in com[1], com
assert "@oscar" not in com[0] and "#1" not in com[0], "el texto del revisor avisa a alguien o enlaza issues: " + com[0]
p = open(f"proyectos/demo/estado/prompts/issue-{n}-correccion-1.md", encoding="utf-8").read()
assert "Falta la explicación (corrige, ronda 1)" in p and "=== TAREA" in p, p
assert "Corregido" in open(f"proyectos/demo/worktrees/issue-{n}/docs/rev-corrige.md", encoding="utf-8").read()
PY
grep -c "CI en verde" "$S.rev-corrige.log" | grep -qx 2 && ok "la CI se repite tras la corrección" || mal "la CI no se repitió"
comprobar_rev "$N" "el hallazgo corregido pasa a lecciones/local.md y a su skill" <<'PY' || true
from revlib import *
t = "docs/rev-corrige.md: Falta la explicación (corrige, ronda 1)"
assert t in lecciones("local"), lecciones("local")
assert t in open(".opencode/skills/equipo-lecciones-local/SKILL.md", encoding="utf-8").read()
PY

N=$(nueva_rev rev-escala local escala ci)
python3 equipo.py demo una-vez > "$S.rev-escala.log" 2>&1 || true
comprobar_rev "$N" "bloqueantes tras la ronda 2 → escala al senior sobre la misma rama, con el historial" <<'PY' || cat "$S.rev-escala.log"
from revlib import *
assert campos["Estado"] == "Testing / Review" and issue["labels"] == ["agent:claude"], (campos, issue["labels"])
assert len(prs) == 1 and pr["head"] == f"agente/local/issue-{n}", prs
assert len(com) == 3 and "Revisión 3/3" in com[2] and "autor: claude" in com[2] and "aprobada" in com[2], com
assert any("pasa a `claude`" in c and "tras la revisión 2" in c and "Revisión 1/2" in c for c in issue["comments"]), issue["comments"]
p = open(f"proyectos/demo/estado/prompts/issue-{n}-correccion-2.md", encoding="utf-8").read()
assert "ha escalado a ti" in p and "Revisión 1/2" in p and "Falta la explicación (escala, ronda 2)" in p, p
assert "Escalada de `local` a `claude`" in pr["body"], pr["body"]
assert "(escala, ronda 1)" in lecciones("local") and "(escala, ronda" not in lecciones("claude")
PY
comprobar_rev "$N" "el senior delega una subtarea al junior (issue hija sin autorizar)" <<'PY' || true
from revlib import *
h = [i for i in s["issues"].values() if i["title"] == "Subtarea delegada al junior"]
assert len(h) == 1 and h[0]["labels"] == ["agent:local"] and f"### Dependencias\n\n#{n}" in h[0]["body"], h
assert not [it for it in tablero["items"].values() if it.get("issue") == f"oscar/demo-app#{h[0]['number']}"], "autorizada sin Óscar"
PY
python3 equipo.py demo reanudar "$N" --desde revision-agentes > /dev/null
python3 equipo.py demo una-vez > "$S.rev-escala2.log" 2>&1 || true
comprobar_rev "$N" "tras escalar, la tarea se reanuda con el senior (la etiqueta manda sobre el campo Agente)" <<'PY' || cat "$S.rev-escala2.log"
from revlib import *
assert "no coincide con la etiqueta" not in (campos.get("Bloqueo") or ""), campos
assert len(com) > 3 and "autor: claude" in com[3], com
PY

N=$(nueva_rev rev-agota claude agota ci)
python3 equipo.py demo una-vez > "$S.rev-agota.log" 2>&1 || true
comprobar_rev "$N" "rondas agotadas con el senior → Bloqueo con el resumen de hallazgos" <<'PY' || cat "$S.rev-agota.log"
from revlib import *
b = campos.get("Bloqueo") or ""
assert campos["Estado"] == "To Do" and "3 rondas agotadas" in b and "Falta la explicación (agota, ronda 3)" in b, campos
assert f"reanudar {n} --desde agente" in b and len(com) == 3 and pr["draft"], (b, com)
assert "(agota" not in lecciones("claude"), "lección de un hallazgo sin corregir"
PY

for GUION in edita intenta ilegible; do
  N=$(nueva_rev "rev-$GUION" local "$GUION" ci)
  python3 equipo.py demo una-vez > "$S.rev-$GUION.log" 2>&1 || true
  comprobar_rev "$N" "revisor que $GUION: la ronda no cuenta y se repite" <<'PY' || cat "$S.rev-$GUION.log"
from revlib import *
assert campos["Estado"] == "Testing / Review", campos
assert len(com) == 3 and "no cuenta" in com[0] and "Revisión 1/2" in com[1] and "Revisión 2/2" in com[2], com
wt = f"proyectos/demo/worktrees/issue-{n}"
assert not os.path.exists(wt + "/escrito-por-el-revisor.txt")
assert not any("Cambiado por el revisor" in open(f"{wt}/docs/{f}", encoding="utf-8").read() for f in os.listdir(wt + "/docs"))
PY
done

revision_demo() {  # revision_demo <pruebas_locales separadas por comas> <intensiva_cada>
  LOCALES="$1" CADA="$2" python3 - <<'PY'
import json, os
ruta = "proyectos/demo/config.json"; c = json.load(open(ruta))
c["pruebas"] = {"docs-tarea": ["{python}", "-c", "import glob,sys; sys.exit(0 if glob.glob('docs/*.md') else 1)"],
                "nota": ["{python}", "-c", "print('nota OK')"], "no-arranca": ["comando-que-no-existe-xyz"]}
c["revision"] = {"antes_de_pr": True, "pruebas_locales": os.environ["LOCALES"].split(","),
                 "intensiva_cada": int(os.environ["CADA"])}
json.dump(c, open(ruta, "w"), indent=2)
PY
}
prs_abiertas() {
  python3 -c "
import sqlite3; print(sqlite3.connect('proyectos/demo/estado/registro.db').execute('SELECT count(*) FROM tareas WHERE pr_numero IS NOT NULL').fetchone()[0])"
}
revision_demo docs-tarea,nota $(( $(prs_abiertas) + 2 ))   # la siguiente PR no es la intensiva
N=$(nueva_rev rev-previa local corrige docs-tarea)
python3 equipo.py demo una-vez > "$S.rev-previa.log" 2>&1 || true
APROBADA=$(grep -n "revisión entre agentes aprobada tras 2 rondas" "$S.rev-previa.log" | head -1 | cut -d: -f1 || true)
SUBIDA=$(grep -n "rama subida" "$S.rev-previa.log" | head -1 | cut -d: -f1 || true)
[ -n "$APROBADA" ] && [ -n "$SUBIDA" ] && [ "$APROBADA" -lt "$SUBIDA" ] \
  && ok "antes_de_pr: la rama y la PR van después de las dos rondas" || { cat "$S.rev-previa.log"; mal "antes_de_pr: orden"; }
comprobar_rev "$N" "antes_de_pr: la descripción documenta rondas, comandos, resultados y riesgos" <<'PY' || cat "$S.rev-previa.log"
from revlib import *
assert campos["Estado"] == "Testing / Review" and len(prs) == 1, (campos, prs)
b = pr["body"]
for x in ("Revisión 1/2 · revisor: claude", "Revisión 2/2 · revisor: claude", "1 bloqueante(s)", "Comandos ejecutados",
          "Revisión 1: `docs-tarea`", "Revisión 2: `docs-tarea`", "Revisión 2: `nota`", "código 0", "nota OK",
          "Riesgos residuales", "Sin prueba de carga"):
    assert x in b, (x, b)
assert "Revisión 1: `nota`" not in b and "intensiva" not in b and len(com) == 2, (b, com)
PY

revision_demo docs-tarea,no-arranca 0
N=$(nueva_rev rev-sin-evidencia local ok docs-tarea)
python3 equipo.py demo una-vez > "$S.rev-sin.log" 2>&1 || true
comprobar_rev "$N" "antes_de_pr sin evidencia de pruebas: Bloqueo y sin PR" <<'PY' || cat "$S.rev-sin.log"
from revlib import *
assert "Sin evidencia de pruebas" in (campos.get("Bloqueo") or "") and "no-arranca" in campos["Bloqueo"], campos
assert not prs and campos["Estado"] == "To Do", (prs, campos)
PY
[ -z "$(git -C "$REM" branch --list "agente/local/issue-$N")" ] && ok "sin evidencia tampoco se sube la rama" || mal "se subió la rama"

revision_demo docs-tarea,nota $(( $(prs_abiertas) + 1 ))   # la siguiente PR sí es la intensiva
N=$(nueva_rev rev-intensiva local ok docs-tarea)
python3 equipo.py demo una-vez > "$S.rev-intensiva.log" 2>&1 || true
comprobar_rev "$N" "intensiva_cada: tercera ronda intensiva antes de la PR que toca" <<'PY' || cat "$S.rev-intensiva.log"
from revlib import *
assert campos["Estado"] == "Testing / Review", campos
assert "Revisión 3/3 · revisor: claude · intensiva" in pr["body"] and "aprobada** tras 3 rondas" in pr["body"], pr["body"]
PY
python3 - <<'PY'
import json
ruta = "proyectos/demo/config.json"; c = json.load(open(ruta))
del c["revision"], c["pruebas"]
json.dump(c, open(ruta, "w"), indent=2)
PY
comprobar_rev "$N" "ninguna PR en Testing / Review sin dos rondas registradas" <<'PY' || true
from revlib import *
for it in tablero["items"].values():
    if it["fields"].get("Estado") == "Testing / Review":
        k = int(it["issue"].split("#")[1])
        p = [p for p in s["prs"] if p["repo"] == "oscar/demo-app" and p["head"].endswith(f"/issue-{k}")][0]
        assert len([c for c in p.get("comments", []) if "· revisor:" in c and "no cuenta" not in c]) >= 2, p
        assert "aprobada** tras" in p["body"], p["body"]
PY

echo "== 4 septies. Fallos del junior: reintento automático, escalado al senior y cuándo no se reintenta"
cat >> "$S.revlib/revlib.py" <<'PY'
import subprocess
def logs_agente(agente):  # veces que se invocó al agente como autor (salida de `una-vez` en LOGU)
    return open(os.environ["LOGU"], encoding="utf-8").read().count(f"#{n}: invocando agente '{agente}'\n")
def pendientes(agente):
    p = "proyectos/demo/estado/lecciones-pendientes.md"
    return (open(p, encoding="utf-8").read() if os.path.exists(p) else "").count(f"· {agente} · issue #{n}\n")
def en_rama(ruta=None):
    rama = f"agente/local/issue-{n}"; rem = os.environ["FAKE_GH_REMOTOS"] + "/demo-app.git"
    if ruta is None:
        return subprocess.run(["git", "-C", rem, "ls-tree", "-r", "--name-only", rama], capture_output=True, text=True).stdout.split()
    return subprocess.run(["git", "-C", rem, "show", f"{rama}:{ruta}"], capture_output=True, text=True).stdout
PY
nueva_fallo() {  # nueva_fallo <nombre> <agente> <guion de fallo de fake_agente> → número de la issue
  python3 equipo.py demo tablero nueva "Fallo $1" --agente "$2" \
    --objetivo "Crea el archivo docs/$1.md con un título. [FALLO:$3]" \
    --archivo "docs/$1.md" --criterio "existe docs/$1.md" --prueba ci --todo | sed -n 's/^#\([0-9]*\) creada.*/\1/p'
}
config_demo() {  # config_demo <clave> <valor JSON> | config_demo restaurar
  if [ "$1" = restaurar ]; then cp "$S.demo-config.bak" proyectos/demo/config.json; return; fi
  cp proyectos/demo/config.json "$S.demo-config.bak"
  CLAVE="$1" VALOR="$2" python3 - <<'PY'
import json, os
ruta = "proyectos/demo/config.json"; c = json.load(open(ruta))
c[os.environ["CLAVE"]] = json.loads(os.environ["VALOR"])
json.dump(c, open(ruta, "w"), indent=2)
PY
}

N=$(nueva_fallo fallo-fuera local fuera1)
python3 equipo.py demo una-vez > "$S.fallo-fuera.log" 2>&1 || true
export LOGU="$S.fallo-fuera.log"
comprobar_rev "$N" "junior fuera de alcance una vez: se reintenta solo y termina, sin Bloqueo ni archivos ajenos" <<'PY' || cat "$S.fallo-fuera.log"
from revlib import *
assert campos["Estado"] == "Testing / Review" and not campos.get("Bloqueo"), campos
assert issue["labels"] == ["agent:local"], issue["labels"]
assert "fuera-de-alcance.txt" not in en_rama() and f"docs/fallo-fuera.md" in en_rama(), en_rama()
assert logs_agente("local") == 2 and logs_agente("claude") == 0, (logs_agente("local"), logs_agente("claude"))
assert pendientes("local") == 1, pendientes("local")
p = open(f"proyectos/demo/estado/prompts/issue-{n}.md", encoding="utf-8").read()
assert "Diff fuera de alcance: fuera-de-alcance.txt" in p and "worktree se ha limpiado" in p, p
PY

N=$(nueva_fallo fallo-junior local junior)
python3 equipo.py demo una-vez > "$S.fallo-junior.log" 2>&1 || true
export LOGU="$S.fallo-junior.log"
comprobar_rev "$N" "junior falla dos veces: pasa a claude (etiqueta, campo Agente, comentario) y claude termina" <<'PY' || cat "$S.fallo-junior.log"
from revlib import *
assert campos["Estado"] == "Testing / Review" and not campos.get("Bloqueo"), campos
assert issue["labels"] == ["agent:claude"], issue["labels"]
assert "### Agente\n\nclaude\n" in issue["body"] and "### Agente\n\nlocal" not in issue["body"], issue["body"]
assert any("pasa a `claude`" in c and "Intento 2 (local" in c for c in issue["comments"]), issue["comments"]
assert en_rama("docs/fallo-junior.md") == "# Hecho por el equipo\n", "claude no partió de un worktree limpio"
assert logs_agente("local") == 2 and logs_agente("claude") == 1, (logs_agente("local"), logs_agente("claude"))
assert pendientes("local") == 2 and pendientes("claude") == 0, (pendientes("local"), pendientes("claude"))
assert "[claude]" in pr["title"] and "autor: claude" in com[0], (pr["title"], com)
p = open(f"proyectos/demo/estado/prompts/issue-{n}.md", encoding="utf-8").read()
assert "ha escalado a ti, el agente senior" in p and "Intento 2 (local" in p, p
PY

N=$(nueva_fallo fallo-cuota local cuota)
python3 equipo.py demo una-vez > "$S.fallo-cuota.log" 2>&1 || true
export LOGU="$S.fallo-cuota.log"
comprobar_rev "$N" "cuota agotada: Bloqueo como hoy, sin reintento ni escalado" <<'PY' || cat "$S.fallo-cuota.log"
from revlib import *
b = campos.get("Bloqueo") or ""
assert campos["Estado"] == "To Do" and "Cuota agotada" in b and "intento(s)" not in b, campos
assert issue["labels"] == ["agent:local"] and logs_agente("local") == 1 and logs_agente("claude") == 0, issue["labels"]
PY

config_demo ollama_url '"http://127.0.0.1:9"'
N=$(nueva_fallo fallo-ollama local ok)
python3 equipo.py demo una-vez > "$S.fallo-ollama.log" 2>&1 || true
export LOGU="$S.fallo-ollama.log"
config_demo restaurar
comprobar_rev "$N" "Ollama caído: Bloqueo como hoy, sin reintento ni escalado" <<'PY' || cat "$S.fallo-ollama.log"
from revlib import *
b = campos.get("Bloqueo") or ""
assert campos["Estado"] == "To Do" and "Ollama no disponible" in b and "intento(s)" not in b, campos
assert issue["labels"] == ["agent:local"] and logs_agente("claude") == 0, issue["labels"]
PY

N=$(nueva_fallo fallo-todos local todos)
python3 equipo.py demo una-vez > "$S.fallo-todos.log" 2>&1 || true
export LOGU="$S.fallo-todos.log"
comprobar_rev "$N" "también falla el senior: Bloqueo con el historial de los intentos" <<'PY' || cat "$S.fallo-todos.log"
from revlib import *
b = campos.get("Bloqueo") or ""
assert campos["Estado"] == "To Do" and "3 intento(s): local ✗, local ✗, claude ✗" in b, campos
assert issue["labels"] == ["agent:claude"], issue["labels"]
assert "Historial de intentos" in issue["comments"][-1] and "Intento 3 (claude" in issue["comments"][-1], issue["comments"]
assert pendientes("local") == 2 and pendientes("claude") == 0, (pendientes("local"), pendientes("claude"))
PY

config_demo escalar_fallos false
N=$(nueva_fallo fallo-sin-escalar local fuera1)
python3 equipo.py demo una-vez > "$S.fallo-sin.log" 2>&1 || true
export LOGU="$S.fallo-sin.log"
config_demo restaurar
comprobar_rev "$N" "escalar_fallos: false → Bloqueo al primer fallo, como antes" <<'PY' || cat "$S.fallo-sin.log"
from revlib import *
b = campos.get("Bloqueo") or ""
assert campos["Estado"] == "To Do" and "Diff fuera de alcance: fuera-de-alcance.txt" in b and "intento(s)" not in b, campos
assert issue["labels"] == ["agent:local"] and logs_agente("local") == 1, (issue["labels"], logs_agente("local"))
assert pendientes("local") == 1, pendientes("local")
PY

echo "== 4 bis. Vista «Tablero»: columnas por Estado (sin aviso) o por otro campo (aviso con el arreglo)"
python3 - <<'PY'
import json, os
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
for proyecto, campo in (("ensayo", "Estado"), ("demo", "Status")):
    n = str(json.load(open(f"proyectos/{proyecto}/config.json"))["tablero"]["numero"])
    s["projects"][n]["views"] = [{"name": "Tablero", "layout": "BOARD_LAYOUT", "agrupar": [campo]},
                                 {"name": "Planning", "layout": "TABLE_LAYOUT"}]
json.dump(s, open(st, "w"))
PY
python3 equipo.py ensayo tablero verificar > "$S.verif-ok.log" 2>&1 || true
if grep -q "Columnas de «Tablero»: \['Estado'\]" "$S.verif-ok.log" && ! grep -q "Column by" "$S.verif-ok.log"; then
  ok "agrupada por Estado: verificar sin aviso"
else cat "$S.verif-ok.log"; mal "verificar avisa con la vista agrupada por Estado"; fi
python3 equipo.py demo tablero verificar > "$S.verif-mal.log" 2>&1 || true
grep -q "agrupa las columnas por Status, no por Estado: Vista Tablero → Column by → Estado → Save" "$S.verif-mal.log" \
  && ok "agrupada por Status: verificar avisa con la instrucción" || { cat "$S.verif-mal.log"; mal "verificar sin aviso de agrupación"; }

echo "== 4 sexies. Siguiente paso recomendado (¿Qué hago ahora?) y campo «Siguiente» del tablero"
PYTHONPATH="$ORIG/repo-plantilla/.equipo-ia" python3 - <<'PY' && ok "siguiente paso: integrar, esperas por solape y dependencia, reanudar, solape inofensivo" || mal "siguiente paso (reglas)"
import tablero_lib as T
R = "oscar/x"
def card(n, estado, archivos=("coordinador.py",), agente="claude", deps=(), bloqueo=""):
    cuerpo = (f"### Agente\n\n{agente}\n\n### Archivos permitidos\n\n" + "\n".join(archivos) +
              "\n\n### Comando de prueba\n\nci\n\n### Dependencias\n\n" + (" ".join(f"#{d}" for d in deps) or "ninguna"))
    return {"item_id": f"I{n}", "numero": n, "repo": R, "titulo": f"Tarea {n}", "cuerpo": cuerpo,
            "creada": f"2026-01-{n:02d}", "abierta": True, "etiquetas": [f"agent:{agente}"], "estado": estado,
            "prioridad": "P2 normal", "bloqueo": bloqueo, "siguiente": "", "url": f"https://x/{n}"}
def pr(num, ci="verde", archivos=("coordinador.py",), conflicto=False):
    return {"pr": num, "url": f"https://x/pull/{num}", "ci": ci, "borrador": False, "conflicto": conflicto,
            "archivos": list(archivos)}
items = [card(1, T.REVIEW), card(2, T.PLANNING), card(3, T.PLANNING),
         card(4, T.PLANNING, archivos=("README.md", "docs/guia.md", "pruebas-dobles/ensayo_completo.sh")),
         card(5, T.PLANNING, archivos=("panel.py",), deps=(1,)),
         card(6, T.PLANNING, archivos=("equipo.py",), bloqueo="Bloqueo de un intento anterior"),
         card(7, T.DONE), card(8, T.PLANNING, archivos=("equipo.py",))]
items[6]["siguiente"] = "texto viejo"
rec = T.recomendar(items, {(R, 1): pr(10, archivos=("coordinador.py", "README.md", "docs/guia.md",
                                                    "pruebas-dobles/ensayo_completo.sh"))})
sig = {n: rec["tarjetas"][(R, n)] for n in range(1, 9)}
a = rec["acciones"]
assert a[0]["tipo"] == "integrar" and a[0]["numero"] == 1 and "PR #10" in a[0]["texto"], a
assert rec["resumen"].startswith("Siguiente paso: integrar la PR #10"), rec["resumen"]
assert sig[1].startswith("▶ 1 · integrar la PR #10"), sig[1]
for n in (2, 3):
    assert sig[n].startswith("⏸ espera") and "coordinador.py" in sig[n] and "PR #10" in sig[n], sig
    assert any(e["numero"] == n and "coordinador.py" in e["texto"] for e in rec["esperas"]), rec["esperas"]
assert sig[5].startswith("⏸ espera dependencia #1") and "en review, sin integrar" in sig[5], sig[5]
assert any(x["numero"] == 6 and x["tipo"] == "reanudar" and x["comando"] == "reanudar 6" for x in a), a
assert "reanudar 6" in sig[6], sig[6]
assert any(x["numero"] == 4 and x["tipo"] == "todo" for x in a), (a, sig[4])
assert sig[8].startswith("⏸ espera a #6") and "equipo.py" in sig[8], sig[8]
assert sig[7] == "", sig[7]
# CI en rojo o conflictos: no se integra; la acción es reintentar con el agente.
rec = T.recomendar(items[:1], {(R, 1): pr(10, ci="rojo")})
assert rec["acciones"][0]["comando"] == "reanudar 1 --desde agente", rec["acciones"]
rec = T.recomendar(items[:1], {(R, 1): pr(10, conflicto=True)})
assert rec["acciones"][0]["tipo"] == "arreglar" and "conflictos" in rec["acciones"][0]["texto"], rec["acciones"]
rec = T.recomendar(items[:1], {(R, 1): pr(10, ci="pendiente")})
assert not rec["acciones"] and rec["tarjetas"][(R, 1)].startswith("⏳"), rec
# Cadena en Review: la dependencia se integra antes aunque sea más nueva.
c = [card(11, T.REVIEW, archivos=("a.py",), deps=(12,)), card(12, T.REVIEW, archivos=("b.py",))]
rec = T.recomendar(c, {(R, 11): pr(21), (R, 12): pr(22)})
assert [x["numero"] for x in rec["acciones"]] == [12, 11], rec["acciones"]
assert T.resumen_ci([{"status": "COMPLETED", "conclusion": "SUCCESS"}]) == "verde"
assert T.resumen_ci([{"status": "IN_PROGRESS", "conclusion": ""}]) == "pendiente"
assert T.resumen_ci([{"status": "COMPLETED", "conclusion": "FAILURE"}]) == "rojo" and T.resumen_ci([]) == "sin_ci"
PY
escrituras() {
  python3 -c "import json,os; print(json.load(open(os.environ['FAKE_GH_STATE'])).get('escrituras', {}).get('Siguiente', 0))"
}
python3 equipo.py demo tablero siguiente > "$S.sig1.log" 2>&1 || true
E1=$(escrituras)
python3 - <<'PY' && ok "campo Siguiente rellenado en el tablero simulado (integrar primero)" || { cat "$S.sig1.log"; mal "campo Siguiente no rellenado"; }
import json, os
s = json.load(open(os.environ["FAKE_GH_STATE"]))
p = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
review = [it["fields"] for it in p["items"].values() if it["fields"].get("Estado") == "Testing / Review"]
assert review and all(f.get("Siguiente") for f in review), review
assert any((f.get("Siguiente") or "").startswith("▶ 1 · integrar la PR #") for f in review), review
bloqueadas = [it["fields"] for it in p["items"].values() if it["fields"].get("Bloqueo")]
assert all("reanudar" in (f.get("Siguiente") or "") for f in bloqueadas), bloqueadas
PY
grep -q "^Siguiente paso: integrar la PR #" "$S.sig1.log" && grep -q "tarjeta(s) actualizada(s)" "$S.sig1.log" \
  && ok "tablero siguiente: la primera acción es integrar la PR" || { cat "$S.sig1.log"; mal "tablero siguiente: resumen"; }
python3 equipo.py demo tablero siguiente > "$S.sig2.log" 2>&1 || true
[ "$(escrituras)" = "$E1" ] && grep -q "0 tarjeta(s) actualizada(s)" "$S.sig2.log" \
  && ok "sin cambios no se vuelve a escribir el campo Siguiente" || { cat "$S.sig2.log"; mal "escrituras repetidas del campo Siguiente"; }
python3 - <<'PY' || mal "no pude simular la integración de una tarjeta en Review"
import json, os
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
p = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
it = next(it for it in p["items"].values() if it["fields"].get("Estado") == "Testing / Review")
it["fields"]["Estado"] = "Done"               # simula la integración: la tarjeta sale de Review
s["issues"][it["issue"]]["state"] = "CLOSED"
n = s["issues"][it["issue"]]["number"]
for pr in s["prs"]:
    if pr["repo"] == "oscar/demo-app" and pr["head"].endswith(f"/issue-{n}"):
        pr["state"], pr["merged"] = "MERGED", True
s["sig_integrada"] = it["issue"]
json.dump(s, open(st, "w"))
PY
python3 equipo.py demo tablero siguiente > "$S.sig3.log" 2>&1 || true
python3 - <<'PY' && ok "campo Siguiente vaciado al integrarse la tarjeta" || { cat "$S.sig3.log"; mal "campo Siguiente no vaciado"; }
import json, os
s = json.load(open(os.environ["FAKE_GH_STATE"]))
p = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
it = next(it for it in p["items"].values() if it.get("issue") == s["sig_integrada"])
assert not it["fields"].get("Siguiente"), it["fields"]
PY

echo "== 4 octies. Dependencias «Blocked by» de GitHub: tablero.py nueva --dep, coordinador (unión con la sección)"
num_de() { sed -n 's/^#\([0-9]*\) creada.*/\1/p'; }
ND=$(python3 equipo.py demo tablero nueva "Dependencia en Backlog" --agente local --objetivo "Crea docs/dep-base.md." \
  --archivo "docs/dep-base.md" --criterio "existe docs/dep-base.md" --prueba ci | num_de)
NR=$(python3 equipo.py demo tablero nueva "Espera por relación" --agente local --objetivo "Crea docs/dep-rel.md." \
  --archivo "docs/dep-rel.md" --criterio "existe docs/dep-rel.md" --prueba ci --todo | num_de)
python3 equipo.py demo tablero nueva "Espera por --dep" --agente local --objetivo "Crea docs/dep-sec.md." \
  --archivo "docs/dep-sec.md" --criterio "existe docs/dep-sec.md" --prueba ci --dep "$ND" --todo > "$S.dep1.log" 2>&1 || true
NS=$(num_de < "$S.dep1.log")
[ -n "$ND" ] && [ -n "$NR" ] && [ -n "$NS" ] && ok "tareas de dependencias creadas (#$ND Backlog, #$NR y #$NS To Do)" \
  || { cat "$S.dep1.log"; mal "no se crearon las tareas de dependencias"; }
ND="$ND" NR="$NR" NS="$NS" python3 - <<'PY' && grep -q "Blocked by #$ND: relación creada" "$S.dep1.log" \
  && ok "tablero.py nueva --dep crea la relación «blocked by» (POST con el id numérico) y la sección" \
  || { cat "$S.dep1.log"; mal "tablero.py nueva --dep no creó la relación"; }
import json, os
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
k = lambda n: f"oscar/demo-app#{os.environ[n]}"
i = s["issues"][k("NS")]
assert i.get("blocked_by") == [k("ND")], i.get("blocked_by")
assert f"### Dependencias\n\n#{os.environ['ND']}" in i["body"], i["body"]
assert "api -X POST" in s["calls"], s["calls"][-10:]
# #NR: sin sección de dependencias; Óscar añade «Blocked by #ND» desde la tarjeta en GitHub.
assert "### Dependencias\n\nninguna" in s["issues"][k("NR")]["body"]
s["issues"][k("NR")]["blocked_by"] = [k("ND")]
json.dump(s, open(st, "w"), indent=1)
PY
FAKE_GH_FALLA_DEPENDENCIAS=1 python3 equipo.py demo tablero nueva "Dependencia con la API caída" --dep "$ND" > "$S.dep2.log" 2>&1 \
  && grep -q "Aviso: no pude crear la relación «blocked by» #$ND" "$S.dep2.log" && [ -n "$(num_de < "$S.dep2.log")" ] \
  && ok "si la API de dependencias falla, tablero.py nueva avisa y no aborta" || { cat "$S.dep2.log"; mal "fallo de la API de dependencias"; }
python3 equipo.py demo una-vez > "$S.dep3.log" 2>&1 || true
ND="$ND" NR="$NR" NS="$NS" python3 - "$S.dep3.log" <<'PY' && ok "coordinador: «blocked by» abierta sin sección espera igual que con la sección" \
  || { cat "$S.dep3.log"; mal "coordinador: dependencias «blocked by»"; }
import json, os, sys
res = json.loads([l for l in open(sys.argv[1], encoding="utf-8").read().splitlines() if l.startswith("{")][-1])
nr, ns = int(os.environ["NR"]), int(os.environ["NS"])
assert nr in res.get("esperando_dependencias", []) and ns in res.get("esperando_dependencias", []), res
s = json.load(open(os.environ["FAKE_GH_STATE"]))
p = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
for n in (nr, ns):
    f = next(it["fields"] for it in p["items"].values() if it.get("issue") == f"oscar/demo-app#{n}")
    assert f.get("Estado") == "To Do" and not f.get("Bloqueo"), (n, f)
PY
ND="$ND" NR="$NR" python3 - <<'PY' && ok "coordinador: unión de sección y «blocked by»; cerrada → lista; API caída → solo la sección" \
  || mal "coordinador: reglas de la unión de dependencias"
import json, os, sys
sys.argv = ["coordinador.py"]
os.environ["EQUIPO_IA_PROYECTO"] = "demo"
import coordinador as C
proc = C.Procesador(C.cargar_config())
nd, nr = int(os.environ["ND"]), int(os.environ["NR"])
assert proc.dependencias_de(nr, []) == [nd], proc.dependencias_de(nr, [])
assert proc.dependencias_de(nr, [nd, 1]) == [nd, 1], proc.dependencias_de(nr, [nd, 1])
assert proc.dependencias_listas([nd]) == [nd]
st = os.environ["FAKE_GH_STATE"]; s = json.load(open(st))
s["issues"][f"oscar/demo-app#{nd}"]["state"] = "CLOSED"; json.dump(s, open(st, "w"), indent=1)
try:
    assert proc.dependencias_de(nr, []) == [], "una relación cerrada no hace esperar"
finally:
    s = json.load(open(st)); s["issues"][f"oscar/demo-app#{nd}"]["state"] = "OPEN"; json.dump(s, open(st, "w"), indent=1)
os.environ["FAKE_GH_FALLA_DEPENDENCIAS"] = "1"
assert proc.dependencias_de(nr, [7]) == [7]
del os.environ["FAKE_GH_FALLA_DEPENDENCIAS"]
assert proc.dependencias_listas(["otro/repo#3"]) == ["otro/repo#3"]
assert C.relaciones_bloqueo([{"number": 3, "state": "closed", "repository_url": "https://api.github.com/repos/o/r"}], "x/y") \
    == [{"repo": "o/r", "numero": 3, "abierta": False, "url": "https://github.com/o/r/issues/3"}]
PY

echo "== 5. Panel local"
PUERTO=8791
python3 equipo.py panel --puerto $PUERTO --no-abrir > "$S.panel.log" 2>&1 &
PANEL=$!
LISTO=no
for _ in $(seq 1 60); do   # hasta 30 s: el runner de GitHub puede tardar en arrancar el panel
  if curl -sf "http://127.0.0.1:$PUERTO/" | grep -q "Equipo IA"; then LISTO=si; break; fi
  sleep 0.5
done
[ "$LISTO" = si ] && ok "panel responde" || { mal "panel no responde"; tail -20 "$S.panel.log"; }
curl -sf "http://127.0.0.1:$PUERTO/api/estado" | python3 -c "
import json,sys; d=json.load(sys.stdin); n=[p['nombre'] for p in d['proyectos']]
assert {'ensayo','demo'} <= set(n), n
assert all(p['error'] is None for p in d['proyectos']), [p['error'] for p in d['proyectos']]" && ok "estado de todos los proyectos" || mal "api/estado"
curl -sf "http://127.0.0.1:$PUERTO/api/estado" | python3 -c "
import json,sys; d={p['nombre']: p for p in json.load(sys.stdin)['proyectos']}
s=d['demo']['siguiente']
assert s['resumen'].startswith('Siguiente paso: integrar la PR #') and s['acciones'][0]['tipo'] == 'integrar', s
ts=[t for g in d['demo']['tarjetas'].values() for t in g]
assert any(t['siguiente'].startswith('▶ 1 · integrar') for t in ts), ts
assert all(t['siguiente'] for t in d['demo']['tarjetas'].get('Testing / Review', [])), ts" \
  && grep -q 'id="siguiente"' panel.html && grep -q "¿Qué hago ahora?" panel.html && grep -q "t.siguiente" panel.html \
  && ok "panel: banner «¿Qué hago ahora?» y siguiente paso por tarjeta" || mal "panel: banner del siguiente paso"
curl -sf "http://127.0.0.1:$PUERTO/api/estado" | python3 -c "
import json,sys; d={p['nombre']: p for p in json.load(sys.stdin)['proyectos']}
aviso = lambda p: [a for a in d[p]['atencion'] if a['tipo'] == 'instalacion' and 'Column by' in a['texto']]
assert not aviso('ensayo'), aviso('ensayo')
assert aviso('demo') and 'Column by → Estado → Save' in aviso('demo')[0]['texto'], d['demo']['atencion']" \
  && ok "panel: aviso de agrupación solo en el proyecto agrupado por Status" || mal "panel: aviso de agrupación"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PUERTO/api/proyecto/demo/arrancar")
[ "$CODIGO" = "403" ] && ok "acciones sin token rechazadas" || mal "acción sin token devolvió $CODIGO"
API="http://127.0.0.1:$PUERTO/api/proyecto"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" \
  -d '{"titulo":"Sin token"}' "$API/demo/tarea")
[ "$CODIGO" = "403" ] && ok "crear tarea sin token rechazada" || mal "crear tarea sin token devolvió $CODIGO"
TOKEN=$(curl -sf "http://127.0.0.1:$PUERTO/" | sed -n 's/.*const TOKEN = "\([^"]*\)".*/\1/p')
[ -n "$TOKEN" ] && ok "token del panel" || mal "no encontré el token en la página del panel"
tarea() {  # tarea <proyecto> <json> → imprime «código cuerpo»
  curl -s -w '\n%{http_code}' -X POST -H "Content-Type: application/json" -H "X-Token: $TOKEN" -d "$2" "$API/$1/tarea"
}
ISSUES_ANTES=$(python3 -c "import json,os;print(len(json.load(open(os.environ['FAKE_GH_STATE']))['issues']))")
R=$(tarea demo '{"titulo":"Incompleta","todo":true}')
[ "$(tail -1 <<<"$R")" = "400" ] && grep -q "Para --todo" <<<"$R" \
  && ok "validación de tablero.py nueva (--todo incompleta) devuelta al formulario" || mal "validación --todo: $R"
R=$(tarea ensayo '{"titulo":"Con CI","agente":"local","archivos":"a.txt","criterios":"existe","prueba":"ci","todo":true}')
[ "$(tail -1 <<<"$R")" = "400" ] && grep -q "no tiene CI" <<<"$R" \
  && ok "prueba «ci» rechazada en un proyecto sin ci.checks" || mal "validación ci: $R"
ISSUES_DESPUES=$(python3 -c "import json,os;print(len(json.load(open(os.environ['FAKE_GH_STATE']))['issues']))")
[ "$ISSUES_ANTES" = "$ISSUES_DESPUES" ] && ok "los errores de validación no crean nada" || mal "se crearon issues con datos no válidos"
R=$(tarea demo '{"titulo":"Tarea desde el panel","objetivo":"Documentar el panel en docs/panel.md.","agente":"claude",
  "archivos":"docs/panel.md\ndocs/indice.md","criterios":"existe docs/panel.md\nenlazado desde el índice","prueba":"ci",
  "dependencias":"#3 4","prioridad":"P1"}')
[ "$(tail -1 <<<"$R")" = "200" ] && ok "tarea creada desde el panel" || mal "crear tarea desde el panel: $R"
R2=$(tarea demo '{"titulo":"Tarea directa","agente":"local","archivos":["docs/b.md"],"criterios":["existe docs/b.md"],
  "prueba":"ci","todo":true}')
[ "$(tail -1 <<<"$R2")" = "200" ] && ok "tarea directa a To Do creada desde el panel" || mal "tarea directa: $R2"
python3 - <<'PY' && ok "tarjetas en el tablero simulado con todos los campos (Planning y To Do)" || mal "tarjetas del panel en el tablero"
import json, os
s = json.load(open(os.environ["FAKE_GH_STATE"]))
p = [p for p in s["projects"].values() if p["title"] == "Equipo IA · demo"][0]
def tarjeta(titulo):
    for it in p["items"].values():
        i = s["issues"].get(it.get("issue", ""))
        if i and i["title"] == titulo:
            return i, it["fields"]
    raise AssertionError(f"no está en el tablero: {titulo}")
i, f = tarjeta("Tarea desde el panel")
assert f.get("Estado") == "Planning", f
assert (f.get("Prioridad") or "").startswith("P1"), f
b = i["body"]
for trozo in ("Documentar el panel en docs/panel.md.", "### Agente\n\nclaude", "docs/panel.md\ndocs/indice.md",
              "- existe docs/panel.md\n- enlazado desde el índice", "### Comando de prueba\n\nci", "#3 #4"):
    assert trozo in b, (trozo, b)
assert any("claude" in l for l in i["labels"]), i["labels"]
i, f = tarjeta("Tarea directa")
assert f.get("Estado") == "To Do", f
assert (f.get("Prioridad") or "").startswith("P2"), f
PY
mover_dep() {  # mover_dep <Estado>: mueve la tarjeta de la dependencia #ND en el tablero simulado
  ND="$ND" E="$1" python3 -c "
import json,os; st=os.environ['FAKE_GH_STATE']; s=json.load(open(st))
p=[p for p in s['projects'].values() if p['title']=='Equipo IA · demo'][0]
it=next(it for it in p['items'].values() if it.get('issue')=='oscar/demo-app#'+os.environ['ND'])
it['fields']['Estado']=os.environ['E']; json.dump(s, open(st,'w'), indent=1)"
}
dep_panel() {  # dep_panel <Estado esperado de #ND | vivo>: «espera a #ND» en #NR y #NS y aviso solo si no está vivo
  curl -sf "http://127.0.0.1:$PUERTO/api/estado?refrescar=1" | ND="$ND" NR="$NR" NS="$NS" E="$1" python3 -c "
import json,os,sys; d={p['nombre']: p for p in json.load(sys.stdin)['proyectos']}['demo']
nd, e = int(os.environ['ND']), os.environ['E']
todo = {t['numero']: t for t in d['tarjetas'].get('To Do', [])}
for n in (int(os.environ['NR']), int(os.environ['NS'])):
    esp = todo[n].get('espera') or []
    assert [x['numero'] for x in esp] == [nd] and esp[0]['texto'] == f'#{nd}', (n, esp)
    assert esp[0]['url'].endswith(f'/issues/{nd}'), esp
    av = [a for a in d['atencion'] if a['tipo'] == 'dependencia' and a['numero'] == n]
    if e == 'vivo':
        assert not av, av
    else:
        assert len(av) == 1 and f'espera a #{nd}, que está en {e}' in av[0]['texto'] and 'para siempre' in av[0]['texto'], av
"
}
dep_panel Backlog && ok "panel: «espera a #N» en To Do y aviso con la dependencia en Backlog" || mal "panel: dependencia en Backlog"
mover_dep Planning && dep_panel Planning && ok "panel: aviso con la dependencia en Planning" || mal "panel: dependencia en Planning"
mover_dep Doing && dep_panel vivo && ok "panel: dependencia en curso → espera sin aviso" || mal "panel: dependencia en curso"
mover_dep Backlog
grep -q "espera a" panel.html && grep -q "t.espera" panel.html && ok "panel.html pinta «espera a #N» con enlace" || mal "panel.html: espera a"

echo "== 5b. Guardar TABLERO_TOKEN desde el panel (tokens falsos; el valor no debe tocar disco ni respuestas)"
XTOK=$(curl -s "http://127.0.0.1:$PUERTO/" | sed -n 's/.*const TOKEN = "\([^"]*\)".*/\1/p')
ALEA=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
TOK_BUENO="ghp_fake_oscar_repo+project_$ALEA"
TOK_SINPROJ="ghp_fake_oscar_repo_$ALEA"
TOK_OTRO="ghp_fake_mallory_repo+project_$ALEA"
TOK_FINO="ghp_fake_oscar_finegrained_$ALEA"
TOK_MALO="ghp_fake_revocado$ALEA"
secreto() {  # $1 = token, $2 = fichero de respuesta, $3 = X-Token (opcional)
  local cab=(-H "Content-Type: application/json")
  if [ -n "${3:-}" ]; then cab+=(-H "X-Token: $3"); fi
  printf '{"token":"%s"}' "$1" | curl -s -o "$2" -w '%{http_code}' -X POST "${cab[@]}" \
    --data-binary @- "http://127.0.0.1:$PUERTO/api/proyecto/demo/secreto"
}
tiene_secreto() {
  python3 -c "
import json,os,sys; s=json.load(open(os.environ['FAKE_GH_STATE']))
sys.exit(0 if 'TABLERO_TOKEN' in s.get('secrets',{}).get('oscar/demo-app',[]) else 1)"
}
CODIGO=$(secreto "$TOK_BUENO" "$S.secreto.403.json")
[ "$CODIGO" = "403" ] && ok "guardar secreto sin X-Token: 403" || mal "guardar secreto sin X-Token devolvió $CODIGO"
for caso in MALO:revocado SINPROJ:permisos OTRO:usuario FINO:clasico; do
  var="TOK_${caso%%:*}"; etiqueta=${caso#*:}
  secreto "${!var}" "$S.secreto.$etiqueta.json" "$XTOK" > /dev/null
  python3 -c "
import json; r=json.load(open('$S.secreto.$etiqueta.json'))
assert r['ok'] is False and r['mensaje'] and not r['guardados'], r" \
    && ! tiene_secreto && ok "token $etiqueta rechazado: $(python3 -c "import json;print(json.load(open('$S.secreto.$etiqueta.json'))['mensaje'])")" \
    || mal "token $etiqueta no se rechazó o se guardó"
done
secreto "$TOK_BUENO" "$S.secreto.ok.json" "$XTOK" > /dev/null
python3 -c "
import json; r=json.load(open('$S.secreto.ok.json'))
assert r['ok'] is True and r['guardados'] == ['oscar/demo-app'] and 'oscar/demo-app' in r['mensaje'], r" \
  && tiene_secreto && ok "token válido guardado en todos los repos del proyecto" || { cat "$S.secreto.ok.json"; mal "token válido"; }
python3 -c "
import hashlib,json,os; s=json.load(open(os.environ['FAKE_GH_STATE']))
assert s['secretos_sha']['oscar/demo-app:TABLERO_TOKEN'] == hashlib.sha256(b'$TOK_BUENO').hexdigest()" \
  && ok "el secreto llegó íntegro por stdin" || mal "valor del secreto incorrecto"
curl -sf "http://127.0.0.1:$PUERTO/api/estado?refrescar=1" | python3 -c "
import json,sys; d=json.load(sys.stdin); p=[p for p in d['proyectos'] if p['nombre']=='demo'][0]
assert all(r['secreto'] is True for r in p['repos']), p['repos']" && ok "el panel ve el secreto guardado" || mal "estado del secreto tras guardar"
FUGAS=""
for t in "$TOK_BUENO" "$TOK_SINPROJ" "$TOK_OTRO" "$TOK_FINO" "$TOK_MALO" "$ALEA"; do
  FUGAS+=$(grep -rlF -- "$t" "$S" "$S".* 2>/dev/null || true)
done
[ -z "$FUGAS" ] && ok "el token no aparece en logs, estado ni respuestas" || mal "el token aparece en: $FUGAS"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" -d '{"color":"rosa"}' \
  "http://127.0.0.1:$PUERTO/api/proyecto/demo/color")
[ "$CODIGO" = "403" ] && ok "cambio de color sin token rechazado" || mal "color sin token devolvió $CODIGO"
TOKEN=$(curl -sf "http://127.0.0.1:$PUERTO/" | sed -n 's/^const TOKEN = "\([^"]*\)";.*/\1/p')
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" -H "X-Token: $TOKEN" \
  -d '{"color":"no-existe"}' "http://127.0.0.1:$PUERTO/api/proyecto/demo/color")
[ "$CODIGO" = "400" ] && ok "color fuera de la paleta rechazado" || mal "color no válido devolvió $CODIGO"
curl -sf -X POST -H "Content-Type: application/json" -H "X-Token: $TOKEN" -d '{"color":"rosa"}' \
  "http://127.0.0.1:$PUERTO/api/proyecto/demo/color" > /dev/null \
  && python3 -c "import json;assert json.load(open('proyectos/demo/config.json'))['color']=='rosa'" \
  && curl -sf "http://127.0.0.1:$PUERTO/api/estado" | python3 -c "
import json,sys; d=json.load(sys.stdin); assert [p['color'] for p in d['proyectos'] if p['nombre']=='demo']==['rosa']" \
  && ok "color guardado con token en config.json" || mal "color con token no se guardó"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{"numero": 1}' "http://127.0.0.1:$PUERTO/api/proyecto/demo/reanudar")
[ "$CODIGO" = "403" ] && ok "reanudar sin token rechazado" || mal "reanudar sin token devolvió $CODIGO"

echo "== 5c. Progreso en directo de las tareas en Doing (log del agente, posible atasco, salida de Doing)"
python3 - <<'PY'
import json
c = json.load(open("proyectos/demo/config.json")); c["umbral_atasco_s"] = 2   # umbral bajo solo para el ensayo
json.dump(c, open("proyectos/demo/config.json", "w"), indent=2)
PY
NP=$(python3 equipo.py demo tablero nueva "Tarea en directo" --agente claude \
  --objetivo "Crea el archivo docs/progreso.md con un título. PASO-A-PASO" \
  --archivo "docs/progreso.md" --criterio "existe docs/progreso.md" --prueba ci --todo | sed -n 's/^#\([0-9]*\) creada.*/\1/p')
[ -n "$NP" ] && ok "tarea en directo creada (#$NP)" || mal "no se creó la tarea en directo"
# fake_agente piensa (30 eventos thinking_tokens), escribe poco a poco (1 s entre eventos) y después calla 15 s:
# con umbral 2 s, posible atasco.
FAKE_AGENTE_PENSAR_N=30 FAKE_AGENTE_PENSAR_S=0.4 FAKE_AGENTE_PASO_S=1 FAKE_AGENTE_SILENCIO_S=15 \
  python3 equipo.py demo una-vez > "$S.prog.log" 2>&1 &
UNAVEZ=$!
NP="$NP" PUERTO="$PUERTO" python3 - <<'PY' || FALLOS=$((FALLOS + 1))
import json, os, re, sys, time, urllib.request
n = int(os.environ["NP"]); base = f"http://127.0.0.1:{os.environ['PUERTO']}"
fallos = 0
def get(ruta):
    return json.load(urllib.request.urlopen(base + ruta, timeout=60))
def demo(refrescar=False):
    return [p for p in get("/api/estado" + ("?refrescar=1" if refrescar else ""))["proyectos"] if p["nombre"] == "demo"][0]
def prog(p):
    return next((x for x in p.get("progreso") or [] if x["numero"] == n), None)
def esperar(cond, s=40):
    fin = time.time() + s
    while time.time() < fin:
        r = cond()
        if r:
            return r
        time.sleep(0.4)
    return None
def check(cond, msg, detalle=""):
    global fallos
    print(("OK    " if cond else "FALLO ") + msg + ("" if cond else f" — {detalle}"))
    fallos += 0 if cond else 1
pg = esperar(lambda: (lambda x: x if x and x["paso"] == "agente" else None)(prog(demo())))
check(pg is not None, "/api/estado devuelve el progreso de la tarea en curso (paso agente)")
if pg is None:
    sys.exit(fallos)
check(isinstance(pg["minutos"], int) and pg["limite_s"] and pg["limite_min"] and pg["ultima_actividad"]
      and isinstance(pg["inactivo_s"], int) and pg["agente"] == "claude",
      "progreso con minutos, límite, última actividad y agente", pg)
# Mientras piensa: una sola línea viva «pensando… N s» con N creciente, y sin aviso de atasco.
vistos, atascado, viva = [], False, None
fin = time.time() + 30
while time.time() < fin:
    p = demo()
    x = prog(p)
    if not x:
        break
    if x.get("pensando_s"):
        if x["ultima_linea"] != f"pensando… {x['pensando_s']} s":
            vistos.append(("línea inesperada", x["ultima_linea"]))
        if not vistos or vistos[-1] != x["pensando_s"]:
            vistos.append(x["pensando_s"])
        atascado = atascado or x["atasco"] or any(a.get("tipo") == "atasco" and a.get("numero") == n
                                                   for a in p["atencion"])
        if viva is None:  # «Ver progreso»: la línea viva va al final del log
            r = get(f"/api/proyecto/demo/progreso/{n}")
            if r.get("linea_viva"):
                viva = r["log"].splitlines()[-1]
    elif vistos:
        break
    time.sleep(0.3)
nums = [v for v in vistos if isinstance(v, int)]
check(len(nums) >= 2 and nums == sorted(nums) and nums[-1] > nums[0] and len(nums) == len(vistos),
      "mientras piensa, /api/estado muestra «pensando… N s» con N creciente", vistos)
check(nums and not atascado, "mientras piensa la tarea no sale como posible atasco", vistos)
check(bool(viva) and re.search(r"\] pensando… \d+ s$", viva), "«Ver progreso» muestra la línea viva al final del log", viva)
log = os.path.join("proyectos", "demo", "estado", "agentes", f"issue-{n}.log")
texto = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
pens = re.findall(r"\] pensó (\d+) s$", texto, re.M)
check(len(pens) == 1 and int(pens[0]) >= 2 and "pensando…" not in texto and "thinking_tokens" not in texto
      and "sesión status" not in texto and "sesión  ·" not in texto,
      "30 eventos thinking_tokens dejan una sola línea «pensó N s» en issue-N.log (ni «sesión thinking_tokens»)",
      texto[-800:])
check(texto.count("sesión iniciada · modelo fake-modelo") == 1, "init se muestra una vez: «sesión iniciada · modelo X»",
      texto[-800:])
pg = esperar(lambda: (lambda x: x if x and (x["archivos_cambiados"] or 0) >= 1 else None)(prog(demo())))
check(pg is not None, "archivos cambiados en el worktree (git status --porcelain)", pg)
log = os.path.join("proyectos", "demo", "estado", "agentes", f"issue-{n}.log")
def en_vivo():
    x = prog(demo())
    if not x or x["paso"] != "agente" or not os.path.exists(log):
        return None
    return "herramienta Write: escribe docs/progreso.md" in open(log, encoding="utf-8").read()
check(esperar(en_vivo, 15), "la salida del agente aparece en issue-N.log mientras se ejecuta (resumen de stream-json)")
r = get(f"/api/proyecto/demo/progreso/{n}")
check(r["en_curso"] and "herramienta Write: escribe docs/progreso.md" in r["log"] and r["progreso"]["paso"] == "agente"
      and len(r["log"].splitlines()) <= 60, "«Ver progreso» devuelve las últimas líneas del log", r)
d = demo(refrescar=True)
doing = [t for t in d["tarjetas"].get("Doing", []) if t["numero"] == n]
check(doing and doing[0].get("progreso", {}).get("paso") == "agente", "la tarjeta en Doing lleva su progreso",
      d["tarjetas"].get("Doing"))
def atasco():
    p = demo()
    a = [a for a in p["atencion"] if a.get("tipo") == "atasco" and a.get("numero") == n]
    x = prog(p)
    return a and x and x["atasco"] and (a[0], x)
r = esperar(atasco, 15)
check(bool(r) and "posible atasco" in r[0]["texto"] and r[0]["nivel"] == "alta" and r[0].get("progreso"),
      "sin actividad > umbral: posible atasco en «Requiere tu atención»", r)
sys.exit(fallos)
PY
wait "$UNAVEZ" || true
grep -q "CI en verde" "$S.prog.log" && ok "la tarea en directo termina (CI en verde)" || { cat "$S.prog.log"; mal "tarea en directo"; }
NP="$NP" PUERTO="$PUERTO" python3 - <<'PY' && ok "el progreso desaparece al salir de Doing" || mal "el progreso sigue tras salir de Doing"
import json, os, urllib.request
n = int(os.environ["NP"])
d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{os.environ['PUERTO']}/api/estado", timeout=60))
p = [p for p in d["proyectos"] if p["nombre"] == "demo"][0]
assert not [x for x in p["progreso"] if x["numero"] == n], p["progreso"]
assert not [a for a in p["atencion"] if a.get("tipo") == "atasco" and a.get("numero") == n], p["atencion"]
f = json.load(open("proyectos/demo/estado/progreso.json"))
assert str(n) not in f.get("tareas", {}), f
PY
LOGP="proyectos/demo/estado/agentes/issue-$NP.log"
grep -q "CI: consulta" "$LOGP" && ok "la espera de la CI cuenta como actividad (consultas en el log)" || mal "sin consultas de CI en $LOGP"
TOKF="ghp_$(printf 'Q7%.0s' $(seq 1 18))"
# El token falso vive en el código de fake_agente.py; sus .pyc (__pycache__) no son logs y no cuentan.
token_filtrado() {
  grep -q "ghp_Q7…" "$LOGP" && [ -z "$(grep -rlF --exclude-dir=__pycache__ --exclude='*.pyc' -- "$TOKF" "$S" "$S".* 2>/dev/null || true)" ]
}
# En un entorno lento la línea de stderr del agente puede tardar en llegar al log: se reintenta unos segundos.
for _ in $(seq 1 20); do token_filtrado && break; sleep 0.5; done
token_filtrado && ok "el token de la salida del agente se filtra en los logs" \
  || { grep -n "stderr" "$LOGP" | tail -5 || true; mal "token sin filtrar en los logs"; }
kill $PANEL 2>/dev/null || true
python3 -c "
import re; h=open('panel.html').read(); open('$S.panel.js','w').write(re.search(r'<script>(.*)</script>', h, re.S).group(1))"
if command -v node >/dev/null; then node --check "$S.panel.js" && ok "JavaScript del panel" || mal "JavaScript del panel"; fi
python3 - <<'PY' && ok "HTML del panel bien anidado" || mal "HTML del panel mal anidado (section/div/form)"
from html.parser import HTMLParser
class P(HTMLParser):
    def __init__(s): super().__init__(); s.pila = []
    def handle_starttag(s, t, a):
        if t in ("section", "div", "form"): s.pila.append(t)
    def handle_endtag(s, t):
        if t in ("section", "div", "form"):
            assert s.pila and s.pila.pop() == t, (t, s.getpos())
p = P(); p.feed(open("panel.html", encoding="utf-8").read().split("<script>")[0]); assert not p.pila, p.pila
PY

echo "== 5d. Palabras de normativa por proyecto (mantenimiento.json + variable NORMATIVA_PALABRAS)"
MANT_DIR="$ORIG/repo-plantilla/.equipo-ia" python3 - <<'PY' || FALLOS=$((FALLOS + 1))
import datetime as dt, json, os, sys
os.environ.pop("NORMATIVA_PALABRAS", None)
os.environ["EQUIPO_IA_HOY"] = "2026-01-15"
sys.path.insert(0, os.environ["MANT_DIR"])
import mantenimiento as M
fallos = 0
def check(cond, msg, detalle=""):
    global fallos
    print(("OK    " if cond else "FALLO ") + msg + ("" if cond else f" — {detalle}"))
    fallos += 0 if cond else 1
fuente = next(f for f in M.CONFIG["normativa"]["fuentes"] if f["tipo"] == "boe-sumario")
base = fuente["palabras"]
check(M.palabras_normativa(base) == base, "sin la variable: exactamente las palabras de mantenimiento.json",
      M.palabras_normativa(base))
check(M.palabras_normativa(base, "  ,  ") == base, "variable vacía o solo comas: sin cambios")
os.environ["NORMATIVA_PALABRAS"] = " servicios de pago,IRPF , entidades de crédito, irpf, Protección de Datos ,, "
mezcla = M.palabras_normativa(base)
check(mezcla == base + ["servicios de pago", "IRPF", "entidades de crédito"],
      "con la variable: se añaden sin duplicados (mayúsculas/tildes) e ignorando espacios", mezcla)
# La búsqueda usa la mezcla: un sumario BOE simulado con un título que solo casa con IRPF.
sumario = {"data": {"sumario": {"diario": [{"seccion": [{"item": [
    {"identificador": "BOE-A-2026-0001", "titulo": "Orden por la que se modifica el modelo del IRPF",
     "url_html": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-0001"},
    {"identificador": "BOE-A-2026-0002", "titulo": "Resolución sobre pesca de bajura"}]}]}]}}}
M.http_json = lambda url, timeout=30: sumario
M.CONFIG["normativa"]["fuentes"] = [dict(fuente, dias=1)]
h = M.fuente_normativa(None)
check(len(h) == 1 and h[0]["clave"].endswith("BOE-A-2026-0001") and "coincide con: IRPF" in h[0]["evidencia"],
      "la búsqueda del BOE usa las palabras de la variable", h)
del os.environ["NORMATIVA_PALABRAS"]
check(M.fuente_normativa(None) == [], "sin la variable, ese título no genera hallazgo")
sys.exit(fallos)
PY

echo "== 5e. Documentación: README corto, páginas de docs/ y enlaces relativos (archivos y anclas)"
DOCS_RAIZ="$ORIG" python3 - <<'PY' || FALLOS=$((FALLOS + 1))
import os, re, sys
from pathlib import Path
from urllib.parse import unquote
raiz = Path(os.environ["DOCS_RAIZ"])
fallos = 0
def check(cond, msg):
    global fallos
    print(("OK    " if cond else "FALLO ") + msg)
    fallos += 0 if cond else 1
def sin_bloques(texto):  # quita los bloques ``` / ~~~: sus «#» no son títulos ni sus [x](y) enlaces
    return re.sub(r"^ {0,3}(```|~~~).*?^ {0,3}\1[^\n]*$", "", texto, flags=re.M | re.S)
def sin_codigo(texto):  # además quita el código en línea (ejemplos de enlace, no enlaces)
    return re.sub(r"`[^`\n]*`", "", sin_bloques(texto))
def slug(titulo):  # ancla de GitHub: minúsculas, sin puntuación (salvo - y _), espacios → guiones
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", titulo.strip().lower())
    return re.sub(r"[^\w\- ]", "", t).replace(" ", "-")
def anclas(ruta):
    vistas, res = {}, set()
    for linea in sin_bloques(ruta.read_text(encoding="utf-8")).splitlines():  # GitHub conserva el `código` del título
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", linea)
        if m:
            s = slug(m.group(1).replace("`", ""))
            n = vistas.get(s, 0); vistas[s] = n + 1
            res.add(s if n == 0 else f"{s}-{n}")
    return res
paginas = ["guia-uso", "instalacion", "panel", "tablero", "ci-y-pruebas", "mantenimiento",
           "agentes-y-lecciones", "arquitectura", "limitaciones"]
docs = sorted((raiz / "docs").glob("*.md"))
for p in ["README"] + paginas:
    check((raiz / "docs" / f"{p}.md").is_file(), f"docs/{p}.md existe")
readme = (raiz / "README.md").read_text(encoding="utf-8")
check(len(readme.splitlines()) <= 60, f"README raíz corto ({len(readme.splitlines())} líneas, máximo 60)")
for p in ["README"] + paginas:
    check(f"](docs/{p}.md)" in readme, f"el README raíz enlaza docs/{p}.md")
indice = (raiz / "docs" / "README.md").read_text(encoding="utf-8") if (raiz / "docs" / "README.md").is_file() else ""
for p in paginas:
    check(f"]({p}.md)" in indice, f"el índice docs/README.md enlaza {p}.md")
for d in docs:
    if d.name == "README.md":
        continue
    lineas = [l for l in d.read_text(encoding="utf-8").splitlines() if l.strip()]
    check(len(lineas) >= 2 and lineas[0].startswith("# ") and "](README.md)" in lineas[1],
          f"docs/{d.name}: empieza con título y enlace de vuelta al índice")
arq = (raiz / "docs" / "arquitectura.md")
check(arq.is_file() and re.search(r"^```mermaid\n(flowchart|graph) ", arq.read_text(encoding="utf-8"), re.M),
      "docs/arquitectura.md incluye un diagrama Mermaid")
cache, rotos, total = {}, [], 0
for origen in [raiz / "README.md"] + docs:
    texto = sin_codigo(origen.read_text(encoding="utf-8"))
    for destino in re.findall(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)", texto):
        if re.match(r"^[a-z][a-z0-9+.-]*:", destino, re.I):  # http:, https:, mailto:… no son relativos
            continue
        total += 1
        ruta, _, ancla = destino.partition("#")
        archivo = (origen.parent / unquote(ruta)).resolve() if ruta else origen
        nombre = f"{origen.relative_to(raiz)} → {destino}"
        if not archivo.exists():
            rotos.append(f"{nombre} (no existe el archivo)")
        elif ancla:
            if archivo.suffix != ".md" or archivo.is_dir():
                rotos.append(f"{nombre} (ancla en algo que no es Markdown)")
                continue
            if archivo not in cache:
                cache[archivo] = anclas(archivo)
            if unquote(ancla).lower() not in cache[archivo]:
                rotos.append(f"{nombre} (no existe el ancla)")
for r in rotos:
    print("      roto:", r)
check(total > 0 and not rotos, f"enlaces relativos entre README.md y docs/*.md ({total} revisados, {len(rotos)} rotos)")
sys.exit(1 if fallos else 0)
PY

echo "== 6. Compilación de todo el código"
python3 -m compileall -q "$ORIG" -x 'proyectos|pruebas-dobles/__pycache__' > /dev/null && ok "compilación" || mal "compilación"

pkill -f fake_ollama.py 2>/dev/null || true
echo
if [ "$FALLOS" -gt 0 ]; then echo "RESULTADO: $FALLOS fallo(s)"; exit 1; fi
echo "RESULTADO: todo en verde"
