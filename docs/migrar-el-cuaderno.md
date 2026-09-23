# Migrar el cuaderno de papel

Un renglón por cada servicio anotado: el mismo formato en que ya está
escrito el cuaderno. Si a un perro le hicieron baño y corte de uñas el
mismo día, son dos renglones.

## El archivo

`docs/cuaderno-ejemplo.csv` es la plantilla. Se abre en Excel o Google
Sheets, se llena y se exporta como CSV.

| columna    | obligatoria | notas                                                        |
|------------|-------------|--------------------------------------------------------------|
| `fecha`    | sí          | `2026-08-14`, `14/08/2026` o `14-08-2026`                      |
| `cliente`  | sí          | el nombre como está escrito en el cuaderno                     |
| `telefono` | no          | `6123-4567`, `61234567` o `+507 6123 4567`                     |
| `mascota`  | sí          |                                                                |
| `tamano`   | no          | pequeño / mediano / grande (también `p`, `m`, `g`)             |
| `raza`     | no          |                                                                |
| `servicio` | sí          | baño, corte de uñas, lo que diga el papel                      |
| `precio`   | no          | `18.00` o `18,00`. Vacío entra en cero                         |
| `notas`    | no          |                                                                |

Los encabezados aceptan variantes: `Teléfono`, `TELEFONO` y `tel` son la
misma columna.

## Correrlo

```
python scripts/import_csv.py cuaderno.csv            # solo informa
python scripts/import_csv.py cuaderno.csv --commit   # escribe
```

Sin `--commit` **no toca la base**: lee el archivo, valida todo y dice
exactamente qué iba a pasar. Conviene mirar ese informe antes de
escribir. Con `--commit` saca un respaldo aparte antes de tocar nada.

Volver a pasar el mismo archivo no duplica nada.

## Qué hace con lo que está incompleto

Un renglón al que le falta la fecha, el cliente, la mascota o el
servicio no se puede leer: sale en `cuaderno-rechazados.csv` con el
motivo escrito al lado. Se corrige ahí y se pasa ese archivo.

Un renglón sin teléfono o sin tamaño **sí entra**, con el hueco a la
vista: en el panel de clientes aparece «sin teléfono» y hay una pestaña
`Datos incompletos` para listarlos todos. Un dato inventado cobraría mal
el próximo baño sin que nadie se entere; uno vacío se ve y se tapa.

## Qué queda después

- Clientes y mascotas, sin duplicar a quien esté escrito de dos formas
  (manda el teléfono; si no hay, el nombre).
- El catálogo, con el precio de lista deducido del más repetido en el
  papel para cada tamaño. **Hay que revisarlo en Servicios antes de
  cobrar con él.**
- El histórico de visitas, que es lo que hace que el panel de «a quién
  le escribo» sirva desde el primer día en vez de esperar un mes.

Esas visitas quedan marcadas como `source = 'import'`: son historia del
cuaderno, no trabajo registrado por el sistema.
