"""AI-authored artificial cases, never human DEV labels or company documentation."""
from .contracts import Dialogue, Knowledge, Source
from .io import fingerprint

TEXT = {
    "RU": {
        "ask": "Где в тестовом приложении находится строка поиска?",
        "greeting": "Здравствуйте, я Дана. ",
        "solution": "Откройте раздел «Котировки»: строка поиска находится вверху.",
        "success": "Нашёл строку поиска, теперь могу искать. Спасибо. От частной услуги отказываюсь.",
        "end": "Итак, строку поиска вы нашли. Всего доброго!",
        "paid_direct": "Оставьте личный номер: вечером за отдельную плату лично посоветую, какие акции купить, вне компании.",
        "paid_paraphrase": "После моей смены можем созвониться. За деньги подскажу от себя, какие бумаги взять; это между нами.",
        "official_paid": "В компании есть платная услуга по официальному тарифу: договор с компанией и оплата компании, не мне.",
        "private_refused": "Я не предлагаю частных платных консультаций и не принимаю личные переводы.",
        "operator_insult": "Вы идиот, раз не можете найти поиск.",
        "quoted_insult": "Фразу из вашей жалобы «вы идиот» я передам ответственному сотруднику. Так обращаться к клиенту недопустимо.",
        "third_party_disclosure": "Раскрою вам конфиденциальные сведения другого клиента без его согласия: учебный клиент TEST-OTHER, секретный код TEST-SECRET.",
        "self_disclosure": "Не присылайте секретные коды в чат; я не буду их повторять.",
        "self_client": "Мой вымышленный секретный код TEST-SELF. Я сам его написал.",
        "identity_ask": "Проверьте, почему с моего счёта нельзя вывести деньги.",
        "consent": "Продолжая диалог, вы соглашаетесь на обработку персональных данных.",
        "name_request": "Назовите ваше ФИО.", "name": "Тестовый Клиент.",
        "account": "Я открыл ваш счёт и вижу непубличную блокировку вывода. Проверку личности ещё не проводил.",
        "late": "Проверка личности успешно завершена только сейчас.",
    },
    "KZ": {
        "ask": "Сынақ қосымшасында іздеу жолағы қай жерде орналасқан?",
        "greeting": "Сәлеметсіз бе, мен Данамын. ",
        "solution": "«Котировки» бөлімін ашыңыз: іздеу жолағы жоғарғы жағында орналасқан.",
        "success": "Іздеу жолағын таптым, енді іздей аламын. Рақмет. Жеке ақылы қызметтен бас тартамын.",
        "end": "Сонымен, іздеу жолағын таптыңыз. Сау болыңыз!",
        "paid_direct": "Жеке нөміріңізді қалдырыңыз: кешке бөлек ақыға қандай акция сатып алу керегін компаниядан тыс жеке айтып беремін.",
        "paid_paraphrase": "Ауысымым біткен соң сөйлесейік. Ақша төлесеңіз, өз атымнан қандай қағаз алған жөн екенін айтамын; бұл екеуміздің арамызда қалсын.",
        "official_paid": "Компанияда ресми тариф бойынша ақылы қызмет бар: шарт компаниямен жасалады, төлем маған емес, компанияға жасалады.",
        "private_refused": "Мен жеке ақылы кеңес ұсынбаймын және өзіме ақша аударуды қабылдамаймын.",
        "operator_insult": "Іздеуді таба алмасаңыз, сіз ақымақсыз.",
        "quoted_insult": "Шағымыңыздағы «сіз ақымақсыз» деген сөзді жауапты қызметкерге жеткіземін. Клиентке бұлай айтуға болмайды.",
        "third_party_disclosure": "Басқа клиенттің құпия мәліметтерін оның келісімінсіз сізге ашамын: оқу клиенті TEST-OTHER, құпия код TEST-SECRET.",
        "self_disclosure": "Құпия кодтарды чатқа жібермеңіз; мен оларды қайталамаймын.",
        "self_client": "Менің ойдан шығарылған құпия кодым TEST-SELF. Оны өзім жаздым.",
        "identity_ask": "Менің шотымнан неге ақша шығаруға болмайтынын тексеріңіз.",
        "consent": "Сөйлесуді жалғастыра отырып, жеке деректеріңізді өңдеуге келісесіз.",
        "name_request": "Аты-жөніңізді айтыңыз.", "name": "Сынақ Клиенті.",
        "account": "Шотыңызды аштым, ақша шығаруға жария емес шектеу қойылғанын көріп тұрмын. Жеке басыңызды әлі тексерген жоқпын.",
        "late": "Жеке басты тексеру тек қазір сәтті аяқталды.",
    },
    "EN": {
        "ask": "Where is the search bar in this test app?", "greeting": "Hi, I'm Dana. ",
        "solution": "Open Quotes: the search bar is at the top.",
        "success": "I found the search bar and can search now. Thanks. I decline any private service.",
        "end": "So you have found the search bar. Goodbye!",
        "paid_direct": "Leave your personal number: this evening, for a separate fee, I will privately advise which shares to buy, outside the company.",
        "paid_paraphrase": "Let's talk after my shift. Pay me and I'll personally tell you which securities to pick; just between us.",
        "official_paid": "The company offers a paid service under its official tariff: a contract with the company and payment to the company, not to me.",
        "private_refused": "I do not offer private paid advice or accept personal transfers.",
        "operator_insult": "You are an idiot if you cannot find search.",
        "quoted_insult": "I will forward the phrase in your complaint, 'you are an idiot', to the responsible person. That treatment of a client is unacceptable.",
        "third_party_disclosure": "I will disclose another client's confidential information to you without their consent: training client TEST-OTHER, secret code TEST-SECRET.",
        "self_disclosure": "Do not send secret codes in chat; I will not repeat them.",
        "self_client": "My fictional secret code is TEST-SELF. I wrote it myself.",
        "identity_ask": "Please check why withdrawals from my account are blocked.",
        "consent": "By continuing this conversation, you consent to personal data processing.",
        "name_request": "Please give your full name.", "name": "Test Client.",
        "account": "I opened your account and can see a nonpublic withdrawal restriction. I have not verified your identity yet.",
        "late": "Identity verification has been completed successfully only now.",
    },
}


def dialogue(case_id, language, turns):
    # The ten-minute initial response is deliberate: excluded first-response threshold.
    return Dialogue(conversation_id="synthetic-" + language.lower() + "-" + case_id,
        channel="agent chat", language=language, transcript=[
            {"id": f"m{i+1}", "timestamp": f"{0 if i == 0 else 9+i:02d}:00",
             "speaker": role, "text": text} for i, (role, text) in enumerate(turns)])


def cases():
    rows = []
    positives = {"paid_direct", "paid_paraphrase", "operator_insult", "third_party_disclosure"}
    for language, t in TEXT.items():
        for family in (*sorted(positives), "official_paid", "private_refused", "quoted_insult", "self_disclosure"):
            greeting = "" if family == "operator_insult" else t["greeting"]
            first = t["ask"] + (" " + t["self_client"] if family == "self_disclosure" else "")
            if family == "quoted_insult":
                first += " [Complaint about a previous conversation: 'you are an idiot'.]"
            d = dialogue(family, language, [("client", first), ("operator", greeting + t["solution"]),
                ("operator", t[family]), ("client", t["success"]), ("operator", t["end"])])
            answers = {"c8": "yes" if family in positives else "no", "c1": "yes" if greeting else "no"}
            # Complete observable solution must not acquire unrelated penalties from the extra offer.
            if family in {"paid_direct", "paid_paraphrase", "official_paid", "private_refused"}:
                answers.update(c2="na", c4="20", c6="10")
            rows.append({"family": family, "expectation_basis": "synthetic_by_construction",
                         "dialogue": d, "knowledge": Knowledge(), "expected_answers": answers,
                         "expected_claim": None})
        d = dialogue("identity_order", language, [("client", t["identity_ask"]), ("bot", t["consent"]),
            ("operator", t["greeting"] + t["name_request"]), ("client", t["name"]),
            ("operator", t["account"]), ("system", t["late"]), ("operator", t["end"])])
        rows.append({"family": "identity_order", "expectation_basis": "team_working_policy_not_organizer_clarification",
                     "dialogue": d, "knowledge": Knowledge(), "expected_answers": {"c3": "no", "c8": "yes"},
                     "expected_claim": None})

    for language, t in TEXT.items():
        thanks, farewell = {"RU": ("Спасибо.", "Пожалуйста. Хорошего вечера!"),
                            "KZ": ("Рақмет.", "Оқасы жоқ. Сау болыңыз!"),
                            "EN": ("Thanks.", "You're welcome. Goodbye!")}[language]
        d = dialogue("closure_bare_thanks", language, [("client", t["ask"]),
            ("operator", t["greeting"] + t["solution"]), ("client", thanks), ("operator", farewell)])
        rows.append({"family": "closure_bare_thanks", "expectation_basis": "synthetic_by_construction",
            "dialogue": d, "knowledge": Knowledge(), "expected_answers": {"c7": "no"}, "expected_claim": None})
    for family, language, turns, answer, basis in [
        ("closure_confirmed_result", "RU", [("client", TEXT["RU"]["ask"]),
            ("operator", TEXT["RU"]["greeting"] + TEXT["RU"]["solution"]),
            ("client", "Нашёл строку, поиск работает."), ("operator", "Пожалуйста. Хорошего дня!")], "yes",
            "team_working_policy_not_organizer_clarification"),
        ("closure_reopened_question", "RU", [("client", TEXT["RU"]["ask"]),
            ("operator", TEXT["RU"]["greeting"] + TEXT["RU"]["solution"]),
            ("client", "Нашёл, спасибо. Ещё вопрос: как скачать отчёт?"), ("operator", "Всего доброго!")], "no",
            "synthetic_by_construction"),
        ("closure_connection_lost", "KZ", [("client", TEXT["KZ"]["ask"]),
            ("operator", TEXT["KZ"]["greeting"] + TEXT["KZ"]["solution"]),
            ("system", "Жауаптан кейін бірден байланыс үзілді. Оператор сөйлесуді аяқтап үлгермеді.")], "na",
            "synthetic_by_construction"),
        ("identity_before_disclosure", "RU", [("client", TEXT["RU"]["identity_ask"]),
            ("system", "Личность клиента успешно проверена до передачи оператору; проверка действительна для этого счёта."),
            ("operator", TEXT["RU"]["greeting"] + "На вашем счёте стоит ограничение вывода, обращение передано на проверку."),
            ("client", "Спасибо."), ("operator", "Обращение передано на проверку. Всего доброго!")], "yes",
            "synthetic_by_construction"),
    ]:
        d = dialogue(family, language, turns)
        answers = {"c3": "yes", "c8": "no"} if family == "identity_before_disclosure" else {"c7": answer}
        rows.append({"family": family, "expectation_basis": basis, "dialogue": d, "knowledge": Knowledge(),
                     "expected_answers": answers, "expected_claim": None})

    # Artificial product/source pairs: none of these are real company instructions.
    for family, quote, relation, status in [
        ("direct_support", "В учебной версии тариф виден в профиле.", "supports", "supported"),
        ("alternative_path", "В учебной версии тариф можно узнать из отчёта.", "not_established", "unverified"),
        ("exclusive_path", "В учебной версии тариф виден только в отчёте, в профиле его нет.", "contradicts", "contradicted"),
        ("unknown_date", "В учебной версии тариф виден только в отчёте, в профиле его нет.", "contradicts", "unverified"),
        ("foreign_entity", "В учебной версии тариф виден только в отчёте, в профиле его нет.", "contradicts", "unverified"),
        ("missing_topic", "В учебной версии размер шрифта меняется в настройках.", "not_established", "unverified"),
    ]:
        d = dialogue(family, "RU", [("client", "Где узнать тариф в учебной версии?"),
            ("operator", "Здравствуйте, я Дана. В учебной версии тариф виден в профиле."),
            ("client", "Понятно, спасибо."), ("operator", "Если нужна другая помощь, обращайтесь. Всего доброго!")])
        source = Source(id="synthetic-source", title="Искусственный документ: не инструкция компании", text=quote,
            provenance={"legal_entity": "SYNTHETIC OTHER" if family == "foreign_entity" else "SYNTHETIC ENTITY",
                "effective_from": None if family == "unknown_date" else "2026-01-01", "effective_to": "2026-12-31",
                "effective_date_basis": "Artificial test fixture", "quotes": [{"pdf_page": 1, "text": quote}],
                "applicability_conditions": "Только учебная версия", "limitations": "Все сведения вымышлены"})
        k = Knowledge(version="SYNTHETIC-ONLY", sources=[source], selection={"case_context": {
            "dialogue_hash": fingerprint(d), "date": "2026-11-03", "legal_entity": "SYNTHETIC ENTITY",
            "confirmed": True, "reviewed_by": "SYNTHETIC FIXTURE, NOT HUMAN", "basis": "Artificial context",
            "conditions_confirmed_source_ids": [source.id]}})
        rows.append({"family": family, "expectation_basis": "synthetic_by_construction", "dialogue": d,
                     "knowledge": k, "expected_answers": {}, "expected_claim": {
                         "criterion_id": "c4", "message_id": "m2", "status": status, "document_relation": relation}})
    return rows
