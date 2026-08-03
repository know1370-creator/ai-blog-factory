"""
MI Creator OS - AI Engine
사용자 입력을 분석하여 브랜드, 콘텐츠 형식, 주제 등을 추출한다.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class AIRequest:
    original_prompt: str
    brand: str
    content_type: str
    topic: str
    tone: str
    keywords: List[str]


class AIEngine:

    BRAND_RULES = {
        "말썽쟁이딸": "말썽쟁이 딸랑구",
        "딸": "말썽쟁이 딸랑구",
        "육아": "말썽쟁이 딸랑구",

        "보험": "보험",

        "애터미": "애터미",

        "쿠팡": "쿠팡",

        "미우": "미우와 웅이",
        "웅이": "미우와 웅이",
    }

    CONTENT_RULES = {
        "릴스": "릴스",
        "인스타툰": "인스타툰",
        "블로그": "블로그",
        "쇼츠": "쇼츠",
        "threads": "Threads",
        "쓰레드": "Threads",
    }

    TONE_RULES = {
        "웃긴": "유머",
        "유머": "유머",
        "감동": "감동",
        "감성": "감성",
        "전문": "전문",
    }

    def analyze(self, prompt: str) -> AIRequest:

        prompt = prompt.strip()

        brand = self._find_brand(prompt)
        content = self._find_content(prompt)
        tone = self._find_tone(prompt)

        return AIRequest(
            original_prompt=prompt,
            brand=brand,
            content_type=content,
            topic=prompt,
            tone=tone,
            keywords=self._keywords(prompt),
        )

    def _find_brand(self, text: str) -> str:

        for key, value in self.BRAND_RULES.items():
            if key in text:
                return value

        return "일반"

    def _find_content(self, text: str) -> str:

        for key, value in self.CONTENT_RULES.items():
            if key.lower() in text.lower():
                return value

        return "자동"

    def _find_tone(self, text: str) -> str:

        for key, value in self.TONE_RULES.items():
            if key in text:
                return value

        return "일반"

    def _keywords(self, text: str):

        words = []

        for word in text.split():

            word = word.strip()

            if len(word) >= 2:
                words.append(word)

        return list(dict.fromkeys(words))