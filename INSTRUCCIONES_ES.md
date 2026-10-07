# CasePilot — Guía rápida

Este es un **nuevo proyecto de demostración para tu portafolio**. No reemplaza tu sistema universitario de trabajos de grado ni representa experiencia laboral que no hayas tenido.

## Abrirlo en Windows

1. Descomprime `CasePilot_Portfolio.zip`.
2. Instala Python 3.11 o superior, si aún no está disponible en Windows.
3. Abre la carpeta y haz doble clic en `START_WINDOWS.bat`.
4. Espera a que se abra `http://127.0.0.1:8765`.
5. Accede con `admin` y `demo1234` o con `agent` y `agent1234`.
6. Explora el panel, registra un ticket, asígnalo, registra notas y consulta el historial.
7. Para detener el servidor sin perder datos, ejecuta `.\STOP_WINDOWS.ps1`. Los registros están en `.runtime/`.

También puedes iniciar desde PowerShell con `.\START_WINDOWS.ps1`; usa `-NoBrowser` si quieres abrir el navegador manualmente.

No requiere Docker ni instalar paquetes Python. El lanzador guarda sus datos locales en `data/demo.sqlite3` (el arranque directo con Python usa `casepilot.sqlite3`) (se crea al iniciarse y no se incluye en el repositorio).

## Validar pruebas

Abre PowerShell en la carpeta del proyecto:

```powershell
py -3 -W error::ResourceWarning -m unittest discover -s tests -v
# Con Node disponible: .\scripts\check.ps1
```

## Cómo presentarlo

- Explica qué problema resuelve: dar seguimiento a solicitudes de soporte.
- Demuestra autenticación, roles, estados, métricas de SLA, trazabilidad y exportación.
- Enseña las pruebas de integración y menciona las limitaciones documentadas.
- Revisa y entiende cada parte del código antes de utilizarlo en una entrevista.
- Describe con sinceridad el apoyo de herramientas de IA cuando te lo pregunten o cuando una evaluación lo requiera.

## Grabación

Incluí un video de demostración silencioso aparte y `DEMO_SCRIPT_EN.md` con frases sencillas para narrarlo. Esa grabación representa **CasePilot**. No es el video oficial solicitado sobre tu tesis.

Si EgoTECHWORLD solicita tu inglés hablado, graba tu voz con el teléfono y agrega ese audio al video original. El narrador sintético no demostraría tu inglés.

## Publicación

La aplicación no está publicada automáticamente en tu GitHub. Crea un repositorio nuevo, por ejemplo `casepilot-service-desk`, y añade el contenido de esta carpeta (sin datos locales, claves o contraseñas privadas). Enlázalo después desde tu portafolio y adjunta capturas verificadas.
