# https://modelpredict.com/language-identification-survey#benchmarked-libraries
# import pycld2 as cld2  # great speed, but inaccurate
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger("phonetize")
_resource_lock = threading.RLock()
_kks = None
_fasttext_model = None
_lid_model_path = Path(__file__).resolve().parents[1] / "lid.176.ftz"


def _script_language(txt):
    if re.search('[\u30a0-\u30ff\u3040-\u309f]+', txt):
        return '__label__ja'
    if re.search('[\u4e00-\u9fa5]+', txt):
        return '__label__zh'
    if re.search('[\uac00-\ud7ff]+', txt):
        return '__label__ko'
    if re.search('[\u0400-\u04FF]+', txt):
        return '__label__ru'
    return None


def _get_kakasi():
    global _kks
    with _resource_lock:
        if _kks is None:
            import pykakasi  # ATTENTION: GPL licensed

            _kks = pykakasi.kakasi()
        return _kks


def _get_fasttext_model():
    global _fasttext_model
    with _resource_lock:
        if _fasttext_model is None:
            import fasttext

            _fasttext_model = fasttext.load_model(str(_lid_model_path))
        return _fasttext_model


def configure_lid_model(path):
    """Configure the local LID asset before the first non-script detection."""

    global _fasttext_model, _lid_model_path
    resolved = Path(path).expanduser().resolve()
    with _resource_lock:
        if _fasttext_model is not None and resolved != _lid_model_path:
            raise RuntimeError("The fastText LID model is already initialized.")
        _lid_model_path = resolved


def phonetize(ch, *, language_detector=None, kakasi_provider=None):
    """
    暂时只识别：zh,ja,ko,en
    :return: 返回数组[(word, phone), ...], 且转换后的phone只包含a-z'~字串
    [('拼', 'pin'), ('音', 'yin'), ('123', '123'), ('english !', 'english !')]
    ['igeoseun', 'je', 'geosi', 'anieyo.imyeongssiui', 'geosieyo.'];
    若无法识别语言，返回[]
    """
    ch = q2bs(ch)  # 全角转半角

    # 先识别语言，再分别转读音
    if ch.isascii():  # 纯ascii或空str，直接返回
        return [(ch, ch)]

    # help(cld2.detect)
    # reliable, _, details = cld2.detect(ch, isPlainText=True, returnVectors=False,
    #                                    hintLanguageHTTPHeaders='zh,ja,ko,en,ru')
    lang_result = (language_detector or detect_language)(ch)

    # 暂时只取1种语言
    ret = []
    if lang_result == '__label__zh':
        from pypinyin import lazy_pinyin

        # 对hhh h234 对冯绍峰撒发!fds dui地方
        ret = lazy_pinyin(ch)
        ret = convertPairsPinyin(ch, ret)
    elif lang_result == '__label__en':
        ret, phs, idx = [], ch.split(), 0
        for ii, ph in enumerate(phs):
            idx1  = ch.find(phs[ii + 1], idx+len(ph)) if ii < len(phs) - 1 else None
            ret.append((ch[idx:idx1], ph))
            idx = idx1
    elif lang_result == '__label__ja':
        # おはようごぎ.い!ます. thank you 123! ohayougogi. かな漢字交じり文.: 'ohayougogi.', 'i!', 'masu.', ' thank you 123!', 'kana', 'kanji', 'majiri', 'bun.'
        ret = (kakasi_provider or _get_kakasi)().convert(ch)
        ret = convertPairsJp(ret)
    elif lang_result == '__label__ko':
        import kroman

        # 이것은 제 것이 아니에요.이명씨의 것이에요. thank-you 123: i-geos-eun je geos-i a-ni-e-yo.i-myeong-ssi-eui geos-i-e-yo. thank-you 123 geos je
        ret = kroman.parse(ch)
        ret = convertPairsKorean(ch, ret)
    elif lang_result == '__label__ru':
        import cyrtranslit

        # Моё судно на воздушной подушке полно угрей
        ret = cyrtranslit.to_latin(ch)
        ret = convertPairsRussian(ch, ret)
    else:
        logger.error('Unsupported language detect: %s, %s', lang_result, ch)
    return ret


def detect_language(txt, *, model_provider=None):
    # 先正则匹配cjk
    script_result = _script_language(txt)
    if script_result is not None:
        return script_result

    lang_result = (model_provider or _get_fasttext_model)().predict(
        txt, k=1)  # (('__label__en',), (0.95,))
    if len(lang_result[-1]) == 0 or lang_result[-1][0] < 0.5:
        logger.warning('unreliable language detect: %s, details=%s',
                    lang_result, txt)
    return lang_result[0][0] if len(lang_result[0]) > 0 else 'un'


class PhoneticConverter:
    """Runtime-scoped, lazy language resources for isolated v2 runtimes."""

    def __init__(
        self,
        lid_model_path,
        *,
        fasttext_loader=None,
        kakasi_factory=None,
        asset_owner=None,
    ):
        self._lid_model_path = Path(lid_model_path).expanduser().resolve()
        self._asset_owner = asset_owner
        self._fasttext_loader = fasttext_loader or self._load_fasttext
        self._kakasi_factory = kakasi_factory or self._load_kakasi
        self._fasttext_model = None
        self._kakasi = None
        self._fasttext_failure = None
        self._kakasi_failure = None
        self._lock = threading.RLock()

    @staticmethod
    def _load_fasttext(path):
        import fasttext

        return fasttext.load_model(str(path))

    @staticmethod
    def _load_kakasi():
        import pykakasi  # ATTENTION: GPL licensed

        return pykakasi.kakasi()

    def _model(self):
        with self._lock:
            if self._fasttext_model is None:
                if self._fasttext_failure is not None:
                    raise self._fasttext_failure
                try:
                    self._fasttext_model = self._fasttext_loader(self._lid_model_path)
                except Exception as exc:
                    self._fasttext_failure = exc
                    raise
            return self._fasttext_model

    def _kakasi_provider(self):
        with self._lock:
            if self._kakasi is None:
                if self._kakasi_failure is not None:
                    raise self._kakasi_failure
                try:
                    self._kakasi = self._kakasi_factory()
                except Exception as exc:
                    self._kakasi_failure = exc
                    raise
            return self._kakasi

    def detect_language(self, txt):
        # fastText's Python binding does not publish a per-instance concurrent
        # call contract.  Keep both initialization and prediction inside the
        # runtime-local lock so one runtime cannot expose a half-initialized or
        # concurrently-mutated provider.  Distinct runtimes intentionally keep
        # distinct locks and may still make progress in parallel.
        with self._lock:
            return detect_language(txt, model_provider=self._model)

    def phonetize(self, text):
        # pykakasi converters are likewise runtime-owned and conservatively
        # serialized until their upstream call-time thread-safety is qualified.
        # RLock is required because phonetize() re-enters detect_language() and
        # the lazy provider accessors.
        with self._lock:
            return phonetize(
                text,
                language_detector=self.detect_language,
                kakasi_provider=self._kakasi_provider,
            )


def convertPairsJp(phones):
    """
    标点排除在phone外
    おはようごぎ.い!ます. thank you 123!かな漢字交じり文.: 'ohayougogi.', 'i!', 'masu.', ' thank you 123!', 'kana', 'kanji', 'majiri', 'bun.'
    :returns: [('おはようごぎ.', 'ohayougogi'), ('い!', 'i'), ('ます.', 'masu'), (' thank you 123!', ' thank you 123!'), ('かな', 'kana'), ('漢字', 'kanji'), ('交じり', 'majiri'), ('文.', 'bun')]
    """
    ret = []
    for item in phones:
        wd, ph = item['orig'], item['hepburn']
        if wd != ph and re.search("[^a-z'~]", ph):
            ph = re.sub("[^a-z'~]", '', ph)
        ret.append((wd, ph))
    return ret


def convertPairsKorean(words, phones):
    """
    convertPairsKorean('ilove이것은 제 것이 아니에요...이명씨의 것이에요. thank-you 123 geos je', 'ilovei-geos-eun je geos-i a-ni-e-yo...i-myeong-ssi-eui geos-i-e-yo. thank-you 123')
    :returns: [('ilove', 'ilove'), ('이', 'i'), ('것', 'geos'), ('은', 'eun'), (' 제', 'je'), (' 것', 'geos'), ('이', 'i'), (' 아', 'a'), ('니', 'ni'), ('에', 'e'), ('요', 'yo'), ('...', '...'), ('이', 'i'), ('명', 'myeong'), ('씨', 'ssi'), ('의', 'eui'), (' 것', 'geos'), ('이', 'i'), ('에', 'e'), ('요', 'yo'), ('. thank-you 123', '. thank-you 123')]
    """
    ret, idx0, wd = [], 0, ''
    for ii, ch in enumerate(words):
        # print(ii, ch, idx0, wd)
        idx1 = phones.find(ch, idx0)
        if idx1 < 0:  # korean
            if len(wd) > 0:
                if len(wd.strip()) <= 0:
                    ch = wd + ch
                else:
                    ret.append((wd, wd))
                wd = ''
            chn = words[ii + 1] if ii < len(words) - 1 else ''
            idx2 = phones.find(chn, idx0+1)
            idx1 = phones.find('-', idx0) if idx2 < 0 else idx2
            ret.append((ch, phones[idx0: None if chn == '' else idx1]))
            idx0 = idx1 + (1 if idx2 < 0 else 0)
        else:
            idx1 += 1
            wd += phones[idx0:idx1]
            idx0 = idx1
    if len(wd) > 0:
        ret.append((wd, wd))
    return ret


def convertPairsPinyin(words, phones):
    """
    convertPairsPinyin('hhh h234 对冯绍峰撒发!fds dui地方', ['hhh h234 ', 'dui', 'feng', 'shao', 'feng', 'sa', 'fa', '!fds dui', 'di', 'fang'])
    """
    ret, idx0 = [], 0
    for ph in phones:
        idx1 = idx0 + len(ph)
        if words[idx0:idx1] == ph:
            ret.append((ph, ph))
            idx0 = idx1
        else:  # pinyin
            ret.append((words[idx0], ph))
            idx0 += 1
    return ret


def convertPairsRussian(words, phones):
    """
    convertPairsRussian()
    """
    ret, phs, chs = [], phones.split(' '), words.split(' ')
    for ii, ph in enumerate(phs):
        if  ii < len(phs):
            ret.append((chs[ii], ph))

    return ret

def q2bs(unicode_str):
    """ 全角转半角
    q2bs("电影《2012》讲述了2012年12月21日的世界末日,主人公Jack以及世界各国人民挣扎求生的经历!。“f”·1‘’－【（）")
    """
    return "".join(map(q2b, unicode_str))


def q2b(ch):
    """ 全角转半角"""
    od = ord(ch)
    if od == 12288:
        return ' '
    elif od == 12289:  # 、
        return ','
    elif od == 12290:
        return '.'
    elif od == 12298:
        return '<'
    elif od == 12299:
        return '>'
    elif od == 12304:
        return '['
    elif od == 12305:
        return ']'
    elif od == 8212:
        return '-'
    elif od == 183:
        return '`'
    elif od == 8221 or od == 8220:
        return '"'
    elif od == 8216 or od == 8217:
        return "'"
    elif 65281 <= od <= 65374:
        return chr(od - 65248)
    return ch


if __name__ == '__main__':
    import cyrtranslit
    import kroman
    from pypinyin import lazy_pinyin

    ch = '对hhh h234 对冯绍峰撒发!fds dui地方'
    ret = lazy_pinyin(ch)
    ret = convertPairsPinyin(ch, ret)
    print(ret)
    ch = '것은 제 것이 아니에요.이명씨의 것이에요. thank-you 123 geos je'
    ret = kroman.parse(ch)
    ret = convertPairsKorean(ch, ret)
    print(ret)
    ch = 'おはようごぎ.い!ます. thank you 123! ohayougogi. かな漢字交じり文.'
    ret = _get_kakasi().convert(ch)
    ret = convertPairsJp(ret)
    print(ret)
    ch = 'Моё'
    ret = cyrtranslit.to_latin(ch)
    ret = convertPairsRussian(ch, ret)
    print(ret)
    
