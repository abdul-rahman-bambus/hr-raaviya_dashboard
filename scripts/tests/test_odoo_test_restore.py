import configparser
import importlib.util
import io
from pathlib import Path
import stat
import unittest
import zipfile


spec = importlib.util.spec_from_file_location('restore', Path(__file__).parents[1] / 'odoo_test_restore.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestoreInputs(unittest.TestCase):
    def test_refuses_source_database_and_non_test_names(self):
        for name in ('raaviya_live', 'latest', 'postgres', 'raaviya_automation_test', 'test;DROP DATABASE x'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                restore.validate_target(name, 'raaviya_automation_test')
        restore.validate_target('raaviya_history_removal_test', 'raaviya_automation_test')

    def archive(self, names):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in names:
                archive.writestr(name, '')
        stream.seek(0)
        return zipfile.ZipFile(stream)

    def test_only_dump_and_filestore_are_selected(self):
        with self.archive(['dump.sql', 'manifest.json', 'filestore/ab/hash', 'README.md']) as archive:
            self.assertEqual([item.filename for item in restore.archive_members(archive)],
                             ['dump.sql', 'filestore/ab/hash'])

    def test_refuses_paths_that_escape_restore_directory(self):
        for name in ('../outside', '/absolute', 'filestore/../../outside', 'filestore\\..\\outside'):
            with self.subTest(name=name), self.archive(['dump.sql', name]) as archive:
                with self.assertRaises(ValueError):
                    restore.archive_members(archive)

    def test_refuses_symlinks_and_non_odoo_archives(self):
        with self.archive(['README.md']) as archive, self.assertRaises(ValueError):
            restore.archive_members(archive)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('dump.sql', '')
            link = zipfile.ZipInfo('filestore/link')
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, '/outside')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive, self.assertRaises(ValueError):
            restore.archive_members(archive)

    def test_config_credentials_are_read_literally(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read_string('[options]\ndb_host=localhost\ndb_user=odoo\n'
                           'db_password=example%literal$not-a-real-secret\ndb_port=5432\n')
        self.assertEqual(restore.connection_options(config)['password'], 'example%literal$not-a-real-secret')

    def test_saas_digest_is_order_independent_for_json_keys(self):
        self.assertEqual(restore.digest({'a': 1, 'b': 2}), restore.digest({'b': 2, 'a': 1}))

    def test_export_bookends_do_not_replace_our_psql_restriction(self):
        source = io.BytesIO(b'-- SQL\n\\restrict exported_token\nSELECT 1;\n\\unrestrict exported_token\n')
        target = io.BytesIO()
        restore.copy_sql(source, target)
        self.assertEqual(target.getvalue(), b'-- SQL\nSELECT 1;\n')
        source = io.BytesIO(b'\\\\restrict literal_copy_data\n\\connect other_database\n\\! command\n')
        target = io.BytesIO()
        restore.copy_sql(source, target)
        self.assertEqual(target.getvalue(), source.getvalue())


if __name__ == '__main__':
    unittest.main()
