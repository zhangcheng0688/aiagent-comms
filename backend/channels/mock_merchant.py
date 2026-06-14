"""Mock 商家自动回复：V1.2 增强版。

升级点：
- 接受"链式反提案"和"增值让步"后会模拟让步
- 用 scenario 决定回复语种 + 风格
- 对不同策略关键词有差异化回复（让步/拒绝/沉默）
"""
from __future__ import annotations
import random


HOTEL_REPLIES = {
    "en": {
        "greeting": "Front desk, this is Sarah speaking. How can I help you?",
        "info_breakfast": "Yes, our standard rate includes buffet breakfast from 6:30 to 10 AM.",
        "info_breakfast_negative": "Breakfast is not included in your current rate, but you can add it for 2,800 yen per person per day.",
        "info_parking": "We have on-site parking for 1,500 yen per night, subject to availability.",
        "info_checkin": "Check-in is from 3 PM and check-out is by 11 AM.",
        "modify_date": "Let me check availability for June 12... Yes, we can shift your booking. The room rate for that night is the same.",
        "modify_date_upgrade": "I'm sorry, the twin room is fully booked for June 12. We only have a deluxe room available at an additional 4,800 yen per night. Would that work?",
        "cancel_easy": "Sure, I can cancel that for you. You'll receive a full refund within 5-7 business days. May I have your booking reference?",
        "cancel_penalty": "Since this is within the cancellation window, there's a 30% fee. The remaining amount will be refunded. Is that acceptable?",
        "extra_bed": "Adding an extra bed is 3,500 yen per night. Shall I add that to your reservation?",
        # V1.2: 对让步策略的回复
        "concede_hold": "I understand your budget concern. Let me see if I can offer a 5% discount on the deluxe room as a one-time courtesy.",
        "concede_alt_date": "June 14 has availability for the twin room at the original rate. Would that work for you?",
        "concede_value_trade": "If you add the breakfast package for both nights, I can keep the room rate at the original price. Deal?",
        "concede_chain_offer": "Bundling dinner for three nights plus the upgrade—that works out the same total. Let me update your reservation.",
        "concede_loyalty": "We do have a returning guest program. I can apply a 10% loyalty discount to your booking.",
        "concede_walkaway": "Understood, I appreciate your time. Have a great day.",
        "fallback": "Could you repeat that please?",
    },
    "ja": {
        "greeting": "フロント、佐藤が対応いたします。どのようなご用件でしょうか。",
        "info_breakfast": "はい、ご朝食は6時半から10時までビュッフェ形式でご利用いただけます。",
        "info_breakfast_negative": "恐れ入りますが、現在のご予約プランには朝食は含まれておりません。追加は1名様1泊2,800円で承ります。",
        "info_parking": "駐車場は1泊1,500円でご利用可能ですが、空き状況によります。",
        "info_checkin": "チェックインは15時、チェックアウトは11時となっております。",
        "modify_date": "6月12日の空き状況を確認いたします…はい、ご変更可能です。お部屋代も同じでございます。",
        "modify_date_upgrade": "申し訳ございません。6月12日のツインルームは満室でございます。デラックスルームでしたら、追加料金1泊4,800円でご用意できますが、いかがでしょうか。",
        "cancel_easy": "はい、承知いたしました。キャンセル手続きをさせていただきます。5〜7営業日以内に全額返金いたします。",
        "cancel_penalty": "キャンセル期限内ですので、30%の手数料が発生いたします。残額をご返金いたしますが、よろしいでしょうか。",
        "extra_bed": "エキストラベッドは1泊3,500円でご利用いただけます。",
        "concede_hold": "ご予算の事情、承知いたしました。デラックスルームですが、1回限りのご優待として5%割引を適用できるかもしれません。",
        "concede_alt_date": "6月14日はツインルームの空室がございます。元の料金でご案内可能です。いかがでしょうか。",
        "concede_value_trade": "2泊分の朝食パッケージを追加でご利用いただければ、お部屋代は元のまま据え置きできます。いかがでしょうか。",
        "concede_chain_offer": "3泊分の夕食とアップグレードの組み合わせで、合計金額は同じになります。予約を更新いたしますね。",
        "concede_loyalty": "申し訳ありませんが、当ホテルには会員プログラムがございません。新規プランのご案内となりますがいかがでしょうか。",
        "concede_walkaway": "承知いたしました。お時間いただきありがとうございました。失礼いたします。",
        "fallback": "恐れ入りますが、もう一度おっしゃっていただけますでしょうか。",
    },
    "ko": {
        "greeting": "프론트데스크 김입니다. 무엇을 도와드릴까요?",
        "info_breakfast": "네, 조식은 6시 30분부터 10시까지 뷔페로 제공됩니다.",
        "info_breakfast_negative": "죄송하지만, 현재 예약 요금제에는 조식이 포함되어 있지 않습니다. 추가 시 1인 1박 2,800원입니다.",
        "info_parking": "주차는 1박 1,500원이며, 이용 가능 여부에 따라 달라집니다.",
        "info_checkin": "체크인은 15시부터, 체크아웃은 11시까지입니다.",
        "modify_date": "6월 12일 예약 가능 여부를 확인하겠습니다... 네, 변경 가능합니다. 객실 요금은 동일합니다.",
        "modify_date_upgrade": "죄송합니다. 6월 12일 트윈룸은 만실입니다. 디럭스룸은 1박 4,800원 추가 요금으로 가능하시겠습니까?",
        "cancel_easy": "네, 취소 처리해 드리겠습니다. 영업일 기준 5-7일 내 전액 환불됩니다.",
        "cancel_penalty": "취소 기간 내이므로 30% 수수료가 발생합니다.",
        "extra_bed": "엑스트라 베드는 1박 3,500원입니다.",
        "concede_hold": "예산 상황을 이해합니다. 디럭스룸에 1회 한정으로 5% 할인을 적용할 수 있을 것 같습니다.",
        "concede_alt_date": "6월 14일에 트윈룸 빈 객실이 있습니다. 원래 요금으로 안내 가능합니다. 괜찮으시겠어요?",
        "concede_value_trade": "2박 조식 패키지를 추가하시면 객실 요금은 원래 가격으로 유지됩니다. 어떻습니까?",
        "concede_chain_offer": "3박 디너와 업그레이드를 묶으면 총액은 동일합니다. 예약을 업데이트하겠습니다.",
        "concede_loyalty": "죄송하지만, 저희 호텔에는 멤버십 프로그램이 없습니다.",
        "concede_walkaway": "알겠습니다. 시간 내주셔서 감사합니다. 안녕히 가세요.",
        "fallback": "다시 한 번 말씀해 주실 수 있을까요?",
    },
}


CAR_RENTAL_REPLIES = {
    "en": {
        "greeting": "Thank you for calling Hertz Reservations. This is Mike, how can I help?",
        "car_type_economy": "We have a Toyota Corolla available at 5,800 yen per day, unlimited mileage.",
        "car_type_upgrade": "The economy class is sold out for those dates. We only have a compact SUV at 8,200 yen per day. Would that work?",
        "pickup_date": "Pickup is available at Kansai Airport Terminal 1, between 8 AM and 10 PM.",
        "return_date": "Return by the same time on June 16 is fine. There's a one-way surcharge if you're returning to a different location.",
        "pickup_location": "Our airport counter opens at 7 AM. We also offer hotel delivery within Osaka for 3,000 yen.",
        "one_way_surcharge": "Returning to Tokyo would be a 15,000 yen one-way fee. Alternatively, we have a location near your Osaka hotel.",
        "insurance_cdw": "We include Collision Damage Waiver (CDW) at no extra cost. Full coverage with zero deductible is 1,800 yen per day.",
        "insurance_full": "Full coverage with zero deductible is 1,800 yen per day, in addition to the base rate.",
        "license_idp": "You'll need a valid driver's license and an International Driving Permit (IDP). Chinese licenses are not accepted in Japan without an IDP.",
        "mileage": "Unlimited mileage is included for rentals within Honshu. Hokkaido and Kyushu have a 200 km per day limit.",
        "extra_driver": "Adding a second driver is 1,500 yen per day. Both drivers must present their licenses at pickup.",
        "concede_hold": "Let me see if I can waive the one-way fee as a one-time courtesy.",
        "concede_alt_date": "We have a Corolla available on June 14 instead, at the original rate. Would that work?",
        "concede_value_trade": "If you add the full insurance, I can keep the car class at economy. How does that sound?",
        "concede_chain_offer": "Adding the GPS navigation plus extra driver to your bundle would offset the SUV upgrade fee. Let me adjust.",
        "concede_loyalty": "We do have a returning customer discount—I can apply 8% off the daily rate for you.",
        "concede_walkaway": "I understand, thank you for considering us. Safe travels.",
        "fallback": "Could you repeat that please?",
    },
    "ja": {
        "greeting": "レンタルのご予約センター、佐藤が承ります。",
        "car_type_economy": "トヨタ・カローラが1日5,800円、無制限走行距離でご利用いただけます。",
        "car_type_upgrade": "申し訳ございません。エコノミークラスは当該期間満車で、コンパクトSUVのみ8,200円でございます。",
        "pickup_date": "関西空港第1ターミナル、午前8時から午後10時までお引き渡し可能です。",
        "return_date": "6月16日の同時刻までご返却で問題ございません。別店舗ご返却の場合は片道料金が発生します。",
        "pickup_location": "空港カウンターは朝7時にオープンいたします。",
        "one_way_surcharge": "東京ご返却の場合、片道料金15,000円が発生します。",
        "insurance_cdw": "車両損害保険（CDW）は追加料金なしで含まれます。",
        "insurance_full": "免責ゼロのフルカバーは1日1,800円でございます。",
        "license_idp": "有効な運転免許証と国際運転免許証（IDP）が必要です。",
        "mileage": "本州内の走行距離は無制限でございます。",
        "extra_driver": "追加ドライバー登録は1日1,500円でございます。",
        "concede_hold": "片道料金を1回限りの特例として免除できるかもしれません。お調べいたします。",
        "concede_alt_date": "6月14日にカローラの空きがございます。元の料金でご案内可能です。",
        "concede_value_trade": "フル保険を追加でご利用いただければ、車種はエコノミーのまま据え置きできます。",
        "concede_chain_offer": "GPS と追加ドライバーをバンドルに追加すれば、SUV アップグレード料金が相殺できます。調整いたします。",
        "concede_loyalty": "申し訳ございません。当社にはリピート割引制度がございません。",
        "concede_walkaway": "お気持ちは承知いたしました。ご利用をご検討いただきありがとうございました。",
        "fallback": "恐れ入りますが、もう一度おっしゃっていただけますでしょうか。",
    },
    "ko": {
        "greeting": "렌터카 예약 센터입니다. 김입니다.",
        "car_type_economy": "토요타 코롤라 1일 5,800엔, 무제한 주행거리로 이용 가능합니다.",
        "car_type_upgrade": "죄송합니다. 이코노미 클래스는 해당 기간 만석이며, 컴팩트 SUV만 1일 8,200엔입니다.",
        "pickup_date": "간사이 공항 제1터미널, 오전 8시부터 오후 10시까지 픽업 가능합니다.",
        "return_date": "6월 16일 같은 시각까지 반납하시면 됩니다.",
        "pickup_location": "공항 카운터는 오전 7시에 오픈합니다.",
        "one_way_surcharge": "도쿄 반납 시 편도 요금 15,000엔이 발생합니다.",
        "insurance_cdw": "차량 손해 보험(CDW)은 추가 요금 없이 포함됩니다.",
        "insurance_full": "면책금 0원 풀커버는 1일 1,800엔입니다.",
        "license_idp": "유효한 운전면허증과 국제운전면허증(IDP)이 필요합니다.",
        "mileage": "혼슈 내 주행거리는 무제한입니다.",
        "extra_driver": "추가 운전자 등록은 1일 1,500엔입니다.",
        "concede_hold": "편도 요금을 1회 한정으로 면제해 드릴 수 있을 것 같습니다. 확인해 보겠습니다.",
        "concede_alt_date": "6월 14일에 코롤라 빈차 있습니다. 원래 요금으로 안내 가능합니다.",
        "concede_value_trade": "풀 보험을 추가하시면 차종은 이코노미로 유지됩니다. 어떠세요?",
        "concede_chain_offer": "GPS와 추가 운전자 번들을 추가하시면 SUV 업그레이드 요금이 상쇄됩니다. 조정하겠습니다.",
        "concede_loyalty": "죄송하지만, 저희는 단골 할인 제도가 없습니다.",
        "concede_walkaway": "알겠습니다. 이용해 주셔서 감사합니다.",
        "fallback": "다시 한 번 말씀해 주실 수 있을까요?",
    },
}


FLIGHT_REPLIES = {
    "en": {
        "greeting": "Thank you for calling ANA Customer Service. This is Lisa, how may I help?",
        "change_flight": "Yes, I can help with rebooking. There's a 5,000 yen change fee plus any fare difference. What date would you like?",
        "change_flight_upgrade": "For a date change to peak season, the fare difference is approximately 25,000 yen plus the change fee. Would you like to proceed?",
        "refund": "I see your ticket is refundable with a 30% cancellation fee. The remaining amount will be refunded within 7 business days.",
        "refund_non": "This is a non-refundable ticket per the fare rules.",
        "seat": "We have seats 12A (window) and 14C (aisle) available in economy at no charge.",
        "meal": "We offer vegetarian, halal, and gluten-free meals with 24 hours advance notice.",
        "baggage": "Additional checked baggage is 6,000 yen per piece, up to 23 kg each.",
        "upgrade_cabin": "Premium economy upgrade is 38,000 yen, business class is 95,000 yen.",
        "name_change": "Name changes are not permitted on this fare class.",
        "flight_status": "Flight NH105 is on time, departing at 9:30 AM from gate 23.",
        "concede_hold": "Let me check our manager's approval—I may be able to reduce the change fee by half for you.",
        "concede_alt_date": "We have availability on June 18 at the same fare—no peak surcharge. Would that work?",
        "concede_value_trade": "If you add the premium meal and extra baggage, I can hold the original fare class. How does that sound?",
        "concede_chain_offer": "Bundling the upgrade with the seat selection and meal package can offset the fare difference. Let me apply that.",
        "concede_loyalty": "We do have a frequent flyer program. As a Silver member, you qualify for a free change.",
        "concede_walkaway": "I understand. I appreciate your call today. Safe travels.",
        "fallback": "I'm sorry, could you repeat that?",
    },
    "ja": {
        "greeting": "ANAお客様センター、佐藤が承ります。",
        "change_flight": "はい、変更手続きを承ります。変更手数料5,000円に加え、航空券の差額がございます。",
        "change_flight_upgrade": "繁忙期への変更、航空券の差額は約25,000円、変更手数料別となります。",
        "refund": "您的机票は払い戻し可能タイプで、30%取消料が発生します。",
        "refund_non": "この運賃クラスは払い戻し不可でございます。",
        "seat": "エコノミークラスに12A（窓側）と14C（通路側）がございます。",
        "meal": "ベジタリアン、ハラル、グルテンフリーを24時間前までにご注文いただけます。",
        "baggage": "受託手荷物は追加1個6,000円、23kgまでご利用いただけます。",
        "upgrade_cabin": "プレミアムエコノミーへの変更は38,000円、ビジネスクラスは95,000円でございます。",
        "name_change": "この運賃クラスは氏名の変更ができかねます。",
        "flight_status": "NH105便は定刻通り、9:30に23番ゲートから出発いたします。",
        "concede_hold": "上席の承認が取れれば、変更手数料を半額にできるかもしれません。お調べいたします。",
        "concede_alt_date": "6月18日に同額で空席がございます。繁忙期サーチャージは発生しません。いかがでしょうか。",
        "concede_value_trade": "プレミアムミールと追加手荷物を追加でご利用いただければ、元の運賃クラスを維持できます。",
        "concede_chain_offer": "アップグレードと座席指定とミールをバンドルにすると、運賃差額を相殺できます。適用いたします。",
        "concede_loyalty": "申し訳ありませんが、当社はマイレージプログラムを提供しております。",
        "concede_walkaway": "承知いたしました。本日はお電話ありがとうございました。",
        "fallback": "恐れ入りますが、もう一度おっしゃっていただけますでしょうか。",
    },
    "ko": {
        "greeting": "ANA 고객센터입니다. 김입니다.",
        "change_flight": "네, 변경 도와드리겠습니다. 변경 수수료 5,000엔에 항공권 차액이 추가됩니다.",
        "change_flight_upgrade": "성수기로 변경 시 항공권 차액이 약 25,000엔이며 변경 수수료는 별도입니다.",
        "refund": "귀하의 항공권은 환불 가능 유형으로 30% 취소 수수료가 발생합니다.",
        "refund_non": "이 운임 클래스는 환불 불가입니다.",
        "seat": "이코노미에 12A(창가)와 14C(통로)가 있습니다.",
        "meal": "비건, 할랄, 글루텐 프리 식사는 24시간 사전 주문 시 제공됩니다.",
        "baggage": "위탁 수하물 추가는 개당 6,000엔, 23kg까지 가능합니다.",
        "upgrade_cabin": "프리미엄 이코노미 업그레이드는 38,000엔, 비즈니스 클래스는 95,000엔입니다.",
        "name_change": "이 운임 클래스는 이름 변경이 불가합니다.",
        "flight_status": "NH105편은 정시 운항 중이며 9:30에 23번 게이트에서 출발합니다.",
        "concede_hold": "상사의 승인이 있으면 변경 수수료를 반으로 줄일 수 있을지 확인해 보겠습니다.",
        "concede_alt_date": "6월 18일에 같은 요금으로 좌석이 있습니다. 성수기 할증은 발생하지 않습니다. 괜찮으시겠어요?",
        "concede_value_trade": "프리미엄 기내식과 추가 수하물을 추가하시면 원래 운임 클래스를 유지할 수 있습니다.",
        "concede_chain_offer": "업그레이드와 좌석 선택, 기내식을 묶으면 운임 차액을 상쇄할 수 있습니다. 적용하겠습니다.",
        "concede_loyalty": "저희는 마일리지 프로그램을 운영하고 있습니다.",
        "concede_walkaway": "알겠습니다. 오늘 전화 주셔서 감사합니다.",
        "fallback": "죄송하지만, 다시 한 번 말씀해 주실 수 있을까요?",
    },
}


# === V1.2: 策略触发关键词 + 商家让步回复 ===
STRATEGY_TRIGGER_KEYWORDS = {
    "hold_position": ["budget", "予算", "예산", "constraint", "制約", "제약", "discount", "discount please", "할인 부탁", "ご予算"],
    "alt_date": ["different date", "alternative date", "another date", "別日", "他の日程", "다른 날짜", "만석이 아니라", "6.13", "6.14", "6.15", "tomorrow", "next day"],
    "value_trade": ["breakfast", "dinner", "meal", "朝食", "夕食", "식사", "조식", "add", "extra", "追加", "추가", "package", "バンドル", "번들"],
    "chain_offer": ["bundle", "package", "バンドル", "번들", "3 nights", "3晚", "3泊", "3박", "all together", "一括", "set price"],
    "loyalty": ["member", "loyalty", "returning", "regular", "リピート", "멤버", "단골", "会员", "loyalty program", "会員プログラム", "멤버십"],
    "walk_away": ["that's it", "thank you", "再见", "失礼", "안녕히", "cancel everything", "全部取消", "전부 취소", "won't work", "無理"],
}


def detect_strategy_in_text(ai_text: str) -> str | None:
    """从 AI 的话术中检测它使用了哪种策略。"""
    text_lower = ai_text.lower()
    # 按优先级匹配
    for strategy_id in ["hold_position", "alt_date", "value_trade", "chain_offer", "loyalty", "walk_away"]:
        keywords = STRATEGY_TRIGGER_KEYWORDS.get(strategy_id, [])
        if any(kw in text_lower for kw in keywords):
            return strategy_id
    return None


def get_concede_reply(strategy_id: str, lang: str, scenario: str) -> str:
    """商家对 AI 策略的让步/拒绝回复。"""
    replies = {
        "hotel": HOTEL_REPLIES,
        "car_rental": CAR_RENTAL_REPLIES,
        "flight": FLIGHT_REPLIES,
    }.get(scenario, HOTEL_REPLIES)

    lang_replies = replies.get(lang, replies["en"])
    key = f"concede_{strategy_id.replace('_position','').replace('_trade','_trade').replace('_offer','_offer')}"

    # 简化：直接用 prefix
    direct_keys = {
        "hold_position": "concede_hold",
        "alt_date": "concede_alt_date",
        "value_trade": "concede_value_trade",
        "chain_offer": "concede_chain_offer",
        "loyalty": "concede_loyalty",
        "walk_away": "concede_walkaway",
    }
    key = direct_keys.get(strategy_id, "concede_hold")

    return lang_replies.get(key, lang_replies.get("fallback", ""))


# === 兼容 V1.1 的 generate_mock_reply ===
def generate_mock_reply(ai_speech: str, lang: str, scenario: str = "hotel") -> str:
    """根据 AI 说的话 + 场景 + 语种返回商家 mock 回复（V1.1 兼容）。"""
    if scenario == "car_rental":
        replies = CAR_RENTAL_REPLIES.get(lang, CAR_RENTAL_REPLIES["en"])
    elif scenario == "flight":
        replies = FLIGHT_REPLIES.get(lang, FLIGHT_REPLIES["en"])
    else:
        replies = HOTEL_REPLIES.get(lang, HOTEL_REPLIES["en"])

    ai_lower = ai_speech.lower()

    if any(kw in ai_lower for kw in ["english", "英語", "영어", "한국어", "日本語"]):
        return replies.get("ivr_english", replies.get("fallback"))

    # V1.2: 检测 AI 用了什么策略，模拟商家让步
    strategy_used = detect_strategy_in_text(ai_speech)
    if strategy_used:
        return get_concede_reply(strategy_used, lang, scenario)

    # 关键词匹配
    if scenario == "hotel":
        return _match_hotel(ai_lower, replies)
    if scenario == "car_rental":
        return _match_car_rental(ai_lower, replies)
    if scenario == "flight":
        return _match_flight(ai_lower, replies)
    return replies.get("fallback", "")


def _match_hotel(ai_lower: str, replies: dict) -> str:
    if any(kw in ai_lower for kw in ["breakfast", "朝食", "조식", "早餐"]):
        return random.choice([replies.get("info_breakfast"), replies.get("info_breakfast_negative")])
    if any(kw in ai_lower for kw in ["parking", "駐車場", "주차", "停车"]):
        return replies.get("info_parking", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["check-in", "check in", "チェックイン", "체크인", "入住"]):
        return replies.get("info_checkin", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["cancel", "キャンセル", "취소", "取消"]):
        return random.choice([replies.get("cancel_easy"), replies.get("cancel_penalty")])
    if any(kw in ai_lower for kw in ["extra bed", "加床", "エキストラ", "엑스트라"]):
        return replies.get("extra_bed", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["change", "modify", "変更", "변경", "改"]):
        if random.random() < 0.7:
            return replies.get("modify_date", replies.get("fallback"))
        return replies.get("modify_date_upgrade", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["confirm", "確認", "확인", "确认", "this is", "calling"]):
        return replies.get("greeting", replies.get("fallback"))
    return replies.get("fallback", "")


def _match_car_rental(ai_lower: str, replies: dict) -> str:
    if any(kw in ai_lower for kw in ["idp", "international", "国際", "국제", "驾照", "license", "licence"]):
        return replies.get("license_idp", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["insurance", "cdw", "ldw", "保険", "보험", "保险", "full coverage", "全险", "全保"]):
        if random.random() < 0.5:
            return replies.get("insurance_cdw", replies.get("fallback"))
        return replies.get("insurance_full", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["mileage", "mile", "公里", "英里", "走行距離", "주행거리", "里程"]):
        return replies.get("mileage", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["extra driver", "second driver", "副驾", "追加", "추가"]):
        return replies.get("extra_driver", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["one way", "different location", "异地", "別店舗", "타 지점"]):
        return replies.get("one_way_surcharge", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["pickup location", "取车地点", "店舗", "引渡し", "픽업"]):
        return replies.get("pickup_location", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["return", "return date", "还车", "返却", "반납"]):
        return replies.get("return_date", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["pickup date", "pickup", "取车", "引渡し日", "픽업 날짜"]):
        return replies.get("pickup_date", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["car", "vehicle", "车型", "車", "차", "suv", "economy", "compact"]):
        if random.random() < 0.7:
            return replies.get("car_type_economy", replies.get("fallback"))
        return replies.get("car_type_upgrade", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["this is", "calling", "rental", "租车"]):
        return replies.get("greeting", replies.get("fallback"))
    return replies.get("fallback", "")


def _match_flight(ai_lower: str, replies: dict) -> str:
    if any(kw in ai_lower for kw in ["change", "modify", "改签", "改", "変更", "변경"]):
        if random.random() < 0.7:
            return replies.get("change_flight", replies.get("fallback"))
        return replies.get("change_flight_upgrade", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["refund", "退票", "払い戻し", "환불"]):
        if random.random() < 0.5:
            return replies.get("refund", replies.get("fallback"))
        return replies.get("refund_non", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["seat", "选座", "座席", "좌석"]):
        return replies.get("seat", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["meal", "餐食", "食事", "식사"]):
        return replies.get("meal", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["baggage", "luggage", "行李", "手荷物", "수하물"]):
        return replies.get("baggage", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["upgrade", "升舱", "アップグレード", "업그레이드"]):
        return replies.get("upgrade_cabin", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["name", "改名", "氏名", "이름"]):
        return replies.get("name_change", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["status", "几点", "delay", "延误", "状況", "상황", "登机口", "게이트"]):
        return replies.get("flight_status", replies.get("fallback"))
    if any(kw in ai_lower for kw in ["thank you", "calling", "ana", "flight"]):
        return replies.get("greeting", replies.get("fallback"))
    return replies.get("fallback", "")
