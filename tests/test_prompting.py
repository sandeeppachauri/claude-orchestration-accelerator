from orchestration_accelerator.prompting import (
    OutputContractError,
    PromptManager,
    PromptValidationError,
)


def test_get_classify_prompt():
    pm = PromptManager()
    cfg = pm.get("classify")
    assert cfg.step == "classify"
    assert cfg.format["type"] == "enum"


def test_get_with_explicit_filename():
    pm = PromptManager()
    cfg = pm.get("extract", filename="extract_v2.yaml")
    assert cfg.step == "extract"
    assert cfg.version == 2


def test_missing_prompt_raises():
    pm = PromptManager()
    try:
        pm.get("does-not-exist")
        assert False, "expected PromptValidationError"
    except PromptValidationError:
        pass


def test_validate_output_enum_ok():
    pm = PromptManager()
    cfg = pm.get("classify")
    assert pm.validate_output("classify", cfg, "billing") == "billing"


def test_validate_output_enum_bad_raises():
    pm = PromptManager()
    cfg = pm.get("classify")
    try:
        pm.validate_output("classify", cfg, "not-a-category")
        assert False, "expected OutputContractError"
    except OutputContractError:
        pass


def test_validate_output_json_ok():
    pm = PromptManager()
    cfg = pm.get("extract", filename="extract_v2.yaml")
    result = pm.validate_output(
        "extract", cfg, '{"summary": "billing issue", "urgency": "high"}'
    )
    assert result["urgency"] == "high"


def test_validate_output_json_strips_markdown_fence():
    pm = PromptManager()
    cfg = pm.get("extract", filename="extract_v2.yaml")
    result = pm.validate_output(
        "extract",
        cfg,
        '```json\n{"summary": "billing issue", "urgency": "high"}\n```',
    )
    assert result["urgency"] == "high"


def test_render_static_only_string_input_unchanged():
    pm = PromptManager()
    cfg, system_prompt, user_content = pm.render("classify", "I was double charged")
    assert system_prompt == cfg.system_prompt
    assert user_content == "I was double charged"


def test_render_static_only_dict_input_raises():
    pm = PromptManager()
    try:
        pm.render("classify", {"body": "x"})
        assert False, "expected PromptValidationError"
    except PromptValidationError:
        pass


def test_render_multi_placeholder_ok():
    pm = PromptManager()
    values = {
        "ticket_id": "T-1",
        "customer_name": "Ada",
        "customer_tier": "gold",
        "body": "My invoice is wrong",
    }
    cfg, system_prompt, user_content = pm.render(
        "ticket_triage", values, filename="ticket_triage.yaml"
    )
    assert "gold-tier" in system_prompt
    assert "T-1" in user_content
    assert "Ada" in user_content
    assert "My invoice is wrong" in user_content
    assert "{{" not in system_prompt and "{{" not in user_content


def test_render_missing_placeholder_key_raises():
    pm = PromptManager()
    try:
        pm.render(
            "ticket_triage",
            {"ticket_id": "T-1", "customer_name": "Ada", "customer_tier": "gold"},
            filename="ticket_triage.yaml",
        )
        assert False, "expected PromptValidationError"
    except PromptValidationError:
        pass


def test_render_extra_key_ignored():
    """Extra dict keys not referenced by this step's placeholders are
    allowed -- a multi-step run shares one flat `input` dict across
    steps with different placeholder needs."""
    pm = PromptManager()
    cfg, system_prompt, user_content = pm.render(
        "ticket_triage",
        {
            "ticket_id": "T-1",
            "customer_name": "Ada",
            "customer_tier": "gold",
            "body": "x",
            "extra_unused": "y",
        },
        filename="ticket_triage.yaml",
    )
    assert "extra_unused" not in system_prompt
    assert "extra_unused" not in user_content


def test_render_placeholders_string_input_raises():
    pm = PromptManager()
    try:
        pm.render("ticket_triage", "just a string", filename="ticket_triage.yaml")
        assert False, "expected PromptValidationError"
    except PromptValidationError:
        pass


def test_render_complex_both_prompts_have_placeholders():
    pm = PromptManager()
    values = {
        "ticket_id": "T-9",
        "customer_name": "Grace",
        "customer_tier": "free",
        "account_history": "2 prior tickets",
        "sla_minutes_remaining": "15",
        "body": "Site is down",
    }
    cfg, system_prompt, user_content = pm.render(
        "escalation_decision", values, filename="escalation_decision.yaml"
    )
    assert "free-tier" in system_prompt
    assert "2 prior tickets" in user_content
    assert "15" in user_content
