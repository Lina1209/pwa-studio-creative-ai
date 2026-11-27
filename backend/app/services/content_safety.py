"""First-layer text safety checks for PWA Studio generation endpoints.

This is a conservative keyword/pattern guard, not a complete moderation system.
Image/video moderation, reports, appeals and human review remain separate work.
"""
import re

from fastapi import HTTPException

_BLOCK_PATTERNS = [
    # Sexual exploitation of minors.
    re.compile(r"(?:child|minor|underage|несовершеннолетн\w*|реб[её]нок|дет[ияей])[^.\n]{0,90}(?:sex|sexual|nude|эрот|сексуал|обнаж)", re.I),
    re.compile(r"(?:sex|sexual|nude|эрот|сексуал|обнаж)[^.\n]{0,90}(?:child|minor|underage|несовершеннолетн\w*|реб[её]нок|дет[ияей])", re.I),
    # Non-consensual intimate imagery / impersonation.
    re.compile(r"(?:без согласия|without consent|revenge porn|интимн\w* фото)[^.\n]{0,100}(?:реальн\w* человек|real person|бывш\w*|сосед|коллег)", re.I),
    # Explicit operational harm instructions.
    re.compile(r"(?:как|how to)\s+(?:сделать|изготовить|собрать|build|make)\s+(?:бомб\w*|взрывчат\w*|оружи\w*|яд\w*|вирус\w*|malware|bomb|explosive|poison|weapon)", re.I),
    re.compile(r"(?:как|how to)\s+(?:покончить с собой|совершить самоубийство|убить человека|избежать полиции|обойти защиту|commit suicide|kill someone|evade law enforcement)", re.I),
    re.compile(r"(?:украсть пароль|steal passwords|фишинг для кражи|credential theft|вымогательское ПО|ransomware deployment)", re.I),
]


def check_content(text: str) -> None:
    """Reject clearly disallowed requests before forwarding them to an AI provider."""
    for pattern in _BLOCK_PATTERNS:
        if pattern.search(text):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Запрос не может быть обработан: он может нарушать правила "
                    "безопасности PWA Studio. Измените запрос на безопасный вариант."
                ),
            )


def check_prompt_content(idea: str, purpose: str, language: str, style: str | None) -> None:
    """Validate every user-controlled field that is forwarded in a prompt request."""
    for value in (idea, purpose, language, style or ""):
        check_content(value)
