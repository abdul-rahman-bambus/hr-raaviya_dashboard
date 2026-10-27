from odoo.addons.bambus_hr_daily_ops.migration import migrate_history_decisions


def migrate(cr, version):
    migrate_history_decisions(cr)
