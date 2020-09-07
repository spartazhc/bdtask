import vapoursynth as vs
import fvsfunc as fvf
import awsmfunc as awf
from vsutil import depth as Depth
import yaml
core = vs.get_core()

with open('../config.yaml', 'r') as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)

src = core.lsmas.LWLibavSource(source = cfg["m2ts"], cache = True,
                                cachefile = f"{cfg['task_dir']}/vs/{cfg['name']}.lwi")
ccrop = cfg["crop"]
crop=core.std.Crop(src, ccrop[0], ccrop[1], ccrop[2], ccrop[3])

#bb = awf.FixRowBrightnessProtect2(bb, 1079, -4)
#bb = awf.FixColumnBrightnessProtect2(bb, 1, -8)
#fb = core.fb.FillBorders(crop,left=1,right=1,bottom=0,mode="fillmargins")
#fb = awf.bbmod(fb, left=2, right=2, u=True, v=True, blur=20, thresh=[5000, 1000])

last = crop
if not "crf_pick" in cfg.keys():
    select = core.std.SelectEvery(last[2000:-2000],cycle=2500, offsets=range(100))
    ret = core.std.AssumeFPS(select, fpsnum=src.fps.numerator, fpsden=src.fps.denominator)
    ret.set_output()
else:
    last.set_output()
