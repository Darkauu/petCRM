# Escribirle a varios

Mandar la misma promo a los cuatro clientes atrasados con perro pequeño,
sin escribirla cuatro veces ni perder la cuenta de por quién ibas.

## Lo que el sistema hace y lo que no

**No manda nada.** WhatsApp no permite enviar en lote desde un programa,
y ninguna vuelta cambia eso: cada chat se abre por separado. Lo que sí se
puede quitar es lo que de verdad cansa, que no son los toques sino
redactar el mismo mensaje seis veces y olvidarse de a quién le faltaba.

El sistema arma el enlace con el mensaje ya escrito y abre el chat. El
mensaje sale del teléfono de la dueña, desde su número, como si lo
hubiera tecleado ella.

## Cómo se usa

1. En **Clientes**, «Escribirle a varios».
2. Elige los grupos. **Se combinan**: «Por escribir» + «Perros pequeños»
   son justo los atrasados de talla chica.
3. Escribe el mensaje una sola vez. `{cliente}` y `{mascota}` se
   reemplazan por los de cada persona; debajo se ve cómo le llega a una
   de ellas, ya resuelto.
4. «Empezar». De ahí en adelante, una persona por pantalla: se toca
   **Abrir el chat**, se envía en WhatsApp, y la pantalla ya pasó sola a
   la siguiente.

Los que se saltan quedan anotados como salteados, no como escritos. Si un
dedo tocó el botón equivocado, en la pantalla final hay un **Rehacer** que
devuelve a esa persona a la cola.

## Quién entra y quién no

- **Sin teléfono, no entra**: no hay a dónde escribirle. Aparecen en
  Clientes bajo `Datos incompletos`.
- **Quien pidió que no le escriban, tampoco**: es el campo
  `preferred_channel = 'none'` del cliente. Hoy se respeta en la consulta
  pero no hay pantalla para marcarlo; se pone a mano en la base. Ponerle
  interfaz es el siguiente paso natural de esto.

## Nota sobre mensajería

Esto son mensajes de la peluquería a sus propios clientes, sobre su
propio perro, enviados desde el teléfono de la dueña. No es envío masivo
ni una lista comprada. Aun así, conviene que quien no quiera recibirlos
tenga cómo decirlo — de ahí el campo de arriba.

Para enviar de verdad en lote, sin abrir chat por chat, haría falta
WhatsApp Business API: cuenta de Meta Business, número verificado,
plantillas aprobadas por Meta y pago por conversación. Se justifica
cuando sean cientos de mensajes al mes, no cuatro.
