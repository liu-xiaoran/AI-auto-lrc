import logging
import re

import audioread
import julius
from .mtl import utils as mtl_utils
import torch
import torchaudio as ta
from demucs import pretrained as demucs_pretrained
from demucs.apply import apply_model as demucs_apply_model
from .mtl.wrapper import align
import warnings
import librosa

logger = logging.getLogger("t2l")


def phonetize(text):
    from .phonetic import phonetize as convert
    return convert(text)


def process(txt_lines, audio_file, mtl_model='MTL',
            demucs_model='mdx_extra', demucs_idx=-1,
            line_only=False, out_file=None, verbose=True,
            vocalize=True, format='lrc'):
    """
    :mtl_model: tuple of pre loaded model, or one of string: "Baseline", "MTL", "Baseline_BDR", "MTL_BDR"
    :return: lrc resutl. TxtValueError if txt_lines invalid, AudioValueError if audio error
    """
    if format != 'lrc':
        raise ValueError(
            "Unsupported format {!r}; only 'lrc' is implemented.".format(format)
        )

    # filter lyric words and phonetize. FIXME: 如何处理数字
    phonetics, lines, pre_lines_unprocessed = [], [], ''  # [[读音],..], [[文字],..]
    for line in txt_lines:
        line = line.strip()
        line = re.sub(r'^\[[\d.:]+\]\s*', '', line)  # 去除已打的时间戳
        line = re.sub(r'^\[[a-zA-Z]{2}:.+\]\s*', '',
                      line)  # 去除 [ar/au/al/ti:...]
        phonetic, words = [], []
        # 转读音
        line_py, pre_wd = phonetize(line), ''
        for wd, ph in line_py:  # [(w, p), ..]
            if len(pre_wd) > 0:
                wd, pre_wd = pre_wd + wd, ''
            if re.search("[^a-z'~]", ph):  # ph进一步拆分
                widx0, phs = 0, re.split(
                    r'[\s\?\.!@#$%\^&\*\(\)\-\+=`_,\{\[\]\}\\;:|"/<>0-9]', ph)
                for ph in phs:
                    lph = len(ph)
                    if lph == 0:
                        continue
                    widx1 = wd.find(ph, widx0) + lph
                    words.append(wd[widx0:widx1])
                    phonetic.append(ph)
                    widx0 = widx1
                if widx0 < len(wd):
                    if len(words) > 0:
                        # 将无phone的word接到上一个word
                        words[-1] = words[-1] + wd[widx0:]
                    else:
                        pre_wd += wd[widx0:]
            else:
                words.append(wd)
                phonetic.append(ph)
        if len(words) > 0:
            phonetics.append(phonetic)
            lines.append(words)
        elif len(lines) > 0:
            lines[-1][-1] += '\n' + line  # 还原lines, TODO 若lines.len==0，则会丢内容
        else:
            pre_lines_unprocessed += ('\n' if len(pre_lines_unprocessed)
                                      > 0 else '') + line

    if len(lines) == 0:
        raise TxtValueError('Invalid lrc file, no valid content.')

    if vocalize:
        vocals, _ = separate_vocals(
            audio_file, demucs_model=demucs_model,
            demucs_idx=demucs_idx, verbose=verbose)
    else:
        vocals, _ = preprocess_audio(audio_file, sr=22050)

    # 打 轴
    verbose and print('Phoneticing...')
    # raw_lines = [" ".join(line) for line in phonetics]
    # raw_words = " ".join(raw_lines).split()
    lyrics_p, _, idx_word_p, idx_line_p = mtl_utils.gen_phone_gt_opt(phonetics)
    word_align, words = align(
        vocals, None, lyrics_p, idx_word_p, idx_line_p,
        method=mtl_model, cuda=True, verbose=verbose)
    lrc_content = gen_lrc(word_align, lines, line_only=line_only)
    if len(pre_lines_unprocessed) > 0:
        lrc_content = pre_lines_unprocessed + '\n' + lrc_content

    # 生成tagged lrc文件
    # lrc_out = lrc + '.lrc'
    if out_file:
        verbose and print('write to lrc file:', out_file)
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(lrc_content)
        # write_csv(lrc_out, word_align, words)

    return lrc_content


class TxtValueError(ValueError):
    pass


class AudioValueError(ValueError):
    pass


def separate_vocals(audio_file, sample_rate=22050, demucs_model='mdx_extra', demucs_idx=-1, verbose=True):
    x, sr = preprocess_audio(audio_file)
    return __vocalize(
        x, sr, sample_rate, demucs_model, demucs_idx, verbose)


def vocalize(audio_file, sample_rate=22050, demucs_model='mdx_extra', demucs_idx=-1, verbose=True):
    return separate_vocals(
        audio_file,
        sample_rate=sample_rate,
        demucs_model=demucs_model,
        demucs_idx=demucs_idx,
        verbose=verbose,
    )


def preprocess_audio(audio_file, sr=None):
    """
    :returns: np/tensor array
    """
    torchaudio_error = None
    try:
        y, sr1 = ta.load(audio_file)
    except (RuntimeError, OSError) as err:
        torchaudio_error = err
        logger.info(
            'torchaudio.load failed for %s; retrying with librosa.',
            audio_file)
        y = None

    if y is None or y.numel() == 0:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                y, sr1 = librosa.load(
                    audio_file, sr=sr, res_type='kaiser_fast')
        except (RuntimeError, OSError, ValueError, EOFError,
                audioread.exceptions.DecodeError) as err:
            message = (
                "Unable to load audio {!r} with torchaudio and librosa."
                .format(audio_file)
            )
            if torchaudio_error is not None:
                message += " torchaudio error: {}.".format(torchaudio_error)
            raise AudioValueError(message) from err

    if not isinstance(y, torch.Tensor):
        y = torch.as_tensor(y)
    if y.numel() == 0:
        raise AudioValueError("Audio file {!r} is empty.".format(audio_file))

    if sr is not None and sr1 != sr:
        y = julius.resample_frac(y, sr1, sr)
    else:
        sr = sr1

    if y.ndim == 1:
        y = y.unsqueeze(0)  # (channel, sample)

    return y, sr


def __vocalize(x, sr, new_sr, demucs_model, demucs_idx, verbose):
    """
    :param x: [c,t]
    """

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    if verbose:
        print('device:', device)
    if not isinstance(x, torch.Tensor):
        x = torch.tensor(x, device=device)
    if torch.cuda.is_available() and not x.is_cuda:
        x = x.to(device=device)

    vocals = None
    if isinstance(demucs_model, str):
        model = load_demucs_model(demucs_model, demucs_idx, device, verbose)
    else:
        model = demucs_model

    verbose and print('Demucsing...')
    if model.samplerate != sr:
        x = julius.resample_frac(x, sr, model.samplerate)
    # ref = x.mean(0)
    # x = (x - ref.mean()) / ref.std()
    if x.shape[0] == 1:
        x = x.expand((2,) + x.shape[1:])
    with torch.inference_mode():
        out = demucs_apply_model(
            model, x[None], device=device, progress=verbose)[0]
    # out = out * ref.std() + ref.mean()

    for name, source in zip(model.sources, out):
        # print(name, source.std() / x.std())
        if name == 'vocals':
            vocals = source
            break

    if new_sr != model.samplerate:
        vocals = julius.resample_frac(vocals, model.samplerate, new_sr)
    return vocals, new_sr


def gen_lrc(word_align, lines, line_only=False):
    """
    :param line_only: True逐句，False逐字
    """
    def _ts(s):
        mm = int(s / 60)
        ss = int(s - mm * 60)
        xx = int(1000 * (s - int(s)))
        return '{:02d}:{:02d}.{:03d}'.format(mm, ss, xx)
    result = ''
    idx, resolution = 0, 256 / 22050 * 3  # @see write_csv
    for line in lines:
        # 边界保护：对齐结果不够时，停止进一步处理，避免越界
        if idx >= len(word_align):
            logger.warning("gen_lrc truncated: word_align shorter than lines. idx=%s, len(word_align)=%s", idx, len(word_align))
            break
        ts_line, txt_line = '[' + _ts(word_align[idx][0] * resolution) + ']', ''
        for ch in line:
            if len(ch) > 0:
                if not line_only:
                    # 边界保护：逐字时间戳插入时，若对齐不足则不插入时间戳，仅输出文本
                    if idx < len(word_align):
                        ch = '<' + _ts(word_align[idx][0] * resolution) + '>' + ch
                txt_line = txt_line + ch
            idx = idx + 1
        if len(txt_line) > 0:
            txt_line = ts_line + txt_line
        result += txt_line + '\n'

    return result[:-1]


def load_demucs_model(demucs_model, demucs_idx, device=None, verbose=False):
    # `model` is a bag of 4 models
    model = demucs_pretrained.get_model(demucs_model)
    verbose and print('Demucs model:', demucs_model, model.samplerate, demucs_idx,
                      model.models and len(model.models))
    if 0 <= demucs_idx < 4:
        model = model.models[demucs_idx]
    if device:
        model.to(device)
    model.eval()
    return model
