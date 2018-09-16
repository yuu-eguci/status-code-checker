#!/usr/bin/env python
# coding: utf-8

'''StatusCodeChecker

好きなだけURL書いてください。
ステータスコードごとに整理します。
時間はかかるけどね。ごめんね。

$ python StatusCodeChecker.py


================================
バージョン1.0(2017-10-19)
    作った。
'''


targets = '''

https://***/

'''


import requests
import begin_set
from pprint import pprint


class StatusCodeChecker:
    @classmethod
    def make_pathlist(cls, targetpaths: str) -> list:
        '''冒頭でインプットした文字列を配列にする。'''
        return filter(lambda t: t, targetpaths.strip().split('\n'))

    @classmethod
    def run(cls, urls):
        '''httpステータスコードごとに分けます。'''
        dic = {}
        for url in urls:
            status_code = requests.get(url, allow_redirects=False).status_code
            if status_code not in dic.keys():
                dic[status_code] = []
            dic[status_code].append(url)
        return dic


begin_set.exec_all(__file__)
urls = StatusCodeChecker.make_pathlist(targets)
result = StatusCodeChecker.run(urls)
pprint(result)
