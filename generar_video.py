#!/usr/bin/env python3
"""Reel vertical: pares anime/realista y renderizado de escenas con hilos."""
from __future__ import annotations
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import threading
import statistics
import time
import wave
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
ROOT = Path(__file__).resolve().parent
RATE = 24000

def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Falló {args[0]}: {result.stderr[-2500:]}")
    return result.stdout


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]))


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


def demo_music(path):
    """Composición instrumental procedural original de 32 s, repetible."""
    t = np.arange(RATE * 32) / RATE
    audio = np.zeros_like(t)
    # Progresión Am–F–C–G; acordes suaves y arpegios, sin muestras externas.
    for bar, notes in enumerate([(45, 52, 57, 60), (41, 48, 53, 57),
                                 (48, 55, 60, 64), (43, 50, 55, 59)] * 2):
        start = bar * 4
        mask = (t >= start) & (t < start + 4)
        u = t[mask] - start
        env = np.minimum(u / .4, 1) * np.minimum((4-u) / .7, 1)
        for note in notes:
            hz = 440 * 2 ** ((note - 69) / 12)
            audio[mask] += .06 * env * np.sin(2*np.pi*hz*u)
        for step in range(8):
            m = (t >= start+step*.5) & (t < start+step*.5+.5)
            v = t[m] - start-step*.5
            hz = 440 * 2 ** ((notes[step % 4]+12-69)/12)
            audio[m] += .055*np.sin(2*np.pi*hz*v)*np.exp(-7*v)*np.minimum(v/.015, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_wav(path, audio)


def synthesize(text, engine, voice, cache):
    key = hashlib.sha256(f'{engine}|{voice}|{text}|reel_v2'.encode()).hexdigest()[:20]
    wav = cache / f'{key}.wav'
    if not wav.exists():
        if engine == 'edge':
            import edge_tts
            mp3 = cache / f'{key}.mp3'
            async def speak():
                await asyncio.wait_for(edge_tts.Communicate(text, voice, rate='+8%').save(str(mp3)), 35)
            asyncio.run(speak())
            run(['ffmpeg','-v','error','-y','-i',mp3,'-ar',RATE,'-ac','1',wav])
        else:
            exe = shutil.which('espeak-ng') or shutil.which('espeak')
            if not exe:
                raise RuntimeError('Instala espeak-ng o utiliza --tts edge con acceso a Internet.')
            raw = cache / f'{key}_raw.wav'
            run([exe,'-v','es','-s','155','-w',raw,text])
            run(['ffmpeg','-v','error','-y','-i',raw,'-ar',RATE,'-ac','1',wav])
            raw.unlink()
    with wave.open(str(wav),'rb') as f:
        return np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(np.float32)/32768


@lru_cache(maxsize=64)
def font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for directory in ['/usr/share/fonts/TTF', '/usr/share/fonts/truetype/dejavu']:
        p = Path(directory)/name
        if p.exists():
            return ImageFont.truetype(str(p),size)
    return ImageFont.truetype(name,size)


def wrapped(draw, text, ft, width):
    lines, line = [], ''
    for word in text.split():
        candidate = (line+' '+word).strip()
        if line and draw.textlength(candidate,font=ft)>width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines+[line]


def srt_time(seconds):
    ms=round(seconds*1000)
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'


def mix_audio(video, narration, music_dir, output, duration, volume):
    tracks=sorted(p for p in music_dir.glob('*') if p.suffix.lower() in {'.wav','.mp3','.ogg','.flac','.m4a'})
    cmd=['ffmpeg','-v','error','-y','-i',video,'-i',narration]
    if tracks:
        # Decodificar todos los archivos y concatenar evita problemas de códecs distintos.
        music=output.parent/'musica_concatenada.wav'
        parts=[]
        for i,track in enumerate(tracks):
            p=output.parent/f'music_{i}.wav'
            run(['ffmpeg','-v','error','-y','-i',track,'-ar',RATE,'-ac','1',p])
            with wave.open(str(p),'rb') as f:
                parts.append(np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)/32768)
            p.unlink()
        write_wav(music,np.concatenate(parts))
        cmd+=['-stream_loop','-1','-i',music]
        filters=(f'[1:a]asplit=2[voice][control];[2:a]volume={volume},'
            f'afade=t=in:d=1,afade=t=out:st={max(0,duration-2)}:d=2[bg];'
            '[bg][control]sidechaincompress=threshold=0.025:ratio=6:attack=20:release=400[duck];'
            '[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]')
        cmd+=['-filter_complex',filters,'-map','0:v:0','-map','[a]']
    else:
        cmd+=['-map','0:v:0','-map','1:a:0']
    cmd+=['-c:v','copy','-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',output]
    run(cmd)
    return [p.name for p in tracks]



def load_portrait(path, size, anime, accent):
    """Preparar encuadre vertical sin alterar los archivos fuente."""
    w,h=size
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im).convert('RGB')
        # El texto incrustado en los PNG originales se sustituye por títulos legibles.
        if not anime:
            im=im.crop((0,0,im.width,round(im.height*.89)))
        im=ImageOps.contain(im,(w,round(h*.58)),Image.Resampling.LANCZOS)
        im=im.copy()
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    glow=np.exp(-(((xx-w*.5)/(w*.65))**2+((yy-h*.45)/(h*.4))**2))
    color=np.array(accent,dtype=np.float32)
    bg=(np.array([8,10,22])+glow[...,None]*color*.32).clip(0,255).astype(np.uint8)
    if not anime:
        blurred=ImageOps.fit(im,size).filter(ImageFilter.GaussianBlur(w*.04))
        bg=(np.asarray(blurred)*.38+bg*.6).clip(0,255).astype(np.uint8)
    canvas=Image.fromarray(bg)
    # Quitar exclusivamente el blanco conectado al borde, no los brillos interiores.
    arr=np.asarray(im)
    if anime:
        whites=(np.min(arr,axis=2)>232).astype(np.uint8)
        _, labels=cv2.connectedComponents(whites)
        border=np.unique(np.concatenate([labels[0],labels[-1],labels[:,0],labels[:,-1]]))
        border=border[border!=0]
        mask=(~np.isin(labels,border)).astype(np.uint8)*255
        alpha=Image.fromarray(mask).filter(ImageFilter.GaussianBlur(.5))
    else:
        a=np.ones((im.height,im.width),np.float32)
        y,x=np.mgrid[:im.height,:im.width]
        a=np.minimum(np.minimum(x,im.width-1-x),np.minimum(y,im.height-1-y))/max(1,w*.025)
        alpha=Image.fromarray((np.clip(a,0,1)*255).astype(np.uint8))
    canvas.paste(im,((w-im.width)//2,round(h*.49-im.height/2)),alpha)
    return np.asarray(canvas).copy()


def prepare_phase(item, images, size):
    anime=load_portrait(images/'basic'/item['basic'],size,True,item['color'])
    real=load_portrait(images/'realistic'/item['realistic'],size,False,item['color'])
    # Extraer bordes en resolución reducida: un trabajo nativo de OpenCV por par.
    small=cv2.resize(real,(180,320))
    gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0)
    gy=cv2.Sobel(gray,cv2.CV_32F,0,1)
    edges=cv2.GaussianBlur(cv2.magnitude(gx,gy),(0,0),2)
    edges=cv2.resize(edges/(float(edges.max()) or 1),size)
    return dict(item=item,anime=anime,real=real,edges=edges)


def transition(phase, progress):
    """Revelado rápido guiado por bordes: extremos exactos y sin deformar caras."""
    if progress<=0: return phase['anime'].copy()
    if progress>=1: return phase['real'].copy()
    p=progress*progress*(3-2*progress)
    alpha=np.clip(p+.65*p*(1-p)*(phase['edges']-.3),0,1)[...,None]
    return (phase['anime']*(1-alpha)+phase['real']*alpha).clip(0,255).astype(np.uint8)


def build_scenes(cfg):
    scenes=[dict(title='GOKU',subtitle='DEL ANIME A LA REALIDAD',text=cfg['introduccion'],mode='intro',phase=0)]
    for i,item in enumerate(cfg['fases']):
        scenes.extend([
            dict(title=item['titulo'],subtitle='ANIME',text=item['narracion_anime'],mode='anime',phase=i),
            dict(title=item['titulo'],subtitle='REALISTA',text=item['narracion_real'],mode='real',phase=i)])
    scenes.append(dict(title='¿CUÁL ELIGES?',subtitle='ANIME  /  REALISTA',text=cfg['cierre'],mode='outro',phase=len(cfg['fases'])-1))
    for scene in scenes: scene['phase_count']=len(cfg['fases'])
    return scenes


def timeline(scenes, voices, fps):
    """Un reloj entero en fotogramas; muestras calculadas desde límites absolutos."""
    cursor=0; chunks=[]; srt=[]
    for i,(scene,voice) in enumerate(zip(scenes,voices)):
        end=.12+len(voice)/RATE
        frames=math.ceil(max(end+.22,1.65)*fps)
        start=cursor/fps; duration=frames/fps
        count=round((cursor+frames)/fps*RATE)-round(cursor/fps*RATE)
        chunk=np.zeros(count,dtype=np.float32)
        offset=round(.12*RATE); chunk[offset:offset+len(voice)]=voice
        chunks.append(chunk)
        scene.update(start=start,duration=duration,frames=frames,speech_end=end)
        srt.append(f'{i+1}\n{srt_time(start+.12)} --> {srt_time(start+end)}\n{scene["text"]}\n')
        cursor+=frames
    return np.concatenate(chunks), '\n'.join(srt),cursor/fps


def render(scene, phase, elapsed, width, height, index, total, previous=None):
    mode=scene['mode']
    if mode=='real':
        frame=transition(phase,min(1,elapsed/.42))
    elif mode=='intro':
        frame=transition(phase,(math.sin(elapsed*3-1.57)+1)/2)
    elif mode=='outro':
        frame=transition(phase,(math.sin(elapsed*4)+1)/2)
    else:
        frame=phase['anime']
        if previous is not None and elapsed<.18:
            frame=cv2.addWeighted(previous,1-elapsed/.18,frame,elapsed/.18,0)
    # Zoom leve: dinamismo sin perder cabeza/pies del personaje.
    zoom=1+.035*min(1,elapsed/scene['duration'])
    mat=cv2.getRotationMatrix2D((width/2,height*.47),0,zoom)
    frame=cv2.warpAffine(frame,mat,(width,height),borderMode=cv2.BORDER_REFLECT)
    canvas=Image.fromarray(frame).convert('RGBA')
    overlay=Image.new('RGBA',canvas.size)
    d=ImageDraw.Draw(overlay)
    def f(n): return font(round(n*width/720),True)
    def center(text,y,ft,fill='white',stroke=2):
        d.text((width/2,y),text,font=ft,anchor='mt',fill=fill,
               stroke_width=round(stroke*width/720),stroke_fill='#080B14')
    accent=tuple(phase['item']['color'])
    # Áreas de lectura alejadas de los botones y del borde inferior de una app.
    center(scene['title'],height*.082,f(57 if len(scene['title'])<13 else 43))
    ft=f(19); tw=d.textlength(scene['subtitle'],font=ft)
    y=height*.153
    d.rounded_rectangle((width/2-tw/2-22,y-9,width/2+tw/2+22,y+34*width/720),radius=12,fill=(*accent,245))
    center(scene['subtitle'],y,ft,fill='#0B1020',stroke=0)
    if mode in ['anime','real']:
        center(f'{scene["phase"]+1:02d} / {scene["phase_count"]:02d}',height*.045,f(15),fill='#DEE3EE',stroke=1)
    if .12<=elapsed<=scene['speech_end']:
        lines=wrapped(d,scene['text'].upper(),f(32),width*.80)
        for j,line in enumerate(lines):
            center(line,height*.78+j*height*.032,f(32),fill='white',stroke=3)
    # Una barra discreta refuerza el ritmo y la continuidad.
    progress=(index+elapsed/scene['duration'])/total
    d.rounded_rectangle((width*.12,height*.90,width*.88,height*.904),radius=2,fill='#56606F')
    d.rounded_rectangle((width*.12,height*.90,width*(.12+.76*progress),height*.904),radius=2,fill=(*accent,255))
    return np.asarray(Image.alpha_composite(canvas,overlay).convert('RGB'))


def render_segment(task):
    """Cada hilo tiene su propio proceso FFmpeg, pipe, fichero y registro."""
    index,scene,phases,folder,width,height,fps,epoch=task
    started=time.perf_counter(); worker=threading.current_thread().name
    target=folder/f'{index:03d}.mp4'
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}',
         '-r',str(fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','19',
         '-threads','1','-pix_fmt','yuv420p',target]
    with (folder/f'{index:03d}.log').open('w') as log:
        proc=subprocess.Popen([str(x) for x in cmd],stdin=subprocess.PIPE,stderr=log)
        try:
            previous=phases[max(0,scene['phase']-1)]['real']
            for n in range(scene['frames']):
                frame=render(scene,phases[scene['phase']],n/fps,width,height,index,len(phases)*2+2,previous)
                proc.stdin.write(frame.tobytes())
        finally:
            proc.stdin.close()
            code=proc.wait()
    if code: raise RuntimeError(f'Error de render en escena {index}; revisar {folder}/{index:03d}.log')
    finished=time.perf_counter()
    print(f'Escena {index+1:02d} terminada por {worker}: {scene["title"]} / {scene["mode"]}',flush=True)
    return dict(index=index,archivo=target.name,hilo=worker,inicio_s=started-epoch,
                fin_s=finished-epoch,duracion_s=finished-started,frames=scene['frames'])


def benchmark_preparation(items, images, size, workers, repetitions=3):
    """Mismo trabajo, calentamiento previo, orden alternado y tres repeticiones."""
    prepare_phase(items[0],images,size)
    results={'secuencial':[],'hilos':[]}
    for rep in range(repetitions):
        for method in (['secuencial','hilos'] if rep%2==0 else ['hilos','secuencial']):
            t=time.perf_counter()
            if method=='secuencial':
                for item in items: prepare_phase(item,images,size)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(lambda x:prepare_phase(x,images,size),items))
            results[method].append(time.perf_counter()-t)
    t1=statistics.median(results['secuencial']);tp=statistics.median(results['hilos'])
    return dict(muestras_s=results,repeticiones=repetitions,T1_s=t1,Tp_s=tp,speedup=t1/tp,eficiencia=t1/tp/workers)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'configuracion.json')
    parser.add_argument('--images',type=Path,default=ROOT/('images' if (ROOT/'images').is_dir() else 'image'))
    parser.add_argument('--music',type=Path,default=ROOT/'music')
    parser.add_argument('--output',type=Path,default=ROOT/'salida')
    parser.add_argument('--tts',choices=['auto','edge','espeak'],default='auto')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--height',type=int,choices=[640,1280,1920],default=1920)
    parser.add_argument('--fps',type=int,choices=[24,25,30],default=30)
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--demo-music',action='store_true')
    parser.add_argument('--music-volume',type=float,default=.36)
    parser.add_argument('--youtube',default='PENDIENTE: añadir enlace de YouTube')
    a=parser.parse_args()
    if a.workers<1 or not 0<=a.music_volume<=1: parser.error('workers >= 1; music-volume entre 0 y 1')
    for exe in ['ffmpeg','ffprobe']:
        if not shutil.which(exe): parser.error(f'Falta {exe}')
    cv2.setNumThreads(1)
    cfg=json.loads(a.config.read_text(encoding='utf-8'))
    if not cfg['fases']: parser.error('No hay fases')
    for item in cfg['fases']:
        for key,folder in [('basic','basic'),('realistic','realistic')]:
            if not (a.images/folder/item[key]).is_file(): parser.error(f'Falta {a.images/folder/item[key]}')
    a.output.mkdir(exist_ok=True,parents=True)
    cache=a.output/'cache_voz';cache.mkdir(exist_ok=True)
    segments=a.output/'segmentos';segments.mkdir(exist_ok=True)
    if a.demo_music and not any(p.suffix.lower() in {'.wav','.mp3','.ogg','.flac','.m4a'} for p in a.music.glob('*')):
        demo_music(a.music/'fondo_original.wav')
    w=a.height*9//16;h=a.height; size=(w,h)
    started=time.perf_counter(); metrics={}
    if a.benchmark:
        print('Midiendo preparación: tres repeticiones secuenciales y concurrentes...',flush=True)
        metrics['benchmark']=benchmark_preparation(cfg['fases'],a.images,size,a.workers)
    t=time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.workers,thread_name_prefix='imagenes') as pool:
        phases=list(pool.map(lambda item:prepare_phase(item,a.images,size),cfg['fases']))
    metrics['preparacion_s']=time.perf_counter()-t
    scenes=build_scenes(cfg);engine=a.tts
    if engine=='auto':
        try:
            synthesize(scenes[0]['text'],'edge',cfg['voz'],cache);engine='edge'
        except Exception as exc:
            print(f'Edge no disponible: {type(exc).__name__}; usando eSpeak.',flush=True);engine='espeak'
    t=time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=min(3,a.workers),thread_name_prefix='voz') as pool:
            voices=list(pool.map(lambda s:synthesize(s['text'],engine,cfg['voz'],cache),scenes))
    except Exception:
        if a.tts!='auto' or engine!='edge':raise
        engine='espeak'
        voices=[synthesize(s['text'],engine,cfg['voz'],cache) for s in scenes]
    metrics['voz_s']=time.perf_counter()-t
    samples,srt,duration=timeline(scenes,voices,a.fps)
    write_wav(a.output/'narracion.wav',samples)
    (a.output/'subtitulos.srt').write_text(srt,encoding='utf-8')
    epoch=time.perf_counter()
    tasks=[(i,s,phases,segments,w,h,a.fps,epoch) for i,s in enumerate(scenes)]
    print(f'Renderizando {len(tasks)} escenas con {a.workers} hilos a {w}x{h}...',flush=True)
    with ThreadPoolExecutor(max_workers=a.workers,thread_name_prefix='render') as pool:
        events=list(pool.map(render_segment,tasks))
    metrics['render_s']=time.perf_counter()-epoch
    # map retorna en orden de entrada aunque las escenas terminen desordenadas.
    (segments/'lista.txt').write_text(''.join(f"file '{e['archivo']}'\n" for e in events),encoding='utf-8')
    silent=a.output/'video_sin_audio.mp4'
    run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',segments/'lista.txt','-c','copy',silent])
    video=a.output/'goku_narrado.mp4'
    tracks=mix_audio(silent,a.output/'narracion.wav',a.music,video,duration,a.music_volume)
    points=sorted([(e['inicio_s'],1) for e in events]+[(e['fin_s'],-1) for e in events])
    active=peak=0
    for _,delta in points:active+=delta;peak=max(peak,active)
    metrics.update(tiempo_total_s=time.perf_counter()-started,workers=a.workers,tts=engine,
      voz=cfg['voz'] if engine=='edge' else 'espeak español',musica=tracks,duracion_s=duration,
      resolucion=f'{w}x{h}',fps=a.fps,escenas=scenes,eventos_render=events,max_tareas_simultaneas=peak,
      youtube=a.youtube,video=probe(video),fuentes=cfg['fases'])
    (a.output/'metadatos.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    from informe import generar_informe
    generar_informe(a.output)
    silent.unlink()
    print(f'Listo: {video} ({duration:.2f} s)',flush=True)

if __name__=='__main__': main()
