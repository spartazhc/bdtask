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

def cfg_update(odir, js_dou, js_imdb):
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
    cfg["full"] = None
    cfg["crf_test"] = True
    cfg["crf"] = [21, 22, 23]
    cfg["crf_final"] = None

def gen_main(pls, tname, src, dstdir, douban, verbose):
    parent_dir = os.path.join(dstdir, tname)
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
    cfg_update(cfg, js_dou, js_imdb)

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
def main():
    parser = argparse.ArgumentParser(prog='bdtask',
                description='bdtask is a script to generate and manage bluray encode tasks')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='increase output verbosity')
    subparsers = parser.add_subparsers(help='sub-commands', dest='subparser_name')
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
    parser_s = subparsers.add_parser('status', help='check task status')
    parser_s.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir to check')

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


if __name__ == "__main__":
    main()