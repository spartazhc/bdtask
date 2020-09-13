#!/usr/bin/python

import json
import subprocess
import sys
import os
import time
import langcodes
import re

def generate_nfo(ifile, info_dir, source, ofile):
    try:
        o = subprocess.check_output(f"mediainfo --Output=JSON {ifile}",
                                        shell=True).decode("UTF-8")
    except subprocess.CalledProcessError as e:
        print("failed to execute command ", e.output)
        raise
    info = json.loads(o)
    media = info['media']
    general = media['track'][0]
    video = media['track'][1]

    s_aud = ""
    s_sub = ""
    for _, trak in enumerate(media['track'], start=2):
        if trak['@type'] == 'Audio':
            s_aud += f"AUDiO {'1' if not '@typeorder' in trak.keys() else trak['@typeorder']}.......: {langcodes.Language.get(trak['Language']).display_name():<7} {trak['Format']:>4} @ {int(trak['BitRate']) / 1000 :.0f} Kbps\n"
        elif trak['@type'] == 'Text':
            if 'Title' in trak.keys():
                if trak['Title'].startwith("Tra"):
                    sub_la = "cht"
                if trak['Title'].startwith("Simp"):
                    sub_la = "chs"
            else:
                sub_la = langcodes.Language.get(trak['Language']).to_tag()
                if trak['Language'] == 'zh':
                    sub_la = "chs"
            if s_sub:
                s_sub += '/'
            s_sub += f"{sub_la}({trak['Format']})"
    if (info_dir):
        with open(os.path.join(info_dir, "douban.json")) as f:
            douban = json.loads(f.read())
        with open(os.path.join(info_dir, "imdb.json"), 'r') as f:
            imdb = json.loads(f.read())
    # print(json.dumps(douban, sort_keys=True, indent=2))
    crf_value = re.match(r".*crf=(\d+\.\d+).*", video['Encoded_Library_Settings'])[1]
    out = f"""
{media['@ref'].split('/')[-1]}


NAME..........: {imdb['name']}
GENRE.........: {imdb['genre']}
RATiNG........: {imdb['imdb_rating']}
iMDB URL......: {imdb['imdb_link']}
DOUBAN URL....: {douban['douban_link']}
RELEASE DATE..: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
ENCODE BY.....: spartazhc @ FRDS
RUNTiME.......: {time.strftime('%H:%M:%S', time.gmtime(int(float(general['Duration']))))}
FiLE SiZE.....: {int(general['FileSize']) / 2**30 :.2f} GiB

ViDEO CODEC...: x265-3.4 @ {int(video['BitRate']) / 1000 :.0f} Kbps @crf={crf_value}
RESOLUTiON....: {video['Sampled_Width']}x{video['Sampled_Height']}
ASPECT RATiO..: {float(video['DisplayAspectRatio']):.2f}:1
FRAME RATE....: {video['FrameRate']} fps
SOURCE........: {source}
SUBTiTLES.....: {s_sub}
{s_aud}
    -= FRDS MNHD TEAM =-
"""
    print(out)
    with open(ofile, "wt") as fd:
        fd.write(out)

def main():
    if (not len(sys.argv) == 5):
        print("usage: ./nfoGen.py [video] [infodir] [source] [output.nfo]")
    ifile  = sys.argv[1]
    infodir = sys.argv[2]
    source = sys.argv[3]
    ofile = sys.argv[4]
    print(ifile, ofile)
    generate_nfo(ifile, infodir, source, ofile)

if __name__ == "__main__":
    main()
