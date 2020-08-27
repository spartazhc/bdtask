import vapoursynth as vs
import fvsfunc as fvf
import awsmfunc as awf
from vsutil import depth as Depth
import yaml
core = vs.get_core()

def FrameInfo(clip, title,
              style="sans-serif,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,7,10,10,10,1"):
    import functools
    def FrameProps(n, clip):
        clip = core.sub.Subtitle(clip, "Frame " + str(n) + " of " + str(
            clip.num_frames) + "\nPicture type: " + clip.get_frame(n).props._PictType.decode(), style=style)
        return clip
    clip = core.std.FrameEval(clip, functools.partial(FrameProps, clip=clip))
    clip = core.sub.Subtitle(clip, ['\n \n \n' + title], style=style)
    return clip

def outfix(clip):
    encode = core.std.SetFrameProp(clip,prop="_Matrix",delete=True)
    encode = core.std.SetFrameProp(encode,prop="_Transfer",delete=True)
    encode = core.std.SetFrameProp(encode,prop="_Primaries",delete=True)
    return encode
   
with open('config.yaml', 'r') as f:
	cfg = yaml.load(f, Loader=yaml.FullLoader) 

src = core.lsmas.LWLibavSource(source = cfg["m2ts"], cache = True,
                               cachefile = cfg["name"] + ".lwi")
ccrop = cfg[crop]
src=core.std.Crop(src, ccrop[0], ccrop[1], ccrop[2], ccrop[3])
src=Depth(src, 10)
src=FrameInfo(src,"source")

if (cfg[crf_test]):
	select=core.std.SelectEvery(src[2000:-2000],cycle=2500, offsets=range(100))
	src=core.std.AssumeFPS(select, fpsnum=src.fps.numerator, fpsden=src.fps.denominator)



encode = core.lsmas.LWLibavSource(source = cfg["full"], cache = True)

encode=FrameInfo(encode,"encode")
encode=outfix(encode)

out=core.std.Interleave([src, encode])
out.set_output()