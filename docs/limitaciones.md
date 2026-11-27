# Limitaciones y problemas resueltos

[← Índice de la documentación](README.md)

## Limitaciones conocidas

- **Varios repos en un proyecto**: el tablero y el mantenimiento cubren todos, pero el coordinador ejecuta las
  tareas del **repo principal** (el primero). Las de los demás repos se quedan en To Do.
- **Dependencias no integradas**: una dependencia cuenta como lista en Testing / Review, pero la tarea
  dependiente parte de `main` sin sus cambios; si tocan los mismos archivos, integra antes la primera (ver
  [Guía de uso](guia-uso.md#dependencias)).
- **PR con conflictos**: GitHub no lanza la CI; el coordinador bloquea la tarea en cuanto lo detecta y hay que
  reintentarla con el agente (ver [CI y pruebas](ci-y-pruebas.md#la-ci-del-proyecto-como-juez---prueba-ci)).
- **Sin relevo entre proveedores**: si Ollama no responde, la tarea local se bloquea; nunca pasa a otro proveedor.
- **Despliegue simulado** en los proyectos sin servidor todavía (ver [Mantenimiento](mantenimiento.md#despliegue-y-pro)).

## Problemas resueltos

Lecciones de configuración del piloto (ya aplicadas):

- OpenCode V2 con `default_agent: plan` global → el laboratorio fuerza `--agent build`.
- Ollama arranca los modelos con 4096 tokens de contexto → usar una variante con `num_ctx 32768`
  (`diagnostico` y `configurar-local` avisan y dan los comandos de PowerShell).
- Tras crear una issue, GitHub tarda unos segundos en mostrarla al filtrar por etiqueta; el ensayo espera.
- `gh pr edit` falla en gh 2.45 (consulta `projectCards`, de los Projects clásicos ya retirados) → al
  reprocesar una tarea con PR abierta, el coordinador actualiza la descripción por la API REST
  (`gh api -X PATCH repos/<repo>/pulls/<n> -f body=...`). El ensayo completo lo comprueba.
