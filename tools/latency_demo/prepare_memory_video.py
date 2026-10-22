import urllib.request,zipfile,hashlib,json
from pathlib import Path
root=Path('/tmp/ttoktti-runtime/memory-benchmark');root.mkdir(exist_ok=True)
url='https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip'
archive=root/'source.zip'
urllib.request.urlretrieve(url,archive)
with zipfile.ZipFile(archive) as z:
 names=[n for n in z.namelist() if n.lower().endswith('.mp4') and not n.startswith('__MACOSX/')]
 assert len(names)==1,names
 with z.open(names[0]) as src, (root/'source.mp4').open('wb') as dst:
  import shutil;shutil.copyfileobj(src,dst)
meta={'url':url,'title':'Big Buck Bunny','attribution':'(c) 2008 Blender Foundation / www.bigbuckbunny.org','license':'CC BY 3.0','license_source':'https://peach.blender.org/about/','sha256':hashlib.sha256((root/'source.mp4').read_bytes()).hexdigest(),'bytes':(root/'source.mp4').stat().st_size}
(root/'source.json').write_text(json.dumps(meta,indent=2))
print(json.dumps(meta),flush=True)
