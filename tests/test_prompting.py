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
