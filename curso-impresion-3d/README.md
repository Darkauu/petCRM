# Dexel Studio — Curso 01 / Impresión 3D

Deck de clase como página web. Todo es local: fuentes, three.js y el bundle viajan
con la carpeta, así que se puede abrir `index.html` directamente, sin red.

## Presentar

| Tecla | Acción |
|---|---|
| → · Espacio · PageDown | siguiente paso / diapositiva |
| ← · PageUp | anterior |
| Inicio / Fin | primera / última |
| `.` o `B` | pantalla en negro (y volver) |
| `F` | pantalla completa |

La URL guarda la diapositiva (`index.html#3`). En táctil: deslizar en horizontal.
Imprimir a PDF da una diapositiva por página, en su estado final.

## Editar

- Contenido: `index.html`. Cada `<section class="slide">` es un **punto** de una
  **sección**; `data-title-lines` fija los cortes del título voxel
  (`|` = línea, `||` separa la versión apaisada de la vertical). El título solo se
  re-arma cuando cambia la sección.
- Código: `src/`. Después de editar, `npm install && npm run build` regenera
  `dist/deck.js` (esbuild, un solo script clásico: funciona desde `file://`).

## Parámetros de prueba

- `?no3d` — ver el deck sin la capa WebGL (lo que ve un equipo sin GPU).
- `?force3d` — no apagar el 3D aunque el presupuesto de fotogramas no alcance.
- `?debug` — expone `window.__deck`.

## Estructura

- `src/voxelTitle.js` — palabra voxel: rasterizado → recorte a la tinta → ajuste al
  presupuesto de cubos → extrusión con relieve; cada glifo avanza como bloque rígido
  según la distancia del puntero; las caras interiores se colapsan en el shader.
- `src/demos.js` — aditiva (boquilla) y sustractiva (láser): la misma pirámide de
  329 cubos, con un guion temporal común.
- `src/gl.js` — un contexto WebGL: campo de ruido de fondo + un pase por zona.
- `src/main.js` — navegación, reloj único, entrada, arranque y salud de fotogramas.
