# encoding=utf-8
import time


# 一个自制的进度条:
# 实例化时参数:
# title: 标题 str
# total: 总进度 int
# progress2str_func: 将进度值转换成str信息的函数 可以自己提供;
# 该类提供bit转换成适合单位的函数data_size,
# 不转换数值 后缀单位可选的函数none_transfrom(), 参数: unit: 返回后缀单位是unit的函数 unit=None时没有后缀单位
# progress: 初始进度
# run_status: 运行状态信息
# fin_status: 结束状态信息
class ProgressBar(object):
    def __init__(self, title, total, progress2str_func, progress=0, run_status=None, fin_status=None):
        self.info = "[{title}] {status} {progress} | {total} {rate:5.1f}% [{bar}]"
        self.title = title
        self.total = total
        self.progress = progress
        self.status = run_status or '运行中'
        self.fin_status = fin_status or '完成'
        self.closed = False
        self.transfrom = self.data_size
        self.transfrom = progress2str_func
        self.begin_time = time.time()
        self.last_time = self.begin_time
        self.total_data_str = self.transfrom(total)
        if total == 0:
            print(self.info.format(title=self.title, status=self.status,
                                   progress=self.transfrom(self.progress),
                                   total=self.total_data_str, rate=100, bar='|' * 20) + ' 总用时: 0 秒')
            self.closed = True
        else:
            print_str = self.__get_info()
            self.last_print_len = len(print_str.encode())
            print(print_str, end='')

    @staticmethod
    def data_size(data_content):
        if (data_content / 1024) > 1024:
            return '{:.2f} MB'.format(data_content / 1024 / 1024).rjust(8)
        else:
            return '{:.2f} KB'.format(data_content / 1024).rjust(8)

    @staticmethod
    def none_transfrom(unit=None):

        if unit:
            def unit_transfrom(data):
                return '{data}'.format(data=data) + ' ' + unit
            return unit_transfrom
        else:
            def none_unit_transfrom(data):
                return '{data}'.format(data=data)
            return none_unit_transfrom

    def bar(self):
        rate = self.progress / self.total
        _bar = int(rate * 20)
        _bar = ('|' * _bar) + (' ' * (20 - _bar))
        return rate * 100, _bar

    def __get_info(self):
        # [名称]状态 已下载 单位 | 总数 单位 百分比 进度条
        data_str = self.transfrom(self.progress)
        rate, _bar = self.bar()
        return self.info.format(title=self.title, status=self.status, progress=data_str,
                                total=self.total_data_str, rate=rate, bar=_bar)

    # 将时间间隔转换成合适的str信息
    @staticmethod
    def use_time(interval):
        struct_time = time.gmtime(interval)
        if struct_time[7] > 1:
            time_str = '%d 天 %d 小时' % (struct_time[7] - 1, struct_time[3])
        elif struct_time[3] > 0:
            time_str = '%d 小时 %d 分钟' % (struct_time[3], struct_time[4])
        elif struct_time[4] > 0:
            time_str = '%d 分 %d 秒' % (struct_time[4], struct_time[5])
        else:
            time_str = '%d 秒' % struct_time[5]
        return time_str

    # 刷新进度条 progress 增加进度; now_time 当前时间戳 当提供时显示剩余时间; add_total 总进度调整 total += add_total
    def refresh(self, progress, now_time=None, add_total=None):
        remain_str = ''
        if self.closed:
            return
        if isinstance(add_total, int):
            self.total += add_total
        self.progress += progress
        if self.progress > self.total:
            self.total = self.progress
            self.total_data_str = self.transfrom(self.total)
            remain_str = ' 剩余时间: 未知'
        elif now_time:
            instant_speed = progress / (now_time - self.last_time)
            average_speed = self.progress / (now_time - self.begin_time)
            speed = (instant_speed + average_speed) / 2
            # remain < 31536000
            remain_str = ' 剩余时间: ' + (self.use_time((self.total - self.progress) / speed) if speed != 0 else '')
        print('\r' + ' ' * self.last_print_len, end='')
        print_str = self.__get_info() + remain_str
        self.last_print_len = len(print_str.encode())
        print('\r' + print_str, end='')

    # 结束进度条 结束后该进度条将无法再刷新 状态改为fin_status 并且显示总用时
    # unexcept_status: 特殊状态信息 提供时状态改为该值
    def close(self, unexcept_status=None):
        if self.closed:
            return
        self.closed = True
        use_time_str = self.use_time(time.time() - self.begin_time)
        if unexcept_status:
            self.status = unexcept_status
        else:
            self.status = self.fin_status
        print('\r' + ' ' * self.last_print_len, end='')
        print_str = self.__get_info() + ' 总用时: ' + use_time_str
        self.last_print_len = len(print_str.encode())
        print('\r' + print_str)

if __name__ == '__main__':
    import random

    bar = ProgressBar('test', 48954879, ProgressBar.data_size)
    time.sleep(1)
    bar.refresh(464)
    time.sleep(2)
    bar.refresh(0)
    time.sleep(2)
    count = 100
    while count > 0:
        time.sleep(0.1)
        bar.refresh(random.randint(0, 654612), now_time=time.time())
        count -= 1
    bar.close(unexcept_status='中断')
