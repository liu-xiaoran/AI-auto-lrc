from pathlib import Path

import pytest

from t2l import phonetic


def test_ascii_phonetize_needs_no_optional_language_resources(monkeypatch):
    monkeypatch.setattr(
        phonetic,
        "_get_fasttext_model",
        lambda: (_ for _ in ()).throw(AssertionError("LID must stay lazy")),
    )
    monkeypatch.setattr(
        phonetic,
        "_get_kakasi",
        lambda: (_ for _ in ()).throw(AssertionError("kakasi must stay lazy")),
    )

    assert phonetic.phonetize("hello world") == [("hello world", "hello world")]


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("かな漢字", "__label__ja"),
        ("中文한글", "__label__zh"),
        ("한글Русский", "__label__ko"),
        ("Русский", "__label__ru"),
    ],
)
def test_script_routes_do_not_load_fasttext(monkeypatch, text, label):
    monkeypatch.setattr(
        phonetic,
        "_get_fasttext_model",
        lambda: (_ for _ in ()).throw(AssertionError("fastText must stay lazy")),
    )

    assert phonetic.detect_language(text) == label


def test_default_lid_path_is_not_relative_to_cwd():
    assert phonetic._lid_model_path == (
        Path(phonetic.__file__).resolve().parents[1] / "lid.176.ftz"
    )


def test_lid_path_cannot_change_after_model_initialization(monkeypatch, tmp_path):
    monkeypatch.setattr(phonetic, "_fasttext_model", object())
    monkeypatch.setattr(phonetic, "_lid_model_path", tmp_path / "one.ftz")

    with pytest.raises(RuntimeError, match="already initialized"):
        phonetic.configure_lid_model(tmp_path / "two.ftz")


def test_runtime_scoped_converters_load_and_cache_independently(tmp_path):
    calls = []

    class Model:
        def __init__(self, label):
            self.label = label

        def predict(self, text, k):
            return ((self.label,), (0.99,))

    def loader(path):
        calls.append(path)
        return Model("__label__en")

    first = phonetic.PhoneticConverter(tmp_path / "one.ftz", fasttext_loader=loader)
    second = phonetic.PhoneticConverter(tmp_path / "two.ftz", fasttext_loader=loader)

    assert first.detect_language("bonjour") == "__label__en"
    assert first.detect_language("again") == "__label__en"
    assert second.detect_language("bonjour") == "__label__en"
    assert calls == [
        (tmp_path / "one.ftz").resolve(),
        (tmp_path / "two.ftz").resolve(),
    ]
