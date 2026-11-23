# Plantilla de propuesta de mantenimiento

La genera `mantenimiento.py` (también puede escribirla el TL a mano). Una propuesta = una issue con la
etiqueta `mantenimiento` y una tarjeta en **Planning**. Nunca entra en desarrollo hasta que Óscar la
mueve a **To Do**, y antes el TL completa la parte ejecutable.

```markdown
<!-- equipo-ia:clave=<categoria>:<owner/repo>:<componente>:<identificador> -->
<!-- equipo-ia:huella=<hash de la evidencia> -->
<!-- auto:inicio -->
## Propuesta de mantenimiento

| Campo | Valor |
|---|---|
| Categoría | Versiones y migraciones · Parches de seguridad · Normativa · Deuda técnica |
| Componente | paquete, runtime, función afectada o workflow |
| Versión en el repositorio | leída del archivo de bloqueo |
| Versión desplegada | del último despliegue correcto · o «exposición en producción pendiente de confirmar» |
| Evidencia | dato verificable — [enlace](https://…) |
| Impacto de aplazar | qué pasa si no se hace |
| Acción sugerida | cambio concreto y verificable |
| Esfuerzo aproximado | S · M · L |
| Prioridad sugerida | P0 urgente · P1 alta · P2 normal · P3 baja |
| Plazo conocido | fecha de fin de soporte, de aplicación normativa… |
| Criterio de cierre | cómo se sabe que está resuelto |
| Última actualización automática | fecha · enlace a la ejecución |
<!-- auto:fin -->

## Notas de Óscar
(se conservan siempre)

## Para pasar a To Do (lo completa el TL)
### Objetivo / ### Agente / ### Rama base / ### Archivos permitidos / ### Criterios de aceptación / ### Comando de prueba / ### Dependencias
```

Reglas: la **clave** es estable (un hallazgo = una issue). Si la evidencia no cambia no se escribe nada;
si cambia se sustituye solo el bloque automático y se añade un comentario. Estado, prioridad y notas
elegidos por Óscar no se tocan. Un hallazgo cerrado no genera otra propuesta.
