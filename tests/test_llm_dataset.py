import csv
import json

import pytest

from hentai_studio.workloads.llm.config import DatasetConfig
from hentai_studio.workloads.llm.dataset import audit_jsonl, source_files, split_name, text_from_record
from hentai_studio.workloads.llm.lora_cpt import ArchiveBlocks, configure_csv_field_limit


@pytest.mark.parametrize(
    ("schema", "record", "expected"),
    [
        ("text", {"text": "hello"}, "hello"),
        ("prompt_completion", {"prompt": "Q", "completion": "A"}, "QA"),
        ("messages", {"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]}, "hello\nhi"),
    ],
)
def test_all_dataset_schemas(schema, record, expected):
    assert text_from_record(record, schema) == expected


def test_audit_is_text_only_and_counts_invalid_rows(tmp_path):
    source = tmp_path / "fixture.jsonl"
    source.write_text("\n".join([json.dumps({"text": "one"}), "not-json", json.dumps({"text": ""}), json.dumps({"text": "one"})]))
    report = audit_jsonl(DatasetConfig(root=str(tmp_path), schema="text", context_length=128))
    assert report.files == 1
    assert (report.records, report.valid, report.invalid, report.empty, report.duplicates) == (4, 2, 1, 1, 1)


def test_audit_supports_erp_csv_message_rows(tmp_path):
    (tmp_path / "fixture.csv").write_text("message,other\none,x\n,x\none,x\n", encoding="utf-8")
    report = audit_jsonl(DatasetConfig(root=str(tmp_path), schema="text", context_length=128))
    assert report.files == 1
    assert (report.records, report.valid, report.invalid, report.empty, report.duplicates) == (3, 2, 0, 1, 1)


def test_split_is_stable():
    assert split_name("same record", 357, 0.2) == split_name("same record", 357, 0.2)


def test_source_files_includes_csv_and_jsonl_only(tmp_path):
    (tmp_path / "records.csv").write_text("message\nhello\n")
    (tmp_path / "records.jsonl").write_text('{"text":"hello"}\n')
    (tmp_path / "ignore.txt").write_text("ignored")
    assert [path.name for path in source_files(tmp_path)] == ["records.csv", "records.jsonl"]


def test_archive_blocks_honors_configured_deterministic_split(tmp_path):
    class Tokenizer:
        eos_token_id = 0
        def __call__(self, text, **_kwargs):
            return {"input_ids": [ord(char) % 31 + 1 for char in text]}

    (tmp_path / "source.csv").write_text("message\nalpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    tokenizer = Tokenizer()
    training = list(ArchiveBlocks(tmp_path, tokenizer, 2, 19, 0.5, False))
    validation = list(ArchiveBlocks(tmp_path, tokenizer, 2, 19, 0.5, True))
    assert training and validation
    assert training == list(ArchiveBlocks(tmp_path, tokenizer, 2, 19, 0.5, False))


def test_csv_field_limit_accepts_long_archive_rows():
    configure_csv_field_limit()
    assert csv.field_size_limit() > 131_072
