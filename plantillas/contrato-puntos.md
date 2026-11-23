# Contrato: suma de puntos

- **Ubicación:** `src/puntos.py` (paquete `src`, ya existe `src/__init__.py`).
- **Nombre y firma:** `sumar_puntos(puntos: list[int]) -> int`
- **Comportamiento:** devuelve la suma de los enteros de la lista. La lista vacía suma `0`.
- **Error:** si algún valor es negativo lanza `ValueError` (el mensaje debe contener la palabra `negativo`).
- **Pruebas:** `tests/test_puntos.py` con `unittest`, importando `from src.puntos import sumar_puntos`.
  Casos mínimos: suma normal (`[1, 2, 3] → 6`), cero (`[0, 0] → 0` y `[] → 0`), negativos (`[1, -2]` → `ValueError`).
- **Ejecución:** desde la raíz del repo, `python -m unittest discover -s tests -t . -v`.
