#!/usr/bin/env bash
# Monta un laboratorio completo contra el GitHub simulado: bash montar_simulacion.sh /tmp/sim
set -e
S=${1:-/tmp/sim}; ORIG=$(cd "$(dirname "$0")/.." && pwd)
pkill -f fake_ollama.py 2>/dev/null || true
rm -rf "$S"; mkdir -p "$S"; cd "$S"
git init -q --bare remoto.git
cp -r "$ORIG" lab; cd lab; rm -rf estado worktrees repo opencode.json config.json __pycache__ .opencode lecciones
D=$S/lab/pruebas-dobles
python3 coordinador.py iniciar >/dev/null
python3 - <<PY
import json
c=json.load(open('config.json'))
c['gh_bin']=['python3','$D/fake_gh.py']
for a in ('claude','local'): c['agentes'][a]['bin']=['python3','$D/fake_agente.py']
c['ollama_url']='http://127.0.0.1:11999'; c['simular_actions']=True
json.dump(c,open('config.json','w'),indent=2)
PY
echo "export FAKE_GH_STATE=$S/gh.json FAKE_OLLAMA=http://127.0.0.1:11999 ANTHROPIC_API_KEY=sk-ant-secreto" > "$S/env.sh"
. "$S/env.sh"
(python3 "$D/fake_ollama.py" 11999 >/dev/null 2>&1 &); sleep 1
python3 coordinador.py configurar-local --modelo qwen2.5-coder:14b >/dev/null
python3 ensayo.py preparar-repo --remoto "$S/remoto.git" >/dev/null
python3 ensayo.py crear-issues >/dev/null
python3 ensayo.py caida-tras-push >/dev/null
python3 tablero.py crear >/dev/null
python3 tablero.py migrar --aplicar >/dev/null
python3 ensayo_tablero.py instalar-github >/dev/null
echo "Simulación lista en $S (source $S/env.sh)"
