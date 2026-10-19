import json
import re
from pathlib import Path


def test_thirty_question_labels_reference_real_fixture_evidence():
    root = Path(__file__).resolve().parents[1] / "evaluation"
    questions = json.loads((root / "questions.json").read_text(encoding="utf-8"))
    assert len(questions) == 30
    assert len({question["id"] for question in questions}) == 30
    assert sum(not question["answerable"] for question in questions) == 6
    for question in questions:
        assert question["answerable"] == bool(question["expected_sources"])
        for expected in question["expected_sources"]:
            assert expected["page_number"] == 1
            assert expected["contains"] in (root / "corpus" / expected["filename"]).read_text(encoding="utf-8")
        for pattern in question["expected_fact_patterns"]:
            re.compile(pattern)
