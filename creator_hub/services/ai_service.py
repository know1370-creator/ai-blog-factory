"""
MI Creator OS AI Service
"""

from .ai_engine import AIEngine
from .prompt_builder import PromptBuilder

# 기존 GPT 생성 함수 사용
from ..legacy_app import generate_article


class AIService:

    def __init__(self):
        self.engine = AIEngine()

    def build_prompt(self, prompt: str):
        analysis = self.engine.analyze(prompt)
        return PromptBuilder.build(analysis)

    # ⭐ 새로 추가
    def generate(
        self,
        topic,
        brand_style,
        article_type,
        length,
        audience,
        notes,
    ):

        # AI 분석
        analysis = self.engine.analyze(topic)

        # 프롬프트 생성
        prompt = PromptBuilder.build(analysis)

        print("=" * 60)
        print("AI Prompt")
        print(prompt)
        print("=" * 60)

        # 기존 GPT 생성기 호출
        return generate_article(
            keyword=topic,
            brand_style=brand_style,
            article_type=article_type,
            length=length,
            audience=audience,
            notes=notes,
        )