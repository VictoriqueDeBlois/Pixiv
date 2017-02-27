# encoding=utf-8
import datetime
import multiprocessing
import os
import queue
import random
import re
import sqlite3
import threading
import time
import zipfile
from functools import reduce
from shutil import rmtree

import requests
from PIL import Image
from bs4 import BeautifulSoup
from pixivpy3 import *


class TryError(requests.exceptions.RequestException):
    pass


class ProgressBar(object):
    def __init__(self, title,
                 total,
                 progress=0,
                 run_status=None,
                 fin_status=None,
                 unit_transfrom_func=None,
                 time_switch=False):
        self.info = "[%s] %s %s | %s %5.1f%% [%s]"
        self.title = title
        self.total = total
        self.progress = progress
        self.status = run_status or '正在下载'
        self.fin_status = fin_status or '下载完成'
        self.isdone = False
        if unit_transfrom_func is None:
            self.unit_transfrom = self.data_size
        else:
            self.unit_transfrom = unit_transfrom_func
        if time_switch:
            self.last_time = time.time()
        else:
            self.last_time = None
        self.total_data_str = self.unit_transfrom(total)
        print(self.__get_info(), end='')

    @staticmethod
    def data_size(data_content):
        if (data_content / 1024) > 1024:
            return '%.2f MB' % (data_content / 1024 / 1024)
        else:
            return '%.2f KB' % (data_content / 1024)

    def bar(self):
        if self.total == 0:
            rate = 1
        else:
            rate = self.progress / self.total
        bar = int(rate * 20)
        bar = ('|' * bar) + (' ' * (20 - bar))
        return rate * 100, bar

    def __get_info(self):
        # [名称]状态 已下载 单位 | 总数 单位 百分比 进度条
        data_str = self.unit_transfrom(self.progress)
        rate, bar = self.bar()
        if 100.0 - rate < 1e-10:
            self.status = self.fin_status
        _info = self.info % (self.title, self.status, data_str, self.total_data_str, rate, bar)
        return _info

    def refresh(self, progress, status=None):
        if self.isdone:
            return
        self.progress += progress
        remain_str = ''
        if self.last_time:
            t = time.time()
            if progress == 0:
                remain_str = ' 剩余时间:'
            else:
                remain = ((self.total - self.progress) / progress) * (t - self.last_time)
                # remain < 31536000
                struct_time = time.gmtime(remain)
                if struct_time[7] > 1:
                    remain_str = ' 剩余时间: %d 天 %d 小时' % (struct_time[7] - 1, struct_time[3])
                elif struct_time[3] > 0:
                    remain_str = ' 剩余时间: %d 小时 %d 分钟' % (struct_time[3], struct_time[4])
                elif struct_time[4] > 0:
                    remain_str = ' 剩余时间: %d 分 %d 秒' % (struct_time[4], struct_time[5])
                else:
                    remain_str = ' 剩余时间: %d 秒' % struct_time[5]
            self.last_time = t
        if status is None:
            status = self.status
        end_str = ''
        if self.progress >= self.total:
            end_str = '\n'
            self.isdone = True
        elif status != self.status and status != self.fin_status:
            end_str = '\n'
            self.status = status
            self.isdone = True
        print('\r' + self.__get_info() + remain_str, end=end_str)


class Spider(object):
    heads = [{"Accept-Language": "zh-CN,zh;q=0.8",
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36 Edge/12.10240'},
             {"Accept-Language": "zh-CN,zh;q=0.8",
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:46.0) Gecko/20100101 Firefox/46.0'},
             {"Accept-Language": "zh-CN,zh;q=0.8",
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko'},
             {"Accept-Language": "zh-CN,zh;q=0.8",
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36 OPR/37.0.2178.31'},
             {"Accept-Language": "zh-CN,zh;q=0.8",
              'User-Agent': 'Opera/9.80 (Windows NT 6.1) Presto/2.12.388 Version/12.16'},
             {"Accept-Language": "zh-CN,zh;q=0.8",
              'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.87 Safari/537.36'}]

    def get_html_tree(self, input_url, header=None):
        try:
            if header is None:
                header = self.heads[random.randint(0, len(self.heads) - 1)]
            resp = requests.get(input_url, headers=header)
            soup = BeautifulSoup(resp.content, "lxml")
        except Exception as connect_error:
            print(connect_error)
            return
        else:
            return soup

    def save_html_page(self, page_url, path, header=None):
        try:
            if header is None:
                header = self.heads[random.randint(0, len(self.heads) - 1)]
            resp = requests.get(page_url, headers=header)
            with open(path, 'wb') as code:
                code.write(resp.content)
        except Exception as connect_error:
            print(connect_error)
            return


# path设置保存地址
class PixivSpider(Spider):
    def __init__(self, path='D:/PixivSpider/'):
        self.savePath = path
        self.processPage = ''
        self.imagesType = ['.png', '.jpg', '.gif']
        self.ranking_dict = {u'综合': '', u'插画': 'illust', u'动画': 'ugoira', u'漫画': 'manga',
                             u'今日': 'daily', u'本周': 'weekly', u'本月': 'monthly', u'新人': 'rookie',
                             u'原创': 'original', u'受男性欢迎': 'male', u'受女性欢迎': 'female',
                             u'男性': 'male', u'女性': 'female',
                             u'国际': 'oversea', u'北海道/东北': 'hokkaido_tohoku',
                             u'关东': 'kanto', u'中部': 'chubu', u'近畿': 'kinki',
                             u'中国/四国': 'chugoku_shikoku', u'九州/冲绳': 'kyusyu_okinawa'}
        self.content_dict = {u'插画': ([u'今日', u'本周', u'本月', u'新人']), u'动画': ([u'今日', u'本周']),
                             u'漫画': ([u'今日', u'本周', u'本月', u'新人'])}
        self.mode_modify = {u'男性': u'受男性欢迎', u'女性': u'受女性欢迎'}

    # 爬pixivison:
    # search_begin_index开始爬的页数
    # search_page爬几页
    # search_content爬的内容即类别 放在set中
    # total_page_count一共搜索类别中的子页面的数量 不设定则为None
    # stop_when_find_exists 遇到存在的文件夹停止
    def run_pixivison(self, search_begin_index=1, search_page=1, search_content=([u"插画"]), total_page_count=None,
                      stop_when_find_exists=True):
        index = search_begin_index
        while search_page != 0:
            if index == 1:
                pixivison_url = 'http://www.pixivision.net/zh/'
            else:
                pixivison_url = 'http://www.pixivision.net/zh/?p=%d' % index
            html_root = self.get_html_tree(pixivison_url)
            if index == 1:
                thumbnail_container = html_root.find('div', {'class': 'aec__thumbnail-container'})
                label = thumbnail_container.span.get_text().split()[0]
                if label in search_content:
                    print(label, 'find in content')
                    next_url = thumbnail_container.find('a', {'data-gtm-action': 'ClickImage'})['href']
                    url = 'http://www.pixivision.net%s' % next_url
                    if stop_when_find_exists is True:
                        self.run_pixivison_page(url, label, True)
                    else:
                        self.run_pixivison_page(url, label, False)
                else:
                    print(label, 'is not in content')
                if total_page_count is not None:
                    total_page_count -= 1
                    if total_page_count == 0:
                        return
            container = html_root.find('ul', {'class': 'main-column-container'}).find_all('li', {
                'class': 'article-card-container'})
            for i in container:
                content = i.find('a', {'data-gtm-action': 'ClickCategory'})
                label = content.span.get_text().split()[0]
                if label in search_content:
                    print(label, 'find in content')
                    next_url = i.find('a', {'data-gtm-action': 'ClickImage'})['href']
                    url = 'http://www.pixivision.net%s' % next_url
                    if stop_when_find_exists is True:
                        if self.run_pixivison_page(url, label, True) == 'exists':
                            return
                    else:
                        self.run_pixivison_page(url, label, False)
                else:
                    print(label, 'is not in content')
                if total_page_count is not None:
                    total_page_count -= 1
                    if total_page_count == 0:
                        return
            search_page -= 1
            index += 1

    # 爬pixivison某一个页面: page_url页面地址, labal爬的类别(目前只有插画类别支持), find_exists找到存在文件夹返回'exists'
    def run_pixivison_page(self, page_url, labal, find_exists):
        html_root = self.get_html_tree(page_url)
        title = html_root.find('meta', {'property': 'twitter:title'})['content']
        title = u''.join(re.split(r'[\\/:*?"<>|]+', title))
        print(title)
        path = self.savePath + title
        if os.path.exists(path):
            print('this dir exists')
            if find_exists is True:
                return 'exists'
        else:
            os.makedirs(path + '/')
        if labal == u'插画':
            eyecatch = html_root.find('div', {'class': '_article-illust-eyecatch'})
            self.run_pixiv_page(eyecatch.a['href'], path + '/')
            for i in html_root.find_all('div', {'class': 'am__work'}):
                self.run_pixiv_page(i.find('h3', {'class': 'am__work__title'}).a['href'], path + '/')
        else:
            print('')
            print('This funcation hasn\'t finished yet')
            print('')
            time.sleep(5)
            pass
            return

    # 爬p站某一个作品页面,支持单图,多图,动图: page_url页面地址, path存储地址(格式: ..:/../../../)
    def run_pixiv_page(self, page_url, path):
        self.processPage = page_url
        html_root = self.get_html_tree(page_url)
        # html_root = BeautifulSoup(open('d:/test/test1.html'), "html.parser")
        while html_root is None:
            time.sleep(1)
            html_root = self.get_html_tree(page_url)
        container = html_root.find('div', {'class': 'img-container'})
        content_title_user_name = html_root.find('meta', {'property': 'og:title'})['content']
        m = re.match(r'\u300c(.*?)\u300d/\u300c(.*?)\u300d.*', content_title_user_name)
        title = m.group(1)
        user_name = m.group(2)
        # 单图
        if (u'_work' in container.a['class']) is True and (u'multiple' in container.a['class']) is False:
            img = container.a.img
            # print img.name, img['src']
            # content = img['alt'].split('/')
            # title = content[0]
            # user_name = content[1]
            pic_id = page_url.split('id')[1]
            save_file_name = '%s by %s id%s' % (title, user_name, pic_id)
            save_file_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', save_file_name))
            for image_type in self.imagesType:
                if os.path.exists(path + save_file_name + image_type):
                    print('file exist')
                    return
            fake_url = img['src'].split('/')
            file_name = fake_url[13].split('_')
            for image_type in self.imagesType:
                file_name_type = file_name[0] + u'_' + file_name[1] + image_type
                real_url = "http://%s/img-original/img/%s/%s/%s/%s/%s/%s/%s" % (fake_url[2], fake_url[7],
                                                                                fake_url[8], fake_url[9],
                                                                                fake_url[10], fake_url[11],
                                                                                fake_url[12], file_name_type)
                return_msg = self.request_pic_url(page_url, real_url)
                while return_msg == 'error':
                    time.sleep(4)
                    return_msg = self.request_pic_url(page_url, real_url)
                if return_msg == 404:
                    continue
                elif isinstance(return_msg, int):
                    print(return_msg)
                    print(self.processPage)
                    time.sleep(8)
                else:
                    try:
                        with open(path + save_file_name + image_type, 'wb') as code:
                            code.write(return_msg.content)
                    except requests.exceptions.RequestException as errno:
                        print(errno)
                        os.remove(path + save_file_name + image_type)
                        time.sleep(5)
                        self.download_pic(page_url, real_url, path + save_file_name + image_type)
                        return
                    else:
                        print('download successful')
                        return
            print(self.processPage)
            print('Cannot find download url')
        # 多图
        elif (u'_work' in container.a['class']) and (u'multiple' in container.a['class']):
            # content = container.a.img['alt'].split('/')
            # title = content[0]
            # user_name = content[1]
            pic_id = page_url.split('id')[1]
            manga_page_url = 'http://www.pixiv.net/' + container.a['href']
            manga_page = self.get_html_tree(manga_page_url)
            # manga_page = BeautifulSoup(open('d:/test/test3.html'), "html.parser")
            while manga_page is None:
                time.sleep(1)
                manga_page = self.get_html_tree(manga_page_url)
            item_container = manga_page.find_all('img', {'data-filter': 'manga-image'})
            for i in item_container:
                data_index = i['data-index']
                save_file_name = '%s by %s id%s_p%s' % (title, user_name, pic_id, data_index)
                save_file_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', save_file_name))
                file_exist = False
                for image_type in self.imagesType:
                    if os.path.exists(path + save_file_name + image_type):
                        print('file exist')
                        file_exist = True
                        break
                if file_exist is True:
                    continue
                fake_url = i['data-src'].split('/')
                file_name = fake_url[-1].split('_')
                success_download = False
                for image_type in self.imagesType:
                    file_name_type = file_name[0] + u'_' + file_name[1] + image_type
                    real_url = "http://%s/img-original/img/%s/%s/%s/%s/%s/%s/%s" % (fake_url[2], fake_url[7],
                                                                                    fake_url[8], fake_url[9],
                                                                                    fake_url[10], fake_url[11],
                                                                                    fake_url[12], file_name_type)
                    manga_big_page_url = manga_page_url.replace('mode=manga', 'mode=manga_big') + '&page=' + data_index
                    return_msg = self.request_pic_url(manga_big_page_url, real_url)
                    while return_msg == 'error':
                        time.sleep(4)
                        return_msg = self.request_pic_url(manga_big_page_url, real_url)
                    if return_msg == 404:
                        continue
                    elif isinstance(return_msg, int):
                        print(return_msg)
                        print(self.processPage)
                        time.sleep(8)
                    else:
                        try:
                            with open(path + save_file_name + image_type, 'wb') as code:
                                code.write(return_msg.content)
                        except requests.exceptions.RequestException as errno:
                            print(errno)
                            os.remove(path + save_file_name + image_type)
                            time.sleep(5)
                            self.download_pic(manga_big_page_url, real_url, path + save_file_name + image_type)
                            success_download = True
                            break
                        else:
                            print('download successful')
                            success_download = True
                            break
                if success_download is False:
                    print(self.processPage)
                    print('Cannot find download url')
        # 动图
        elif (u'_work' in container.a['class']) is False:
            html = html_root.get_text()
            # content = html_root.find('meta', {'property': 'og:title'})['content']
            # m = re.match(ur'\u300c(.*?)\u300d/\u300c(.*?)\u300d.*', content)
            # title = m.group(1)
            # user_name = m.group(2)
            pic_id = page_url.split('id')[1]
            save_file_name = title + ' by ' + user_name + ' id' + pic_id + '.zip'
            save_file_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', save_file_name))
            if os.path.exists(path + save_file_name):
                print('file exist')
            else:
                m = re.search(r'"src":"(http:\\/\\/.+?.zip)"', html)
                zip_url = m.group(1)
                zip_url = ''.join(zip_url.replace('600x600', '1920x1080').split('\\'))
                self.download_pic(page_url, zip_url, path + save_file_name)
            # 自动转gif动图
            if os.path.exists(path + save_file_name[:-4] + '.gif'):
                print('file exist')
            else:
                zip_name = save_file_name
                zip_dir = path + save_file_name[:-4] + '/'
                if os.path.exists(zip_dir):
                    print('dir exists')
                else:
                    os.makedirs(zip_dir)
                if zipfile.is_zipfile(path + zip_name):
                    file_zip = zipfile.ZipFile(path + zip_name, 'r')
                    for single_file in file_zip.namelist():
                        if os.path.exists(zip_dir + single_file):
                            print('file exists')
                        else:
                            file_zip.extract(single_file, zip_dir)
                else:
                    print('This file is not zip file')
                    time.sleep(5)
                files = os.listdir(zip_dir)
                images = [Image.open(zip_dir + fn) for fn in files]
                m = re.search(r'"frames":\[(\{"file":.+\})\]', html)
                images_duration = re.findall(r'\{"file":".+?","delay":(\d+?)\}', m.group(1))
                images_duration = list(map(lambda x: (int(x) if int(x) >= 20 else 20), images_duration))
                with open(path + save_file_name[:-4] + '.gif', 'wb') as fp:
                    images[0].save(fp=fp, save_all=True, append_images=images[1:], loop=65535, duration=images_duration)
                rmtree(zip_dir)

    # 下载某一个图片: page_url图片存在的作品页面地址, pic_url图片真正地址, path保存文件完整地址   PS.不了解不需要直接调用
    def download_pic(self, page_url, pic_url, path):
        msg = self.request_pic_url(page_url, pic_url)
        while msg == 'error':
            time.sleep(3)
            msg = self.request_pic_url(page_url, pic_url)
        if isinstance(msg, int):
            print(msg)
            print(self.processPage)
            print('')
            time.sleep(8)
        else:
            try:
                with open(path, 'wb') as code:
                    code.write(msg.content)
            except requests.exceptions.RequestException as error:
                print(error)
                os.remove(path)
                time.sleep(5)
                self.download_pic(page_url, pic_url, path)
            else:
                print('download successful')

    # 请求服务器, 不直接调用
    def request_pic_url(self, page_url, pic_url):
        host = pic_url.split('/')[2]
        header = {"Accept": "image/webp,image/*,*/*;q=0.8",
                  "Accept - Encoding": "gzip, deflate, sdch",
                  "Accept - Language": "zh - CN, zh;q = 0.8",
                  "Cache-Control": "max-age=0",
                  "Connection": "keep-alive",
                  "Host": host,
                  "Referer": page_url,
                  "User-Agent": self.heads[random.randint(0, len(self.heads) - 1)]["User-Agent"]}
        try:
            response = requests.get(pic_url, headers=header, stream=True, timeout=50)
            if response.status_code == 200:
                print('connect successful')
                return response
            else:
                return response.status_code
        except requests.exceptions.RequestException as error:
            # print error.args[0][0], 'errno code = %d' % error.args[0][1][0]
            print(error)
            # errno code 10054
            # return error.args[0][1][0]
            return 'error'

    # 爬p站排行榜(非地区排行榜):
    # search_content爬的种类: 综合 插画 动图 漫画
    # search_range爬的范围: 今日 本周 本月 新人 原创 受男性欢迎 受女性欢迎 国际 北海道/东北 关东 中部 近畿
    # ranking_date哪一天的排行: 年月日
    # rank_range排名范围: (开始名次,结束名次)
    # search_R18是否搜索R-18(没有完成)
    def run_pixiv_ranking(self, search_content=u'综合', search_range=u'今日', ranking_date=u'', rank_range=(1, 50),
                          search_r18=False):
        base_url = 'http://www.pixiv.net/ranking.php'
        if search_r18 is True:
            print('Need login')
            return
        m = re.match(r'(\d{4})[-\\/\s.]*(\d{2})[-\\/\s.]*(\d{2})', ranking_date)
        input_time = ''
        if m is not None:
            input_time = '%s%s%s' % (m.group(1), m.group(2), m.group(3))
            local_time = time.strftime('%Y%m%d')
            if local_time <= input_time:
                input_time = ''
        content = self.ranking_dict[search_content]
        mode = self.ranking_dict[search_range]
        date = input_time
        if (search_content in self.content_dict) and (search_range in self.content_dict[search_content]) is False:
            search_content = u'综合'
        if search_content in self.mode_modify:
            search_content = self.mode_modify[search_content]
        if content == '' and date == '':
            search_url = '%s?mode=%s' % (base_url, mode)
        elif content == '' and date != '':
            search_url = '%s?mode=%s&date=%s' % (base_url, mode, date)
        elif content != '' and date == '':
            search_url = '%s?mode=%s&content=%s' % (base_url, mode, content)
        else:
            search_url = '%s?mode=%s&content=%s&date=%s' % (base_url, mode, content, date)
        html_tree = self.get_html_tree(search_url)
        while html_tree is None:
            time.sleep(2)
            html_tree = self.get_html_tree(search_url)
        date = html_tree.find('ul', {'class': 'sibling-items'}).li.next_sibling.get_text()
        date = date.replace('/', '-')
        if search_range in self.mode_modify:
            search_range = self.mode_modify[search_range]
        save_dir = '%s%s %s %s/' % (self.savePath, search_content, search_range, date)
        print(save_dir)
        if os.path.exists(save_dir):
            print('dir exisits')
        else:
            os.makedirs(save_dir)
        sections = html_tree.find_all('section', {'class': 'ranking-item'})
        if sections is None:
            print('Cannot find ranking')
            return
        for rank_item in sections:
            index = int(rank_item['id'])
            if rank_range[0] <= index <= rank_range[1]:
                self.run_pixiv_page(
                    'http://www.pixiv.net/member_illust.php?mode=medium&illust_id=%s' % rank_item['data-id'], save_dir)

    def run_pixiv_area_ranking(self):
        pass


class PixivSpiderLogin(object):
    # path设置保存地址 processes设置最大进程数
    def __init__(self, path='D:/PixivSpider/', num_processes=None, num_threading=10):
        self.heads = [{"Accept-Language": "zh-CN,zh;q=0.8",
                       'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36 Edge/12.10240'},
                      {"Accept-Language": "zh-CN,zh;q=0.8",
                       'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:46.0) Gecko/20100101 Firefox/46.0'},
                      {"Accept-Language": 'zh-CN,zh;q=0.8',
                       'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko'},
                      {"Accept-Language": "zh-CN,zh;q=0.8",
                       'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36 OPR/37.0.2178.31'},
                      {"Accept-Language": "zh-CN,zh;q=0.8",
                       'User-Agent': 'Opera/9.80 (Windows NT 6.1) Presto/2.12.388 Version/12.16'},
                      {"Accept-Language": "zh-CN,zh;q=0.8",
                       'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.87 Safari/537.36'}]
        self.savePath = path
        self.processPage = ''
        self.content_dict = {'all': dict(daily=10, weekly=10, monthly=10, rookie=6, original=6, male=10, female=10,
                                         daily_r18=2, weekly_r18=2, male_r18=6, female_r18=6, r18g=1, oversea=2,
                                         hokkaido_tohoku=1, kanto=1, chubu=1, kinki=1, chugoku_shikoku=1,
                                         kyusyu_okinawa=1),
                             'illust': dict(daily=10, weekly=10, monthly=6, rookie=6, daily_r18=2, weekly_r18=2,
                                            r18g=1),
                             'ugoira': dict(daily=2, weekly=2, daily_r18=1, weekly_r18=1),
                             'manga': dict(daily=10, weekly=2, monthly=2, rookie=2, daily_r18=2, weekly_r18=2, r18g=1)}
        self.cookies = {}
        self.pixiv_context_token = ''
        # 多进程的数量
        self.num_processes = num_processes
        # 多图下载时的最大线程数
        self.num_threading = num_threading

    # 登录pixiv 登录后保存cookies.txt 类也会保存cookies可以之后直接调用登录后的操作
    def login_pixiv(self, pixiv_id, password):
        header = {"Accept": "application/json, text/javascript, */*; q=0.01",
                  "Accept-Encoding": "gzip, deflate, br",
                  "Accept-Language": "zh-CN,zh;q=0.8",
                  "Host": "accounts.pixiv.net",
                  "Origin": "https://accounts.pixiv.net",
                  "Referer": "https://accounts.pixiv.net/login?lang=zh&source=pc&view_type=page&ref=wwwtop_accounts_index",
                  "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 Safari/537.36",
                  'Content-Type': "application/x-www-form-urlencoded; charset=UTF-8",
                  'Connection': "keep-alive"}
        login_url = "https://accounts.pixiv.net/api/login?lang=zh"
        resp, s = self.get_response(
            "https://accounts.pixiv.net/login?lang=zh&source=pc&view_type=page&ref=wwwtop_accounts_index")
        postkey = re.search(r'<input type="hidden".*?value="(.*?)">', resp.text).group(1)
        formdata = {"pixiv_id": pixiv_id,
                    "password": password,
                    "captcha": "",
                    "g_recaptcha_response": "",
                    "post_key": postkey,
                    "source": "pc"}
        resp, s = self.post_response(login_url, data=formdata, headers=header, session=s)
        json = resp.json()
        if json['error'] is True:
            print(json['message'])
            print("联系开发者")
            return
        else:
            if 'validation_errors' in json['body']:
                if 'password' in json['body']['validation_errors']:
                    print(json['body']['validation_errors']['password'])
                elif 'pixiv_id' in json['body']['validation_errors']:
                    print(json['body']['validation_errors']['pixiv_id'])
            elif 'success' in json['body']:
                print("登录成功")
        cookies = s.cookies
        fp = open("cookies.txt", 'w')
        fp.write('; '.join(['='.join(item) for item in cookies.items()]))
        fp.close()
        self.cookies = cookies
        resp, s = self.get_response("http://www.pixiv.net/", headers=self.heads[random.randint(0, len(self.heads) - 1)],
                                    session=s)
        m = re.search(r'pixiv\.context\.token\s*=\s*\"(.+?)\";', resp.text)
        self.pixiv_context_token = m.group(1)

    # 读取本地cookies 调用后才可以调用登录后的操作
    def load_cookies(self, filename="cookies.txt"):
        if os.path.exists(filename) is False:
            print("cookies不存在")
            return False
        f = open(filename, 'r')
        try:
            for line in f.read().split(';'):
                name, value = line.strip().split('=', 1)
                self.cookies[name] = value
        except Exception as error:
            print(error)
            print("cookies有误")
            f.close()
            return False
        f.close()
        html = self.get_html_tree("http://www.pixiv.net/")
        if html.find('div', {'class': 'signup-form'}) is not None:
            print("cookies失效 重新登录")
            return False
        m = re.search(r'pixiv\.context\.token\s*=\s*\"(.+?)\";', html.get_text())
        self.pixiv_context_token = m.group(1)
        return True

    # 获取网页的beautifulsoup
    def get_html_tree(self, url, header=None, params=None):
        if header is None:
            header = self.heads[random.randint(0, len(self.heads) - 1)]
        resp, s = self.get_response(url, params=params, headers=header, cookies=self.cookies, timeout=50)
        try:
            soup = BeautifulSoup(resp.content, "lxml")
            return soup
        except Exception as error:
            print(error)
            return

    # 保存网页 path 完整地址
    def save_html_page(self, url, path, header=None, params=None):
        connect = False
        while connect is False:
            try:
                if header is None:
                    header = self.heads[random.randint(0, len(self.heads) - 1)]
                s = requests.Session()
                req = requests.Request('GET', url=url, params=params, headers=header, cookies=self.cookies)
                prepped = s.prepare_request(req)
                resp = s.send(prepped, timeout=50)
                with open(path, 'wb') as code:
                    code.write(resp.content)
                connect = True
            except Exception as connect_error:
                print(connect_error)

    # 爬p站某一个作品页面, 支持单图, 多图, 动图: illust_id 图片id, path 存储地址(格式:..: /../../../ )
    # 修改后基于登录,不用猜测图片类型
    # 漫画会单独放在一个文件夹里
    def run_pixiv_page(self, illust_id, path):
        process_page = "http://www.pixiv.net/member_illust.php?mode=medium&illust_id=%s" % illust_id
        html_root = self.get_html_tree(process_page)
        works_display = html_root.find('div', {'class': 'works_display'})
        if works_display is None:
            print(illust_id, '作品不存在或不可见')
            return
        content_title_user_name = html_root.find('meta', {'property': 'og:title'})['content']
        m = re.match(r'\u300c(.*?)\u300d/\u300c(.*?)\u300d.*', content_title_user_name)
        title = m.group(1)
        user_name = m.group(2)
        # 单图
        if works_display.div['class'][-1] == 'ui-modal-trigger':
            # 得到原图地址
            img = html_root.find('img', {'class': 'original-image'})
            data_src = img['data-src']
            # 编辑保存文件名
            save_file_name = '%s by %s id=%s' % (title, user_name, illust_id)
            # 去除非法字段
            save_file_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', save_file_name))
            filename_type = re.split(r'\.', data_src)[-1]
            if os.path.exists(path + save_file_name + '.' + filename_type):
                print('file exist')
                return
            self.download_pic(process_page, data_src, path + save_file_name + '.' + filename_type)
        # 多图
        elif works_display.div['class'][-1] == '_layout-thumbnail':
            lock = threading.Lock()
            max_threading = self.num_threading

            def alloc(func, args_list):
                for args in args_list:
                    t = threading.Thread(target=func, args=args)
                    t.start()
                    yield

            def run_thread(func, url, args):
                item_page = func(url)
                _index = re.split(r'=', url)[-1]
                _img = item_page.find('img')
                src = _img['src']
                _filename_type = re.split(r'\.', src)[-1]
                if os.path.exists(path + save_file_name + _index + '.' + _filename_type):
                    print('file exist')
                    return
                lock.acquire()
                try:
                    args.append((url, src, path + save_file_name + _index + '.' + _filename_type))
                finally:
                    lock.release()

            a = html_root.find('div', {'class': 'works_display'}).a
            save_file_name = '%s by %s id=%s_p' % (title, user_name, illust_id)
            save_file_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', save_file_name))
            if 'manga' in a['class']:
                path = path + save_file_name[:-2] + '/'
                if os.path.exists(path):
                    print('this dir exists')
                else:
                    os.makedirs(path)
            manga_page_url = "http://www.pixiv.net/" + a['href']
            manga_page = self.get_html_tree(manga_page_url)
            download_args = []
            item_container = manga_page.find_all('div', {'class': 'item-container'})
            # 另一种漫画页面 e.g 54976833
            if not item_container:
                html = manga_page.get_text()
                pic_urls = re.findall(r'pixiv\.context\.originalImages\[\d+\]\s*=\s*\"(.+?)\";', html)
                pic_urls = map(lambda x: ''.join(re.split(r'\\', x)), pic_urls)
                for pic_url in pic_urls:
                    spilt = re.split(r'\.', pic_url)
                    filename_type = spilt[-1]
                    index = re.split(r'_p', spilt[-2])[-1]
                    if os.path.exists(path + save_file_name + index + '.' + filename_type):
                        print('file exist')
                        continue
                    download_args.append((manga_page_url, pic_url, path + save_file_name + index + '.' + filename_type))
            else:
                run_thread_args = map(lambda x: (self.get_html_tree,
                                                 "http://www.pixiv.net/" + x.a['href'], download_args), item_container)
                a = alloc(run_thread, run_thread_args)
                while True:
                    if threading.active_count() < max_threading + 1:
                        try:
                            next(a)
                        except StopIteration:
                            break
                runing_threads = threading.enumerate()
                list(map(lambda t: t.join(), runing_threads[1:]))
            # 多线程下载插画
            a = alloc(self.download_pic, download_args)
            while True:
                if threading.active_count() < max_threading + 1:
                    try:
                        next(a)
                    except StopIteration:
                        break
            runing_threads = threading.enumerate()
            list(map(lambda t: t.join(), runing_threads[1:]))
        # 动图
        elif works_display.div['class'][-1] == '_ugoku-illust-player-container':
            save_file_name = title + ' by ' + user_name + ' id=' + str(illust_id) + '.zip'
            save_file_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', save_file_name))
            html = html_root.get_text()
            m = re.search(r'pixiv.context.ugokuIllustFullscreenData\s*=\s*\{(.+?)\};', html)
            ugoku_illust_fullscreen_data = m.group(1)
            if os.path.exists(path + save_file_name):
                print('file exist')
            else:
                m = re.search(r'"src":"(http:\\/\\/.+?.zip)"', ugoku_illust_fullscreen_data)
                zip_url = m.group(1)
                zip_url = ''.join(zip_url.split('\\'))
                self.download_pic(process_page, zip_url, path + save_file_name)
            # 自动转gif动图
            if os.path.exists(path + save_file_name[:-4] + '.gif'):
                print('file exist')
            else:
                zip_name = save_file_name
                zip_dir = path + save_file_name[:-4] + '/'
                if os.path.exists(zip_dir):
                    print('dir exists')
                else:
                    os.makedirs(zip_dir)
                if zipfile.is_zipfile(path + zip_name):
                    file_zip = zipfile.ZipFile(path + zip_name, 'r')
                    for single_file in file_zip.namelist():
                        if os.path.exists(zip_dir + single_file):
                            print('file exists')
                        else:
                            file_zip.extract(single_file, zip_dir)
                else:
                    print('This file is not zip file')
                files = os.listdir(zip_dir)
                images = [Image.open(zip_dir + fn).convert('P', palette=Image.ADAPTIVE, dither=Image.FLOYDSTEINBERG) for
                          fn in files]
                m = re.search(r'"frames":\[(\{"file":.+\})\]', ugoku_illust_fullscreen_data)
                images_duration = re.findall(r'\{"file":".+?","delay":(\d+?)\}', m.group(1))
                # 使用PTL 关于GIFFile的save(), 由gif标准 duration >=20
                images_duration = list(map(lambda x: (int(x) if int(x) >= 20 else 20), images_duration))
                with open(path + save_file_name[:-4] + '.gif', 'wb') as fp:
                    images[0].save(fp=fp, save_all=True, append_images=images[1:], loop=65535, duration=images_duration)
                rmtree(zip_dir)

    # 爬p站用户:
    # user_id 用户id
    # method 搜索的方向: 个人资料 member; 作品 illust; 收藏 bookmark;
    # 其他参数:(php的参数)
    # member.php 个人资料
    #
    # member_illust.php 作品:
    # type=illust 插画; all 综合; manga 漫画; ugoira 动图
    # p=(int) 页数(从1开始)
    # tag=()标签
    #
    # bookmark.php 收藏:
    # order=desc 收藏顺序; date_d 投稿顺序(顺序对于爬虫似乎没有什么卵用)
    # rest=show 公开; hide 私人(只能自己用)
    # p=(int) 页数(从1开始)
    # tag=()标签
    # untagged=1 未分类(优先级高于tag)
    # type=illust_all 全部(无用舍弃)
    #
    # page:从第几页开始
    def run_pixiv_user(self, user_id, method="illust", search_type="", tag="", order="desc", rest="show",
                       untagged="", page='1'):
        if method == "illust":
            self.processPage = "http://www.pixiv.net/member_illust.php"
            params = {'id': user_id, 'type': search_type, 'tag': tag, 'p': page}
            current_method = u"作品"
        elif method == "bookmark":
            self.processPage = "http://www.pixiv.net/bookmark.php"
            params = {'id': user_id, 'rest': rest, 'order': order, 'tag': tag, 'untagged': untagged, 'p': page}
            current_method = u"收藏"
        elif method == "member":
            pass
            # FIXME 获取个人资料不知道有什么用就没有写了
            return
        else:
            print("no such method")
            return

        temp = [key for key in params if params[key] == '']
        list(map(lambda x: params.pop(x), temp))

        html_root = self.get_html_tree(self.processPage, params=params)
        div = html_root.find('div', {'class': 'error-unit'})
        if div is not None:
            print(div.h2.get_text())
            print(div.p.get_text())
            return
        # 获取图片id 没有结果返回
        image_items = html_root.find_all('li', {'class': 'image-item'})
        if not image_items:
            print("未找到任何相关结果")
            return
        # 获取用户昵称
        user_name = html_root.find('h1', {'class': 'user'}).get_text()
        user_name = u''.join(re.split(r'[\\/:*?"<>|\x00-\x1f]+', user_name))
        current_type = ""
        # 获取作品类型
        if method == 'illust':
            current = html_root.find('ul', {"class": "menu-items"}).find('a', {'class': 'current'})
            current_type = current.get_text() + ' '
        # 获取标签
        tag_badge = html_root.find('span', {'class': 'tag-badge'})
        if tag_badge is None:
            current_tag = ""
        else:
            current_tag = tag_badge.get_text()
        # 创建路径
        path = "%s%s id=%s/%s %s%s/" % (self.savePath, user_name, user_id, current_method, current_type, current_tag)
        print(path)
        if os.path.exists(path):
            print('this dir exists')
        else:
            os.makedirs(path)
        illust_ids = []
        for item in image_items:
            img_id = item.img['data-id']
            illust_ids.append(img_id)
        # 获取下一页
        next_url = html_root.find('span', {'class': 'next'})
        if next_url is None:
            return
        else:
            next_url = next_url.a
        # 若有下一页 继续
        while next_url is not None:
            self.processPage = "http://www.pixiv.net/member_illust.php%s" % next_url['href']
            html_root = self.get_html_tree(self.processPage)
            image_items = html_root.find_all('li', {'class': 'image-item'})
            for item in image_items:
                img_id = item.img['data-id']
                self.run_pixiv_page(img_id, path)
            next_url = html_root.find('span', {'class': 'next'}).a
        self.async_run_pixiv_page(illust_ids, path)

    # 下载某一个图片: page_url图片存在的作品页面地址, pic_url图片真正地址, path保存文件完整地址 (直接下载)
    def download_pic(self, page_url, pic_url, path):
        host = pic_url.split('/')[2]
        headers = {"Accept": "image/webp,image/*,*/*;q=0.8",
                   "Accept - Encoding": "gzip, deflate, sdch",
                   "Accept - Language": "zh - CN, zh;q = 0.8",
                   "Cache-Control": "max-age=0",
                   "Connection": "keep-alive",
                   "Host": host,
                   "Referer": page_url,
                   "User-Agent": self.heads[random.randint(0, len(self.heads) - 1)]["User-Agent"]}
        # GET 请求
        resp, s = self.get_response(pic_url, headers=headers, stream=True, timeout=50)
        if resp.status_code != 200:
            resp.close()
            raise TryError(resp.status_code)
        content_size = int(resp.headers.get('content-length'))
        progress = ProgressBar(path.split('/')[-1], total=content_size)
        # 下载保存
        try:
            with open(path, 'wb') as code:
                file = b''
                for data in resp.iter_content(chunk_size=1024 * 60):
                    file += data
                    progress.refresh(len(data))
                code.write(file)
        except requests.exceptions.RequestException:
            progress.refresh(0, status='下载中断')
            resp.close()
            os.remove(path)
            self.download_pic(page_url, pic_url, path)
        finally:
            if resp:
                resp.close()

    # 主要参数:(php参数)
    # content='all' 综合(缺省); 'illust' 插画; 'ugoira' 动画; 'manga' 漫画
    # mode='daily' 今日(缺省); 'weekly' 本周; 'monthly' 本月; 'rookie' 新人;
    #      'original' 原创; 'male' 受男性欢迎; 'female' 受女性欢迎;
    #      'daily_r18' 今日R18; 'weekly_r18' 本周R18;
    #      'male_r18' 受男性欢迎R18; 'female_r18' 受女性欢迎R18; 'r18g' R18G(本周)
    #      'oversea' 国际; 'hokkaido_tohoku' 北海道/东北;
    #      'kanto' 关东; 'chubu' 中部; 'kinki' 近畿;
    #      'chugoku_shikoku' 中国/四国; 'kyusyu_okinawa' 九州/冲绳
    #      (mode为数字1-33(目前)时可能是节日排行榜:万圣 圣诞 新年 七夕;
    #      为什么是可能呢,因为p站这个数字没有规律,有些是不存在的)
    # date=(year)(month)(day) e.g 20170120 日期 (缺省为昨日)
    #
    # search_range=(start, end) 爬的排名范围 支持负数性质 0代表最后一名
    # filter_func 一个函数参数 函数自己实现一个满足某种条件的插画判断,传入dict 即一个插画的信息 例子见下, 通过返回True 不通过返回False
    # self.content_dict里面标注了除all以外的content允许的mode 不符合则返回
    # e.g 一个插图json含有的信息
    # illust_id :  61210737 (插画id)
    # view_count :  28177
    # user_id :  1024922
    # attr : (illust_content_type 中True的键)
    # illust_page_count :  1 (插画页数)
    # tags :  [u'オリジナル', u'女の子', u'COMITIA119', u'ブレザー', u'金髪ロング', u'白ソックス', u'制服', u'美少女', u'しゃがみ', u'オリジナル5000users入り']
    # url :  http://i2.pixiv.net/c/240x480/img-master/img/2017/01/31/21/41/10/61210737_p0_master1200.jpg (缩略图地址)
    # total_score :  32682
    # title :  はなあらし
    # rank :  1 (排名)
    # height :  842
    # width :  595
    # illust_upload_timestamp :  1485866470 上传时间戳
    # illust_content_type :  {
    # u'homosexual': False, 同性恋
    # u'bl': False, BL
    # u'lo': False, 洛丽塔
    # u'antisocial': False, 反社会
    # u'grotesque': False, 怪诞(可能R18G)
    # u'drug': False, 吸烟(毒)(醉酒?)
    # u'religion': False, 宗教
    # u'violent': False, 暴力
    # u'yuri': False, 百合
    # u'furry': False, 兽迷
    # u'sexual': 0, 色情(0 1 2)级别
    # u'original': False, 原创
    # u'thoughts': False} (不懂)幻想? 想象?
    # profile_img :  http://i4.pixiv.net/user-profile/img/2016/07/26/07/56/19/11251275_505f1e7bdbeb8d08ee8ea7516792d4aa_50.jpg
    # yes_rank :  9 (上次排名)
    # date :  2017年01月31日 21:41 上传时间(和上传时间戳信息其实是重复了)
    # illust_type :  0  (0 插画, 1 漫画, 2 动画)
    # illust_book_style :  0 (1 高赞作品? 2 超高赞作品?)(还是很玄)
    # user_name :  フライ○ティアゆ08a
    def run_pixiv_ranking(self, content='all', mode='daily', date='', search_range=(1, 50), filter_func=None):
        base_url = 'http://www.pixiv.net/ranking.php'
        if content in self.content_dict:
            if mode not in self.content_dict[content]:
                print('错误的mode')
                return
        temp_range = [int(search_range[0]), int(search_range[1])]
        # date 的合法性检测 不合法则缺省
        # 理论上还是支持(year)-(month)-(day)
        # (year)/(month)/(day)
        # (year)\(month)\(day)
        # (year) (month) (day)
        m = re.match(r'(\d{4})[-\\/\s.]*(\d{2})[-\\/\s.]*(\d{2})', date)
        input_time = ''
        if m is not None:
            input_time = '%s%s%s' % (m.group(1), m.group(2), m.group(3))
            local_time = time.strftime('%Y%m%d')
            if local_time <= input_time:
                input_time = ''
        date = input_time
        # query string parameters
        params = {'content': content, 'mode': mode, 'date': date}
        temp = [key for key in params if params[key] == '']
        list(map(lambda x: params.pop(x), temp))
        # 请求页面 若返回4xx 报告错误
        headers = self.heads[random.randint(0, len(self.heads) - 1)]
        resp, s = self.get_response(base_url, params=params, headers=headers, cookies=self.cookies)
        if re.match(r'4\d\d', str(resp.status_code)):
            print("发生了错误")
            return
        # 获取当前页面信息
        html_root = BeautifulSoup(resp.content, "lxml")
        current_title = html_root.find('h1', {'class': 'column-title'}).a.get_text()
        current_date = html_root.find('ul', {'class': 'sibling-items'}).find('a', {'class': 'current'}).get_text()
        current_title = current_title.replace(u'排行榜', '')
        save_dir = '%s%s %s/' % (self.savePath, current_title, current_date)
        print(save_dir)
        if os.path.exists(save_dir):
            print('dir exisits')
        else:
            os.makedirs(save_dir)
        # 获取json
        tt = html_root.find('input', {'name': 'tt'})['value']
        params['p'] = 1
        params['format'] = 'json'
        params['tt'] = tt
        headers = self.heads[random.randint(0, len(self.heads) - 1)]
        resp, s = self.get_response(base_url, params=params, headers=headers, cookies=self.cookies, session=s)
        json = resp.json()
        if re.match(r'4\d\d', str(resp.status_code)):
            print(json['error'])
            return
        # 负数特性(不靠谱 p站排名总数往往不是和json上的一样的)
        rank_total = int(json['rank_total'])
        if temp_range[0] <= 0:
            temp_range[0] = search_range[0] + rank_total
        if temp_range[0] <= 0:
            print("范围出错")
            return
        if temp_range[1] <= 0:
            temp_range[1] = search_range[1] + rank_total
        if temp_range[1] <= 0:
            print("范围出错")
            return
        # 超范围修正
        if temp_range[1] > rank_total:
            print("超出范围 修正最大值:", rank_total)
            temp_range[1] = rank_total
        if temp_range[0] > temp_range[1]:
            print("范围出错")
            return
        print('range:', temp_range)
        # 一页50张图 模50的最小正完全剩余系 得到开始结束地址
        p_begin = ((temp_range[0] - 1) // 50) + 1
        i_begin = temp_range[0] % 50
        if i_begin == 0:
            i_begin = 50
        p_end = ((temp_range[1] - 1) // 50) + 1
        i_end = temp_range[1] % 50
        if i_end == 0:
            i_end = 50
        # 开始爬
        p = p_begin
        i = i_begin
        illust_ids = []
        while p <= p_end:
            params['p'] = p
            headers = self.heads[random.randint(0, len(self.heads) - 1)]
            resp, s = self.get_response(base_url, params=params, headers=headers, cookies=self.cookies, session=s)
            json = resp.json()
            if re.match(r'4\d\d', str(resp.status_code)):
                print(json['error'], "p站欺骗了我")
                return
            max_item = len(json['contents'])
            if p != p_end:
                while i <= 50 and i <= max_item:
                    item = json['contents'][i - 1]
                    if filter_func is None:
                        illust_ids.append(item['illust_id'])
                    else:
                        if filter_func(item):
                            illust_ids.append(item['illust_id'])
                    i += 1
            else:
                while i <= i_end and i <= max_item:
                    item = json['contents'][i - 1]
                    if filter_func is None:
                        illust_ids.append(item['illust_id'])
                    else:
                        if filter_func(item):
                            illust_ids.append(item['illust_id'])
                    i += 1
            i = 1
            p += 1
        self.async_run_pixiv_page(illust_ids, save_dir)

    # 参数
    # folder= 保存的文件夹名字, 文件夹在类默认路径下(名字Unicode编码)
    # num_recommendations=int() 申请的推荐数(返回多少是玄学)
    # sample_illusts=(illust_id) 根据该作品(们?)推荐
    # tags=list() 筛选出list中tag的插画(list为空表示不筛选)
    # match_mode=0, 1  0 tag字段完全匹配; 1 tag字段部分匹配
    # strict_fliter=  True tags中每个tag都满足才通过; False tags中任意一个tag满足就通过
    def run_pixiv_recommended(self, folder='推荐', num_recommendations=500, sample_illusts=None, tags=None, match_mode=0,
                              strict_fliter=False):
        self.processPage = 'http://www.pixiv.net/recommended.php'
        tt = self.pixiv_context_token
        recommender_url = 'http://www.pixiv.net/rpc/recommender.php'
        illust_list_url = 'http://www.pixiv.net/rpc/illust_list.php'
        # num_recommendations 返回插画数(玄学)
        if sample_illusts is None:
            sample_illusts = 'auto'
        elif isinstance(sample_illusts, str):
            sample_illusts = ''.join(sample_illusts.split())
        elif isinstance(sample_illusts, (list, tuple)):
            sample_illusts = reduce(lambda x, y: x + ',' + y, sample_illusts)
        params = {'type': 'illust', 'sample_illusts': sample_illusts, 'num_recommendations': num_recommendations,
                  'tt': tt}
        headers = self.heads[random.randint(0, len(self.heads) - 1)]
        headers['Referer'] = 'http://www.pixiv.net/recommended.php'
        headers['Host'] = 'www.pixiv.net'
        # 获取推荐json
        resp, s = self.get_response(recommender_url, params=params, headers=headers, cookies=self.cookies)
        if re.match(r'4\d\d', str(resp.status_code)):
            print("发生了错误")
            return
        recommender_json = resp.json()
        recommender_list = recommender_json['recommendations']
        print("获得插画:", len(recommender_list))
        if tags:
            print("筛选插画列表:")
        recommender_list = recommender_list[:700]
        remain_list = recommender_list[700:]
        illust_id_list = []
        while recommender_list:
            illust_ids = str(recommender_list)[1:-1]
            illust_ids = ''.join(re.split(r'\s', illust_ids))
            # 获取illust_list json
            # 似乎illust_ids有多少就返回多少(url 长度极限)  exclude_muted_illusts必须是数字
            # 信息
            # illust_id : 60795883
            # tags : [ピンク髪, 女の子, オリジナル, ツインテール]
            # url : http://i4.pixiv.net/c/150x150/img-master/img/2017/01/06/12/06/37/60795883_p0_master1200.jpg
            # illust_x_restrict : 0 (不知道什么用)
            # illust_user_id : 19068684
            # illust_title : ピンク髪
            # illust_restrict : 0 (不知道什么用)
            # illust_type : 0 (不知道什么用)
            # user_name : ぴもぴ@お仕事募集中
            params = {'illust_ids': illust_ids, 'exclude_muted_illusts': 1, 'tt': tt}
            resp, s = self.get_response(illust_list_url, params=params, headers=headers, cookies=self.cookies,
                                        session=s)
            json = resp.json()
            if not tags:
                for item in json:
                    print(item['illust_id'], item['illust_title'], str(item['tags']))
                    illust_id_list.append(item['illust_id'])
            else:
                if match_mode == 0:
                    if strict_fliter is False:
                        for item in json:
                            for i in tags:
                                if i in item['tags']:
                                    print(item['illust_id'], item['illust_title'], str(item['tags']))
                                    illust_id_list.append(item['illust_id'])
                    else:
                        for item in json:
                            content = True
                            for i in tags:
                                if i not in item['tags']:
                                    content = False
                                    break
                            if content is True:
                                print(item['illust_id'], item['illust_title'], str(item['tags']))
                                illust_id_list.append(item['illust_id'])
                elif match_mode == 1:
                    if strict_fliter is False:
                        for item in json:
                            for i in tags:
                                str_tags = str(item['tags'])
                                if str_tags.find(i) != -1:
                                    print(item['illust_id'], item['illust_title'], str(item['tags']))
                                    illust_id_list.append(item['illust_id'])
                    else:
                        for item in json:
                            content = True
                            for i in tags:
                                str_tags = str(item['tags'])
                                if str_tags.find(i) == -1:
                                    content = False
                                    break
                            if content is True:
                                print(item['illust_id'], item['illust_title'], str(item['tags']))
                                illust_id_list.append(item['illust_id'])
            recommender_list = remain_list[:700]
            remain_list = remain_list[700:]
        if tags:
            print("筛选插画:", len(illust_id_list))
        path = self.savePath + folder + '/'
        print(path)
        if os.path.exists(path):
            print('this dir exists')
        else:
            os.makedirs(path)
        self.async_run_pixiv_page(illust_id_list, path)

    @staticmethod
    def create_pixiv_ranking_database(db_path='Pixiv.db'):
        database = sqlite3.connect(db_path)
        try:
            database.execute('''create table pixiv_ranking(
                              illust_id int PRIMARY KEY not null,
                              view_count int,
                              user_id int,
                              attr text,
                              illust_page_count int,
                              tags text,
                              url text,
                              total_score int,
                              title text,
                              height int,
                              width int,
                              illust_upload_timestamp timestamp(10),
                              homosexual boolean,
                              bl boolean,
                              lo boolean,
                              antisocial boolean,
                              grotesque boolean,
                              drug boolean,
                              religion boolean,
                              violent boolean,
                              yuri boolean,
                              furry boolean,
                              sexual int,
                              original boolean,
                              thoughts boolean,
                              date text,
                              illust_type int,
                              illust_book_style int,
                              user_name text,
                              img PICTURE,
                              latest boolean
                              )''')
        except Exception as error:
            print(error)
        database.commit()
        database.close()

    @staticmethod
    def create_pixiv_papi_database(db_path='Pixiv.db'):
        conn = sqlite3.connect(db_path)
        try:
            # date text,
            # attr text,
            # new:
            # tools text,
            # scored_count int,
            # favorited_count int,
            # commented_count int,
            # age_limit text,
            # change:
            # illust_type int,
            # illust_book_style int,
            conn.execute('''create table pixiv_papi(
                            illust_id int PRIMARY KEY not null,
                            title text,
                            user_id int,
                            user_name text,
                            tags text,
                            tools text,
                            url text,
                            height int,
                            width int,
                            view_count int,
                            total_score int,
                            scored_count int,
                            favorited_count int,
                            commented_count int,
                            age_limit text,
                            illust_page_count int,
                            illust_upload_timestamp timestamp(10),
                            illust_type text,
                            illust_book_style text,
                            img PICTURE,
                            latest boolean
                            )''')
        except sqlite3.Error as error:
            print(error)
        conn.commit()
        conn.close()

    # save_img 是否将缩略图存入数据库 (单线程不推荐 慢死你)
    # db_path .db文件的地址 例如:'Pixiv.db'
    # 注意date严格按照20170206格式
    def run_pixiv_ranking_update_database(self, db_path, content='all', mode='daily', date='', save_img=False):
        database = sqlite3.connect(db_path)
        base_url = 'http://www.pixiv.net/ranking.php'
        # 请求页面
        params = {'content': content, 'mode': mode, 'date': date}
        temp = [key for key in params if params[key] == '']
        list(map(lambda x: params.pop(x), temp))
        params['p'] = 1
        params['format'] = 'json'
        params['tt'] = self.pixiv_context_token
        # 获取信息
        finish = False
        p = 1
        while finish is False:
            params['p'] = p
            headers = self.heads[random.randint(0, len(self.heads) - 1)]
            # 获取json
            resp, s = self.get_response(base_url, params=params, headers=headers, cookies=self.cookies)
            json = resp.json()
            if re.match(r'4\d\d', str(resp.status_code)):
                finish = True
                continue
            contents = json['contents']
            print('\r' + json['content'], json['mode'], json['date'], 'p =', p, end='')
            # 收集编辑信息 存入数据库
            for item in contents:
                illust_id = item['illust_id']
                try:
                    database.execute('INSERT INTO pixiv_ranking (illust_id) VALUES (%s)' % illust_id)
                except sqlite3.Error:
                    continue
                view_count = item['view_count']
                user_id = item['user_id']
                attr = item['attr']
                tags = item['tags']
                if tags:
                    tags = map(lambda x: '\"' + x + '\"', tags)
                    tags = reduce(lambda x, y: x + ' ' + y, tags)
                else:
                    tags = ''
                url = item['url']
                illust_page_count = item['illust_page_count']
                total_score = item['total_score']
                title = item['title']
                height = item['height']
                width = item['width']
                illust_upload_timestamp = item['illust_upload_timestamp']
                timearray = time.localtime(illust_upload_timestamp)
                illust_upload_timestamp = time.strftime("%Y-%m-%d %H:%M:%S", timearray)
                homosexual = int(item['illust_content_type']['homosexual'])
                bl = int(item['illust_content_type']['bl'])
                lo = int(item['illust_content_type']['lo'])
                antisocial = int(item['illust_content_type']['antisocial'])
                grotesque = int(item['illust_content_type']['grotesque'])
                drug = int(item['illust_content_type']['drug'])
                religion = int(item['illust_content_type']['religion'])
                violent = int(item['illust_content_type']['violent'])
                yuri = int(item['illust_content_type']['yuri'])
                furry = int(item['illust_content_type']['furry'])
                sexual = item['illust_content_type']['sexual']
                original = int(item['illust_content_type']['original'])
                thoughts = int(item['illust_content_type']['thoughts'])
                date = item['date']
                illust_type = item['illust_type']
                illust_book_style = item['illust_book_style']
                user_name = item['user_name']
                if save_img:
                    r, s = self.get_response(url, headers=self.heads[random.randint(0, len(self.heads) - 1)], session=s)
                    img = sqlite3.Binary(r.content)
                else:
                    img = ''
                info_list = [view_count, user_id, attr, illust_page_count, tags, url, total_score, title, height, width,
                             illust_upload_timestamp,
                             homosexual, bl, lo, antisocial, grotesque, drug,
                             religion, violent, yuri, furry, sexual, original, thoughts,
                             date, illust_type, illust_book_style, user_name, img, illust_id]
                command = '''UPDATE pixiv_ranking
                             set view_count = ?, user_id = ?, attr = ?, illust_page_count = ?, tags = ?, url = ?, total_score = ?, title = ?, height = ?, width = ?,
                             illust_upload_timestamp = ?,
                             homosexual = ?, bl = ?, lo = ?, antisocial = ?, grotesque = ?, drug = ?,
                             religion = ?, violent = ?, yuri = ?, furry = ?, sexual = ?, original = ?, thoughts = ?,
                             date = ?, illust_type = ?, illust_book_style = ?, user_name = ?, img = ?
                             WHERE illust_id = ?'''
                try:
                    database.execute(command, info_list)
                except Exception as error:
                    print(error)
                    print(illust_id)
            database.commit()
            p += 1
        database.close()
        print()

    # content: all illust ugoira manga 或者是这些参数的列表, 元组, 迭代器
    # mode:'daily' 今日(缺省); 'weekly' 本周; 'monthly' 本月; 'rookie' 新人;
    #      'original' 原创; 'male' 受男性欢迎; 'female' 受女性欢迎;
    #      'daily_r18' 今日R18; 'weekly_r18' 本周R18;
    #      'male_r18' 受男性欢迎R18; 'female_r18' 受女性欢迎R18; 'r18g' R18G(本周)
    #      'oversea' 国际; 'hokkaido_tohoku' 北海道/东北;
    #      'kanto' 关东; 'chubu' 中部; 'kinki' 近畿;
    #      'chugoku_shikoku' 中国/四国; 'kyusyu_okinawa' 九州/冲绳 或者是这些参数的列表, 元组, 迭代器
    # date: %Y%m%d 例如 20170206 的格式 或者是列表, 元组, 迭代器
    # save_img 是否将缩略图存入数据库
    # db_path .db文件的地址 例如:'Pixiv.db'
    def run_pixiv_ranking_update_database_threading(self, db_path, **kwargs):
        self.create_pixiv_ranking_database(db_path)
        # 处理统一传入参数 提高鲁棒性
        if 'content' in kwargs:
            content = kwargs['content']
        else:
            content = 'all'
        if 'mode' in kwargs:
            mode = kwargs['mode']
        else:
            mode = 'daily'
        if 'date' in kwargs:
            date = kwargs['date']
        else:
            date = ''
        if 'save_img' in kwargs:
            save_img = kwargs['save_img']
        else:
            save_img = False

        if isinstance(content, str):
            content = (content,)

        if isinstance(mode, str):
            mode = (mode,)

        if isinstance(date, str):
            date = (date,)

        content = set(content)
        if '' in content:
            content.remove('')
            content.add('all')

        mode = set(mode)
        if '' in mode:
            mode.remove('')
            mode.add('daily')

        # 有待商榷
        date = set(date)

        # 根据content_dict剔除不正确的组合 提高鲁棒性
        content_mode = []
        for item_content in content:
            if item_content in self.content_dict:
                for item_mode in mode:
                    if item_mode in self.content_dict[item_content]:
                        content_mode.append((item_content, item_mode))

        # GET请求基本信息
        base_url = 'http://www.pixiv.net/ranking.php'
        header = self.heads
        params = {'format': 'json', 'tt': self.pixiv_context_token}

        # 线程准备
        queue_for_contents = queue.Queue()
        queue_for_combine = queue.Queue()
        value_queue = queue.Queue()
        max_threading = self.num_threading + 2

        # get_combine_info_consumer 使用list
        content_mode_date_p = []

        def alloc(func, args_list):
            for args in args_list:
                t = threading.Thread(target=func, args=args)
                t.start()
                yield

        def get_json_args():
            for item_date in date:
                if item_date != '':
                    params['date'] = item_date
                for combine in content_mode:
                    params['content'] = combine[0]
                    params['mode'] = combine[1]
                    yield (params.copy(),)

        def get_json(_params):
            _headers = header[random.randint(0, len(header) - 1)]
            r, _s = self.get_response(base_url, params=_params, headers=_headers, cookies=self.cookies)
            if re.match(r'4\d\d', str(r.status_code)):
                return
            queue_for_combine.put(r.json())

        def get_combine_info_consumer():
            total_p = 0
            bar = ProgressBar('预处理', len(date) * len(content_mode), run_status='处理中', fin_status='处理完成',
                              unit_transfrom_func=unit_transfrom)
            while True:
                json = queue_for_combine.get()
                if json is None:
                    break
                rank_total = int(json['rank_total'])
                p = rank_total // 50 + (1 if (rank_total % 50) > 0 else 0)
                total_p += p
                content_mode_date_p.append((json['content'], json['mode'], json['date'], p))
                queue_for_contents.put(json['contents'])
                bar.refresh(1)
            value_queue.put(total_p)

        def get_json_contents_args():
            for combine in content_mode_date_p:
                params['content'] = combine[0]
                params['mode'] = combine[1]
                params['date'] = combine[2]
                for p in range(2, combine[3] + 1):
                    params['p'] = p
                    yield (params.copy(),)

        def get_json_contents(_params):
            _headers = header[random.randint(0, len(header) - 1)]
            r, _s = self.get_response(base_url, params=_params, headers=_headers, cookies=self.cookies)
            if re.match(r'4\d\d', str(r.status_code)):
                queue_for_contents.put([])
                return
            _json = r.json()
            queue_for_contents.put(_json['contents'])

        def update_database_consumer():
            row_count = 0
            bar = ProgressBar(db_path.split('/')[-1], total_progress, run_status='正在更新', fin_status='更新完成',
                              unit_transfrom_func=unit_transfrom, time_switch=True)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute('update pixiv_ranking set latest = 0')
            except sqlite3.Error as e:
                m = re.search(r'no such column', str(e))
                if m:
                    conn.execute('alter table pixiv_ranking add latest boolean')
                else:
                    print(e)
                    queue_for_contents.put(None)
                    conn.close()
                    return
            conn.commit()
            while True:
                contents = queue_for_contents.get()
                if contents is None:
                    break
                for item in contents:
                    illust_id = item['illust_id']
                    try:
                        conn.execute('INSERT INTO pixiv_ranking (illust_id) VALUES (?)', (illust_id,))
                    except sqlite3.Error:
                        conn.execute('update pixiv_ranking set latest = 1 where illust_id = ?', (illust_id,))
                        continue
                    view_count = item['view_count']
                    user_id = item['user_id']
                    attr = item['attr']
                    tags = item['tags']
                    if tags:
                        tags = map(lambda x: '\"' + x + '\"', tags)
                        tags = reduce(lambda x, y: x + ' ' + y, tags)
                    else:
                        tags = ''
                    url = item['url']
                    illust_page_count = item['illust_page_count']
                    total_score = item['total_score']
                    title = item['title']
                    height = item['height']
                    width = item['width']
                    illust_upload_timestamp = item['illust_upload_timestamp']
                    timearray = time.localtime(illust_upload_timestamp)
                    illust_upload_timestamp = time.strftime("%Y-%m-%d %H:%M:%S", timearray)
                    homosexual = int(item['illust_content_type']['homosexual'])
                    bl = int(item['illust_content_type']['bl'])
                    lo = int(item['illust_content_type']['lo'])
                    antisocial = int(item['illust_content_type']['antisocial'])
                    grotesque = int(item['illust_content_type']['grotesque'])
                    drug = int(item['illust_content_type']['drug'])
                    religion = int(item['illust_content_type']['religion'])
                    violent = int(item['illust_content_type']['violent'])
                    yuri = int(item['illust_content_type']['yuri'])
                    furry = int(item['illust_content_type']['furry'])
                    sexual = item['illust_content_type']['sexual']
                    original = int(item['illust_content_type']['original'])
                    thoughts = int(item['illust_content_type']['thoughts'])
                    _date = item['date']
                    illust_type = item['illust_type']
                    illust_book_style = item['illust_book_style']
                    user_name = item['user_name']
                    info_list = [view_count, user_id, attr, illust_page_count, tags, url, total_score, title, height,
                                 width,
                                 illust_upload_timestamp,
                                 homosexual, bl, lo, antisocial, grotesque, drug,
                                 religion, violent, yuri, furry, sexual, original, thoughts,
                                 _date, illust_type, illust_book_style, user_name, illust_id]
                    command = '''UPDATE pixiv_ranking
                                 set view_count = ?, user_id = ?, attr = ?, illust_page_count = ?, tags = ?, url = ?, total_score = ?, title = ?, height = ?, width = ?,
                                 illust_upload_timestamp = ?,
                                 homosexual = ?, bl = ?, lo = ?, antisocial = ?, grotesque = ?, drug = ?,
                                 religion = ?, violent = ?, yuri = ?, furry = ?, sexual = ?, original = ?, thoughts = ?,
                                 date = ?, illust_type = ?, illust_book_style = ?, user_name = ?, latest = 1
                                 WHERE illust_id = ?'''
                    try:
                        conn.execute(command, info_list)
                    except Exception as _error:
                        print(_error)
                    row_count += 1
                bar.refresh(1)
            conn.commit()
            conn.close()
            value_queue.put(row_count)

        def unit_transfrom(data):
            return '%d' % data

        # 获取rank_total计算总json数量 都是为了进度条
        consumer_thread = threading.Thread(target=get_combine_info_consumer, args=())
        consumer_thread.start()
        prev_threading = threading.enumerate()
        a = alloc(get_json, get_json_args())
        while True:
            if threading.active_count() < max_threading:
                try:
                    next(a)
                except StopIteration:
                    break
        runing_threads = threading.enumerate()
        list(map(lambda t: t.join() if t not in prev_threading else t, runing_threads[1:]))
        queue_for_combine.put(None)
        consumer_thread.join()
        total_progress = value_queue.get()

        # 更新数据库
        consumer_thread = threading.Thread(target=update_database_consumer, args=())
        consumer_thread.start()
        prev_threading = threading.enumerate()
        a = alloc(get_json_contents, get_json_contents_args())
        while True:
            if threading.active_count() < max_threading:
                try:
                    next(a)
                except StopIteration:
                    break
        runing_threads = threading.enumerate()
        list(map(lambda t: t.join() if t not in prev_threading else t, runing_threads[1:]))
        queue_for_contents.put(None)
        consumer_thread.join()
        rowcount = value_queue.get()

        # 下载缩略图
        if save_img:
            connect = sqlite3.connect(db_path, check_same_thread=False)
            try:
                cursor = connect.execute('select illust_id, url from pixiv_ranking where latest == 1')
            except sqlite3.Error as error:
                print(error)
                return

            def get_img(_id, url):
                r, s = self.get_response(url, headers=self.heads[random.randint(0, len(self.heads) - 1)], stream=True,
                                         timeout=50)
                while True:
                    try:
                        img = r.content
                        break
                    except requests.exceptions.RequestException:
                        r.close()
                        r, s = self.get_response(url, headers=self.heads[random.randint(0, len(self.heads) - 1)],
                                                 stream=True, timeout=50, session=s)
                queue_for_contents.put((img, _id))

            def insert_img():
                count = 0
                bar = ProgressBar(db_path.split('/')[-1], rowcount, run_status='正在下图', fin_status='更新完成',
                                  unit_transfrom_func=unit_transfrom_pic, time_switch=True)
                t1 = time.time()
                while True:
                    info_tuple = queue_for_contents.get()
                    if info_tuple is None:
                        bar.refresh(count)
                        break
                    try:
                        connect.execute('update pixiv_ranking set img = ? where illust_id = ?', info_tuple)
                        count += 1
                        t2 = time.time()
                        # 2s 刷新
                        if (t2 - t1) > 2:
                            bar.refresh(count)
                            count = 0
                            t1 = t2
                    except sqlite3.Error:
                        return

            def unit_transfrom_pic(data):
                return '%d 张' % data

            consumer_thread = threading.Thread(target=insert_img, args=())
            consumer_thread.start()
            prev_threading = threading.enumerate()
            a = alloc(get_img, cursor)
            while True:
                if threading.active_count() < max_threading:
                    try:
                        next(a)
                    except StopIteration:
                        break
            runing_threads = threading.enumerate()
            list(map(lambda t: t.join() if t not in prev_threading else t, runing_threads[1:]))
            queue_for_contents.put(None)
            consumer_thread.join()
            connect.commit()
            connect.close()

    # illust_id :  61210737 (插画id)
    # view_count :  28177
    # user_id :  1024922
    # attr : (illust_content_type 中True的键)
    # illust_page_count :  1 (插画页数)
    # tags :  "オリジナル" "女の子" "COMITIA119" "ブレザー" "金髪ロング" "白ソックス" "制服" "美少女" "しゃがみ" "オリジナル5000users入り" (要完全匹配某一个标签加上双引号)
    # url :  http://i2.pixiv.net/c/240x480/img-master/img/2017/01/31/21/41/10/61210737_p0_master1200.jpg (缩略图地址)
    # total_score :  32682
    # title :  はなあらし
    # height :  842
    # width :  595
    # illust_upload_timestamp :  1485866470 上传时间戳
    # homosexual: False, 同性恋
    # bl: False, BL
    # lo: False, 洛丽塔
    # antisocial: False, 反社会
    # grotesque: False, 怪诞(可能R18G)
    # drug: False, 吸烟(毒)(醉酒?)
    # religion: False, 宗教
    # violent: False, 暴力
    # yuri: False, 百合
    # furry: False, 兽迷
    # sexual: 0, 色情(0 1 2)级别
    # original: False, 原创
    # thoughts: False} (不懂)幻想? 想象?
    # date :  2017年01月31日 21:41 上传时间(和上传时间戳信息其实是重复了)
    # illust_type :  0  (0 插画, 1 漫画, 2 动画)
    # illust_book_style :  0 (1 高赞作品? 2 超高赞作品?)(还是很玄)
    # user_name :  フライ○ティアゆ08a
    #
    # db_path 数据库地址
    # table 数据库中的表名
    # command= sqlite 的 条件语句 教程:http://www.runoob.com/sqlite/sqlite-tutorial.html (东西太多了没有好的办法整合, 一个一个弄参数太多了)
    def run_pixiv_database(self, db_path, table, command, folder='排行数据库'):
        database = sqlite3.connect(db_path)
        command = 'select illust_id from %s where %s' % (table, command)
        try:
            cursor = database.execute(command)
        except Exception as error:
            print(error)
            return
        path = self.savePath + folder + '/'
        print(path)
        if os.path.exists(path):
            print('dir exists')
        else:
            os.makedirs(path)
        illust_id_list = [row[0] for row in cursor]
        print("搜索插画数量:", len(illust_id_list))
        self.async_run_pixiv_page(illust_id_list, path)
        database.close()

    # 多进程下载插画
    def async_run_pixiv_page(self, illust_id_list, path):
        p = multiprocessing.Pool(self.num_processes)
        for illust_id in illust_id_list:
            p.apply_async(self.run_pixiv_page, args=(illust_id, path,))
        p.close()
        p.join()
        print("download finished")

    @staticmethod
    def get_response(url, try_time=50, **kwargs):
        if 'session' in kwargs:
            s = kwargs.pop('session')
        else:
            s = requests.Session()
        r = None
        while try_time > 0:
            try:
                r = s.get(url, **kwargs)
                break
            except requests.exceptions.RequestException:
                try_time -= 1
        if try_time <= 0:
            try:
                s.get(url, **kwargs)
            except requests.exceptions.RequestException as error:
                raise TryError(error, "过多的尝试")
        return r, s

    @staticmethod
    def post_response(url, try_time=50, **kwargs):
        if 'session' in kwargs:
            s = kwargs.pop('session')
        else:
            s = requests.Session()
        r = None
        while try_time > 0:
            try:
                r = s.post(url, **kwargs)
                break
            except requests.exceptions.RequestException:
                try_time -= 1
        if try_time <= 0:
            try:
                s.post(url, **kwargs)
            except requests.exceptions.RequestException as error:
                raise TryError(error, "过多的尝试")
        return r, s

    # 参数:
    # db_path 数据库地址
    # word_and 包含全部关键词 (使用 list tuple等 将关键字组合一起)
    # word_or 包含其中任意一个关键词 (使用 list tuple等 将关键字组合一起)
    # word_not 排除的关键词 (使用 list tuple等 将关键字组合一起)
    # save_img 是否保存缩略图
    # php? php参数
    # s_mode: 部分一致: s_tag 标签, s_tc 标题/简介; 完全一致: s_tag_full, s_tc_full
    # type: illust 插画, ugoira 动图, manga 漫画, 缺省 综合
    # order: date 按旧排序, 缺省 按最新排序
    # scd: %Y-%m-%d 在这个日期及以后 还可以%Y%m%d; %Y/%m/%d; %Y %m %d; %Y\%m\%d
    # ecd: %Y-%m-%d 在这个日期及以前 同上
    # r18: 1 仅限R18
    # ratio: 长宽比: 0.5 横长, -0.5 高长, 0 正方形(可以其他值, 算法未知)
    # wlt: 横长大于该像素值
    # wgt: 横长小于该像素值
    # hlt: 高度大于该像素值
    # hgt: 高度小于该像素值
    # weight_range: 横长像素范围 支持list tulpe: (-1表示无穷) e.g (-1, 1000); str: (\d+|\s*)\-(\d+|\s*) e.g 1000-
    # height_range: 高度像素范围 同上
    # tool: 工具, 缺省 全部工具
    def run_pixiv_search_update_database(self, db_path, word_and, word_or=None, word_not=None, exact_match=False,
                                         **kwargs):
        self.create_pixiv_papi_database(db_path)
        base_url = 'http://www.pixiv.net/search.php?'
        # 参数处理
        word = []
        if word_and:
            if isinstance(word_and, str):
                word_and = (word_and,)
            word_and = set(word_and)
            word.append(reduce(lambda x, y: x + ' ' + y, word_and))

        if word_or:
            if isinstance(word_or, str):
                word_or = (word_or,)
            word_or = set(word_or)
            word.append('(' + reduce(lambda x, y: x + ' OR ' + y, word_or) + ')')

        if word_not:
            if isinstance(word_not, str):
                word_not = (word_not,)
            word_not = set(word_not)
            word.append(reduce(lambda x, y: x + ' ' + y, map(lambda x: '-' + x, word_not)))

        if not word:
            print('关键字错误')
            return

        word = reduce(lambda x, y: x + ' ' + y, word)
        params = {'word': word}

        if 's_mode' in kwargs:
            s_mode = kwargs['s_mode']
            if exact_match and s_mode.find('_full') == -1:
                s_mode += '_full'
            params['s_mode'] = s_mode
        else:
            if exact_match:
                params['s_mode'] = 's_tag_full'
            else:
                params['s_mode'] = 's_tag'
        if 'type' in kwargs:
            params['type'] = kwargs['type']
        if 'order' in kwargs:
            params['order'] = kwargs['order']
        if 'scd' in kwargs:
            m = re.match(r'(\d{4})[-\\/\s.]*(\d{2})[-\\/\s.]*(\d{2})', kwargs['scd'])
            if m:
                try:
                    scd_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except TryError as error:
                    print(error)
                    return
            else:
                print('日期格式错误')
                return
            params['scd'] = scd_date
        if 'ecd' in kwargs:
            m = re.match(r'(\d{4})[-\\/\s.]*(\d{2})[-\\/\s.]*(\d{2})', kwargs['ecd'])
            if m:
                try:
                    ecd_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except TryError as error:
                    print(error)
                    return
            else:
                print('日期格式错误')
                return
            params['ecd'] = ecd_date
        if 'r18' in kwargs:
            params['r18'] = kwargs['r18']
        if 'ratio' in kwargs:
            params['ratio'] = kwargs['ratio']
        if 'weight_range' in kwargs:
            weight_range = kwargs['weight_range']
            if isinstance(weight_range, str):
                m = re.match(r'(\d+|\s*)-(\d+|\s*)', weight_range)
                if m:
                    if m.group(1) != '':
                        params['wlt'] = m.group(1)
                    if m.group(2) != '':
                        params['wgt'] = m.group(2)
                else:
                    print('范围输入出错')
            elif isinstance(weight_range, (list, tuple)):
                if weight_range[0] != -1:
                    params['wlt'] = weight_range[0]
                if weight_range[1] != -1:
                    params['wgt'] = weight_range[1]
            else:
                raise TryError('unexcept type')
        if 'height_range' in kwargs:
            height_range = kwargs['height_range']
            if isinstance(height_range, str):
                m = re.match(r'(\d+|\s*)-(\d+|\s*)', height_range)
                if m:
                    if m.group(1) != '':
                        params['hlt'] = m.group(1)
                    if m.group(2) != '':
                        params['hgt'] = m.group(2)
                else:
                    print('范围输入出错')
            elif isinstance(height_range, (list, tuple)):
                if height_range[0] != -1:
                    params['hlt'] = height_range[0]
                if height_range[1] != -1:
                    params['hgt'] = height_range[1]
            else:
                raise TryError('unexcept type')
        if 'wgt' in kwargs:
            params['wgt'] = kwargs['wgt']
        if 'wlt' in kwargs:
            params['wlt'] = kwargs['wlt']
        if 'hgt' in kwargs:
            params['hgt'] = kwargs['hgt']
        if 'hlt' in kwargs:
            params['hlt'] = kwargs['hlt']
        if 'tool' in kwargs:
            params['tool'] = kwargs['tool']
        if 'save_img' in kwargs:
            save_img = kwargs['save_img']
        else:
            save_img = False

        # 获取搜索结果数
        html = self.get_html_tree(base_url, params=params)
        count_badge = html.find('span', {'class': 'count-badge'}).get_text()
        m = re.search(r'\d+', count_badge)
        count_badge = int(m.group())
        max_p = count_badge // 20 + (1 if (count_badge % 20) else 0)
        if max_p > 1000:
            # FIXME 可以用日期分割搜索结果
            max_p = 1000
            count_badge = 20 * 1000

        # 使用PixivAPI 需要账号密码
        papi = PixivAPI()
        papi.login(kwargs['username'], kwargs['password'])

        # 多线程 多进程 准备
        pool = multiprocessing.Pool()
        manager = multiprocessing.Manager()

        queue_for_process = manager.Queue()
        queue_for_value = queue.Queue()

        # FIXME 在爬取过程中搜索结果更新的处理想不出好的解决方案

        def get_illust_id_args():
            for p in range(1, max_p + 1):
                params['p'] = p
                yield (params.copy(), papi, queue_for_process)

        def alloc(func, args_list):
            for args in args_list:
                t = threading.Thread(target=func, args=args)
                t.start()
                yield

        def unit_transfrom(data):
            return '%d' % data

        def update_database():
            rowcount = 0
            bar = ProgressBar(db_path.split('/')[-1], count_badge, run_status='正在更新', fin_status='更新完成',
                              unit_transfrom_func=unit_transfrom, time_switch=True)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute('update pixiv_papi set latest = 0')
            except sqlite3.Error as e:
                if re.search(r'no such column', str(e)):
                    conn.execute('alter table pixiv_papi add latest boolean')
                else:
                    print(e)
                    conn.close()
                    return
            conn.commit()
            count = 0
            _t1 = time.time()
            while True:
                response = queue_for_process.get()
                if response is None:
                    bar.refresh(count)
                    break
                # 失败
                if response == 1:
                    count += 1
                    continue
                illust_id = int(response['id'])
                try:
                    conn.execute('INSERT INTO pixiv_papi (illust_id) VALUES (?)', (illust_id,))
                except sqlite3.Error:
                    # 失败
                    conn.execute('update pixiv_papi set latest = 1 where illust_id = ?', (illust_id,))
                    count += 1
                    continue
                title = response['title']
                tags = response['tags']
                if tags:
                    tags = map(lambda x: '\"' + x + '\"', tags)
                    tags = reduce(lambda x, y: x + ' ' + y, tags)
                else:
                    tags = ''
                tools = response['tools']
                if tools:
                    tools = map(lambda x: '\"' + x + '\"', tools)
                    tools = reduce(lambda x, y: x + ' ' + y, tools)
                else:
                    tools = ''
                url = response['image_urls']['px_480mw']
                width = response['width']
                height = response['height']
                scored_count = response['stats']['scored_count']
                total_score = response['stats']['score']
                view_count = response['stats']['views_count']
                favorited_count = reduce(lambda x, y: int(x) + int(y),
                                         dict(response['stats']['favorited_count']).values())
                commented_count = response['stats']['commented_count']
                age_limit = response['age_limit']
                illust_upload_timestamp = response['created_time']
                user_id = response['user']['id']
                user_name = response['user']['name']
                illust_page_count = response['page_count']
                illust_book_style = response['book_style']
                illust_type = response['type']
                info_list = [title, tags, tools, url, width, height, scored_count, total_score, view_count,
                             favorited_count, commented_count, age_limit, illust_upload_timestamp, user_id, user_name,
                             illust_page_count, illust_book_style, illust_type, illust_id]
                command = '''UPDATE pixiv_papi
                             set title = ?, tags = ?, tools = ?, url = ?, width = ?, height = ?, scored_count = ?,
                             total_score = ?, view_count = ?, favorited_count = ?, commented_count = ?, age_limit = ?,
                             illust_upload_timestamp = ?, user_id = ?, user_name = ?, illust_page_count = ?,
                             illust_book_style = ?, illust_type = ?, latest = 1
                             WHERE illust_id = ?'''
                try:
                    conn.execute(command, info_list)
                    rowcount += 1
                    count += 1
                    _t2 = time.time()
                    # 3.5s 刷新
                    if (_t2 - _t1) > 3.5:
                        bar.refresh(count)
                        count = 0
                        _t1 = _t2
                except Exception as _error:
                    print(_error)
                    bar.refresh(0, status='更新出错')
                    return
            conn.commit()
            conn.close()
            queue_for_value.put(rowcount)

        db_consumer_thread = threading.Thread(target=update_database, args=())
        db_consumer_thread.start()
        prev_threading = threading.enumerate()
        for arg in get_illust_id_args():
            pool.apply_async(self.get_illust_id_for_search_process, args=arg)
        pool.close()
        pool.join()
        queue_for_process.put(None)

        if save_img:
            queue_for_thread = queue.Queue()

            connect = sqlite3.connect(db_path, check_same_thread=False)
            try:
                cursor = connect.execute('select illust_id, url from pixiv_ranking where latest == 1')
            except sqlite3.Error as error:
                print(error)
                return

            def get_img(_id, url):
                r, s = self.get_response(url, headers=self.heads[random.randint(0, len(self.heads) - 1)], stream=True,
                                         timeout=50)
                while True:
                    try:
                        img = r.content
                        break
                    except requests.exceptions.RequestException:
                        r.close()
                        r, s = self.get_response(url, headers=self.heads[random.randint(0, len(self.heads) - 1)],
                                                 stream=True, timeout=50, session=s)
                queue_for_thread.put((img, _id))

            def insert_img():
                count = 0
                bar = ProgressBar(db_path.split('/')[-1], row_count, run_status='正在下图', fin_status='更新完成',
                                  unit_transfrom_func=unit_transfrom_pic, time_switch=True)
                t1 = time.time()
                while True:
                    info_tuple = queue_for_thread.get()
                    if info_tuple is None:
                        bar.refresh(count)
                        break
                    try:
                        connect.execute('update pixiv_ranking set img = ? where illust_id = ?', info_tuple)
                        count += 1
                        t2 = time.time()
                        # 2s 刷新
                        if (t2 - t1) > 2:
                            bar.refresh(count)
                            count = 0
                            t1 = t2
                    except sqlite3.Error:
                        return

            def unit_transfrom_pic(data):
                return '%d 张' % data

            consumer_thread = threading.Thread(target=insert_img, args=())
            consumer_thread.start()
            prev_threading = threading.enumerate()
            a = alloc(get_img, cursor)
            while True:
                if threading.active_count() < self.num_threading:
                    try:
                        next(a)
                    except StopIteration:
                        break
            runing_threads = threading.enumerate()
            list(map(lambda t: t.join() if t not in prev_threading else t, runing_threads[1:]))
            queue_for_thread.put(None)
            consumer_thread.join()
            connect.commit()
            connect.close()

    # 在run_pixiv_search_update_database中多进程调用的函数
    def get_illust_id_for_search_process(self, _params, papi, _queue):

        def alloc(func, args_list):
            for args in args_list:
                t = threading.Thread(target=func, args=args)
                t.start()
                yield

        def get_illust_json_use_papi(illust_id):
            json = papi.works(illust_id)
            if json['status'] == 'success':
                for i in json['response']:
                    _queue.put(i)
            else:
                print(illust_id, '作品获取失败')
                # 失败算一个进度
                _queue.put(1)

        _url = 'http://www.pixiv.net/search.php?'
        html_root = self.get_html_tree(_url, params=_params)
        search_result = html_root.find('section', {'class': 'column-search-result'})
        args_map = map(lambda item: (int(item.img['data-id']),), search_result.find_all('li', {'class': 'image-item'}))
        prev_threading = threading.enumerate()
        a = alloc(get_illust_json_use_papi, args_map)
        while True:
            if threading.active_count() < self.num_threading:
                try:
                    next(a)
                except StopIteration:
                    break
        runing_threads = threading.enumerate()
        list(map(lambda t: t.join() if t not in prev_threading else t, runing_threads[1:]))

# TODO 60420835 debug
# bookmark_detail.php 收藏详细信息 可以用于搜索
if __name__ == '__main__':
    modebase = ('daily', 'weekly', 'monthly', 'rookie',
                'original', 'male', 'female',
                'daily_r18', 'weekly_r18',
                'male_r18', 'female_r18', 'r18g',
                'oversea', 'hokkaido_tohoku',
                'kanto', 'chubu', 'kinki',
                'chugoku_shikoku', 'kyusyu_okinawa')
    contentbase = ('all', 'illust', 'ugoira', 'manga')
    test = PixivSpiderLogin()
    if test.load_cookies():
        print('登录成功')
    t1 = time.time()
    test.run_pixiv_search_update_database('test9.db', '百合',
                                          username=, password=)
    t2 = time.time()
    time_s = time.gmtime(t2 - t1)
    print(time_s)
    print(time_s[4], time_s[5])

