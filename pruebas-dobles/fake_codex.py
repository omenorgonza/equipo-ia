#!/usr/bin/env python3
"""Doble de Codex CLI (`codex exec --json -`, prompt por stdin, eventos JSONL), `codex --version` y
`codex login status`. Sin red ni credenciales.

Guion por la marca [CODEX:…] del objetivo de la tarea:
  cuota    Codex no tiene cuota (como autor y como revisor).
  escribe  como revisor, escribe en el worktree la primera vez (la ronda no debe contar).
Variables: FAKE_CODEX_LOGIN = chatgpt (por defecto) | apikey | ninguna; FAKE_CODEX_LOG = archivo donde se anota cada
invocación (papel y argumentos) para que el ensayo lo compruebe.
"""
import json, os, re, sys
from pathlib import Path

a = sys.argv[1:]
leak = [k for k in os.environ if k.startswith(("ANTHROPIC_", "OPENAI_")) or k == "CODEX_API_KEY"]
if leak:
    print("FUGA DE CREDENCIALES:", leak, file=sys.stderr)
    sys.exit(3)
if a[:1] == ["--version"]:
    print("codex-cli 0.0.0-fake")
    sys.exit(0)
if a[:2] == ["login", "status"]:
    modo = os.environ.get("FAKE_CODEX_LOGIN", "chatgpt")
    # Un token en la salida: `diagnostico` no debe mostrarlo.
    secreto = "eyJhbGciOiJIUzI1NiJ9." + "c2VjcmV0bw" * 4 + ".firma-secreta"
    if modo == "chatgpt":
        print(f"Logged in using ChatGPT (access_token={secreto})")
        sys.exit(0)
    if modo == "apikey":
        print("Logged in using an API key - sk-proj-" + "X9" * 20)
        sys.exit(0)
    print("Not logged in", file=sys.stderr)
    sys.exit(1)
if a[:1] != ["exec"] or a[-2:] != ["--json", "-"]:
    print("USO NO PREVISTO DEL DOBLE DE CODEX:", a, file=sys.stderr)
    sys.exit(2)

prompt = sys.stdin.read()
revisor = "=== REVISIÓN ENTRE AGENTES" in prompt
sandbox = a[a.index("--sandbox") + 1] if "--sandbox" in a else ""
guion = (re.search(r"\[CODEX:(\w+)\]", prompt) or [None, ""])[1]
issue = (re.search(r"issue #(\d+)", prompt) or [None, "0"])[1]
if os.environ.get("FAKE_CODEX_LOG"):
    with open(os.environ["FAKE_CODEX_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"issue": int(issue), "papel": "revisor" if revisor else "autor", "args": a}) + "\n")


def ev(d: dict) -> None:
    print(json.dumps(d, ensure_ascii=False), flush=True)


def mensaje(texto: str) -> None:
    ev({"type": "item.completed", "item": {"id": "item_9", "type": "agent_message", "text": texto}})


ev({"type": "thread.started", "thread_id": "fake-hilo"})
ev({"type": "turn.started"})
if guion == "cuota":
    ev({"type": "error", "message": "You've hit your usage limit. Try again later."})
    ev({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}})
    sys.exit(1)
if revisor:
    if a.count("--sandbox") != 1 or sandbox != "read-only" or {"--full-auto", "--yolo", "resume"} & set(a):
        print("EL REVISOR TIENE PERMISOS DE ESCRITURA:", a, file=sys.stderr)
        sys.exit(4)
    ronda = int((re.search(r"ronda (\d+) de", prompt) or [None, "1"])[1])
    marca = Path(os.environ["FAKE_GH_STATE"] + f".codex-escribe-{issue}")
    if guion == "escribe" and not marca.exists():
        marca.write_text("1")  # el sandbox de verdad lo impediría; el doble escribe para probar que no cuenta
        Path("escrito-por-codex.txt").write_text("no debería\n")
        ev({"type": "item.completed", "item": {"id": "item_1", "type": "file_change",
                                               "changes": [{"path": "escrito-por-codex.txt", "kind": "add"}]}})
    ev({"type": "item.completed", "item": {"id": "item_2", "type": "reasoning", "text": "Reviso el diff."}})
    mensaje("He revisado el cambio.\n```json\n" + json.dumps(
        {"veredicto": "aprobada", "hallazgos": [{"gravedad": "menor", "archivo": "(general)",
                                                  "detalle": f"Revisado por codex (ronda {ronda})"}],
         "riesgos": ["Sin prueba de carga"]}, ensure_ascii=False) + "\n```")
    ev({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}})
    sys.exit(0)
if sandbox != "workspace-write":
    print(f"Codex como autor sin sandbox de escritura ({sandbox or 'ninguno'}): no puede escribir", file=sys.stderr)
    sys.exit(1)
m = re.search(r"Crea el archivo (docs/\S+?\.md)", prompt)
ruta = m.group(1) if m else "docs/codex.md"
Path(ruta).parent.mkdir(parents=True, exist_ok=True)
previo = Path(ruta).read_text() if Path(ruta).exists() else ""
ev({"type": "item.started", "item": {"id": "item_0", "type": "command_execution", "command": "ls docs"}})
Path(ruta).write_text(previo + "Corregido tras la revisión.\n" if previo else "# Hecho por codex\n")
ev({"type": "item.completed", "item": {"id": "item_1", "type": "file_change",
                                       "changes": [{"path": ruta, "kind": "update" if previo else "add"}]}})
mensaje("hecho")
ev({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}})
