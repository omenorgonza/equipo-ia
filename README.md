# equipo-ia-lab

Un equipo pequeño de agentes de IA que trabaja sobre tus repos de GitHub: Óscar apunta y autoriza tareas en un
tablero, Codex (Team Leader) las prepara y revisa, y Claude Code u OpenCode + Ollama las desarrollan cada una en
su `git worktree` hasta dejar una PR con la CI en verde. Solo biblioteca estándar de Python 3.9+.

## Versión 4 — varios proyectos y panel local

Un solo equipo instalado y varios proyectos configurados; arrancas el que te interese.

```
equipo-ia-lab/
  equipo.py · panel.py · panel.html     ← gestión de proyectos y panel web local
  equipo.json                            ← compartido: agentes, modelo local, límites
  lecciones/                             ← compartidas: lo que aprende el agente local sirve en todos
  proyectos/<nombre>/                    ← por proyecto: config.json, estado/, worktrees/, repo/
```

## Arranque rápido

```bash
python3 equipo.py panel                       # http://127.0.0.1:8765 (se abre en tu navegador de Windows)
python3 equipo.py proyectos                   # lista y estado
python3 equipo.py family-finance vigilar      # arrancar el equipo en un proyecto (o el botón del panel)
python3 equipo.py family-finance parar        # parada suave: termina la tarea en curso
```

¿Primera vez? Empieza por la [instalación](docs/instalacion.md). ¿Ya está instalado? La
[guía de uso](docs/guia-uso.md) explica el día a día.

## Escalado automático al senior

Cuando el junior (p. ej. `local`) falla una tarea por su culpa (termina con error, no cambia nada, se sale de los
archivos permitidos o deja las pruebas en rojo), el coordinador la repite desde un worktree limpio y, cuando ha
gastado sus intentos, la pasa al senior (`revision.senior`, por defecto `claude`): etiqueta, campo Agente y un
comentario con el historial. Cuota agotada, Ollama caído o la red no cuentan como fallo del agente.

**Desde el panel.** Cada proyecto tiene la casilla «Escalar al senior» y el selector «tras N fallo(s) del junior».
Pulsa «Guardar escalado»: el panel cambia solo esas dos claves del `config.json` del proyecto y el equipo en marcha
las aplica en el ciclo siguiente, sin reiniciar.

**A mano, en `proyectos/<nombre>/config.json`** (o en `equipo.json` para todos los proyectos):

```jsonc
"escalar_fallos": true,      // false: el primer fallo bloquea la tarea, sin reintento ni escalado
"fallos_para_escalar": 2     // intentos del junior antes de pasar al senior (1–5; con 1 escala al primer fallo)
```

Los intentos gastados se guardan en el registro: tras un Bloqueo y `reanudar`, el junior solo tiene los que le
quedaban (si ya los gastó, la tarea pasa directamente al senior). Si después de escalar devuelves la etiqueta al
junior, manda la etiqueta: el coordinador pone el campo Agente al día y el junior empieza con todos sus intentos.

## Documentación

Toda la documentación vive en [`docs/`](docs/README.md):

- [Guía de uso](docs/guia-uso.md): día a día, cola y prioridades, dependencias, integrar PR, parar, bloqueos,
  Done/PRO, «¿Qué hago ahora?» y actualizar la instalación.
- [Instalación](docs/instalacion.md): WSL, agentes, Ollama, token y secretos, migrar desde la v3.
- [Panel](docs/panel.md): qué hace el panel local y cada uno de sus botones.
- [Tablero](docs/tablero.md): columnas, quién mueve cada tarjeta, campos, vistas y etiquetas.
- [CI y pruebas](docs/ci-y-pruebas.md): la CI como juez, ensayo completo, pruebas dobles y ensayos de aceptación.
- [Mantenimiento](docs/mantenimiento.md): workflows de Actions, versiones, seguridad, normativa, deuda, despliegue y PRO.
- [Agentes y lecciones](docs/agentes-y-lecciones.md): perfiles, revisión entre agentes, escalado, lecciones y skills.
- [Arquitectura](docs/arquitectura.md): piezas, pasos del coordinador y diagrama del flujo Backlog → PRO.
- [Limitaciones](docs/limitaciones.md): limitaciones conocidas y problemas resueltos.

Si cambias el comportamiento del equipo, actualiza la página de `docs/` correspondiente en la misma PR: el
ensayo completo comprueba que los enlaces entre páginas siguen funcionando.
