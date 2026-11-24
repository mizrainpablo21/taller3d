# Taller 3D

App para un taller de impresión 3D: cotizador, seguimiento de pedidos, guías de envío y billetera.

Abrir: https://mizrainpablo21.github.io/taller3d/

## Avance en vivo de la impresora Bambu Lab

1. `pip install paho-mqtt`
2. `python3 bambu_puente.py` (pide IP, serial y código de acceso de la impresora)
3. En la app: Ajustes > Impresora Bambu Lab > "Usar avance en vivo"

`python3 bambu_puente.py --demo` simula una impresión para probar.

### Ver el avance desde cualquier red

El puente puede publicar el estado en un Gist secreto de GitHub. Hace falta un token clásico con permiso `gist` (github.com/settings/tokens). Al configurar el puente, pega el token y copia el "ID para la app" en Ajustes > Impresora Bambu Lab > ID de la nube.
