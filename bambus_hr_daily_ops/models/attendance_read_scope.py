"""Batch contract inputs for one dashboard read; never retain results across RPCs."""
from odoo import fields, models


class DashboardReadScope:
    """An internal, request-owned object; JSON contexts cannot supply this type."""

    def __init__(self, day):
        self.day = fields.Date.to_date(day)
        self.contracts = None

    def load(self, employees):
        if self.contracts is not None:
            return
        # Match the shared date-specific helper exactly, including undated
        # starts and its deliberate sudo. Financial callers retain their own
        # company/wage checks; do not silently select a different contract.
        contracts = employees.env['hr.contract'].sudo().search([
            ('employee_id', 'in', employees.ids), ('state', '!=', 'cancel'),
            '|', ('date_start', '=', False), ('date_start', '<=', self.day),
            '|', ('date_end', '=', False), ('date_end', '>=', self.day),
        ], order='date_start desc, id desc')
        empty = contracts.browse()
        self.contracts = dict.fromkeys(employees.ids, empty)
        for contract in contracts:
            if not self.contracts[contract.employee_id.id]:
                self.contracts[contract.employee_id.id] = contract

    def covers(self, employee, day):
        return (self.contracts is not None and fields.Date.to_date(day) == self.day
                and employee.id in self.contracts)


class DashboardReadEmployee(models.Model):
    _inherit = 'hr.employee'

    def _get_attendance_contract(self, day):
        self.ensure_one()
        scope = self.env.context.get('_bambus_dashboard_read_scope')
        if isinstance(scope, DashboardReadScope) and scope.covers(self, day):
            return scope.contracts[self.id].with_env(self.sudo().env)
        return super()._get_attendance_contract(day)


class DashboardReadOvertime(models.Model):
    _inherit = 'hr.attendance.overtime'

    def _get_contract_on_date(self, employee, day):
        scope = self.env.context.get('_bambus_dashboard_read_scope')
        if isinstance(scope, DashboardReadScope) and scope.covers(employee, day):
            return employee._get_attendance_contract(day)
        return super()._get_contract_on_date(employee, day)
