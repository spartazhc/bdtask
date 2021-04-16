#!/usr/bin/python3

import argparse
import sys
import os
import subprocess
import logging
import yaml
import json
import re
import requests
import langcodes
import time
from scripts.nfogen import generate_nfo
from titlecase import titlecase
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import Request, urlopen

template_dir = "/home/spartazhc/source/bdtask/templates/"
cfg = {}
verbose = False

fake_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
'(KHTML, like Gecko) Chrome/80.0.3987.106 Safari/537.36'

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

    def set_mpls(self, mpls):
        self.playlist = int(mpls.get('playlist').split('.')[0])
        self.duration = mpls.get('duration')
        if (mpls['clips'][0]['streams']['audio']):
            self.audio = {'codec': mpls['clips'][0]['streams']['audio'][0]['codec'],
                      'channels': mpls['clips'][0]['streams']['audio'][0]['channels']}
        else:
            self.audio = {}

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
            sup['duration'] = self.duration
            sup['type'] = 'supplement'
            sup['crf'] = 23 # TODO
            sup['need'] = True
            if self.audio:
                sup['audio'] = self.audio
            if self.desc:
                sup['desc'] = self.desc
            return [sup]

    def __str__(self):
        return f"{self.name}: {self.playlist},{len(self.sub_sup)} desc: {self.desc}\n "" {[str(sub) for sub in self.sub_sup] if self.sub_sup else ''}"


class FilmTask(TaskBase):
    def __init__(self, params):
        self.params = params
        self.bd_path = params.get('src')
        self.playlist = 1
        self.bdinfo = None
        self.film_info: dict = None
        self.task_dict: dict = {}
        self.supplements: list = []
        self.get_path()
        self.logger_init(params.get('subparser_name').upper())

    def get_path(self):
        if self.params.get('subparser_name') == 'gen':
            self.film_info = self.get_bluray_name(
                os.path.basename(self.bd_path))
            # base_path uses film name extract from bluray filename
            # it may different from publish_path
            self.base_path = os.path.join(
                os.path.abspath(self.params.get('taskdir')),
                self.film_info.get('name').replace(' ', '.'))
        else:
            self.base_path = os.path.abspath(self.params.get('taskdir'))
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
        fileh = logging.FileHandler(os.path.join(self.base_path, 'bdtask.log'), 'a')
        formater = logging.Formatter(
            '%(asctime)-15s %(name)-3s %(levelname)s %(message)s')
        fileh.setFormatter(formater)
        self.logger.addHandler(fileh)

    @staticmethod
    def get_bluray_name(vf):
        """
        get info from file name
        ret = {'name': name, 'year': year, 'reso': reso, 'cut': cut}
        """
        country_codes = ["BFI", "CEE", "CAN", "CHN", "ESP", "EUR", "FRA", "GBR",
                         "GER", "HKG", "IND", "ITA", "JPN", "KOR", "NOR", "NLD",
                         "POL", "RUS", "TWN", "USA"]
        cut_types = {'cc': 'Criterion Collection', 'criterion': 'Criterion Collection',
                     'director': 'Directors Cut',
                     'extended': 'Extended Cut', 'uncut': 'UNCUT',
                     'remastered': 'Remastered', 'repack': 'Repack',
                     'uncensored': 'Uncensored', 'unrated': 'Unrated'}

        vf_en = re.sub("[\u4E00-\u9FA5]+.*[\u4E00-\u9FA5]+.*?\\.",
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
            # sometimes there is no resolution in filename, maybe the uploader
            # missed it
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
        ret = {'name': name, 'year': year, 'resolution': reso, 'bluray_tag': cut}
        print(f'filename parsed:{name}, {year}, {reso}, {cut}')
        return ret

    def run_gen(self):
        if not self.check_cache():
            self.search_info_from_douban_and_ptgen()
            self.get_chapters()
            self.call_bdinfo()
            self.write_cache()
            self.gen_vs_scripts()
            self.extract_components()
            self.publish_info()
            self.bluray_enhance()

        self.export_task()
        # post process
        if self.params.get('vscache'):
            self.logger.info("call vspipe --info to generate cache.lwi")
            try:
                o = subprocess.check_output(f"vspipe -i {os.path.join(self.vs_path, 'sample.vpy')} -",
                                            shell=True).decode("UTF-8")
            except subprocess.CalledProcessError as e:
                print("failed to execute command ", e.output)
                raise

        # if self.params.get('autocrf'):
        #     self.autocrf()

    def run_crf(self):
        self.logger.info("run crf")
        hevc_dir = os.path.join(self.comp_path, "hevc")
        if self.params.get('show'):
            if (not os.path.exists(hevc_dir)):
                self.logger.warning("no crf log to show, return")
                return
            else:
                self.logger.info("show crf")
                try:
                    o = subprocess.check_output(f"grep encoded {hevc_dir}/*.log ",
                                                shell=True).decode("UTF-8")
                except subprocess.CalledProcessError as e:
                    print("failed to execute command ", e.output)
                    raise
                print(o)
                return
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
            crf_diff = [crf for crf in crf_list if str(crf) not in cfg_ori["crf"]]
            cfg_update["crf"].extend(crf_diff)
            if (self.params.get('force')):
                crf_diff = crf_list

        with open(task_path, "w+") as fd:
            yaml.dump(cfg_update, fd, sort_keys=False)
            if (self.params.get('pick')):
                return

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

    def run_extra(self):
        self.logger.info("run extra")
        self.check_cache()
        supplements = []
        try:
            with open(os.path.join(self.base_path, 'supplements.yaml'), 'r') as fd:
                for item in yaml.load_all(fd, Loader=yaml.BaseLoader):
                    supplements.append(item)
        except Exception as e:
            raise FilmTaskStopException(f"fail to read load, {e}")
        for sup in supplements:
            if sup.get('need') == 'true':
                self.launch_task(sup)

    def run_mkv(self):
        self.logger.info("run mkv")
        self.check_cache()
        publish_dir = os.path.join(self.base_path, self.task_dict.get('publish'))
        mkv = os.path.join(publish_dir,
                           '.'.join(self.task_dict.get('publish').split('.')[1:]) + '.mkv')
        hevc = os.path.join(self.comp_path,
                        f"hevc/crf-{self.task_dict.get('crf_pick')}-full.hevc")

        cmd = f"mkvmerge -o \"{mkv}\" --chapters {self.comp_path}/chapter.xml -d 0 {hevc} "
        cmd += f"--attachment-name cover --attach-file \"{publish_dir}/cover.jpg\" "
        for aud in self.task_dict.get('auds'):
            aud_lang = aud.split('.')[0][:-1]
            cmd += f"-a 0 --language 0:{aud_lang} {self.comp_path}/{aud} "
        for sub in self.task_dict.get('subs'):
            sub_lang = sub.split('.')[0][:-1]
            cmd += f"-s 0 --language 0:{sub_lang} {self.comp_path}/{sub} "
        esubs = self.params.get('subs')
        while esubs and len(esubs) > 0:
            cmd += f"-s 0 --language 0:\"{esubs.pop(0)}\" --track-name 0:\"{esubs.pop(0)}\" \"{subs.pop(0)}\" "
        # TODO: tee to log
        if (self.params.get('check')):
            print(cmd)
        else:
            try:
                o = subprocess.check_output(cmd, shell=True).decode("UTF-8")
            except subprocess.CalledProcessError as e:
                print("failed to execute command ", e.output)
                raise
            print(o)

    def run_nfo(self):
        self.logger.info("generate nfo")
        self.check_cache()
        publish_dir = os.path.join(self.base_path, self.task_dict.get('publish'))
        mkv = os.path.join(publish_dir,
                           '.'.join(self.task_dict.get('publish').split('.')[1:]) + '.mkv')
        try:
            o = subprocess.check_output(f"mediainfo --Output=JSON \"{mkv}\"",
                                            shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            print("failed to execute command ", e.output)
            raise
        mkvinfo = json.loads(o)
        media = mkvinfo['media']
        general = media['track'][0]
        video = media['track'][1]

        s_aud = ""
        s_sub = ""
        for _, trak in enumerate(media['track'], start=2):
            if trak['@type'] == 'Audio':
                s_aud += f"AUDiO {'1' if not '@typeorder' in trak.keys() else trak['@typeorder']}.......: {langcodes.Language.get(trak['Language']).display_name():<7} " \
                    f"{trak['Format']:>4} @ {int(trak['BitRate']) / 1000 :.0f} Kbps\n"
            elif trak['@type'] == 'Text':
                if 'Title' in trak.keys():
                    if trak['Title'].startswith("Tra"):
                        sub_la = "cht"
                    elif trak['Title'].startswith("Simp"):
                        sub_la = "chs"
                    elif trak['Title'].startswith("chs&"):
                        sub_la = trak['Title']
                else:
                    sub_la = langcodes.Language.get(trak['Language']).to_tag()
                    if trak['Language'] == 'zh':
                        sub_la = "chs"
                if s_sub:
                    s_sub += '/'
                s_sub += f"{sub_la}({trak['Format']})"
        # print(json.dumps(douban, sort_keys=True, indent=2))
        crf_value = re.match(r".*crf=(\d+\.\d+).*", video['Encoded_Library_Settings'])[1]
        out = \
f"""{media['@ref'].split('/')[-1]}

NAME..........: {self.jimdb['name']}
GENRE.........: {self.jimdb['genre'] if isinstance(self.jimdb['genre'], str) else " | ".join(self.jimdb['genre'])}
RATiNG........: {self.jimdb['imdb_rating']}
iMDB URL......: {self.jimdb['imdb_link']}
DOUBAN URL....: {self.jdouban['douban_link']}
RELEASE DATE..: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
ENCODE BY.....: spartazhc @ FRDS
RUNTiME.......: {time.strftime('%H:%M:%S', time.gmtime(int(float(general['Duration']))))}
FiLE SiZE.....: {int(general['FileSize']) / 2**30 :.2f} GiB

ViDEO CODEC...: x265-3.4 @ {int(video['BitRate']) / 1000 :.0f} Kbps @crf={crf_value}
RESOLUTiON....: {video['Sampled_Width']}x{video['Sampled_Height']}
ASPECT RATiO..: {float(video['DisplayAspectRatio']):.2f}:1
FRAME RATE....: {video['FrameRate']} fps
SOURCE........: {os.path.basename(self.bd_path)}
SUBTiTLES.....: {s_sub}
{s_aud}
    -= FRDS MNHD TEAM =-
"""
        print(out)
        with open(mkv.replace('mkv', 'nfo'), "wt") as fd:
            fd.write(out)

    def launch_task(self, sup):
        # TODO: 1. crf 2. crop
        audio_rate = '32k' if sup.get('audio').get('channels') == 'Mono' else '64k'
        if 'crop' in sup.keys():
            width = int(sup.get('crop'))
            crop = f" -vf crop={width}:1080:{(1920-width)//2}:0 "
        else:
            crop = ""
        cmd = f"ffmpeg -hide_banner -playlist {sup.get('playlist')} -i \"bluray:{self.bd_path}\" " \
            f"{crop} -c:v libx265 -crf {sup.get('crf')} -c:a libopus -vbr on -b:a {audio_rate} " \
            f"\"/tmp/bdtask/{sup.get('name')}.mkv\" 2> \"/tmp/bdtask/{sup.get('name')}.log\""

        post_data = {'cmd': cmd,
                     'name': sup.get('name'),
                     'ip': '172.16.7.245',
                     'dest': os.path.join(self.base_path, self.task_dict.get('publish'), "extras/")}
        if self.params.get('check'):
            print(post_data)
        else:
            self.post(f"http://{self.params.get('server')}/add",
                       post_data)

    @staticmethod
    def post(url, pf):
        request = Request(url, urlencode(pf).encode())
        return urlopen(request).read().decode()

    def x265_encode(self, crf, isfull):
        cfg = self.task_dict.get('x265')
        try:
            o = subprocess.check_output(f"vspipe -i {os.path.join(self.vs_path, 'sample.py')} -",
                                        shell=True).decode("UTF-8")
            m = re.search(r"Frames:\s+(\d+)", o)
            frames = m[1] if m else 0
            print(f"frames={frames}")
        except subprocess.CalledProcessError as e:
            print("failed to execute command ", e.output)
            raise
        # if (pools == 0):
        #     numa_str = f"--pools \"+,-\""
        # elif (pools == 1):
        #     numa_str = f"--pools \"-,+\""
        # else:
        #     numa_str = f"--pools \"*\""
        default_cfg = {
            'vpy': os.path.join(self.vs_path, "sample.py"),
            'name': os.path.join(self.comp_path, f"hevc/crf-{crf}{'-full' if isfull else ''}"),
            'crf': crf,
            'frames': m[1] if m else 0,
            'qcomp': 0.6,
            'preset': "veryslow",
            'bframes': 8,
            'b-adapt': 2,
            'ctu': 32,
            '': 4,
            'subme': 7,
            'ref': 6,
            'rc-lookahead': 80,
            'vbv-bufsize': 160000,
            'vbv-maxrate': 160000,
            'colorprim': "bt709",
            'transfer': "bt709",
            'colormatrix': "bt709",
            'deblockrd': "-3:-3",
            'ipratio': 1.3,
            'pbratio': 1.2,
            'aq-mode': 2,
            'aq-strength': 1.0,
            'psy-rd': 1.0,
            'psy-rdoq': 1.0,
        }
        if cfg != 'null':
            default_cfg.update(cfg)

        cmd = 'vspipe \"{vpy}\" --y4m - | x265 -D 10 --frames {frames} --preset {preset} --crf {crf} --high-tier --ctu {ctu} --rd {rd} ' \
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

    def extract_components(self):
        cmd = f"ffmpeg -hide_banner -playlist {self.playlist} -i \"bluray:{self.bd_path}\" "
        # TODO: deal with condition when there are multiple clips
        if (len(self.bdinfo['clips']) != 1):
            self.logger.error("bdinfo shows more than one clip, please update this function")
            return

        clip = self.bdinfo['clips'][0]
        auds = []
        subs = []
        # there should be only one video stream
        for i, aud in enumerate(clip['streams']['audio']):
            if aud['codec'] == "PCM":
                if aud['channels'] != 'Mono':
                    self.logger.warning("audio is not Mono, check!")
                aud_name = f"{aud['language']}{i}.flac"
                aud_path = os.path.join(self.comp_path, aud_name)
                auds.append(aud_name)
                cmd += f"-codec flac -compression_level 12 -map 0:i:{aud['pid']} \"{aud_path}\" "
            elif (aud['codec'] == "AC3"):
                aud_name = f"{aud['language']}{i}.ac3"
                aud_path = os.path.join(self.comp_path, aud_name)
                auds.append(aud_name)
                cmd += f"-codec copy -map 0:i:{aud['pid']} \"{aud_path}\" "
            else:
                self.logger.error(f"please support more audio codec {aud['codec']}")
        for i, sub in enumerate(clip['streams']['subtitles']):
            if (sub['codec'] != "HDMV/PGS"):
                self.logger.error(f"please support more subtitle codec {sub['codec']}")
                break
            sub_name = f"{sub['language']}{i}.sup"
            sub_path = os.path.join(self.comp_path, sub_name)
            subs.append(sub_name)
            cmd += f"-codec copy -map 0:i:{sub['pid']} \"{sub_path}\" "
        self.task_dict['auds'] = auds
        self.task_dict['subs'] = subs

        cmd += f" 2>&1 | tee {os.path.join(self.comp_path, 'extract.log')}"
        with open(os.path.join(self.cache_path, "extract.sh"), "wt") as fd:
            fd.write(cmd)
        if self.params.get('extract'):
            try:
                self.logger.info("call extract.sh to extract components")
                subprocess.run(cmd, shell=True)
            except subprocess.CalledProcessError as e:
                raise FilmTaskStopException(f"fail to extract, {e}")

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
                    "]", " "), Loader=yaml.BaseLoader)
        task_path = os.path.join(self.base_path, 'task.yaml')
        if os.path.isfile(task_path):
            with open(task_path, 'r') as fd:
                task = yaml.load(fd, Loader=yaml.FullLoader)
            self.load_task(task)
        if ret:
            self.logger.info("use cache")
        return ret

    def parse_bdinfo(self):
        pass

    def load_task(self, cache):
        self.bd_path = cache.get('bd_path')
        self.playlist = cache.get('playlist')
        self.film_info = cache.get('film_info')
        self.task_dict = cache

    def export_task(self):
        self.logger.info("export task")
        self.task_dict['name'] = self.jdouban.get('foreign_title')
        self.task_dict['playlist'] = self.playlist
        self.task_dict['type'] = 'main'
        self.task_dict['bd_path'] = self.bd_path
        self.task_dict['film_info'] = self.film_info
        self.task_dict['stream'] = self.bdinfo['clips'][0]['streams']
        # stream = self.bdinfo['clips'][0]['streams']
        self.task_dict['x265'] = None  # TODO
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
            self.task_dict['crop'] = [cw, cw, ch, ch]

        with open(os.path.join(self.base_path, "task.yaml"), "wt") as fd:
            yaml.dump(self.task_dict, fd, sort_keys=False)

        if self.supplements:
            info = []
            for sup in self.supplements:
                info += sup.export_task()
            with open(os.path.join(self.base_path, "supplements.yaml"), "wt") as fd:
                yaml.dump_all(info, fd, explicit_start=True, sort_keys=False)

    def publish_info(self):
        # https://scenerules.org/t.html?id=2020_X265.nfo
        # Feature.Title.<YEAR>.<TAGS>.[LANGUAGE].<RESOLUTION>.<FORMAT>.<x264|x265>-GROUP
        tmp = []
        tmp.append(self.jdouban.get('chinese_title'))
        tmp.append(re.sub(r"[^A-Za-z0-9_-]", '.', self.jdouban.get('foreign_title')))
        tmp.append(self.jimdb.get('year'))
        if (self.film_info.get('bluray_tag')):
            tmp.append(self.film_info.get('bluray_tag'))
        tmp.append(self.film_info.get('resolution'))
        tmp.append('Bluray')
        tmp.append('x265.10bit')
        tmp.append(self.task_dict['auds'][0].split('.')[-1].upper())
        tmp.append('MNHD-FRDS')
        publish_name = '.'.join(tmp)
        self.task_dict['publish'] = publish_name
        publish_path = os.path.join(self.base_path, publish_name)
        if not os.path.exists(publish_path):
            os.makedirs(publish_path)
        self.cover_download_wget(self.jdouban.get('poster'), publish_path)

    def cover_download_wget(self, url, opath):
        self.logger.info("download cover")
        try:
            subprocess.call(
                f"wget -O \"{os.path.join(opath, 'cover.jpg')}\" {url}", shell=True)
        except subprocess.CalledProcessError as e:
            self.logger.error("failed to download cover: ", e.output)

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
            print('task_dir already exists, please check!')
            # sys.exit()
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
            yaml.dump(self.bdinfo, fd,sort_keys=False)

    def gen_vs_scripts(self):
        self.logger.info('generate vapoursynth scripts')
        script = f"""
import vapoursynth as vs
import fvsfunc as fvf
import awsmfunc as awf
import yaml
from vsutil import depth as Depth

core = vs.get_core()
with open('../task.yaml', 'r') as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)

mpls = core.mpls.Read(cfg['bd_path'], cfg['playlist'])
clips = []
for i in range(mpls['count']):
    clips.append(core.lsmas.LWLibavSource(source=mpls['clip'][i], cache = True,
                    cachefile=f"{self.vs_path}/cache_{{i}}.lwi"))
src = core.std.Splice(clips)

ccrop = cfg['crop']
crop=core.std.Crop(src, ccrop[0], ccrop[1], ccrop[2], ccrop[3])

# bb = awf.FixRowBrightnessProtect2(bb, 1079, -4)
# bb = awf.FixColumnBrightnessProtect2(bb, 1, -8)
# fb = core.fb.FillBorders(crop,left=1,right=1,bottom=0,mode="fillmargins")
# fb = awf.bbmod(fb, left=2, right=2, u=True, v=True, blur=20, thresh=[5000, 1000])

last = crop
if not cfg.get('crf_pick'):
    select = core.std.SelectEvery(last[2000:-2000],cycle=2500, offsets=range(100))
    ret = core.std.AssumeFPS(select, fpsnum=src.fps.numerator, fpsden=src.fps.denominator)
    ret.set_output()
else:
    last.set_output()
"""
        ipynb = r"""
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
    "%%vspreview\n",
    "import yaml\n",
    "\n",
    "with open('../task.yaml', 'r+') as fd:\n",
    "    cfg = yaml.load(fd, Loader=yaml.FullLoader)\n",
    "    print('last crop value: ', cfg['crop'])\n",
    "# with open('../task.yaml', 'wt') as fd:\n",
    "#     cfg['crop'] = [232, 232, 0, 0]\n",
    "#     print('current crop value: ', cfg['crop'])\n",
    "#     yaml.dump(cfg, fd, sort_keys=False)\n",
    "    \n",
    "%execvpy sample.py"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",t'
            sup['crf'] = 23 # TODO
            sup['need'] = True
            if self.audio:
                sup['audio'] = self.audio
            if self.desc:
                sup['desc'] = self.desc
            return [sup]

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
        with open(os.path.join(self.vs_path, "sample.py"), 'w') as fd:
            fd.write(script)
        with open(os.path.join(self.vs_path, "check.ipynb"), 'w') as fd:
            fd.write(ipynb)

    def get_chapters(self):
        try:
            o = subprocess.check_output(f"bdinfo -cp {self.playlist} \"{self.bd_path}\""
                                f" > \"{os.path.join(self.cache_path, 'chapter.xml')}\"",
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
        return yaml.load_all(o.replace("]", " "),
                             Loader=yaml.BaseLoader)

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
                                Loader=yaml.BaseLoader)

    def bluray_enhance(self):
        self.logger.info('try to add supplements')
        try:
            with open(os.path.join(self.bd_path, "BDMV/JAR/00001/eng_us.txt"), 'r') as fd:
                bdtxt = fd.read()
        except BaseException:
            self.logger.warning('fail to open eng_us.txt')
            return
        try:
            o = subprocess.check_output(f"bdinfo -i \"{self.bd_path}\"",
                                        shell=True).decode("UTF-8")
        except subprocess.CalledProcessError as e:
            self.logger.fatal('bdinfo fail')
            raise

        sub_mpls = []
        bdinfo_all = yaml.load_all(o.replace("]", " "), Loader=yaml.BaseLoader)
        for mpls in bdinfo_all:
            m = re.search("(008\d+).mpls", mpls.get('playlist'))
            if m:
                sub_mpls.append(mpls)
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
        for m in re.finditer("\d+=([0-9A-Za-z,:;()\n'\"\s.?!]+)\n", bdtxt):
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
                ch = re.search("\d+\. ([0-9A-Za-z,;\n'\"\s.?!]+)", lines[i])
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
                            sup_dict[lines[i - 1]].add_description(lines[i])
                            if lines[i + 1] == 'PLAY':
                                sup_dict[lines[i - 1]
                                         ].set_mpls(sub_mpls.pop(0))
                            else:
                                last_parent = sup_dict[lines[i - 1]]
                            flag = False
                            # print(j, 'key:',lines[i-1], 'val:', lines[i])
                        else:
                            # branch level
                            if lines[i] == 'PLAY':
                                continue
                            # print(lines[i])
                            sup = Supplement(lines[i])
                            sup.set_mpls(sub_mpls.pop(0))
                            # print(last_parent.name)
                            last_parent.add_sub(sup)
                            sup_dict[lines[i]] = sup
        # print(chapter_txt)
        # for sup in self.supplements:
        #     print(sup)
        #     print('-----------')
        self.enhance_chapter(chapter_txt)

    def enhance_chapter(self, chapter_txt):
        tree = ET.parse(os.path.join(self.cache_path, 'chapter.xml'))
        root = tree.getroot()
        EditionEntry = root[0]
        for chap in EditionEntry.iterfind('ChapterAtom'):
            chap[-1].tail = "\n\t\t\t"
            lang = ET.Element('ChapterDisplay')
            lang.tail = "\n\t\t"
            lang.text = "\n\t\t\t\t"
            sub = ET.SubElement(lang, 'ChapterString')
            sub.tail = "\n\t\t\t\t"
            sub.text = chapter_txt.pop(0)
            sub = ET.SubElement(lang, 'ChapterLanguage')
            sub.tail = "\n\t\t\t"
            sub.text = "eng"
            chap.append(lang)
        tree.write(os.path.join(self.comp_path, 'chapter.xml'), encoding='utf-8', xml_declaration=True)

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
    parser_g.add_argument('--vscache', action='store_true', default=False,
                          help='call vspipe -i after GEN')
    parser_g.add_argument('--extract', action='store_true', default=False,
                          help='execute extract.sh after GEN')
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
    # subparser [extra]
    parser_e = subparsers.add_parser('extra', help='configure and launch supplements')
    parser_e.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')
    parser_e.add_argument('--server', type=str, help='server IP post to')
    parser_e.add_argument('--check', action='store_true', default=False,
                          help='check command but not launch')
    # subparser [mkv]
    parser_m = subparsers.add_parser(
        'mkv', help='call mkvmerge to mux all components')
    parser_m.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')
    parser_m.add_argument('--check', action='store_true', default=False,
                          help='check command but not launch')
    parser_m.add_argument(
        '--sub', nargs='*', help='add additional subtitles: [lang] [track name] [file]')
    # subparser [nfo]
    parser_n = subparsers.add_parser('nfo', help='generate nfo from mkv')
    parser_n.add_argument('-d', '--taskdir', type=str, default='.', required=True,
                          help='task dir')

    args = parser.parse_args()
    params = vars(args)

    logging.basicConfig(format='%(asctime)-15s %(name)-3s %(levelname)s %(message)s',
                        level=logging.INFO)

    bdtask = FilmTask(params)
    if (args.subparser_name == "gen"):
        bdtask.run_gen()
    elif (args.subparser_name == "crf"):
        bdtask.run_crf()
    elif (args.subparser_name == "extra"):
        bdtask.run_extra()
    elif (args.subparser_name == "mkv"):
        bdtask.run_mkv()
    elif (args.subparser_name == "nfo"):
        bdtask.run_nfo()


if __name__ == "__main__":
    main()
