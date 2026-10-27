#!/usr/bin/env python3
"""Restore an Odoo ZIP into a new local test DB; compare saved payroll after upgrade.

Run with the same Python/virtualenv as Odoo (requires psycopg2 and psql).
No Odoo/SaaS code is imported or upgraded by this script. Existing databases are
never dropped or overwritten. The original config and ZIP are read-only inputs.
"""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    raise SystemExit('Activate the Python/virtualenv used by Odoo; psycopg2 is required. No database changed.')


REVIEW_FIELDS = (
    'id employee_id company_id date status attendance_status_manual '
    'overtime_state overtime_hours overtime_amount overtime_calculation_type '
    'overtime_rate overtime_resolved_rate overtime_template_id overtime_slab_id '
    'overtime_note overtime_updated_by_id overtime_updated_on '
    'fine_state fine_hours fine_amount fine_calculation_type fine_rate fine_note '
    'fine_updated_by_id fine_updated_on fine_review_data hourly_pay_state '
    'hourly_pay_hours hourly_pay_amount hourly_pay_calculation_type hourly_pay_rate '
    'hourly_pay_note hourly_pay_updated_by_id hourly_pay_updated_on'
).split()


def read_config(path):
    config = configparser.ConfigParser(interpolation=None)
    try:
        loaded = config.read(path)
    except configparser.Error:
        raise ValueError('Unable to parse config; check its INI syntax locally.') from None
    if not loaded or not config.has_section('options'):
        raise ValueError('Config must exist and contain an [options] section.')
    return config


def connection_options(config):
    options = config['options']
    result = {}
    for source, target in [('db_host', 'host'), ('db_port', 'port'),
                           ('db_user', 'user'), ('db_password', 'password'),
                           ('db_sslmode', 'sslmode')]:
        value = options.get(source, '').strip()
        if value and value.lower() not in ('false', 'none'):
            result[target] = value
    return result


def validate_target(name, original):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name):
        raise ValueError('Use a lower-case database name, at most 63 characters.')
    if not re.search(r'(^|_)test(_|$)', name):
        raise ValueError('The new database name must contain a separate "test" segment.')
    if name in {item.strip() for item in original.split(',')}:
        raise ValueError('Choose a NEW test database name, different from the source config.')


def archive_members(archive):
    names = set()
    members = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
            raise ValueError('Unsafe ZIP path; nothing was restored.')
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('ZIP symlinks are not supported.')
        name = str(path)
        if name in names:
            raise ValueError('Duplicate ZIP members are not supported.')
        names.add(name)
        if not info.is_dir() and (name == 'dump.sql' or name.startswith('filestore/')):
            members.append(info)
    if 'dump.sql' not in names:
        raise ValueError('Expected an Odoo ZIP containing dump.sql and optional filestore/.')
    return members


def copy_sql(source, target):
    # Recent pg_dump versions add their own restrict/unrestrict bookends.
    # Keep OUR random restriction active for the whole restore instead.
    bookend = re.compile(rb'\\(?:un)?restrict[ \t]+[A-Za-z0-9_]+[ \t]*\r?\n?')
    for line in source:
        if not bookend.fullmatch(line):
            target.write(line)


def exists(cursor, table):
    cursor.execute('SELECT to_regclass(%s)', (table,))
    return bool(cursor.fetchone()[0])


def rows(cursor, table, requested=None):
    if not exists(cursor, table):
        return None
    cursor.execute('SELECT column_name FROM information_schema.columns '
                   "WHERE table_schema='public' AND table_name=%s", (table,))
    available = {item[0] for item in cursor.fetchall()}
    columns = sorted(available) if requested is None else [c for c in requested if c in available]
    if requested is not None and columns != requested:
        raise ValueError('Missing baseline columns in ' + table)
    cursor.execute(sql.SQL('SELECT {} FROM {}').format(
        sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table)))
    values = json.loads(json.dumps(cursor.fetchall(), default=str))
    values.sort(key=lambda row: json.dumps(row, sort_keys=True))
    return {'columns': columns, 'rows': values}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(cursor, previous=None):
    tables = {
        'payslips': ('hr_payslip', 'id employee_id company_id contract_id date_from date_to state paid'.split()),
        'salary_lines': ('hr_payslip_line', 'id slip_id salary_rule_id code category_id amount quantity rate total'.split()),
        'punches': ('hr_attendance', 'id employee_id check_in check_out worked_hours'.split()),
        'paid_day_decisions': ('bambus_attendance_paid_day_decision', None),
    }
    result = {}
    for key, (table, columns) in tables.items():
        if previous and previous.get(key):
            columns = previous[key]['columns']
        result[key] = rows(cursor, table, columns)
    table = ('bambus_attendance_day_review' if exists(cursor, 'bambus_attendance_day_review')
             else 'bambus_hr_attendance_sheet_line')
    columns = previous['reviews']['columns'] if previous and previous.get('reviews') else None
    if columns is None and exists(cursor, table):
        cursor.execute('SELECT column_name FROM information_schema.columns WHERE table_name=%s', (table,))
        available = {item[0] for item in cursor.fetchall()}
        columns = [c for c in REVIEW_FIELDS if c in available]
    result['reviews'] = rows(cursor, table, columns)
    # Store hashes, never SaaS credentials/configuration values in the baseline.
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                   "AND tablename LIKE 'bambus\\_saas%' ORDER BY tablename")
    result['saas_tables'] = {table: digest(rows(cursor, table)) for (table,) in cursor.fetchall()}
    cursor.execute("SELECT key,value FROM ir_config_parameter WHERE key ILIKE '%saas%' ORDER BY key")
    result['saas_parameters_hash'] = digest(cursor.fetchall())
    return result


def restore(args):
    original = Path(args.config).expanduser().resolve()
    backup = Path(args.backup).expanduser().resolve()
    config = read_config(original)
    validate_target(args.database, config['options'].get('db_name', ''))
    if not 1024 <= args.port <= 65535:
        raise ValueError('Choose a local test HTTP port between 1024 and 65535.')
    source_port = int(config['options'].get('http_port', config['options'].get('xmlrpc_port', '8069')))
    if args.port == source_port:
        raise ValueError('The test HTTP port must differ from the source instance port.')
    pg = connection_options(config)
    pg_path = config['options'].get('pg_path', '').strip()
    if not pg_path or pg_path.lower() in ('false', 'none'):
        pg_path = os.environ.get('PATH')
    psql = shutil.which('psql', path=pg_path)
    if not psql:
        raise ValueError('psql is required. Install the PostgreSQL client or configure pg_path.')
    root = Path(args.directory).expanduser().resolve() if args.directory else (
        Path.home() / '.local/share/raaviya-rehearsal' / args.database)
    if root.exists():
        raise ValueError('Output directory already exists; choose a new directory. Nothing overwritten.')
    if root == backup or backup.is_relative_to(root) or original.is_relative_to(root):
        raise ValueError('Keep the original ZIP/config outside the new output directory.')
    with zipfile.ZipFile(backup) as archive:
        members = archive_members(archive)
        connection = psycopg2.connect(dbname='postgres', **pg)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname=%s', (args.database,))
                if cursor.fetchone():
                    raise ValueError('Database already exists. This script never drops or replaces databases.')
                cursor.execute('SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user')
                if not cursor.fetchone()[0]:
                    raise ValueError('The configured PostgreSQL user needs CREATEDB permission.')
                root.mkdir(parents=True, mode=0o700)
                cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING %s').format(
                    sql.Identifier(args.database)), ('UTF8',))
        finally:
            connection.close()
        # No Odoo registry, module initialization, or SaaS hooks run during restore.
        with tempfile.TemporaryDirectory(prefix='restore-', dir=root) as staging:
            dump = Path(staging) / 'dump.sql'
            with archive.open('dump.sql') as source, dump.open('wb') as target:
                copy_sql(source, target)
            command = [psql, '-X', '--set=ON_ERROR_STOP=1', '--dbname=' + args.database]
            for key, flag in [('host', '--host'), ('port', '--port'), ('user', '--username')]:
                if key in pg:
                    command += [flag, str(pg[key])]
            # Odoo 18 uses psql restricted mode to prevent dump meta-commands
            # from invoking a shell or reconnecting to an existing database.
            command += ['-c', '\\restrict ' + secrets.token_hex(), '-f', str(dump)]
            process_env = dict(os.environ)
            if pg.get('password'):
                process_env['PGPASSWORD'] = pg['password']
            if pg.get('sslmode'):
                process_env['PGSSLMODE'] = pg['sslmode']
            log_path = root / 'restore.log'
            with log_path.open('w') as log:
                os.chmod(log_path, 0o600)
                subprocess.run(command, env=process_env, stdout=log, stderr=subprocess.STDOUT, check=True)
        filestore = root / 'data/filestore' / args.database
        filestore.mkdir(parents=True, mode=0o700)
        for info in members:
            if not info.filename.startswith('filestore/'):
                continue
            destination = filestore / PurePosixPath(info.filename).relative_to('filestore')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open('xb') as target:
                shutil.copyfileobj(source, target)
    with psycopg2.connect(dbname=args.database, **pg) as connection:
        with connection.cursor() as cursor:
            for table in ('ir_mail_server', 'fetchmail_server'):
                if exists(cursor, table):
                    cursor.execute(sql.SQL('UPDATE {} SET active=false').format(sql.Identifier(table)))
            if exists(cursor, 'mail_mail'):
                cursor.execute("UPDATE mail_mail SET state='cancel' WHERE state IN ('outgoing','exception')")
            if exists(cursor, 'payment_provider'):
                cursor.execute("UPDATE payment_provider SET state='disabled'")
            for key, value in [('database.uuid', str(uuid.uuid4())),
                               ('web.base.url', 'http://localhost:' + str(args.port)),
                               ('web.base.url.freeze', 'True')]:
                cursor.execute('INSERT INTO ir_config_parameter(key,value) VALUES(%s,%s) '
                               'ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value', (key, value))
            baseline = snapshot(cursor)
    baseline['database'] = args.database
    baseline['original_config_path'] = str(original)
    baseline['original_config_hash'] = hashlib.sha256(original.read_bytes()).hexdigest()
    for key, value in {'db_name': args.database, 'dbfilter': '^' + args.database + '$',
                       'data_dir': str(root / 'data'), 'http_interface': '127.0.0.1',
                       'logfile': str(root / 'odoo-test.log'), 'pidfile': str(root / 'odoo-test.pid'),
                       'http_port': str(args.port), 'workers': '0', 'max_cron_threads': '0',
                       'proxy_mode': 'False', 'list_db': 'False',
                       'smtp_server': '127.0.0.1', 'smtp_port': '1'}.items():
        config['options'][key] = value
    # Remove legacy port alias from the copied config; source remains unchanged.
    config['options'].pop('xmlrpc_port', None)
    for name, content in [('baseline.json', json.dumps(baseline, indent=2)), ('odoo-test.conf', None)]:
        path = root / name
        with path.open('w') as file:
            os.chmod(path, 0o600)
            file.write(content) if content is not None else config.write(file)
    print('Restored NEW test database:', args.database)
    print('Test config:', root / 'odoo-test.conf')
    print('Baseline:', root / 'baseline.json')
    print('Test URL: http://localhost:' + str(args.port))
    print('Background cron is disabled in the test config; mail/payment connections disabled in the copy.')
    print('Original config/ZIP and existing databases unchanged. SaaS code/configuration not modified.')
    print('Next: upgrade only the four attendance/report modules, then run this script with verify.')


def verify(args):
    root = Path(args.directory).expanduser().resolve()
    baseline = json.loads((root / 'baseline.json').read_text())
    config = read_config(root / 'odoo-test.conf')
    if config['options']['db_name'] != baseline['database']:
        raise ValueError('Test config database does not match the captured baseline.')
    with psycopg2.connect(dbname=baseline['database'], **connection_options(config)) as connection:
        with connection.cursor() as cursor:
            current = snapshot(cursor, baseline)
            changed = [key for key in current if current[key] != baseline[key]]
            if changed:
                raise ValueError('Baseline differs: ' + ', '.join(changed) + '. Stop and investigate before manual tests.')
            cursor.execute("SELECT model FROM ir_model WHERE model IN "
                           "('bambus.hr.attendance.sheet','bambus.hr.attendance.sheet.line')")
            if cursor.fetchall():
                raise ValueError('Saved data matches, but History models still exist. Upgrade the four modules first.')
    original = Path(baseline['original_config_path'])
    if not original.exists() or hashlib.sha256(original.read_bytes()).hexdigest() != baseline['original_config_hash']:
        raise ValueError('Original config changed since restore. Review that separate change.')
    for name in ('payslips', 'salary_lines', 'punches', 'reviews', 'paid_day_decisions'):
        value = baseline.get(name)
        print('PASS:', name, '(' + str(len(value['rows']) if value else 0) + ' saved rows unchanged)')
    print('PASS: SaaS table/configuration hashes unchanged; original config unchanged.')
    print('PASS: History models absent. Baseline verified BEFORE manual attendance/payroll changes.')
    print('This comparison checks preservation, not calculation accuracy or complete release readiness.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('restore', help='Create a new test copy; never overwrite a DB.')
    new.add_argument('--config', required=True)
    new.add_argument('--backup', required=True)
    new.add_argument('--database', default='raaviya_history_removal_test')
    new.add_argument('--port', type=int, default=1562)
    new.add_argument('--directory')
    check = commands.add_parser('verify', help='Compare saved data immediately after upgrade.')
    check.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        (restore if args.command == 'restore' else verify)(args)
    except (ValueError, OSError, zipfile.BadZipFile, psycopg2.Error, subprocess.CalledProcessError) as error:
        print('STOP:', error, file=sys.stderr)
        print('No databases were dropped. If restore failed, keep the partial test DB/log for inspection.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
