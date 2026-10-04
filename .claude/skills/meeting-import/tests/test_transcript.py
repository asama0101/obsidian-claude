"""transcript.py のテスト（unittest、追加インストール不要）。"""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import transcript  # noqa: E402

VTT = """WEBVTT

1a2b-3c/12-0
00:00:01.000 --> 00:00:03.000
<v 佐藤 花子>おはようございます。</v>

1a2b-3c/13-0
00:00:03.500 --> 00:00:05.000
<v 佐藤 花子>始めます。</v>

00:00:06.000 --> 00:00:08.000
<v 田中>資料は金曜までに送ります &amp; 共有します。</v>
"""


class TestTranscript(unittest.TestCase):
    def test_vtt_merges_consecutive_lines_of_the_same_speaker(self):
        self.assertEqual(
            transcript.from_vtt(VTT),
            "佐藤 花子: おはようございます。 始めます。\n田中: 資料は金曜までに送ります & 共有します。",
        )

    def test_docx_paragraphs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.docx"
            xml = ('<w:document><w:body><w:p><w:r><w:t>会議メモ</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t xml:space="preserve">決定: </w:t></w:r><w:r><w:t>A 案</w:t></w:r></w:p>'
                   '<w:p></w:p></w:body></w:document>')
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", xml)
            self.assertEqual(transcript.from_docx(path), "会議メモ\n決定: A 案")


if __name__ == "__main__":
    unittest.main()
