"""Transactional conversion of legacy sheet decisions, retaining their IDs."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate_history_decisions(cr):
    """Preserve approvals/FKs and archive raw snapshots; never price salaries."""
    cr.execute("SELECT to_regclass('bambus_hr_attendance_sheet_line'), to_regclass('bambus_attendance_day_review')")
    old, new = cr.fetchone()
    if not old:
        return
    if new:
        raise RuntimeError('Both legacy attendance lines and new decisions exist. Resolve the migration before upgrading; no records were overwritten.')
    cr.execute('''SELECT employee_id, company_id, date, count(*)
        FROM bambus_hr_attendance_sheet_line GROUP BY employee_id, company_id, date
        HAVING count(*) > 1 LIMIT 1''')
    if cr.fetchone():
        raise RuntimeError('Duplicate legacy attendance decisions exist for an employee/date. Review them before upgrading; approved money cannot be merged automatically.')
    cr.execute('''SELECT count(*) FROM bambus_hr_attendance_sheet_line
        WHERE employee_id IS NULL OR company_id IS NULL OR date IS NULL''')
    if cr.fetchone()[0]:
        raise RuntimeError('Legacy attendance decisions have incomplete employee/company/date keys. Correct these before upgrading.')
    cr.execute('''SELECT line.id FROM bambus_hr_attendance_sheet_line line
        JOIN hr_employee employee ON employee.id=line.employee_id
        WHERE line.company_id IS DISTINCT FROM employee.company_id LIMIT 1''')
    if cr.fetchone():
        raise RuntimeError('A legacy decision belongs to a different company from its employee. Resolve the company mismatch before upgrading.')
    cr.execute('''SELECT line.id FROM bambus_hr_attendance_sheet_line line
        WHERE (line.check_in IS NOT NULL OR line.check_out IS NOT NULL)
        AND EXISTS (SELECT 1 FROM bambus_hr_attendance_time_audit audit
            WHERE audit.employee_id=line.employee_id AND audit.date=line.date
            AND audit.adjustment_type='attendance'
            AND audit.check_in IS NOT DISTINCT FROM line.check_in
            AND audit.check_out IS NOT DISTINCT FROM line.check_out)
        AND NOT EXISTS (SELECT 1 FROM hr_attendance attendance
            WHERE attendance.employee_id=line.employee_id
            AND attendance.check_in >= date_trunc('day', COALESCE(line.check_in,line.check_out))
            AND attendance.check_in < date_trunc('day', COALESCE(line.check_in,line.check_out)) + interval '1 day')
        LIMIT 1''')
    if cr.fetchone():
        raise RuntimeError('Legacy manual attendance times exist without actual Punch Logs. Review and enter the real punches before upgrading. No attendance or salary was changed.')
    # Immutable raw evidence remains available to the administrator for rollback
    # and audit; no runtime dashboard/report reads either archive table.
    cr.execute('''CREATE TABLE IF NOT EXISTS bambus_legacy_attendance_review_archive
        AS TABLE bambus_hr_attendance_sheet_line''')
    cr.execute('ALTER TABLE bambus_hr_attendance_sheet_line RENAME TO bambus_attendance_day_review')
    cr.execute('ALTER TABLE bambus_attendance_day_review RENAME COLUMN sheet_id TO legacy_sheet_id')
    cr.execute('ALTER TABLE bambus_attendance_day_review ALTER COLUMN legacy_sheet_id DROP NOT NULL')
    cr.execute('''SELECT conname FROM pg_constraint
        WHERE conrelid='bambus_attendance_day_review'::regclass AND contype='f'
        AND confrelid='bambus_hr_attendance_sheet'::regclass''')
    from psycopg2 import sql
    for (name,) in cr.fetchall():
        cr.execute(sql.SQL('ALTER TABLE bambus_attendance_day_review DROP CONSTRAINT {}').format(sql.Identifier(name)))
    old_model, new_model = 'bambus.hr.attendance.sheet.line', 'bambus.attendance.day.review'
    cr.execute('UPDATE ir_model SET model=%s WHERE model=%s', (new_model, old_model))
    cr.execute('UPDATE ir_model_fields SET model=%s WHERE model=%s', (new_model, old_model))
    cr.execute('UPDATE ir_model_fields SET relation=%s WHERE relation=%s', (new_model, old_model))
    cr.execute('UPDATE ir_model_data SET model=%s WHERE model=%s', (new_model, old_model))
    cr.execute('''UPDATE ir_model_data SET name='model_bambus_attendance_day_review'
        WHERE module='bambus_hr_daily_ops' AND name='model_bambus_hr_attendance_sheet_line' ''')
    cr.execute('''UPDATE ir_model_fields SET name='legacy_sheet_id', ttype='integer',
        relation=NULL, related=NULL WHERE model=%s AND name='sheet_id' ''', (new_model,))
    # Field XML IDs must follow the renamed model; preserve their IDs and links.
    cr.execute('''UPDATE ir_model_data SET name=replace(name,
        'field_bambus_hr_attendance_sheet_line__', 'field_bambus_attendance_day_review__')
        WHERE module='bambus_hr_daily_ops' AND name LIKE 'field_bambus_hr_attendance_sheet_line__%%' ''')
    cr.execute('''UPDATE ir_model_data SET name='field_bambus_attendance_day_review__legacy_sheet_id'
        WHERE module='bambus_hr_daily_ops' AND name='field_bambus_attendance_day_review__sheet_id' ''')
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('bambus_hr_daily_ops.ir_cron_bambus_daily_attendance_sheet', raise_if_not_found=False)
    if cron:
        cron.unlink()
    # Stop old links from opening models that no longer exist. Normal module
    # cleanup removes obsolete module-owned views/actions/ACLs on upgrade.
    for name in ('menu_bambus_hr_attendance_history', 'menu_hrms_attendance_history'):
        menu = env.ref('bambus_hr_daily_ops.' + name, raise_if_not_found=False)
        if menu:
            menu.unlink()
    cr.execute('SELECT count(*) FROM bambus_attendance_day_review')
    _logger.info('Preserved %s attendance decisions with original IDs; legacy snapshots archived.', cr.fetchone()[0])
