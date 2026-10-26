"""System prompts and prompt builders. Hard rules live here and are shared by every mode."""

from __future__ import annotations

from app.schemas import Classification, RetrievedChunk

HARD_RULES = """\
HARD RULES (never break them):
1. Never give trading advice: no buy/sell recommendations, signals, price predictions or targets,
   strategy or leverage suggestions. Factual account information quoted from the knowledge base
   (e.g. the maximum leverage offered) is allowed; recommending a value is not. Decline politely.
2. Never decide or predict the outcome of a complaint, KYC/verification or AML review, and never
   promise refunds or compensation. Acknowledge, say a specialist will review, and stop there.
3. Never invent policy, fees, limits, timelines, payment methods or procedures. Every factual
   statement must be supported by a quote from the provided knowledge-base excerpts. If the
   excerpts do not cover something, say it is not covered / an agent will confirm it."""

CLASSIFY_RULES = """\
Classify the customer ticket for a retail forex/CFD broker (Valetax).

Fields:
- category: main topic. deposit | withdrawal | account_opening | verification (KYC documents,
  identity/address proof, verification status) | trading_conditions (leverage, spreads, swaps,
  account types, instruments, and any trading-advice request) | platform_technical (MT4/MT5,
  app, login errors) | account_access (password, 2FA, locked/hacked account) | other.
- urgency: high = money appears lost/stuck beyond stated timelines, account blocked or
  compromised, customer cannot withdraw, or explicit escalation threats; medium = an
  in-progress transaction or verification the customer is waiting on; low = general
  information questions.
- language: ISO 639-1 code of the language the customer wrote in.
- sentiment: positive | neutral | negative (frustration, anger, distrust).
- trading_advice_request: asks what/when to buy or sell, for signals, forecasts, price targets,
  which leverage or lot size to use, or which strategy/instrument is best.
- complaint: dissatisfaction framed as a complaint or dispute, accusations of fraud/scam,
  demands for compensation, threats to go to a regulator/lawyer/social media.
- kyc_aml_decision_request: asks why verification/documents were rejected, asks to approve or
  speed up a verification decision, or concerns account restrictions, source-of-funds or AML
  checks.
- has_supportable_question: true if the ticket contains any support question besides a
  trading-advice request.
- search_query: a short standalone English query describing the support question(s), used to
  search the help-center knowledge base. Translate if needed.
- summary: one short English line for the support agent."""

DRAFT_RULES = """\
Draft a reply that a human support agent will review before sending.

Knowledge base: only the <chunk> excerpts in the user message. Each has an id.

Write the reply as an ordered list of segments (roughly one sentence each):
- kind "boilerplate": greeting, thanks, sign-off. No facts, no numbers.
- kind "claim": any statement of fact, policy, procedure, limit or timeline. MUST have at least
  one citation {chunk_id, quote} where quote is a short (5-25 words) span copied
  CHARACTER-FOR-CHARACTER from that chunk's text, in the chunk's original language (English),
  even when the reply is in another language. Do not paraphrase inside quote, do not fix typos.
- kind "unknown": states that a specific point is not covered by our help pages and the
  agent/team will confirm. No numbers, no guesses.
- kind "decline": politely declines a trading-advice request (we cannot provide investment
  advice; trading decisions are the customer's own).
- kind "handoff": says a specialist team will review the case. No outcome, no timeline.

Rules:
- Reply in the customer's language ({language}). Keep it short and practical.
- Answer only what the excerpts support. Partial coverage: answer the covered part with claims
  and add an "unknown" segment for the rest.
- Set abstain=true (segments=[]) only if the excerpts contain nothing relevant to the customer's
  support question. Give abstain_reason.
- If excerpts conflict (e.g. "instant" vs "within 60 minutes"), state the more conservative
  version, cite it, and mention the conflict in agent_note.
- Never mention internal ids, "chunks", "excerpts" or "knowledge base" in the reply text; to the
  customer these are "our help pages".
- agent_note: one or two short English sentences for the agent (gaps, conflicts, what to check
  in the back office). Empty string if nothing to add."""

CLASSIFY_SYSTEM = f"You are a support-ticket triage assistant.\n\n{CLASSIFY_RULES}\n\n{HARD_RULES}"

DRAFT_SYSTEM = f"You are a support co-pilot for Valetax, a retail forex/CFD broker.\n\n{DRAFT_RULES}\n\n{HARD_RULES}"

COMBINED_SYSTEM = (
    "You are a support co-pilot for Valetax, a retail forex/CFD broker. Return both the "
    "classification and the draft reply.\n\n"
    f"PART 1 - CLASSIFICATION\n{CLASSIFY_RULES}\n\nPART 2 - DRAFT\n"
    + DRAFT_RULES.replace("({language})", "(the language you detected in part 1)")
    + f"\n\n{HARD_RULES}"
)


def format_chunks(hits: list[RetrievedChunk]) -> str:
    if not hits:
        return "<no_relevant_excerpts/>"
    return "\n".join(
        f'<chunk id="{h.chunk.id}" pages="{" | ".join(h.chunk.page_titles)}">\n{h.chunk.text}\n</chunk>' for h in hits
    )


def classify_user(ticket: str) -> str:
    return f"<ticket>\n{ticket}\n</ticket>"


def draft_system(language: str) -> str:
    return DRAFT_SYSTEM.replace("{language}", language)


def draft_user(ticket: str, cls: Classification, hits: list[RetrievedChunk]) -> str:
    flags = [f for f in ("trading_advice_request", "complaint", "kyc_aml_decision_request") if getattr(cls, f)]
    return (
        f"<ticket>\n{ticket}\n</ticket>\n\n"
        f"<triage category=\"{cls.category}\" language=\"{cls.language}\" flags=\"{','.join(flags) or 'none'}\">"
        f"{cls.summary}</triage>\n\n"
        f"<knowledge_base>\n{format_chunks(hits)}\n</knowledge_base>"
    )


def combined_user(ticket: str, hits: list[RetrievedChunk]) -> str:
    return f"<ticket>\n{ticket}\n</ticket>\n\n<knowledge_base>\n{format_chunks(hits)}\n</knowledge_base>"


# Deterministic decline used in two_call mode when a ticket is *only* a trading-advice request,
# so no drafting call is spent. Keys: ISO 639-1. Unlisted languages fall back to English.
DECLINE_TEMPLATES = {
    "en": "Thank you for reaching out. We're not able to provide trading or investment advice, including buy/sell recommendations, signals, price forecasts or leverage suggestions; trading decisions remain your own. We're happy to help with anything related to your account, deposits, withdrawals or verification.",
    "es": "Gracias por contactarnos. No podemos ofrecer asesoramiento de trading o de inversión, incluidas recomendaciones de compra/venta, señales, previsiones de precios o sugerencias de apalancamiento; las decisiones de trading son suyas. Con gusto le ayudamos con su cuenta, depósitos, retiros o verificación.",
    "pt": "Obrigado pelo contato. Não podemos oferecer aconselhamento de trading ou investimento, incluindo recomendações de compra/venda, sinais, previsões de preço ou sugestões de alavancagem; as decisões de trading são suas. Teremos prazer em ajudar com sua conta, depósitos, saques ou verificação.",
    "fr": "Merci de nous avoir contactés. Nous ne pouvons pas fournir de conseils de trading ou d'investissement, y compris des recommandations d'achat/vente, des signaux, des prévisions de prix ou des suggestions d'effet de levier ; les décisions de trading vous appartiennent. Nous restons à votre disposition pour votre compte, vos dépôts, retraits ou votre vérification.",
    "ar": "شكرًا لتواصلك معنا. لا يمكننا تقديم نصائح تداول أو استثمار، بما في ذلك توصيات الشراء أو البيع أو الإشارات أو توقعات الأسعار أو اقتراحات الرافعة المالية؛ قرارات التداول تعود إليك. يسعدنا مساعدتك في كل ما يتعلق بحسابك أو الإيداع أو السحب أو التحقق.",
    "id": "Terima kasih telah menghubungi kami. Kami tidak dapat memberikan saran trading atau investasi, termasuk rekomendasi beli/jual, sinyal, prediksi harga, atau saran leverage; keputusan trading sepenuhnya milik Anda. Kami siap membantu terkait akun, deposit, penarikan, atau verifikasi Anda.",
    "ms": "Terima kasih kerana menghubungi kami. Kami tidak dapat memberikan nasihat dagangan atau pelaburan, termasuk cadangan beli/jual, isyarat, ramalan harga atau cadangan leverage; keputusan dagangan adalah milik anda. Kami sedia membantu berkaitan akaun, deposit, pengeluaran atau pengesahan anda.",
    "vi": "Cảm ơn bạn đã liên hệ. Chúng tôi không thể đưa ra lời khuyên giao dịch hoặc đầu tư, bao gồm khuyến nghị mua/bán, tín hiệu, dự báo giá hoặc gợi ý đòn bẩy; quyết định giao dịch là của bạn. Chúng tôi sẵn sàng hỗ trợ về tài khoản, nạp tiền, rút tiền hoặc xác minh.",
    "ru": "Спасибо за обращение. Мы не можем давать торговые или инвестиционные рекомендации, включая советы покупать/продавать, сигналы, прогнозы цен или выбор кредитного плеча; торговые решения остаются за вами. Будем рады помочь с вопросами по счёту, пополнению, выводу средств или верификации.",
    "th": "ขอบคุณที่ติดต่อเรา เราไม่สามารถให้คำแนะนำด้านการเทรดหรือการลงทุน รวมถึงคำแนะนำซื้อ/ขาย สัญญาณ การคาดการณ์ราคา หรือการแนะนำเลเวอเรจ การตัดสินใจเทรดเป็นของคุณเอง เรายินดีช่วยเหลือเรื่องบัญชี การฝาก การถอน หรือการยืนยันตัวตน",
    "hi": "संपर्क करने के लिए धन्यवाद। हम ट्रेडिंग या निवेश सलाह नहीं दे सकते, जिसमें खरीद/बिक्री की सिफारिशें, सिग्नल, मूल्य पूर्वानुमान या लीवरेज सुझाव शामिल हैं; ट्रेडिंग निर्णय आपके अपने हैं। हम आपके खाते, जमा, निकासी या सत्यापन से जुड़ी किसी भी मदद के लिए तैयार हैं।",
}
