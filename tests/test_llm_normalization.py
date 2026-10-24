import json

from hentai_studio.workloads.llm.normalization import normalize_csv_archive, normalize_message


def test_normalize_message_removes_scripts_and_preserves_breaks():
    assert normalize_message("<p>Hello<br>there</p><script>discard()</script><p>Again</p>") == "Hello\nthere\n\nAgain"


def test_normalize_archive_groups_adjacent_thread_turns(tmp_path):
    source, output = tmp_path / "source", tmp_path / "clean"
    source.mkdir()
    (source / "fixture.csv").write_text(
        ",thread_title,thread_href,message_timestamp,message_username,message\n"
        "0,One,/one,,A,<p>First</p>\n"
        "1,One,/one,,B,<p>Second</p>\n"
        "2,Two,/two,,C,<script>x</script><p>Third</p>\n",
        encoding="utf-8",
    )
    report = normalize_csv_archive(source, output)
    rows = [json.loads(line) for line in (output / "fixture.jsonl").read_text(encoding="utf-8").splitlines()]
    assert (report.files, report.documents, report.kept_messages) == (1, 2, 3)
    assert rows[0]["text"] == "Thread: One\n\nA:\nFirst\n\nB:\nSecond"
    assert rows[1]["text"].endswith("C:\nThird")
