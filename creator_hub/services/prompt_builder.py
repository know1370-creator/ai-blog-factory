"""
MI Creator OS
Prompt Builder
"""

from .ai_engine import AIRequest


class PromptBuilder:

    @staticmethod
    def build(request: AIRequest) -> str:

        return f"""
당신은 MI Creator OS의 전문 콘텐츠 AI입니다.

## 브랜드
{request.brand}

## 콘텐츠 종류
{request.content_type}

## 주제
{request.topic}

## 말투
{request.tone}

## 키워드
{", ".join(request.keywords)}

## 작업

브랜드에 맞는 최고의 콘텐츠를 작성하세요.

반드시 콘텐츠 종류 형식에 맞게 작성하세요.

퀄리티는 전문가 수준으로 작성하세요.
"""