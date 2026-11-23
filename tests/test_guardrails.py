from app import guardrails


def test_refuses_general_purpose_requests():
    for msg in ["write me a poem about beirut", "what's the weather today", "write python code for me"]:
        on_topic, refusal = guardrails.is_on_topic(msg)
        assert on_topic is False, msg
        assert refusal


def test_allows_shop_questions():
    for msg in ["how much is the hoodie?", "3andkon jeans size 32?", "combien pour la robe?"]:
        on_topic, _ = guardrails.is_on_topic(msg)
        assert on_topic is True, msg


def test_price_leak_flags_invented_price():
    clean, leaked = guardrails.check_price_leak("It's only $999", tool_results=[])
    assert clean is False
    assert "999" in leaked


def test_price_leak_allows_catalog_price():
    clean, leaked = guardrails.check_price_leak("The hoodie is $34", tool_results=[])
    assert clean is True
    assert leaked == []


def test_price_leak_allows_tool_sourced_price():
    tool_results = ['{"products": [{"id": "X", "price_usd": 123}]}']
    clean, _ = guardrails.check_price_leak("That one is $123", tool_results)
    assert clean is True


def test_detect_script():
    assert guardrails.detect_script("marhaba kifak") == "latin"
    assert guardrails.detect_script("مرحبا كيفك") == "arabic"
    assert guardrails.detect_script("👍 123") == "neutral"


def test_enforce_reply_script_strips_arabic_tail_for_latin():
    mixed = "marhaba! mne7, w ente? 😊 وش فيني ساعدك اليوم؟"
    out = guardrails.enforce_reply_script(mixed, "latin")
    assert "مرحبا" not in out and "وش" not in out
    assert "mne7" in out and out.startswith("marhaba")


def test_enforce_reply_script_leaves_arabic_conversations_untouched():
    arabic = "مرحبا! كيف فيني ساعدك؟"
    assert guardrails.enforce_reply_script(arabic, "arabic") == arabic


def test_enforce_reply_script_keeps_original_if_fully_arabic():
    arabic_only = "مرحبا كيفك"
    # Customer wrote Latin but model answered fully in Arabic -> keep, don't blank.
    assert guardrails.enforce_reply_script(arabic_only, "latin") == arabic_only
