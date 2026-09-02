#!/usr/bin/env python
import argparse
import os
import re


def to_standard_lrc(enhanced_lrc):
    """将增强型LRC（含逐字<mm:ss.xxx>时间戳）转为标准LRC（仅保留行级时间戳）"""
    return re.sub(r'<\d+:\d{2}\.\d{3}>', '', enhanced_lrc)


def build_parser():
    parser = argparse.ArgumentParser(description='自动打轴工具')
    parser.add_argument('lrc_file', help='歌词文本')
    parser.add_argument('music_file', help='歌曲文件')
    parser.add_argument('-f', '--format', choices=('lrc',), default='lrc',
                        help='输出文件格式，仅支持lrc（默认）')
    parser.add_argument('-l', '--line_only', type=int, choices=(0, 1), default=0,
                        help='1:逐句/0:逐字, 默认：逐字')
    parser.add_argument('-v', '--vocalize', type=int, choices=(0, 1), default=1,
                        help='1:分离人声/0:不分离, 默认：分离')
    parser.add_argument(
        '-m', '--model', choices=('mdx', 'mdx_extra', 'mdx_q', 'mdx_extra_q'),
        help='demucs模型，默认：mdx_extra', default='mdx_extra')
    parser.add_argument(
        '-i', '--idx', type=int, choices=(-1, 0, 1, 2, 3),
        help='demucs模型idx, 默认：-1', default=-1)
    parser.add_argument('-o', '--out_dir', type=str, default='demofile',
                        help='标准LRC输出目录，默认：demofile')
    return parser


def cli():
    args = build_parser().parse_args()

    import ext.t2lutils as t2lutils
    from t2l.t2l import process

    txt_lines = None
    encoding = t2lutils.__get_file_encoding(args.lrc_file)
    with open(args.lrc_file, 'r', encoding=encoding) as fp:
        txt_lines = fp.readlines()
    lrc = process(
        txt_lines,
        args.music_file,
        demucs_model=args.model,
        demucs_idx=args.idx,
        format=args.format,
        line_only=(args.line_only == 1),
        vocalize=(args.vocalize == 1),
    )
    print(lrc)

    # 转为标准LRC并保存到输出目录
    standard_lrc = to_standard_lrc(lrc)
    os.makedirs(args.out_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(args.music_file))[0]
    out_path = os.path.join(args.out_dir, base_name + '.lrc')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(standard_lrc)
    print(f'\n标准LRC已保存至: {out_path}')


if __name__ == '__main__':
    cli()
