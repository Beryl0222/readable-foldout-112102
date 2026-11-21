"""检查交换资料的标识、文本和跨表引用。"""

import json
from pathlib import Path
import unittest


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class SourceDataTest(unittest.TestCase):
    def setUp(self):
        self.tables = {}
        for path in sorted(DATA_DIR.glob("*.json")):
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(rows, list)
            self.assertTrue(rows, path.name)
            by_id = {}
            for row in rows:
                identifier = row["id"]
                self.assertIsInstance(identifier, str, path.name)
                self.assertNotIn(identifier, by_id, path.name)
                if "text" in row:
                    self.assertIsInstance(row["text"], str, path.name)
                by_id[identifier] = row
            self.tables[path.stem] = by_id

    def test_exchange_tables_present(self):
        self.assertEqual(set(self.tables), {'channels', 'copy', 'layout'})

    def test_related_source_records(self):
        data = self.tables
        layout = data["layout"]
        for row in layout.values():
            left, top, right, bottom = row["bbox"]
            self.assertLess(left, right)
            self.assertLess(top, bottom)
        for draft in data["copy"].values():
            self.assertTrue(set(draft["source_ref"]) <= layout.keys())
        refs = data["copy"]["E6"]["source_ref"]
        self.assertGreater(len({layout[key]["page"] for key in refs}), 1)
        self.assertNotEqual(data["channels"]["C3"]["units"][0]["budget"],
                            data["channels"]["C1"]["units"][0]["budget"])
