#!/usr/bin/python3

import argparse
import sys
import os
import time
import subprocess
import logging
import yaml
import yamlordereddictloader
import json
import re
import requests
from distutils.dir_util import copy_tree
from scripts.nfogen import generate_nfo
from titlecase import titlecase
import xml.etree.ElementTree as ET

template_dir = "/home/spartazhc/source/bdtask/templates/"
cfg = {}
verbose = False

fake_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.106 Safari/537.36'

ptgen_api = 'https://api.rhilip.info/tool/movieinfo/gen'
# ptgen_api = 'https://api.nas.ink/infogen'
# ptgen_api = 'https://ptgen.rhilip.info/'


def ptgen_request(url):
    ptgen = "https://api.rhilip.info/tool/movieinfo/gen"
    param = {'url': url}
    r = requests.get(url=ptgen, params=param)
    if (r.status_code != 200):
        return None
    else:
        return r.json()

# def cover_download(url, odir):
#     retry = 0
#     while (retry < 5):
#         print(f"downloading poster {url}, try={retry}")
#         r = requests.get(url, stream=True)
#         retry += 1
#         if (r.status_code == 200):
#             break
#     if (r.status_code == 200):
#         with open(os.path.join(odir, "cover.jpg"), 'wb') as fd:
#             for chunk in r.iter_content(1024):
#                 fd.write(chunk)
#         return 1
#     else:
#         return 0


def cover_download_wget(url, odir):
    try:
        subprocess.call(
            f"wget -O \"{os.path.join(odir, 'cover.jpg')}\" {url}", shell=True)
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
        o = subprocess.check_output(
            "bdinfo -ip {} \"{}\"".format(playlist, bd_path),
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
    cfg["m2ts"] = os.path.join(bd_path, "BDMV", "STREAM", clip["name"])
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
    cfg["fullname"] = "{}.{}.Bluray.1080p.x265.10bit.FLAC.MNHD-FRDS".format(
        name, js_imdb["year"])
    cfg["pub_dir"] = "{}.{}".format(js_dou["chinese_title"], cfg["fullname"])
    # auto setup crop by aspect ratio
    if ("Aspect Ratio" in js_imdb["details"].keys()):
        ratio_str = js_imdb["details"]["Aspect Ratio"]
        m = re.match(r"(\d+\.*\d*).*(\d+\.*\d*)", ratio_str)
        cfg["ratio"] = m[0]
        ratio = float(m[1]) / float(m[2])
        w, h = 1920, 1080
        if (ratio == 1.33):  # special case
            w = 1440
        elif (ratio > 1.78):
            h = 1920 / ratio
        elif (ratio < 1.77):
            w = 1080 * ratio
        cw = round((1920 - w) / 4) * 2
        ch = round((1080 - h) / 4) * 2
        cfg["crop"] = [cw, cw, ch, ch]
    else:
        cfg["crop"] = [0, 0, 0, 0]

    # maybe set them later?
    # cfg["full"] = None
    # cfg["crf_test"] = True
    # cfg["crf"] = [21, 22, 23]
    # cfg["crf_final"] = None
    x265_cfg = {}
    x265_cfg['vpy'] = "vs/sample.vpy"
    x265_cfg['qcomp'] = 0.6
    x265_cfg['preset'] = "veryslow"
    x265_cfg['bframes'] = 16
    x265_cfg['ctu'] = 32
    x265_cfg['rd'] = 4
    x265_cfg['subme'] = 7
    x265_cfg['ref'] = 6
    x265_cfg['rc-lookahead'] = 250
    x265_cfg['vbv-bufsize'] = 160000
    x265_cfg['vbv-maxrate'] = 160000
    x265_cfg['colorprim'] = "bt709"
    x265_cfg['transfer'] = "bt709"
    x265_cfg['colormatrix'] = "bt709"
    x265_cfg['deblock'] = "-3:-3"
    x265_cfg['ipratio'] = 1.3
    x265_cfg['pbratio'] = 1.2
    x265_cfg['aq-mode'] = 2
    x265_cfg['aq-strength'] = 1.0
    x265_cfg['psy-rd'] = 1.0
    x265_cfg['psy-rdoq'] = 1.0
    cfg["x265_cfg"] = x265_cfg


def gen_main(pls, taskdir, src, douban, source, is_aka, verbose):
    if not os.path.exists(taskdir):
        os.makedirs(taskdir)
    logger = logging.getLogger(name='GEN')
    fileh = logging.FileHandler(f"{taskdir}/bdtask.log", 'a')
    formater = logging.Formatter(
        '%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
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
            fd.write(json.dumps(js_dou, indent=2))
        js_imdb = ptgen_request(js_dou["imdb_link"])
        if (js_imdb):
            logger.info("imdb requested", extra={'task': 'ptgen'})
            with open(os.path.join(info_dir, "imdb.json"), "wt") as fd:
                fd.write(json.dumps(js_imdb, indent=2))
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
                print(
                    f"[{log['time']}] [{log['parent']}/{log['name']}] {log['detail']}")
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
    formater = logging.Formatter(
        '%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
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
        logger.info(f"crf: {cfg_ori['crf_pick']} will be encoded", extra={
                    'task': 'full'})
        x265_encode(x265_cfg, "components/hevc",
                    cfg_ori['crf_pick'], pools, True)
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
        logger.info(f"crf value {crf_list[0]} is picked", extra={
                    'task': 'pick'})

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
        print(
            f"crf: nothing to do! crf value {crf_list} may have be tested already.")
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
    formater = logging.Formatter(
        '%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
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
    formater = logging.Formatter(
        '%(asctime)-15s %(name)-3s %(task)-5s %(levelname)s %(message)s')
    fileh.setFormatter(formater)
    logger.addHandler(fileh)
    with open("config.yaml", 'r') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)
    mkv = f"{cfg['pub_dir']}/{cfg['fullname']}.mkv"
    nfo = f"{cfg['pub_dir']}/{cfg['fullname']}.nfo"
    generate_nfo(mkv, "info", cfg['source'], nfo)
    logger.info("nfo generated", extra={'task': 'nfo'})


class FilmTaskStopException(Exception):
    pass


class Chapter:
    ChapStrings = []

    def __init__(self):
        pass

    def load_xml(self, file_in):
        pass

    def write_xml(self, file_out):
        pass


class BDinfo:
    def __init__(self, bdinfo):
        self.video: dict = None
        self.audio: dict = None
        self.sub: dict = None

    def parse_bdinfo(self, bdinfo):
        pass


class TaskBase:
    def __init__(self, name):
        self.name = name
        self.desc: str = None
        self.chapter: Chapter = None
        self.bd_path: str = None
        self.playlist: int = None
        self.base_path: str = None
        self.vs_path: str = None

    def add_description(self, desc):
        self.desc = desc

    def add_chapter(self, chapter):
        self.chapter = chapter


class Supplement(TaskBase):
    """
    这部分使用 FFmpeg 简单处理，只需要切除黑边，不使用 vapoursynth
    """

    def __init__(self, name):
        super(Supplement, self).__init__(name)
        self.sub_sup = []
        self.parent = None

    def add_sub(self, supplement):
        # print("add sub")
        self.sub_sup.append(supplement)
        supplement.add_parent(self)

    def add_parent(self, supplement):
        self.parent = supplement

    def set_playlist(self, num):
        self.playlist = num

    def export_task(self):
        if self.sub_sup:
            info = []
            for sub in self.sub_sup:
                info += sub.export_task()
            return info
        else:
            sup = {}
            if self.parent:
                sup['name'] = titlecase(
                    self.parent.name) + '-' + titlecase(self.name).replace('"', '')
            else:
                sup['name'] = titlecase(self.name).replace('"', '')
            sup['name'] = sup['name'].replace(' ', '.')
            # sup['bd_path'] = self.bd_path
            sup['playlist'] = self.playlist
            sup['type'] = 'supplement'
            if self.desc:
                sup['desc'] = self.desc
            return [sup]

    def __str__(self):
        return f"{self.name}: {self.playlist},{len(self.sub_sup)} desc: {self.desc}\n  {[str(sub) for sub in self.sub_sup] if self.sub_sup else ''}"


class FilmTask(TaskBase):
    def __init__(self, params):
        self.params = params
        self.bd_path = params.get('src')
        self.playlist = 1
        self.bdinfo = None
        self.film_info: dict = None
        self.supplements: list = []
        self.get_path()
        self.logger_init(params.get('subparser_name').upper())

    def get_path(self):
        if self.params.get('subparser_name') == 'gen':
            self.film_info = self.get_bluray_name(
                os.path.basename(self.bd_path))
            self.base_path = os.path.join(os.path.abspath(
                self.params.get('taskdir')), self.film_info.get('name'))
        else:
            self.base_path = os.path.join(
                os.path.abspath(self.params.get('taskdir')))
        self.cache_path = os.path.join(self.base_path, 'cache')
        self.vs_path = os.path.join(self.base_path, 'vs')
        self.comp_path = os.path.join(self.base_path, 'comp')

        if self.params.get('subparser_name') == 'gen':
            self.mkdir_of_task()
        else:
            if not os.path.exists(self.base_path):
                raise FilmTaskStopException(f"Error: no dir {self.base_path}")

    def logger_init(self, logger_name):
        self.logger = logging.getLogger(name=logger_name)
        fileh = logging.FileHandler(f"{self.base_path}/bdtask.log", 'a')
        formater = logging.Formatter(
            '%(asctime)-15s %(name)-3s %(levelname)s %(message)s')
        fileh.setFormatter(formater)

    @staticmethod
    def get_bluray_name(vf):
        """
        get info from file name
        ret = {'name': name, 'year': year, 'reso': reso, 'cut': cut}
        """
        country_codes = ["BFI", "CEE", "CAN", "CHN", "ESP", "EUR", "FRA", "GBR", "GER",
                         "HKG", "IND", "ITA", "JPN", "KOR", "NOR", "NLD", "POL", "RUS", "TWN", "USA"]
        cut_types = {'cc': 'CC', 'criterion': 'CC', 'director': 'Directors Cut', 'extended': 'Extended Cut',
                     'uncut': 'UNCUT', 'remastered': 'Remastered', 'repack': 'Repack', 'uncensored': 'Uncensored', 'unrated': 'Unrated'}

        vf_en = re.sub("[\u4E00-\u9FA5]+.*[\u4E00-\u9FA5]+.*?\.",
                       "", os.path.basename(vf))
        # print(vf_en)
        m = re.match(
            r"\.?([\w,.'!?&\s-]+)[\s|.]+(\d{4}).*((?:720|1080|2160)[pP]).*", vf_en)
        cut = ""
        country = ""
        # check FIFA country code
        for code in country_codes:
            if code in vf_en:
                country = code
                break
        vf_en_lower = vf_en.lower()
        for key, val in cut_types.items():
            if key in vf_en_lower:
                cut = val
                break
        # Normally, there should be either country or cut
        cut = country + cut
        if m is None:
            # sometimes there is no resolution in filename, maybe the uploader missed it
            m = re.match(r"([\w,.'!?&-]+).(\d{4})+.*", vf_en)
            if m is None:
                print(f"vf_en: {vf_en}, fail in regex match")
                return
            name, year, reso = m[1], m[2], "1080p"
            if "AKA" in m[1]:
                try:
                    name = re.match(r"([\w,.'!?&-]+)\.AKA.*", m[1])[1]
                except TypeError:
                    print(f"vf_en: {vf_en}, fail in AKA regex match")
            # fname = f"{name.replace('.', ' ')} ({year}) - [{cut if cut else reso}].{suffix}"
        else:
            name, year, reso = m[1], m[2], m[3].lower()
            if "AKA" in m[1]:
                try:
                    name = re.match(r"([\w,.'!?&-]+)\.AKA.*", m[1])[1]
                except TypeError:
                    print(f"vf_en: {vf_en}, fail in AKA2 regex match")
            # fname = f"{name.replace('.', ' ')} ({year}) - [{cut if cut else reso}].{suffix}"
        name = name.replace('.', ' ')
        ret = {'name': name, 'year': year, 'reso': reso, 'cut': cut}
        print(f'filename parsed:{name}, {year}, {reso}, {cut}')
        return ret

    def getinfo(self):
        if not self.check_cache():
            self.search_info_from_douban_and_ptgen()
            self.get_chapters()
            self.call_bdinfo()
            self.write_cache()
            self.gen_vs_scripts()
        self.add_supplement()
        self.export_task()

    def run_crf(self):
        self.logger.info("run crf")
        # load x265_setting from config.yaml
        task_path = os.path.join(self.base_path, "task.yaml")
        if (not os.path.isfile(task_path)):
            return
        with open(task_path, 'r') as f:
            try:
                cfg_ori = yaml.load(f, Loader=yaml.BaseLoader)
            except Exception as e:
                raise FilmTaskStopException(f"fail to read {task_path}, {e}")
            # logger.error("fail to parse config.yaml")
        cfg_update = cfg_ori
        self.task_dict = cfg_ori
        crf_list = self.params.get('val')

        # pick crf value
        if (self.params.get('pick')):
            cfg_update["crf_pick"] = crf_list[0]
            self.logger.info(f"crf value {crf_list[0]} is picked")

        # encode full film using 'crf_pick' value
        if (self.params.get('full')):
            self.logger.info(f"{cfg_ori['crf_pick']} will be encoded")
            self.x265_encode(cfg_ori['crf_pick'], isfull=True)
            return

        # update config.yaml
        if not "crf" in cfg_ori.keys():
            crf_diff = crf_list
            cfg_update["crf"] = crf_list
        else:
            crf_diff = [crf for crf in crf_list if crf not in cfg_ori["crf"]]
            cfg_update["crf"].extend(crf_diff)
            if (self.params.get('force')):
                crf_diff = crf_list

        with open("config.yaml", "w+") as fd:
            yaml.dump(cfg_update, fd, sort_keys=False)
            if (self.params.get('pick')):
                return

        hevc_dir = os.path.join(self.comp_path, "hevc")
        if not os.path.exists(hevc_dir):
            os.makedirs(hevc_dir)

        if (crf_diff):
            self.logger.info(f"crf: {crf_diff} will be tested!")
            for crf in crf_diff:
                self.x265_encode(crf, isfull=False)
        else:
            self.logger.warning(
                f"crf: nothing to do! crf value {crf_list} may have be tested already.")
        return

    def x265_encode(self, crf, isfull):
        cfg = self.task_dict.get('x265')

        # if (pools == 0):
        #     numa_str = f"--pools \"+,-\""
        # elif (pools == 1):
        #     numa_str = f"--pools \"-,+\""
        # else:
        #     numa_str = f"--pools \"*\""
        default_cfg = {
            'vpy': os.path.join(self.vs_path, "sample.vpy"),
            'name': os.path.join(self.comp_path, f"hevc/crf-{crf}{'-full' if isfull else ''}"),
            'crf': crf,
            'qcomp': 0.6,
            'preset': "veryslow",
            'bframes': 16,
            'b-adapt': 2,
            'ctu': 32,
            'rd': 4,
            'subme': 7,
            'ref': 6,
            'rc-lookahead': 80,
            'vbv-bufsize': 160000,
            'vbv-maxrate': 160000,
            'colorprim': "bt709",
            'transfer': "bt709",
            'colormatrix': "bt709",
            'deblock': "-3:-3",
            'ipratio': 1.3,
            'pbratio': 1.2,
            'aq-mode': 2,
            'aq-strength': 1.0,
            'psy-rd': 1.0,
            'psy-rdoq': 1.0,
        }
        if cfg != 'null':
            default_cfg.update(cfg)

        cmd = 'vspipe \"{vpy}\" --y4m - | x265 -D 10 --preset {preset} --crf {crf} --high-tier --ctu {ctu} --rd {rd} ' \
            '--subme {subme} --ref {ref} --pmode --no-rect --no-amp --rskip 0 --tu-intra-depth 4 --tu-inter-depth 4 --range limited ' \
            '--no-open-gop --no-sao --rc-lookahead {rc-lookahead} --bframes {bframes} --b-adapt {b-adapt} --vbv-bufsize {vbv-bufsize} --vbv-maxrate {vbv-maxrate} ' \
            '--colorprim {colorprim} --transfer {transfer} --colormatrix {colormatrix} --deblock {deblock} --ipratio {ipratio} --pbratio {pbratio} --qcomp {qcomp} ' \
            '--aq-mode {aq-mode} --aq-strength {aq-strength} --psy-rd {psy-rd} --psy-rdoq {psy-rdoq} --output \"{name}.hevc\" --y4m - 2>&1 | tee \"{name}.log\"'.format(
                **default_cfg)
        print(cmd)
        try:
            subprocess.run(cmd, shell=True)
        except subprocess.CalledProcessError as e:
            raise FilmTaskStopException(f"fail to encode, {e}")

    def check_cache(self):
        ret = False
        douban_path = os.path.join(self.cache_path, 'douban.json')
        if os.path.isfile(douban_path):
            ret = True
            with open(douban_path, 'r') as fd:
                self.jdouban = json.load(fd)
        imdb_path = os.path.join(self.cache_path, 'imdb.json')
        if os.path.isfile(imdb_path):
            ret = True
            with open(imdb_path, 'r') as fd:
                self.jimdb = json.load(fd)
        bdinfo_path = os.path.join(self.cache_path, 'bdinfo.yaml')
        if os.path.isfile(bdinfo_path):
            ret = True
            with open(bdinfo_path, 'r') as fd:
                txt = fd.read()
                self.bdinfo = yaml.load(txt.replace(
                    "]", " "), Loader=yamlordereddictloader.Loader)
        return ret

    def parse_bdinfo(self):
        pass

    def export_task(self):
        main_info = {}
        main_info['name'] = self.jdouban.get('foreign_title')
        main_info['playlist'] = self.playlist
        main_info['type'] = 'main'
        main_info['bd_path'] = self.bd_path
        main_info['stream'] = self.bdinfo['clips'][0]['streams']
        # stream = self.bdinfo['clips'][0]['streams']
        # main_info['video'] = stream['video']
        # main_info['audio'] = stream['audio']
        # main_info['subs'] = stream['subtitles']
        main_info['x265'] = None  # TODO
        self.task_dict = main_info

        info = []
        for sup in self.supplements:
            info += sup.export_task()

        with open(os.path.join(self.base_path, "task.yaml"), "wt") as fd:
            yaml.dump(main_info, fd, Dumper=yamlordereddictloader.Dumper)
        with open(os.path.join(self.base_path, "supplements.yaml"), "wt") as fd:
            yaml.dump_all(info, fd, explicit_start=True,
                          Dumper=yamlordereddictloader.Dumper)

    def search_info_from_douban_and_ptgen(self):
        """
        1. search on douban to get douban_id
        2. search douban_url / imdb_url on PT-GEN
        3. get return and save
        """
        douban_search_title = self.film_info.get('name')

        # 通过豆瓣API获取到豆瓣链接
        self.logger.info('使用关键词 %s 在豆瓣搜索', douban_search_title)
        try:
            r = requests.get('https://movie.douban.com/j/subject_suggest',
                             params={'q': douban_search_title},
                             headers={'User-Agent': fake_ua})
            rj = r.json()
            ret: dict = rj[0]  # 基本上第一个就是我们需要的233333
        except Exception as e:
            raise FilmTaskStopException('豆瓣未返回正常结果，报错如下 %s' % (e,))

        self.logger.info('获得到豆瓣信息, 片名: %s , 豆瓣链接: %s', ret.get(
            'title'), ret.get('url'))

        # 通过Pt-GEN接口获取详细简介
        douban_url = f"https://movie.douban.com/subject/{ret.get('id')}/"
        self.logger.info('通过Pt-GEN 获取资源 %s 详细简介', douban_url)

        rdouban = requests.get(ptgen_api, params={'url': douban_url}, headers={
                               'User-Agent': fake_ua})
        rjdouban = rdouban.json()
        if rjdouban.get('success', False):
            rimdb = requests.get(ptgen_api, params={'url': rjdouban['imdb_link']}, headers={
                                 'User-Agent': fake_ua})
            rjimdb = rimdb.json()
            if not rjimdb.get('success', False):
                raise FilmTaskStopException(
                    'Pt-GEN-imdb 返回错误，错误原因 %s' % (rjimdb.get('error', '')))
        else:  # Pt-GEN接口返回错误
            raise FilmTaskStopException(
                'Pt-GEN 返回错误，错误原因 %s' % (rjdouban.get('error', '')))

        self.jdouban = rjdouban
        self.jimdb = rjimdb

    def mkdir_of_task(self):
        # self.logger.info('mkdir of task')
        if os.path.exists(self.base_path):
            # self.logger.fatal('task_dir already exists, please check!')
            sys.exit()
        else:
            os.makedirs(self.base_path)
            os.makedirs(self.cache_path)
            os.makedirs(self.vs_path)
            os.makedirs(self.comp_path)

    def write_cache(self):
        with open(os.path.join(self.cache_path, "ptgen.txt"), "wt") as fd:
            fd.write(self.jdouban["format"])
        with open(os.path.join(self.cache_path, "douban.json"), "wt") as fd:
            fd.write(json.dumps(self.jdouban, indent=2))
        with open(os.path.join(self.cache_path, "imdb.json"), "wt") as fd:
            fd.write(json.dumps(self.jimdb, indent=2))
        with open(os.path.join(self.cache_path, "bdinfo.yaml"), "wt") as fd:
            yaml.dump(self.bdinfo, fd, Dumper=yamlordereddictloader.Dumper)
        # with open(os.path.join(self.comp_path, "chapter.xml"), "wt") as fd:
        #     fd.write()

    def gen_vs_scripts(self):
        cw = ch = 0
        if ("Aspect Ratio" in self.jimdb["details"].keys()):
            ratio_str = self.jimdb["details"]["Aspect Ratio"]
            m = re.match(r"(\d+\.*\d*).*(\d+\.*\d*)", ratio_str)
            ratio = float(m[1]) / float(m[2])
            w, h = 1920, 1080
            if (ratio == 1.33):  # special case
                w = 1440
            elif (ratio > 1.78):
                h = 1920 / ratio
            elif (ratio < 1.77):
                w = 1080 * ratio
            cw = round((1920 - w) / 4) * 2
            ch = round((1080 - h) / 4) * 2
        script = f"""
import vapoursynth as vs
import fvsfunc as fvf
import awsmfunc as awf
from vsutil import depth as Depth

core = vs.get_core()

mpls = core.mpls.Read(r'{self.bd_path}', {self.playlist})
clips = []
for i in range(mpls['count']):
    clips.append(core.lsmas.LWLibavSource(source=mpls['clip'][i], cache = True,
                    cachefile=f"{self.vs_path}/cache_{{i}}.lwi"))
clip = core.std.Splice(clips)

crop=core.std.Crop(clip, {cw}, {cw}, {ch}, {ch})

# bb = awf.FixRowBrightnessProtect2(bb, 1079, -4)
# bb = awf.FixColumnBrightnessProtect2(bb, 1, -8)
# fb = core.fb.FillBorders(crop,left=1,right=1,bottom=0,mode="fillmargins")
# fb = awf.bbmod(fb, left=2, right=2, u=True, v=True, blur=20, thresh=[5000, 1000])

last = crop
select = core.std.SelectEvery(last[2000:-2000],cycle=2500, offsets=range(100))
ret = core.std.AssumeFPS(
    select, fpsnum=clip.fps.numerator, fpsden=clip.fps.denominator)
ret.set_output()
"""
        ipynb = """
{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "%load_ext yuuno"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "%%vspreview
    "%execvpy sample.vpy"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.8.5"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 4
}
"""
        with open(os.path.join(self.vs_path, "sample.vpy"), 'w') as fd:
            fd.write(script)
        with open(os.path.join(self.vs_path, "check.ipynb"), 'w') as fd:
            fd.write(ipynb)

    def get_chapters(self):
        try:
            o = subprocess.check_output(f"bdinfo -cp {self.playlist} \"{self.bd_path}\"",  # > \"{opath}/chapters.xml\"",
                                        shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            print("failed to execute command ", e.output)
            raise

    def call_bdinfo_all(self):
        """
        call bdinfo to retrive bdinfo, write it to bdinfo.yaml
        """
        try:
            o = subprocess.check_output(f"bdinfo -i \"{self.bd_path}\"",
                                        shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            print("failed to execute command ", e.output)
            raise
        return yaml.load_all(o.replace("]", " "), Loader=yamlordereddictloader.Loader)

    def call_bdinfo(self):
        """
        call bdinfo to retrive bdinfo, write it to bdinfo.yaml
        """
        try:
            o = subprocess.check_output(f"bdinfo -i -p {self.playlist} \"{self.bd_path}\"",
                                        shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            print("failed to execute command ", e.output)
            raise
        self.bdinfo = yaml.load(o.replace("]", " "),
                                Loader=yamlordereddictloader.Loader)

    def add_supplement(self):
        self.logger.info('try to add supplements')
        try:
            with open(os.path.join(self.bd_path, "BDMV/JAR/00001/eng_us.txt"), 'r') as fd:
                bdtxt = fd.read()
        except:
            self.logger.warning('fail to open eng_us.txt')
            return
        try:
            o = subprocess.check_output(f"bdinfo -i \"{self.bd_path}\"",
                                        shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            self.logger.fatal('bdinfo fail')
            raise

        sup_playlists = []
        for m in re.finditer("playlist: (008\d+).mpls", o):
            if m[1]:
                # print(m[1])
                sup_playlists.append(int(m[1]))
        print(sup_playlists)
        bdtxt = bdtxt.replace('§', '')
        bdtxt = bdtxt.replace('ψ', '')
        bdtxt = bdtxt.replace('ŧ', '')
        bdtxt = bdtxt.replace('“', '"')
        bdtxt = bdtxt.replace('”', '"')
        bdtxt = bdtxt.replace('’', '\'')
        # print(bdtxt)
        chapter_txt = []
        sup_dict = {}
        chapter_flag = True
        supplement_flag = 0
        lines = []
        last_parent = None
        # i = 0
        for m in re.finditer("\d+=([0-9A-Za-z,;()\n'\"\\s.?!]+)\n", bdtxt):
            if m[1]:  # and m[1] != 'PLAY':
                lines.append(m[1].replace('\n', ' ').strip())
                # print(i, m[1].replace('\n', ' ').strip())
                # i += 1

        # print(lines)
        flag = False
        j = 0
        for i in range(len(lines)):
            # print(line)
            if chapter_flag:
                ch = re.search("\d+\. ([0-9A-Za-z,;\n'\"\\s.?!]+)", lines[i])
                if ch:
                    chapter_txt.append(ch[1])
                    continue
                else:
                    chapter_flag = False
                    if lines[i] == "SUPPLEMENTS":
                        supplement_flag = 1
            else:
                # print(lines[i])
                if lines[i] == "SUPPLEMENTS":
                    supplement_flag = 1
                    continue
                if supplement_flag == 1:
                    # print(lines[i])
                    if lines[i] not in sup_dict.keys():
                        # top level, add directly
                        # sup_dict[lines[i]] = ''
                        sup = Supplement(lines[i])
                        sup_dict[lines[i]] = sup
                        self.supplements.append(sup)
                    else:
                        supplement_flag = 2
                        # continue
                if supplement_flag == 2:
                    # print(lines[i])
                    if lines[i] in sup_dict.keys():
                        # val flag
                        flag = True
                        continue
                    if lines[i] not in sup_dict.keys():
                        if flag:
                            # repeat flag, add description
                            sup_dict[lines[i-1]].add_description(lines[i])
                            if lines[i+1] == 'PLAY':
                                sup_dict[lines[i-1]
                                         ].set_playlist(sup_playlists.pop(0))
                            else:
                                last_parent = sup_dict[lines[i-1]]
                            flag = False
                            # print(j, 'key:',lines[i-1], 'val:', lines[i])
                        else:
                            # branch level
                            if lines[i] == 'PLAY':
                                continue
                            # print(lines[i])
                            sup = Supplement(lines[i])
                            sup.set_playlist(sup_playlists.pop(0))
                            # print(last_parent.name)
                            last_parent.add_sub(sup)
                            sup_dict[lines[i]] = sup
        # print(chapter_txt)
        # for sup in self.supplements:
        #     print(sup)
        #     print('-----------')


def main():
    parser = argparse.ArgumentParser(prog='bdtask',
                                     description='bdtask is a script to generate and manage bluray encode tasks')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='increase output verbosity')
    subparsers = parser.add_subparsers(
        help='sub-commands', dest='subparser_name')
    # subparser [gen]
    parser_g = subparsers.add_parser(
        'gen', help='generate a bluray encode task')
    parser_g.add_argument('-p', '--playlist', type=int, default='1',
                          help='select bluray playlist')
    parser_g.add_argument('-n', '--name', type=str, default='bdtask_default',
                          help='name of task')
    parser_g.add_argument('-s', '--src', type=str, required=True,
                          help='bluray disc path')
    parser_g.add_argument('-d', '--taskdir', type=str, default='.',
                          help='output destination dir')
    parser_g.add_argument('--douban', type=str,  # required=True,
                          help='douban url')
    parser_g.add_argument('--source', type=str,  # required=True,
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
    parser_m = subparsers.add_parser(
        'mkv', help='call mkvmerge to mux all components')
    parser_m.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')
    parser_m.add_argument('--run', action='store_true',
                          help='run the mkvmerge script')
    parser_m.add_argument(
        '--sub', nargs='*', help='add additional subtitles: [lang] [track name] [file]')
    # subparser [nfo]
    parser_n = subparsers.add_parser('nfo', help='generate nfo from mkv')
    parser_n.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')

    args = parser.parse_args()
    params = vars(args)
    print(params)

    verbose = args.verbose
    taskdir = args.taskdir

    logging.basicConfig(format='%(asctime)-15s %(name)-3s %(levelname)s %(message)s',
                        level=logging.INFO)
    if (args.subparser_name == "gen"):
        bdtask = FilmTask(params)
        bdtask.getinfo()

    elif (args.subparser_name == "status"):
        os.chdir(taskdir)
        status_main(taskdir)
    elif (args.subparser_name == "crf"):
        bdtask = FilmTask(params)
        bdtask.run_crf()
        crf_list = args.val
        pools = args.pools
        is_show = args.show
        is_force = args.force
        is_pick = args.pick
        is_full = args.full
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
