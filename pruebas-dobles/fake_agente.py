#!/usr/bin/env python3
"""Doble de claude (prompt por stdin) y opencode (prompt por --file). Escribe archivos según la tarea."""
import json, os, sys
from pathlib import Path

a = sys.argv[1:]
modo = os.environ.get("FAKE_AGENTE_MODO", "ok")
leak = [k for k in os.environ if k.startswith(("ANTHROPIC_", "OPENAI_"))]
if leak:
    print("FUGA DE CREDENCIALES:", leak, file=sys.stderr)
    sys.exit(3)
if "--file" in a:
    prompt = Path(a[a.index("--file") + 1]).read_text(encoding="utf-8")
    import urllib.request
    urllib.request.urlopen(os.environ.get("FAKE_OLLAMA", "http://127.0.0.1:11999") + "/api/tags", timeout=2)
else:
    prompt = sys.stdin.read()
if modo == "cuota":
    print("Claude AI usage limit reached|1700000000", file=sys.stderr)
    sys.exit(1)
if modo == "nada":
    print("He pensado en la tarea pero no he escrito nada.")
    sys.exit(0)
def evento(ev: dict, texto: str) -> None:
    """claude (stdin) emite eventos stream-json; opencode (--file), texto tal cual. Siempre con flush."""
    print(texto if "--file" in a else json.dumps(ev), flush=True)


if "PASO-A-PASO" in prompt:
    # Progreso en directo: escribe poco a poco, tarda unos segundos y luego se queda callado (posible atasco).
    import re as _re
    import time as _time
    paso = float(os.environ.get("FAKE_AGENTE_PASO_S", "1"))
    silencio = float(os.environ.get("FAKE_AGENTE_SILENCIO_S", "6"))
    ruta = _re.search(r"Crea el archivo (docs/\S+?\.md)", prompt).group(1)
    evento({"type": "system", "subtype": "init", "model": "fake-modelo"}, "opencode: sesión iniciada")
    _time.sleep(paso)
    evento({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "README.md"}}]}}, "Read README.md")
    _time.sleep(paso)
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta).write_text("# Progreso en directo\n")
    evento({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": ruta}}]}}, f"Write {ruta}")
    # Un token en la salida: el log en directo debe filtrarlo.
    print("[stderr-fake] usando ghp_" + "Q7" * 18 + " para nada", file=sys.stderr, flush=True)
    _time.sleep(paso)
    evento({"type": "assistant", "message": {"content": [{"type": "text", "text": "Archivo escrito; repaso."}]}},
           "Archivo escrito; repaso.")
    _time.sleep(silencio)
    evento({"type": "result", "subtype": "success", "is_error": False, "result": "hecho", "duration_ms": 9000,
            "num_turns": 3, "total_cost_usd": 0.0}, "Listo.")
    sys.exit(0)
if "prueba-" in prompt and "LISTO" in prompt:
    nombre = prompt.split("archivo ")[1].split()[0]
    Path(nombre).write_text("LISTO\n")
elif "Implementa la función" in prompt:
    Path("src").mkdir(exist_ok=True)
    Path("src/puntos.py").write_text(
        "def sumar_puntos(puntos: list[int]) -> int:\n"
        "    for p in puntos:\n"
        "        if p < 0:\n"
        "            raise ValueError(f'valor negativo no permitido: {p}')\n"
        "    return sum(puntos)\n")
    if modo == "fuera":
        Path("README.md").write_text("tocado fuera de alcance\n")
elif "Escribe las pruebas" in prompt:
    Path("tests").mkdir(exist_ok=True)
    Path("tests/test_puntos.py").write_text(
        "import unittest\nfrom src.puntos import sumar_puntos\n\n\n"
        "class TestPuntos(unittest.TestCase):\n"
        "    def test_suma_normal(self):\n        self.assertEqual(sumar_puntos([1, 2, 3]), 6)\n\n"
        "    def test_cero(self):\n        self.assertEqual(sumar_puntos([0, 0]), 0)\n        self.assertEqual(sumar_puntos([]), 0)\n\n"
        "    def test_negativos(self):\n        with self.assertRaises(ValueError):\n            sumar_puntos([1, -2])\n\n\n"
        "if __name__ == '__main__':\n    unittest.main()\n")
elif "Crea el archivo docs/" in prompt:
    import re as _re
    ruta = _re.search(r"Crea el archivo (docs/\S+?\.md)", prompt).group(1)
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    previo = Path(ruta).read_text() if Path(ruta).exists() else ""
    Path(ruta).write_text(previo + "# Hecho por el equipo\n" if not previo else previo + "Corregido tras la revisión de la CI.\n")
    Path(os.environ.get("FAKE_AGENTE_LOG", "/dev/null")).open("a").write(ruta + "\n")
elif "notas-ensayo" in prompt:
    Path("docs").mkdir(exist_ok=True)
    Path("docs/notas-ensayo.md").write_text("# Notas del ensayo\n\nCompletada tras recuperar Ollama.\n")
print(json.dumps({"type": "result", "is_error": False, "result": "hecho", "total_cost_usd": 0.0}))
