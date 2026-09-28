import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

BOOK_MINER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOOK_MINER_DIR))

# BookMiner.py は import 時に cwd 配下の log/ にログファイルを作るため、一時ディレクトリで import する。
_import_dir = tempfile.TemporaryDirectory()
_cwd = os.getcwd()
os.chdir(_import_dir.name)
try:
    with contextlib.redirect_stdout(io.StringIO()):
        import BookMiner as bm  # noqa: E402
finally:
    os.chdir(_cwd)


def tearDownModule():
    _import_dir.cleanup()


class CleanupOldBackupsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def touch(self, *names):
        for name in names:
            Path(self.dir, name).write_text("x", encoding="utf-8")

    def remaining(self):
        return sorted(os.listdir(self.dir))

    def cleanup(self, keep_count, protected=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return bm.cleanup_old_backups(keep_count, protected or [], self.dir)

    def test_keeps_latest_n_per_kind(self):
        self.touch(
            "book_miner-20260101000000_10.db",
            "book_miner-20260102000000_20.db",
            "book_miner-20260103000000_30.db",
            "peta_book-20260101000000_10.db",
            "peta_book-20260102000000_20.db",
            "peta_book-20260103000000_30.db",
        )
        removed = self.cleanup(2)
        self.assertEqual(len(removed), 2)
        self.assertEqual(
            self.remaining(),
            [
                "book_miner-20260102000000_20.db",
                "book_miner-20260103000000_30.db",
                "peta_book-20260102000000_20.db",
                "peta_book-20260103000000_30.db",
            ],
        )

    def test_keep_count_zero_disables_cleanup(self):
        self.touch(
            "book_miner-20260101000000_10.db",
            "book_miner-20260102000000_20.db",
        )
        self.assertEqual(self.cleanup(0), [])
        self.assertEqual(len(self.remaining()), 2)

    def test_excluded_files_are_never_removed(self):
        excluded = [
            "book_miner-20260101000000_10_ply100.db",
            "book_miner-20260101000000_10.ybb",
            "peta_book-20260101000000_10.ybb",
            "tmp-book_miner-20260101000000_10.db",
            "tmp-peta_book-20260101000000_10.db",
            "book_miner.db",
        ]
        self.touch(*excluded)
        self.touch(
            "book_miner-20260102000000_20.db",
            "book_miner-20260103000000_30.db",
        )
        self.cleanup(1)
        self.assertEqual(
            self.remaining(),
            sorted(excluded + ["book_miner-20260103000000_30.db"]),
        )

    def test_peta_book_without_count_is_target(self):
        self.touch(
            "peta_book-20260101000000.db",
            "peta_book-20260102000000_20.db",
        )
        self.cleanup(1)
        self.assertEqual(self.remaining(), ["peta_book-20260102000000_20.db"])

    def test_protected_paths_are_kept(self):
        self.touch(
            "book_miner-20260101000000_10.db",
            "book_miner-20260102000000_20.db",
            "book_miner-20260103000000_30.db",
            "peta_book-20260101000000_10.db",
            "peta_book-20260103000000_30.db",
        )
        protected = [
            os.path.join(self.dir, "book_miner-20260101000000_10.db"),
            os.path.join(self.dir, "peta_book-20260101000000_10.db"),
            None,
        ]
        self.cleanup(1, protected)
        self.assertEqual(
            self.remaining(),
            [
                "book_miner-20260101000000_10.db",
                "book_miner-20260103000000_30.db",
                "peta_book-20260101000000_10.db",
                "peta_book-20260103000000_30.db",
            ],
        )

    def test_skips_while_peta_shock_is_running(self):
        self.touch(
            "book_miner-20260101000000_10.db",
            "book_miner-20260102000000_20.db",
        )
        with bm.BACKUP_FILES_LOCK:
            self.assertEqual(self.cleanup(1), [])
        self.assertEqual(len(self.remaining()), 2)

    def test_missing_dir_returns_empty(self):
        self.assertEqual(
            bm.cleanup_old_backups(1, [], os.path.join(self.dir, "missing")),
            [],
        )


class BackupKeepCountSettingTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json5")
            Path(path).write_text(text, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                return bm.load_book_miner_settings(path)

    def test_default_is_zero(self):
        self.assertEqual(self.load("{}").backup_keep_count, 0)

    def test_reads_value(self):
        self.assertEqual(self.load("{backup_keep_count: 2}").backup_keep_count, 2)

    def test_rejects_negative(self):
        with self.assertRaises(Exception):
            self.load("{backup_keep_count: -1}")

    def test_rejects_bool(self):
        with self.assertRaises(Exception):
            self.load("{backup_keep_count: true}")


if __name__ == "__main__":
    unittest.main()
