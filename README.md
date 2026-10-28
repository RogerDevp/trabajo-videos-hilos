# Reel de Goku — Computación Paralela

Video vertical **1080×1920, 30 FPS**, con pares **anime → realista** de las seis fases,
voz sintética, subtítulos incrustados, música y renderizado de escenas con hilos.

## Entrega

- `salida/goku_narrado.mp4`: video vertical final para subir a Shorts, Reels o TikTok.
- `salida/informe.docx` y `informe.pdf`: informe centrado en código, concurrencia y mediciones.
- `salida/metadatos.json`: tiempos, benchmark y eventos de los trabajadores.
- `salida/capturas/`: capturas del video y gráfico de actividad por hilo.
- `salida/subtitulos.srt`: subtítulos separados, además de los incrustados.
- `Entrega_videos_con_hilos.zip`: código, imágenes y entregables actualizados.

## Ejecutar

Requisitos: Python 3.10+, FFmpeg, eSpeak NG y fuente DejaVu Sans.
En Debian/Ubuntu: `sudo apt install ffmpeg espeak-ng fonts-dejavu-core python3-venv`.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python generar_video.py --benchmark --demo-music
```

El entorno local ya está listo:

```bash
.venv/bin/python generar_video.py --benchmark --demo-music
```

Opciones:

```bash
python generar_video.py --workers 4 --height 1920 --fps 30
python generar_video.py --workers 2 --height 1280 --tts espeak
python generar_video.py --images image --music music --output salida
```

El proceso sobrescribe los entregables de la carpeta de salida y conserva la caché de voz.
La primera versión horizontal se conserva por separado en `versiones/primera_version/`.

## Imágenes, guion y música

`configuracion.json` empareja explícitamente los archivos:

| Fase | Anime (`image/basic`) | Realista (`image/realistic`) |
|---|---|---|
| Base | base.jpeg | goku_base.png |
| SSJ 1 | ssj1.jpeg | goku_ssj1.png |
| SSJ 2 | ssj2.jpeg | goku_ssj2.png |
| SSJ 3 | ssj3.jpeg | goku_ssj3.png |
| SSJ 4 | ssj4.jpeg | goku_ssj4.png |
| Dios | ssjgod.jpeg | goku_dios.png |

Si se usa el nombre `images`, se puede indicar `--images images` (también se autodetecta
al iniciar si existe). Se usan las imágenes suministradas, sin filtros de Van Gogh.
El blanco exterior de las imágenes anime se retira por componentes conectados; el título
antiguo de las realistas se recorta en memoria. Los archivos originales no se modifican.
Cada fase alterna anime y realista; la introducción y el cierre oscilan entre ambos.

Cambiar `narracion_anime`, `narracion_real`, `introduccion` y `cierre` para editar el guion.
Usar frases breves para mantener el ritmo y la legibilidad de los subtítulos.
`--tts auto` intenta Edge TTS y utiliza eSpeak si falla. Edge requiere Internet y envía el
texto al servicio. La voz predeterminada es `es-PE-AlexNeural`. eSpeak funciona sin red.

Colocar música MP3, WAV, OGG, FLAC o M4A en `music/`: se concatena por nombre, se repite
hasta el final y se atenúa durante la voz. `--music-volume 0.36` ajusta la ganancia.
`--demo-music` crea un fondo instrumental si no hay pistas. Para reemplazarlo, retirar
`fondo_original.wav` y añadir las pistas deseadas. Sin música el video mantiene la voz.

## Organización del código

- `prepare_phase`: lectura de pares, encuadre y extracción de características con Sobel.
- `transition`: mezcla continua guiada por bordes; termina exactamente en la imagen realista preparada.
- `synthesize`: voz, conversión PCM y caché.
- `timeline`: reloj entero de fotogramas y muestras PCM, sin deriva acumulativa.
- `render`: imagen vertical, zoom, títulos y subtítulos.
- `render_segment`: trabajador que genera un MP4 con su propio FFmpeg.
- `benchmark_preparation`: tres comparaciones de preparación, orden alternado y mediana.
- `main`: pools de imágenes, voz y render; barreras; concatenación ordenada y mezcla final.
- `informe.py`: documento técnico con fragmentos de código y evidencias medidas.

Los trabajadores no comparten el codificador ni escriben el mismo archivo. `executor.map`
recoge segmentos en orden de entrada aunque terminen desordenados. FFmpeg se limita a
un hilo por proceso; OpenCV a un hilo interno. La concatenación y mezcla son secuenciales.
La aceleración reportada corresponde **solo a preparación**, no al render total.
El gráfico de hilos muestra intervalos observados, no porcentajes de uso de CPU.

## Verificar y añadir el enlace

```bash
python -m unittest discover -s tests -v
ffmpeg -v error -i salida/goku_narrado.mp4 -f null -
python informe.py --output salida --youtube 'https://www.youtube.com/watch?v=TU_VIDEO'
```

Siete pruebas cubren escala de fuentes pequeñas, pares reales, extremos de transición, orden de escenas, recolección
concurrente ordenada, tiempos SRT y conservación de muestras de voz. El último comando
actualiza PDF, DOCX y Markdown sin renderizar el video. Completar estudiante y docente
en el Word. El programa no publica el video en ninguna plataforma.

Fuentes: guías en `referencias/`, documentación de
[concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html),
[FFmpeg concat](https://ffmpeg.org/ffmpeg-formats.html#concat) y
[Edge TTS](https://github.com/rany2/edge-tts).

Para actualizar el ZIP después de cambiar el enlace o el código:

```bash
python empaquetar.py
```

La entrega empaquetada excluye cachés, versiones antiguas y segmentos intermedios;
los intervalos de cada segmento quedan documentados en `metadatos.json`.
