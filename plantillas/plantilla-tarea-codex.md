# Plantilla para que Codex (Team Leader) publique una tarea

**Cuenta y repositorio:** publica con la identidad de GitHub de Óscar (la cuenta que muestra
`gh auth status`) en el repositorio indicado en `config.json → repo`. El coordinador ignora
cualquier issue de otro autor o de otro repositorio.

## Reglas para el TL

1. Una issue = una tarea pequeña con un solo agente y un conjunto cerrado de archivos.
2. Etiquetas obligatorias: `ready` y exactamente una de `agent:claude` / `agent:local`.
3. `Comando de prueba` es una **clave** de `config.json → pruebas`, nunca un comando libre.
4. Si dos tareas deben partir del mismo punto, pon el mismo SHA en `Commit base`.
5. Revisa las PR en estado `review`; una issue `blocked` trae un comentario con causa y recuperación.
   Para reencolarla tras corregir, vuelve a poner la etiqueta `ready`.

## Comando

```powershell
gh issue create --repo <OWNER/REPO> --title "<título corto>" `
  --label ready --label agent:<claude|local> --body-file tarea.md
```

## Cuerpo (`tarea.md`) — conserva los encabezados exactamente

```markdown
### Objetivo

<Qué hay que conseguir. Incluye el contrato: nombre, firma, ubicación y errores esperados.>

### Agente

<claude | local>

### Rama base

main

### Commit base

<SHA opcional; deja "_No response_" si no aplica>

### Archivos permitidos

src/<archivo>.py

### Criterios de aceptación

- <criterio verificable 1>
- <criterio verificable 2>

### Comando de prueba

<import-src | sintaxis-tests | unit>

### Dependencias

<#N o "ninguna">
```
