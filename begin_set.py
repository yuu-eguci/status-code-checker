#!/usr/bin/env python
# coding: utf-8

'''begin_set

俺式アプリ準備セット。
    1. カレント移して
    2. カレント以下のディレクトリを取得して
    3. 全部インポートパスに登録しますよ。

使い方はこう!
    import begin_set
    begin_set.exec_all(__file__)

でどうぞ! これを直接実行してもちゃんとテスト動作でうごくよ。
'''

import os
import sys
from pprint import pprint


def cd_(file_path):
    '''カレントディレクトリを file_path の場所に移す。'''

    if not isinstance(file_path, str) or not os.path.exists(file_path):
        raise ValueError(f'No such file: {file_path}')

    os.chdir(os.path.dirname(
        sys.executable
        if hasattr(sys, 'frozen') else os.path.abspath(file_path)))


def get_directory_tree(top_dir, rmpycache=True):
    '''トップディレクトリ以下全ディレクトリのリストを入手します。
    デフォルトでは__pycache__は除きます。'''

    tree = [os.path.abspath(top_dir)]
    for directory in tree:
        # ファイル内包表記と高階関数にハマってるのでこんなことになってる。
        # 見やすさ度外視! 読みづれえ!
        tree.extend([
            file for file in map(
                lambda file: directory + os.sep + file, os.listdir(directory))
            if (os.path.isdir(file)
                and not (
                    rmpycache and os.path.basename(file) == '__pycache__'))
        ])
    return tree


def remake_import_path(directory_tree):
    '''インポートパスに追加する。'''

    sys.path = directory_tree + sys.path


def exec_all(file_name):
    '''このモジュールをフル実行します。引数には__file__を渡せばいいと思います。'''

    cd_(file_name)
    remake_import_path(get_directory_tree(os.path.dirname(file_name), True))


if __name__ == '__main__':
    print(f'__file__: {__file__}' + '\n')

    print('cd_実行後の os.getcwd():')
    print(os.getcwd() + '\n')

    print('get_directory_tree(os.path.dirname(__file__), True):')
    pprint(get_directory_tree(os.path.dirname(__file__), True))
    print()

    print('make_import_path(directory_tree)後のsys.path:')
    remake_import_path(get_directory_tree(os.path.dirname(__file__), True))
    pprint(sys.path)
