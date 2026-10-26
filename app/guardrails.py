"""Cheap deterministic guards that complement the LLM.

pre_screen: multilingual keyword patterns on the incoming ticket. Hits are OR-ed with the LLM
flags (we optimise recall on must-route / must-decline cases; false positives only cost an extra
human look).
output_violations: patterns that must never appear in a draft (trading advice, deciding a
complaint/KYC/AML outcome, promising refunds).
"""

from __future__ import annotations

import re

_I = re.IGNORECASE | re.UNICODE

PRE_PATTERNS: dict[str, list[str]] = {
    "trading_advice": [
        r"\bshould i (buy|sell|go long|go short|open|close|hold)\b",
        r"\b(buy|sell) or (buy|sell|hold|wait)\b",
        r"\b(trading |forex |gold |crypto )?signals?\b",
        r"\bprice (target|prediction|forecast)s?\b",
        r"\b(will|is) (gold|xau|eur/?usd|gbp/?usd|usd/?jpy|btc|bitcoin|oil|nasdaq|the market)\b.{0,40}\b(go|going|rise|fall|drop|pump|up|down)\b",
        r"\bwhat (leverage|lot size) should i\b",
        r"\b(which|best|recommended|good) (leverage|lot size)\b",
        r"\b(best|good|profitable) (pair|instrument|strategy|trade) to\b",
        r"\b(comprar|vender) o (vender|comprar|esperar)\b",
        r"\bse(ñ|n)ales? de trading\b",
        r"\b(beli|jual) (atau|apa) (jual|beli)\b",
        r"\bsinyal (trading|forex)\b",
        r"(شراء|أشتري).{0,15}(بيع|أبيع)",
        r"توصيات? (تداول|شراء)",
        r"\b(купить|покупать) или (продать|продавать)\b",
        r"\bсигнал(ы)? (на|по)\b",
        r"\b(acheter|vendre) ou (vendre|acheter)\b",
        r"\bmua hay bán\b",
    ],
    "complaint": [
        r"\b(complain|complaint|scam|scammer|fraud|fraudulent|steal|stole|stolen|thie(f|ves)|cheat(ed|ing)?)\b",
        r"\b(regulator|ombudsman|lawyer|legal action|sue you|police|chargeback|report you)\b",
        r"\b(refund|compensat(e|ion)) (me|my)\b",
        r"\b(estafa|fraude|robo|reclamaci(ó|o)n|queja|abogado)\b",
        r"\b(penipuan|penipu|tipu|keluhan|komplain)\b",
        r"(احتيال|نصب|شكوى|محامي|سرقة)",
        r"\b(мошенни\w*|жалоб\w*|обман\w*|верните деньги)\b",
        r"\b(arnaque|escroquerie|plainte|voleurs?)\b",
        r"\b(lừa đảo|khiếu nại)\b",
    ],
    "kyc_aml": [
        r"\b(verification|kyc|documents?|account)\b.{0,30}\b(rejected|declined|refused|failed|denied|blocked|frozen|suspended|restricted)\b",
        r"\b(rejected|declined|blocked|frozen|suspended|restricted)\b.{0,30}\b(verification|kyc|documents?|account)\b",
        r"\b(aml|anti[- ]money|source of (funds|wealth)|money laundering|compliance (team|check|review))\b",
        r"\bwhy (was|is) my (account|verification|kyc)\b",
        r"\b(verificaci(ó|o)n|cuenta)\b.{0,30}\b(rechazad[ao]|bloquead[ao]|congelad[ao])\b",
        r"\b(verifikasi|akun)\b.{0,30}\b(ditolak|diblokir|dibekukan)\b",
        r"(رفض|حظر|تجميد).{0,30}(التحقق|الحساب|المستندات)",
        r"\b(верификац\w*|аккаунт|сч(е|ё)т)\b.{0,30}\b(отклон\w*|заблокир\w*|заморож\w*)\b",
    ],
}

OUTPUT_PATTERNS: dict[str, list[str]] = {
    "trading advice in draft": [
        r"\b(you should|we recommend|i recommend|i suggest|we suggest|consider)\b.{0,40}\b(buy|sell|going long|going short|leverage of|1:\d+)\b",
        r"\b(buy|sell) (signal|now|at)\b",
        r"\bprice target\b",
    ],
    "decides KYC/AML/complaint outcome": [
        r"\b(your )?(account|verification|documents?|kyc)\b.{0,25}\b(has|have) been (approved|verified|rejected|declined|unblocked|blocked)\b",
        r"\bwe (will|have) (refund|compensate|reimburse)\b",
        r"\byou will (be refunded|be compensated|receive a refund)\b",
        r"\byour complaint (is|has been) (resolved|rejected|upheld|dismissed)\b",
    ],
}

_PRE = {k: [re.compile(p, _I) for p in v] for k, v in PRE_PATTERNS.items()}
_OUT = {k: [re.compile(p, _I) for p in v] for k, v in OUTPUT_PATTERNS.items()}


def pre_screen(ticket: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for flag, patterns in _PRE.items():
        found = [m.group(0) for p in patterns if (m := p.search(ticket))]
        if found:
            hits[flag] = found
    return hits


# "Once your account has been verified, you can trade" describes a process, not an outcome.
_CONDITIONAL = re.compile(r"\b(once|when|after|if|until|as soon as)\s+(\w+\s+){0,2}$", _I)


# "We cannot provide a BUY signal" is a decline, not advice.
_NEGATED = re.compile(r"\b(cannot|can't|can not|unable|not able|won't|will not|do not|don't|never|no)\b", _I)


def output_violations(text: str) -> list[str]:
    found = []
    for name, patterns in _OUT.items():
        for p in patterns:
            for m in p.finditer(text):
                before = text[max(0, m.start() - 60):m.start()]
                if _CONDITIONAL.search(before[-30:]) or _NEGATED.search(before):
                    continue
                found.append(f"{name}: '{m.group(0)}'")
                break
    return found
