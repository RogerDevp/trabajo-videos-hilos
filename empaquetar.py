"""Crear un ZIP con el código y la entrega actual, sin cachés ni versiones antiguas."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parent
names=['generar_video.py','informe.py','empaquetar.py','configuracion.json','requirements.txt','requirements-lock.txt','README.md']
files=[root/p for p in names]
for folder in ['image','music','referencias','tests','salida']:
    files.extend(p for p in (root/folder).rglob('*') if p.is_file()
       and not {'__pycache__','cache_voz','segmentos'}.intersection(p.parts)
       and p.name not in {'musica_concatenada.wav','ffmpeg.log','video_sin_audio.mp4'})
with ZipFile(root/'Entrega_videos_con_hilos.zip','w',ZIP_DEFLATED) as z:
    for p in sorted(files):z.write(p,p.relative_to(root))
with ZipFile(root/'Entrega_videos_con_hilos.zip') as z:
    assert z.testzip() is None
    print(f'ZIP verificado: {len(z.namelist())} archivos.')
