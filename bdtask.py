#!/usr/bin/python

import argparse
import sys
import os
import time
import subprocess
import logging
import yaml
import json
import re
import shutil
import requests
from distutils.dir_util import copy_tree
from scripts.nfogen import generate_nfo

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
        print(f"downloading poster {url}, try={retry}")
        r = requests.get(url, stream=True)
        retry += 1
        if (r.status_code == 200):
            break
    if (r.status_code == 200):
        with open(os.path.join(odir, "cover.jpg"), 'wb') as fd:
            for chunk in r.iter_content(1024):
                fd.write(chunk)
        return 1
    else:
        return 0

def cover_download_wget(url, odir):
    try:
        subprocess.call(f"wget -O \"{os.path.join(odir, 'cover.jpg')}\" {url}", shell=True)
    except subprocess.CalledProcessError as e:
        print("failed to execute command ", e.output)
        return 0
    return 1

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

    info = yaml.load(o.replace("]", " "), Loader=yaml.BaseLoader)
    return info

def get_chapters(playlist, bd_path, opath):
    try:
        subprocess.call(f"bdinfo -cp {playlist} \"{bd_path}\" > \"{opath}/chapters.xml\"",
                                        shell=True)
    except subprocess.CalledProcessError as e:
        print("failed to execute command ", e.output)
        raise

# TODO: generate cmd to concat those have multiple clips
def extract_cmd(info, playlist, bd_path, odir):
    cmd = f"ffmpeg -playlist {playlist} -i \"bluray:{bd_path}\" "
    # TODO: deal with condition when there are multiple clips
    if (len(info["clips"]) != 1):
        return

    clip = info["clips"][0]
    cfg["m2ts"]= os.path.join(bd_path, "BDMV", "STREAM", clip["name"])
    aud_l = []
    sub_l = []
    # there should be only one video stream
    for i, aud in enumerate(clip["streams"]["audio"]):
        if (aud["codec"] == "PCM"):
            aud_name = "{}{}.flac".format(aud["language"], i)
            aud_path = os.path.join(odir, aud_name)
            aud_l.append(aud_name)
            cmd += f"-codec flac -compression_level 12 -map a:{i} \"{aud_name}\" "
        elif (aud["codec"] == "AC3"):
            aud_name = "{}{}.ac3".format(aud["language"], i)
            aud_path = os.path.join(odir, aud_name)
            aud_l.append(aud_name)
            cmd += f"-codec copy -map a:{i} \"{aud_path}\" "
    for i, sub in enumerate(clip["streams"]["subtitles"]):
        if (sub["codec"] != "HDMV/PGS"):
            break
        sub_name = f"{sub['language']}{i}.sup"
        sub_path = os.path.join(odir, sub_name)
        sub_l.append(sub_name)
        cmd += f"-codec copy -map s:{i} \"{sub_path}\" "
    cfg["aud"] = aud_l
    cfg["sub"] = sub_l
    if (verbose):
        print(cmd)
    with open(os.path.join(odir, "extract.sh"), "wt") as fd:
        fd.write(cmd)

def cfg_update(js_dou, js_imdb, is_aka):
    if not is_aka:
        name = js_imdb["name"].replace(" ", ".")
    else:
        name = js_dou['aka'][0].replace(" ", ".")
    cfg["name"] = name
    # TODO: deal with audio type: FLAC
    cfg["fullname"] = "{}.{}.Bluray.1080p.x265.10bit.FLAC.MNHD-FRDS".format(name, js_imdb["year"])
    cfg["pub_dir"] = "{}.{}".format(js_dou["chinese_title"], cfg["fullname"])
    # auto setup crop by aspect ratio
    if ("Aspect Ratio" in js_imdb["details"].keys()):
        ratio_str = js_imdb["details"]["Aspect Ratio"]
        m = re.match(r"(\d+\.*\d*).*(\d+\.*\d*)", ratio_str)
        cfg["ratio"] = m[0]
        ratio = float(m[1]) / float(m[2])
        w, h = 1920, 1080
        if (ratio == 1.33): # special case
            w = 1440
        elif (ratio > 1.78):
            h = 1920 / ratio
        elif ( ratio < 1.77):
            w = 1080 * ratio
        cw = round((1920 - w) / 4) *2
        ch = round((1080 - h) / 4) *2
        cfg["crop"] = [cw, cw, ch, ch]
    else:
        cfg["crop"] = [0, 0, 0, 0]


    # maybe set them later?
    # cfg["full"] = None
    # cfg["crf_test"] = True
    # cfg["crf"] = [21, 22, 23]
    # cfg["crf_final"] = None
    x265_cfg = {}
    x265_cfg['vpy']          = "vs/sample.vpy"
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


def gen_main(pls, taskdir, src, douban, source, is_aka, verbose):
    if not os.path.exists(taskdir):
        os.makedirs(taskdir)
    logger = logging.getLogger(name='GEN')
    fileh = logging.FileHandler(f"{taskdir}/bdtask.log", 'a')
    formater = logging.Formatter('%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
    fileh.setFormatter(formater)
    logger.addHandler(fileh)
    parent_dir = taskdir
    cfg["task_dir"] = os.path.abspath(parent_dir)
    cfg['source'] = source
    info_dir = os.path.join(parent_dir, "info")
    if not os.path.exists(info_dir):
        os.makedirs(info_dir)
    vs_dir = os.path.join(parent_dir, "vs")
    if not os.path.exists(vs_dir):
        os.makedirs(vs_dir)
    # copy template files to parent_dir
    copy_tree(template_dir, vs_dir)
    components_dir = os.path.join(parent_dir, "components")
    components_dir = os.path.abspath(components_dir)
    if not os.path.exists(components_dir):
        os.makedirs(components_dir)

    bdinfo = get_bdinfo(pls, src, info_dir)
    get_chapters(pls, src, components_dir)
    extract_cmd(bdinfo, pls, src, components_dir)

    # request ptgen to get infomation
    js_dou = ptgen_request(douban)
    if (js_dou):
        logger.info("douban requested", extra={'task': 'ptgen'})
        with open(os.path.join(info_dir, "ptgen.txt"), "wt") as fd:
            fd.write(js_dou["format"])
        with open(os.path.join(info_dir, "douban.json"), "wt") as fd:
            fd.write(json.dumps(js_dou, indent = 2))
        js_imdb = ptgen_request(js_dou["imdb_link"])
        if (js_imdb):
            logger.info("imdb requested", extra={'task': 'ptgen'})
            with open(os.path.join(info_dir, "imdb.json"), "wt") as fd:
                fd.write(json.dumps(js_imdb, indent = 2))
        else:
            logger.error("failed to request imdb", extra={'task': 'ptgen'})

    else:
        logger.error("failed to request douban", extra={'task': 'ptgen'})

    cfg_update(js_dou, js_imdb, is_aka)

    publish_dir = os.path.join(parent_dir, cfg["pub_dir"])
    if not os.path.exists(publish_dir):
        os.makedirs(publish_dir)
    print(publish_dir)
    if cover_download_wget(js_dou["poster"], publish_dir):
        logger.info("poster downloaded", extra={'task': 'poster'})
    else:
        if cover_download_wget(js_imdb["poster"], publish_dir):
            logger.info("poster downloaded", extra={'task': 'poster'})
        else:
            logger.error("failed to download poster", extra={'task': 'poster'})

    if (verbose):
        print(yaml.dump(cfg))
    with open(os.path.join(parent_dir, "config.yaml"), "wt") as out_file:
        out_file.write(yaml.dump(cfg))
        logger.info("config.yaml writed", extra={'task': 'cfg'})

def status_new_item(logfd, parent, name, detail):
    item = {}
    item["parent"] = parent
    item["name"] = name
    item["detail"] = detail
    item["time"] = time.strftime("%Y/%m/%d-%H:%M:%S", time.localtime())
    with open(logfd, 'a+') as fd:
        fd.write("---")
        fd.write(yaml.dump(item))

def status_main(dstdir):
    if (os.path.isfile("tasklog.yaml")):
        logs = []
        with open("tasklog.yaml", 'r') as fd:
            for log in yaml.load_all(fd, Loader=yaml.FullLoader):
                logs.append(log)
        for log in logs:
            if (log['parent']):
                print(f"[{log['time']}] [{log['parent']}/{log['name']}] {log['detail']}")
    else:
        return

def x265_encode(rcfg, hevc_dir, crf, pools, is_full):
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

    if (pools == 0):
        numa_str = f"--pools \"+,-\""
    elif (pools == 1):
        numa_str = f"--pools \"-,+\""
    else:
        numa_str = f"--pools \"*\""

    cmd = f'vspipe {vpy} --y4m - | x265 -D 10 {numa_str} --preset {preset} --crf {crf} --high-tier --ctu {ctu} --rd {rd} ' \
          f'--subme {subme} --ref {ref} --pmode --no-rect --no-amp --rskip 0 --tu-intra-depth 4 --tu-inter-depth 4 --range limited ' \
          f'--no-open-gop --no-sao --rc-lookahead {rclookahead} --bframes {bframes} --vbv-bufsize {vbvbufsize} --vbv-maxrate {vbvmaxrate} ' \
          f'--colorprim {colorprim} --transfer {transfer} --colormatrix {colormatrix} --deblock {deblock} --ipratio {ipratio} --pbratio {pbratio} --qcomp {qcomp} ' \
          f'--aq-mode {aqmode} --aq-strength {aqstrength} --psy-rd {psyrd} --psy-rdoq {psyrdoq} --output "{name}.hevc" --y4m - 2>&1 | tee "{name}.log"'
    print(cmd)
    try:
        subprocess.run(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print("failed to execute command ", e.output)
        raise

def crf_main(crf_list, pools, is_force, is_pick, is_full):
    logger = logging.getLogger(name='CRF')
    fileh = logging.FileHandler("bdtask.log", 'a')
    formater = logging.Formatter('%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
    fileh.setFormatter(formater)
    logger.addHandler(fileh)
    # load x265_setting from config.yaml
    if (not os.path.isfile("config.yaml")):
        return
    with open("config.yaml", 'r') as f:
        cfg_ori = yaml.load(f, Loader=yaml.FullLoader)
    if not cfg_ori:
        logger.error("fail to parse config.yaml", extra={'task': 'prepare'})
    x265_cfg = cfg_ori["x265_cfg"]
    cfg_update = cfg_ori

    if (is_full):
        logger.info(f"crf: {cfg_ori['crf_pick']} will be encoded", extra={'task': 'full'})
        x265_encode(x265_cfg, "components/hevc", cfg_ori['crf_pick'], pools, True)
        return

    # update config.yaml
    if not "crf" in cfg_ori.keys():
        crf_diff = crf_list
        cfg_update["crf"] = crf_list
    else:
        crf_diff = [crf for crf in crf_list if crf not in cfg_ori["crf"]]
        cfg_update["crf"].extend(crf_diff)
        if (is_force):
            crf_diff = crf_list

    #  if not "crf_pick" in cfg_ori.keys():
    if (is_pick):
        cfg_update["crf_pick"] = crf_list[0]
        logger.info(f"crf value {crf_list[0]} is picked", extra={'task': 'pick'})

    with open("config.yaml", "w+") as fd:
        fd.write(yaml.dump(cfg_update))
        if (is_pick):
            return

    hevc_dir = os.path.join("components/hevc")
    if not os.path.exists(hevc_dir):
        os.makedirs(hevc_dir)

    if (crf_diff):
        print(f"crf: {crf_diff} will be tested!")
        logger.info(f"crf: {crf_diff} will be tested", extra={'task': 'crf'})
        for crf in crf_diff:
            x265_encode(x265_cfg, hevc_dir, crf, pools, False)
    else:
        print(f"crf: nothing to do! crf value {crf_list} may have be tested already.")
    return

# TODO: current grep is ok, but maybe use re to refine output
def crf_show():
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

def mkv_main(is_run, subs):
    logger = logging.getLogger(name='MKV')
    fileh = logging.FileHandler(f"bdtask.log", 'a')
    formater = logging.Formatter('%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
    fileh.setFormatter(formater)
    logger.addHandler(fileh)
    with open("config.yaml", 'r') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)
    mkv = f"{cfg['pub_dir']}/{cfg['fullname']}.mkv"
    hevc = f"components/hevc/crf-{cfg['crf_pick']}-full.hevc"

    cmd = f"mkvmerge -o \"{mkv}\" --chapters components/chapters.xml -d 0 {hevc} "
    cmd += f"--attachment-name cover --attach-file {cfg['pub_dir']}/cover.jpg "
    for aud in cfg['aud']:
        aud_lang = aud.split('.')[0][:-1]
        cmd += f"-a 0 --language 0:{aud_lang} components/{aud} "
    for sub in cfg['sub']:
        sub_lang = sub.split('.')[0][:-1]
        cmd += f"-s 0 --language 0:{sub_lang} components/{sub} "
    while subs and len(subs) > 0:
        cmd += f"-s 0 --language 0:\"{subs.pop(0)}\" --track-name 0:\"{subs.pop(0)}\" \"{subs.pop(0)}\" "
    print(cmd)
    # TODO: tee to log
    if (is_run):
        try:
            o = subprocess.check_output(cmd, shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            print("failed to execute command ", e.output)
            raise
        print(o)
        logger.info("mkv muxed", extra={'task': 'mkv'})

def nfo_main():
    logger = logging.getLogger(name='NFO')
    fileh = logging.FileHandler(f"bdtask.log", 'a')
    formater = logging.Formatter('%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
    fileh.setFormatter(formater)
    logger.addHandler(fileh)
    with open("config.yaml", 'r') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)
    mkv = f"{cfg['pub_dir']}/{cfg['fullname']}.mkv"
    nfo = f"{cfg['pub_dir']}/{cfg['fullname']}.nfo"
    generate_nfo(mkv, "info", cfg['source'], nfo)
    logger.info("nfo generated", extra={'task': 'nfo'})

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
    parser_g.add_argument('-d', '--taskdir', type=str, default='.',
                          help='output destination dir')
    parser_g.add_argument('--douban', type=str, required=True,
                          help='douban url')
    parser_g.add_argument('--source', type=str, required=True,
                          help='bluray source')
    parser_g.add_argument('--aka', action='store_true',
                          help='use aka as film name')
    # subparser [status]
    parser_s = subparsers.add_parser('status', help='check task status')
    parser_s.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir to check')
    # subparser [crf]
    parser_c = subparsers.add_parser('crf', help='submit crf test')
    parser_c.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')
    parser_c.add_argument('-c', '--val', type=float, nargs='+',
                          help='crf value to test')
    parser_c.add_argument('--pools', type=int, default=-1,
                          help='numa pools to use, only support 2 numa node')
    parser_c.add_argument('--show', action='store_true',
                          help='show crf test results')
    parser_c.add_argument('--force', action='store_true',
                        help='re-run crf test forcely')
    parser_c.add_argument('--pick', action='store_true',
                        help='pick crf value')
    parser_c.add_argument('--full', action='store_true',
                        help='run full encode')
    # subparser [mkv]
    parser_m = subparsers.add_parser('mkv', help='call mkvmerge to mux all components')
    parser_m.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')
    parser_m.add_argument('--run', action='store_true', help='run the mkvmerge script')
    parser_m.add_argument('--sub', nargs='*', help='add additional subtitles: [lang] [track name] [file]')
    # subparser [nfo]
    parser_n = subparsers.add_parser('nfo', help='generate nfo from mkv')
    parser_n.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')


    args = parser.parse_args()
    verbose = args.verbose
    taskdir = args.taskdir

    logging.basicConfig(format='%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s',
                        level=logging.INFO)
    if (args.subparser_name == "gen"):
        pls    = args.playlist
        src    = args.src
        douban = args.douban
        source = args.source
        tname  = args.name.replace(" ", ".")
        is_aka = args.aka
        parent_dir = os.path.join(taskdir, tname)
        gen_main(pls, parent_dir, src, douban, source, is_aka, verbose)
    elif (args.subparser_name == "status"):
        os.chdir(taskdir)
        status_main(taskdir)
    elif (args.subparser_name == "crf"):
        crf_list = args.val
        pools     = args.pools
        is_show  = args.show
        is_force = args.force
        is_pick  = args.pick
        is_full  = args.full
        # chdir will simplify subsequent dir operations
        os.chdir(taskdir)
        if (crf_list or is_full):
            crf_main(crf_list, pools, is_force, is_pick, is_full)
        if (is_show):
            crf_show()
    elif (args.subparser_name == "mkv"):
        is_run = args.run
        subs = args.sub
        os.chdir(taskdir)
        mkv_main(is_run, subs)
    elif (args.subparser_name == "nfo"):
        os.chdir(taskdir)
        nfo_main()


if __name__ == "__main__":
    main()
