from __future__ import annotations
from enum import Enum


class Language(Enum):
    ORIGINAL        = ("Original Language", [])  # uses the language of the first audio track
    ENGLISH         = ("English",           ["eng"])
    NON_ENGLISH     = ("Non-English",       [])  # picks first non-English track
    KOREAN          = ("Korean",            ["kor"])
    JAPANESE   = ("Japanese",   ["jpn"])
    THAI       = ("Thai",       ["tha"])
    VIETNAMESE = ("Vietnamese", ["vie"])
    FRENCH     = ("French",     ["fra"])
    GERMAN     = ("German",     ["deu", "ger"])
    ITALIAN    = ("Italian",    ["ita"])
    SPANISH    = ("Spanish",    ["spa"])
    DUTCH      = ("Dutch",      ["nld", "dut"])
    PORTUGUESE = ("Portuguese", ["por"])
    CHINESE    = ("Chinese",    ["zho", "chi"])
    POLISH     = ("Polish",     ["pol"])
    DANISH     = ("Danish",     ["dan"])
    SWEDISH    = ("Swedish",    ["swe"])
    FINNISH    = ("Finnish",    ["fin"])
    NORWEGIAN  = ("Norwegian",  ["nor"])

    def __init__(self, label: str, codes: list[str]):
        self.label = label
        self.codes = codes

    def matches(self, code: str) -> bool:
        return code in self.codes

    @classmethod
    def from_label(cls, label: str, default: "Language" = None) -> "Language":
        for lang in cls:
            if lang.label == label:
                return lang
        return default if default is not None else cls.ENGLISH

    @classmethod
    def labels(cls) -> list[str]:
        return [lang.label for lang in cls]
