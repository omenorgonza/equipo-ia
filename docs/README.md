# Documentación del equipo IA

[← Volver al README del repositorio](../README.md)

Esta carpeta es la «wiki» del equipo: páginas en Markdown que GitHub muestra con su navegación y que los agentes
mantienen en la misma PR que cada mejora.

| Página | De qué trata |
|---|---|
| [Guía de uso](guia-uso.md) | El día a día: cola y prioridades, dependencias, integrar PR, parar, bloqueos, Done/PRO, «¿Qué hago ahora?», actualizar la instalación. |
| [Instalación](instalacion.md) | WSL, agentes (Claude Code, OpenCode + Ollama), token y secretos, repositorio de ensayo, migrar desde la v3, pasar a otro proyecto. |
| [Panel](panel.md) | Qué hace el panel local y cada botón: Arrancar/Parar, Reanudar, Reintentar, color, TABLERO_TOKEN, Nueva tarea, nuevo/añadir proyecto, progreso en directo. |
| [Tablero](tablero.md) | Columnas, quién mueve cada tarjeta, campos, plantilla, vistas y agrupación por Estado, etiquetas `estado:*`/`prioridad:*`, crear tareas. |
| [CI y pruebas](ci-y-pruebas.md) | La CI como juez, ensayo completo, pruebas dobles (GitHub simulado) y ensayos de aceptación. |
| [Mantenimiento](mantenimiento.md) | Workflows de Actions, versiones, seguridad, normativa BOE, deuda técnica, despliegue y PRO. |
| [Agentes y lecciones](agentes-y-lecciones.md) | Perfiles (Codex TL, Claude senior, local junior), revisión entre agentes, reintento y escalado, lecciones y skills. |
| [Arquitectura](arquitectura.md) | Piezas (`equipo.py`, `coordinador.py`, `tablero.py`, panel, `repo-plantilla`, `proyectos/`), pasos del coordinador y diagrama del flujo. |
| [Limitaciones](limitaciones.md) | Limitaciones conocidas y problemas ya resueltos (gh 2.45, contexto de Ollama…). |

## Cómo mantener esta documentación

- Cada página empieza con un título `#` y, justo debajo, un enlace de vuelta a este índice.
- Si una mejora cambia el comportamiento, actualiza la página que lo describe **en la misma PR**.
- Enlaza entre páginas con rutas relativas (`tablero.md#quién-mueve-cada-tarjeta`). El ensayo completo
  (`pruebas-dobles/ensayo_completo.sh`, check «ensayos») comprueba que todos los enlaces relativos entre
  `README.md` y `docs/*.md` apuntan a archivos y anclas que existen.
- El README raíz se queda corto (unas 60 líneas): qué es, arranque rápido y enlaces aquí.
