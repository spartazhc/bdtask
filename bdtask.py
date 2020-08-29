#!/usr/bin/python

import argparse
import sys
import os
import subprocess
import yaml
import json
import shutil
import requests
from distutils.dir_util import copy_tree

template_dir = "/home/spartazhc/source/bdtask/templates/"
cfg = {}
verbose = False

def ptgen_request(url):
    ptgen = "https://api.rhilip.info/tool/movieinfo/gen"
    param = {'url' : url}
    r = requests.get(url = ptgen, params = param)
    if (r.status_code != 200):
        return None
    else:
        return r.json()

def cover_download(url, odir):
    retry = 0
    while (retry < 5):
        r = requests.get(url, stream=True)
        if (r.status_code == 200):
            break
    if (r.status_code == 200):
        with open(os.path.join(odir, "cover.jpg"), 'wb') as fd:
            for chunk in r.iter_content(1024):
                fd.write(chunk)


"""
call bdinfo to retrive bdinfo, write it to bdinfo.yaml
@return info in dict
"""
def get_bdinfo(playlist, bd_path, opath):
    try:
        o = subprocess.check_output("bdinfo -ip {} \"{}\"".format(playlist, bd_path),
                                        shell=True).decode("UTF-8")
    except subprocess.CalledProcessError as e:
        print("failed to execute command ", e.output)
        raise
    with open(os.path.join(opath, "bdinfo.yaml"), "wt") as fd:
        fd.write(o)
    info = yaml.load(o, Loader=yaml.BaseLoader)
    return info

# TODO: generate cmd to concat those have multiple clips
def extract_cmd(info, playlist, bd_path, odir):
    cmd = "ffmpeg -playlist {} -i 'bluray:{}' ".format(playlist, bd_path)
    # TODO: deal with condition when there are multiple clips
    if (len(info["clips"]) != 1):
        return

    clip = info["clips"][0]
    cfg["m2ts"]= os.path.join(bd_path, "BDMV", "STREAM", clip["name"])
    # there should be only one video stream
    for i, aud in enumerate(clip["streams"]["audio"]):
        if (aud["codec"] == "PCM"):
            aud_name = "{}{}.flac".format(aud["language"], i)
            aud_path = os.path.join(odir, aud_name)
            cmd += "-codec flac -compression_level 12 -map a:{} {} ".format(i, aud_path)
        elif (aud["codec"] == "AC3"):
            aud_name = "{}{}.ac3".format(aud["language"], i)
            aud_path = os.path.join(odir, aud_name)
            cmd += "-codec copy -map a:{} {} ".format(i, aud_path)
    for i, sub in enumerate(clip["streams"]["subtitles"]):
        if (sub["codec"] != "HDMV/PGS"):
            break
        sub_name = "{}{}.sup".format(sub["language"], i)
        sub_path = os.path.join(odir, sub_name)
        cmd += "-codec copy -map s:{} {} ".format(i, sub_path)
    if (verbose):
        print(cmd)
    with open(os.path.join(odir, "extract.sh"), "wt") as fd:
        fd.write(cmd)

def cfg_update(js_dou, js_imdb):
    name = js_imdb["name"].replace(" ", ".")
    cfg["name"] = name
    # TODO: deal with audio type: FLAC
    cfg["fullname"] = "{}.{}.Bluray.1080p.x265.10bit.FLAC.MNHD-FRDS".format(name, js_imdb["year"])
    cfg["pub_dir"] = "{}.{}".format(js_dou["chinese_title"], cfg["fullname"])
    # auto setup crop by aspect ratio
    ratio_str = js_imdb["details"]["Aspect Ratio"]
    cfg["ratio"] = ratio_str
    ratio_list = [float(i) for i in ratio_str.split(" : ")]
    ratio = ratio_list[0] / ratio_list[1]
    w, h = 1920, 1080
    if (ratio == 1.33): # special case
        w = 1440
    elif (ratio > 1.78):
        h = 1920 / ratio
    elif ( ratio < 1.77):
        w = 1080 * ratio
    cw = int((1920 - w) / 2)
    ch = int((1080 - h) / 2)
    cfg["crop"] = [cw, cw, ch, ch]

    # maybe set them later?
    # cfg["full"] = None
    # cfg["crf_test"] = True
    # cfg["crf"] = [21, 22, 23]
    # cfg["crf_final"] = None
    x265_cfg = {}
    x265_cfg['vpy']          = "sample.vpy"
    x265_cfg['qcomp']        = 0.6
    x265_cfg['preset']       = "veryslow"
    x265_cfg['bframes']      = 16
    x265_cfg['ctu']          = 32
    x265_cfg['rd']           = 4
    x265_cfg['subme']        = 7
    x265_cfg['ref']          = 6
    x265_cfg['rc-lookahead'] = 250
    x265_cfg['vbv-bufsize']  = 160000
    x265_cfg['vbv-maxrate']  = 160000
    x265_cfg['colorprim']    = "bt709"
    x265_cfg['transfer']     = "bt709"
    x265_cfg['colormatrix']  = "bt709"
    x265_cfg['deblock']      = "-3:-3"
    x265_cfg['ipratio']      = 1.3
    x265_cfg['pbratio']      = 1.2
    x265_cfg['aq-mode']      = 2
    x265_cfg['aq-strength']  = 1.0
    x265_cfg['psy-rd']       = 1.0
    x265_cfg['psy-rdoq']     = 1.0
    cfg["x265_cfg"] = x265_cfg


def gen_main(pls, tname, src, dstdir, douban, verbose):
    parent_dir = os.path.join(dstdir, tname)
    cfg["task_dir"] = os.path.abspath(parent_dir)
    # copy template files to parent_dir
    copy_tree(template_dir, parent_dir)
    components_dir = os.path.join(parent_dir, "components")
    if not os.path.exists(components_dir):
        os.makedirs(components_dir)

    bdinfo = get_bdinfo(pls, src, parent_dir)
    extract_cmd(bdinfo, pls, src, components_dir)

    # request ptgen to get infomation
    js_dou = ptgen_request(douban)
    if (js_dou):
        with open(os.path.join(parent_dir, "ptgen.txt"), "wt") as fd:
            fd.write(js_dou["format"])
        with open(os.path.join(parent_dir, "douban.txt"), "wt") as fd:
            fd.write(json.dumps(js_dou, indent = 2))
        js_imdb = ptgen_request(js_dou["imdb_link"])
        if (js_imdb):
            with open(os.path.join(parent_dir, "imdb.txt"), "wt") as fd:
                fd.write(json.dumps(js_imdb, indent = 2))
    cfg_update(js_dou, js_imdb)

    publish_dir = os.path.join(parent_dir, cfg["pub_dir"])
    if not os.path.exists(publish_dir):
        os.makedirs(publish_dir)
    cover_download(js_dou["poster"], publish_dir)

    if (verbose):
        print(yaml.dump(cfg))
    with open(os.path.join(parent_dir, "config.yaml"), "wt") as out_file:
        out_file.write(yaml.dump(cfg))

def status_main(dstdir):
    return

def load_x265_setting(config):
    if (os.path.isfile(config)):
        with open(config, 'r') as f:
            set = yaml.load(f, Loader=yaml.FullLoader)
            return set['x265_cfg']
    else:
        return None


def x265_encode(rcfg, hevc_dir, crf, is_full):
    vpy = rcfg['vpy']
    qcomp = rcfg['qcomp']
    preset = rcfg['preset']
    bframes = rcfg['bframes']
    ctu = rcfg['ctu']
    rd = rcfg['rd']
    subme = rcfg['subme']
    ref = rcfg['ref']
    rclookahead = rcfg['rc-lookahead']
    vbvbufsize = rcfg['vbv-bufsize']
    vbvmaxrate = rcfg['vbv-maxrate']
    colorprim = rcfg['colorprim']
    transfer = rcfg['transfer']
    colormatrix = rcfg['colormatrix']
    deblock = rcfg['deblock']
    ipratio = rcfg['ipratio']
    pbratio = rcfg['pbratio']
    aqmode = rcfg['aq-mode']
    aqstrength = rcfg['aq-strength']
    psyrd = rcfg['psy-rd']
    psyrdoq = rcfg['psy-rdoq']

    if (not is_full):
        name = os.path.join(hevc_dir, f"crf-{crf}")
    else:
        name = os.path.join(hevc_dir, f"crf-{crf}-full")
    cmd = f'vspipe {vpy} --y4m - | x265 -D 10 --preset {preset} --crf {crf} --high-tier --ctu {ctu} --rd {rd} ' \
          f'--subme {subme} --ref {ref} --pmode --no-rect --no-amp --rskip 0 --tu-intra-depth 4 --tu-inter-depth 4 --range limited ' \
          f'--no-open-gop --no-sao --rc-lookahead {rclookahead} --no-cutree --bframes {bframes} --vbv-bufsize {vbvbufsize} --vbv-maxrate {vbvmaxrate} ' \
          f'--colorprim {colorprim} --transfer {transfer} --colormatrix {colormatrix} --deblock {deblock} --ipratio {ipratio} --pbratio {pbratio} --qcomp {qcomp} ' \
          f'--aq-mode {aqmode} --aq-strength {aqstrength} --psy-rd {psyrd} --psy-rdoq {psyrdoq} --output "{name}.mkv" --y4m - 2>&1 | tee "{name}.log"'
    try:
        subprocess.run(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print("failed to execute command ", e.output)
        raise

def crf_main(dstdir, crf_list):
    # load x265_setting from config.yaml
    if (not os.path.isfile("config.yaml")):
        return
    with open("config.yaml", 'r') as f:
        cfg_ori = yaml.load(f, Loader=yaml.FullLoader)
    x265_cfg = cfg_ori["x265_cfg"]
    cfg_update = cfg_ori
    if (not cfg_ori["crf"]):
        crf_diff = crf_list
        cfg_update["crf"] = crf_list
    else:
        crf_diff = [crf for crf in crf_list if crf not in cfg_ori["crf"]]
        cfg_update["crf"].extend(crf_diff)

    with open("config.yaml", "w+") as fd:
        fd.write(yaml.dump(cfg_update))

    hevc_dir = os.path.join("components/hevc")
    if not os.path.exists(hevc_dir):
        os.makedirs(hevc_dir)
    for crf in crf_diff:
        x265_encode(x265_cfg, hevc_dir, crf, False)
    return

def main():
    parser = argparse.ArgumentParser(prog='bdtask',
                description='bdtask is a script to generate and manage bluray encode tasks')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='increase output verbosity')
    subparsers = parser.add_subparsers(help='sub-commands', dest='subparser_name')
    # subparser [gen]
    parser_g = subparsers.add_parser('gen', help='generate a bluray encode task')
    parser_g.add_argument('-p', '--playlist', type=int, default='1',
                          help='select bluray playlist')
    parser_g.add_argument('-n', '--name', type=str, default='bdtask_default',
                          help='name of task')
    parser_g.add_argument('-s', '--src', type=str, required=True,
                          help='bluray disc path')
    parser_g.add_argument('-d', '--dstdir', type=str, default='.',
                          help='output destination dir')
    parser_g.add_argument('--douban', type=str, required=True,
                          help='douban url')
    # subparser [status]
    parser_s = subparsers.add_parser('status', help='check task status')
    parser_s.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir to check')
    # subparser [crf]
    parser_c = subparsers.add_parser('crf', help='submit crf test')
    parser_c.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')
    parser_c.add_argument('-c', '--val', type=int, nargs='+',
                          help='crf value to test')
    parser_c.add_argument('--show', action='store_true',
                          help='show crf test results')


    args = parser.parse_args()
    verbose = args.verbose

    if (args.subparser_name == "gen"):
        pls    = args.playlist
        tname  = args.name.replace(" ", ".")
        src    = args.src
        dstdir = args.dstdir
        douban = args.douban
        gen_main(pls, tname, src, dstdir, douban, verbose)
    elif (args.subparser_name == "status"):
        dstdir = args.taskdir
        status_main(dstdir)
    elif (args.subparser_name == "crf"):
        dstdir = args.taskdir
        crf_list = args.val
        is_show = args.show
        os.chdir(dstdir)
        if (is_show):
            hevc_dir = "components/hevc"
            if (not os.path.exists(hevc_dir)):
                return
            else:
                try:
                    o = subprocess.check_output(f"grep encoded {hevc_dir}/*.log ",
                                                    shell=True).decode("UTF-8")
                except subprocess.CalledProcessError as e:
                    print("failed to execute command ", e.output)
                    raise
                print(o)
                return
        print(f"crf: {crf_list} will be tested!")
        crf_main(dstdir, crf_list)


if __name__ == "__main__":
    main()