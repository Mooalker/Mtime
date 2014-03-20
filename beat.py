# coding=utf-8
'''
把需要抓取的电影id发送给MQ, 他是一切任务的生成源
'''
from parse import get_movie_ids, get_movie_pages
from utils import get_unfinished, group, sleep2
from spider import Search
from conf import SEARCH_PAGE, SEARCH_API, MIN_YEAR, TASK_BEAT_NUM, TASK_BEAT
from models import YearFinished, IdFinished
from schedulers import Message
from control import Scheduler, periodic
from log import error, info, debug, warn

scheduler = Scheduler('beat')


def get_year():
    '''根据年份从前向后,获取当前要执行的第一个年份(min)'''
    obj = YearFinished.objects
    if obj:
        c_year = obj.first()
        return c_year.year
    else:
        return MIN_YEAR - 1


def fetch(year, page):
    s = Search(params={'Ajax_CallBack': True,
                       'Ajax_CallBackType': 'Mtime.Channel.Pages.SearchService',  # noqa
                       'Ajax_CallBackMethod': 'SearchMovieByCategory',
                       'Ajax_CrossDomain': 1,
                       'Ajax_CallBackArgument10': year,
                       'Ajax_CallBackArgument14': '1',
                       'Ajax_CallBackArgument16': '1',
                       'Ajax_CallBackArgument18': page,
                       'Ajax_CallBackArgument19': '1',
                       'Ajax_CallBackArgument9': year,
                       'Ajax_CallBackArgument17': 8,
                       'Ajax_CallBackArgument8': '',
                       'Ajax_RequestUrl': SEARCH_PAGE.format(year=year)
                       })
    s.fetch(SEARCH_API)
    print s.content
    return s


def mtime_beat():
    '''每次任务只跑一年的'''
    y_list = []
    y = get_year() + 1  # 要抓取的年份
    debug('Fetch Year: {} starting...'.format(y))
    instance = fetch(y, 1)
    page = get_movie_pages(instance)
    if page is None:
        warn('Movie"page has not fetched')
        # 执行间隔自适应
        if scheduler.get_interval < TASK_BEAT * 7:
            scheduler.change_interval(incr=True)
        return
    ids = get_movie_ids(instance)
    if ids is None:
        # 间隔自适应也不能太大
        warn('Movie has not fetched')
        if scheduler.get_interval < TASK_BEAT * 7:
            scheduler.change_interval(incr=True)
        return
    # 当任务继续能执行的时候,回到默认的间隔
    if scheduler.get_interval > TASK_BEAT:
        debug('Interval back to default')
        scheduler.change_interval(TASK_BEAT)
    y_list.extend(ids)
    if not y_list:
        # 本年没有电影
        debug('Year: {} has not movie'.format(y))
        YearFinished(year=y).save()
        sleep2()
        return mtime_beat()
    if page > 1:
        for p in range(2, page + 1):
            instance = fetch(y, p)
            debug('Fetch Year:{} Page:{}'.format(y, p))
            ids = get_movie_ids(instance)
            if ids is None:
                # 间隔自适应也不能太大
                if scheduler.get_interval < TASK_BEAT * 7:
                    scheduler.change_interval(incr=True)
                return
            y_list.extend(ids)
            sleep2()
    obj = IdFinished.objects(year=y).first()
    if obj is not None:
        has_finished = obj.ids
    else:
        has_finished = []
    to_process = get_unfinished(has_finished, y_list)
    # 给相应队列添加任务
    for payload in group(to_process, TASK_BEAT_NUM):
        for task in ['Fullcredits', 'Releaseinfo', 'Movie', 'Comment',
                     'MicroComment', 'Company', 'Scenes', 'Awards',
                     'Plot', 'Poster', 'Details']:
            debug('Push payload: {} to {} Queue'.format(payload, task))
            Message(task=task, payload=payload).save()
    # 当前年份数据已经入MQ
    YearFinished(year=y).save()
    debug('Year: {} done'.format(y))
    # IdFinished.objects(year=y).update(add_to_set__ids=to_process)


def main():
    periodic(scheduler, mtime_beat)
    scheduler.run()


if __name__ == '__main__':
    main()
