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
