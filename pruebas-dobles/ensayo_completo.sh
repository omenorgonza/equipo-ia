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
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PUERTO/api/proyecto/demo/arrancar")
[ "$CODIGO" = "403" ] && ok "acciones sin token rechazadas" || mal "acción sin token devolvió $CODIGO"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{"numero": 1}' "http://127.0.0.1:$PUERTO/api/proyecto/demo/reanudar")
[ "$CODIGO" = "403" ] && ok "reanudar sin token rechazado" || mal "reanudar sin token devolvió $CODIGO"
kill $PANEL 2>/dev/null || true
python3 -c "
import re; h=open('panel.html').read(); open('$S.panel.js','w').write(re.search(r'<script>(.*)</script>', h, re.S).group(1))"
if command -v node >/dev/null; then node --check "$S.panel.js" && ok "JavaScript del panel" || mal "JavaScript del panel"; fi

echo "== 6. Compilación de todo el código"
python3 -m compileall -q "$ORIG" -x 'proyectos|pruebas-dobles/__pycache__' > /dev/null && ok "compilación" || mal "compilación"

pkill -f fake_ollama.py 2>/dev/null || true
echo
if [ "$FALLOS" -gt 0 ]; then echo "RESULTADO: $FALLOS fallo(s)"; exit 1; fi
echo "RESULTADO: todo en verde"
