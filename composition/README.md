# composition/

Montajes de vídeo generados a partir de un prompt de estado del proyecto.
Cada montaje son **tres ficheros** con un número creciente (`composition1`,
`composition2`, …):

| Fichero | Descripción |
|---|---|
| `compositionN.prompt` | Entrada. Preámbulo en prosa + una línea JSON gigante con el estado: canción (secciones, BPM, beats/downbeats, letras), vídeos (descripciones, IA score, estrellas, highlights/ranges) y la línea temporal actual. Lo genera la app. |
| `compositionN.output.json` | Salida. Un objeto `{ summary, actions }` que la app aplica para reconstruir la línea temporal. Lo escribe el compositor (Claude). |
| `validate_composition.py` | Validador reutilizable. Comprueba cualquier par prompt+output contra las reglas. |

## Flujo de trabajo

1. La app vuelca el estado a `compositionN.prompt`.
2. El compositor lee el prompt y escribe `compositionN.output.json` (ver esquema
   más abajo).
3. Se valida:

```bash
# autodetecta el N más alto que tenga prompt+output
python composition/validate_composition.py

# o explícito
python composition/validate_composition.py composition/composition2.prompt composition/composition2.output.json
```

Salida de ejemplo (composition1):

```
clips  : 39  tracks [0]  unique 38/39  ends 157.47/157.47
ERRORS: none
WARNINGS (8):   <- deriva de tempo en el outro, no son fallos
```

- **Exit code 0** → sin errores duros (el montaje es aplicable).
- **Exit code 1** → hay errores duros (solapes, source fuera de rango, se pasa
  del final…). Corregir antes de aplicar.

## Esquema del output

```json
{
  "summary": "una o dos frases describiendo el montaje",
  "actions": [
    {"action": "clear_track", "track": 0},
    {"action": "remove", "clip_id": 12},
    {"action": "move", "clip_id": 13, "timeline_start": 10.0,
     "track": 1, "source_in": 2.0, "source_out": 5.0},
    {"action": "place", "video_id": 3, "track": 0,
     "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.5}
  ]
}
```

- Las acciones se aplican **en orden**. `track` es índice base 0.
- En `move`, todos los campos salvo `clip_id` son opcionales (solo cambian los
  indicados).
- `clip_id` referencia clips **existentes** en la línea temporal del prompt;
  `video_id` referencia vídeos del catálogo (solo para `place`).

## Qué comprueba el validador

**Errores (duros — el montaje no se debe aplicar si los hay):**
- El montaje se pasa del final de la canción.
- Solapamiento entre clips de la misma pista.
- `source_in` / `source_out` fuera de la duración del vídeo.
- Ventana de source no positiva (`source_out <= source_in`), `timeline_start < 0`.

**Avisos (blandos — calidad, no bloqueantes):**
- Corte que no cae en un beat (los downbeats son los más fuertes).
- Ventana que no solapa ningún range manual ni highlight de IA.
- Mismo vídeo repetido consecutivo en una pista.

El validador **extrapola** la rejilla de beats/downbeats más allá del último
sampleo (los datos sueLen cortarse antes del outro) y configura stdout a UTF-8
para no cascar en consolas Windows (cp1252).

## Convención de nombres

Para que la autodetección funcione, los ficheros deben llamarse
`composition<N>.prompt` y `composition<N>.output.json` con el mismo `N`.
El validador elige el `N` más alto que tenga ambos.

## Nota

La parte creativa (qué clip va en cada sección, emparejado con la letra y la
energía de la canción) **no es scriptable** — se hace a mano para cada canción.
Lo reutilizable es la comprobación de que el resultado cumple todas las reglas.
