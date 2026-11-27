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

**Escalado automático al senior**: actívalo y ajústalo por proyecto desde el panel o el `config.json`
([cómo](docs/agentes-y-lecciones.md#activar-y-ajustar-el-escalado)).

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
