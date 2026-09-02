# -*- coding: utf-8 -*-
from odoo import api, fields, models
from datetime import timedelta

class HrLeave(models.Model):
    _inherit = "hr.leave"

    def _bambus_impacted_days(self):
        """Return set of (employee_id, day_date) impacted by this leave (local-date safe enough)."""
        impacted = set()
        for lv in self:
            if not lv.employee_id or not lv.date_from or not lv.date_to:
                continue
            d_from = fields.Datetime.to_datetime(lv.date_from).date()
            d_to = fields.Datetime.to_datetime(lv.date_to).date()
            cur = d_from
            while cur <= d_to:
                impacted.add((lv.employee_id.id, cur))
                cur += timedelta(days=1)
        return impacted

    def _bambus_recompute_impacted(self, impacted):
        if not impacted:
            return
        ot = self.env["hr.attendance.overtime"].sudo()
        # recompute per employee/day (fast)
        for emp_id, day in impacted:
            ot.bambus_recompute_range([emp_id], day, day)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        # if created directly as validated, recompute
        impacted = recs.filtered(lambda r: r.state == "validate")._bambus_impacted_days()
        recs._bambus_recompute_impacted(impacted)
        return recs

    def write(self, vals):
        # capture before
        before = self._bambus_impacted_days()
        res = super().write(vals)
        # recompute if leave details/state changed (common when HR edits half-day later)
        trigger = {"state", "date_from", "date_to", "employee_id", "request_date_from", "request_date_to"}
        if trigger.intersection(vals.keys()):
            after = self._bambus_impacted_days()
            self._bambus_recompute_impacted(before | after)
        return res

    def unlink(self):
        impacted = self._bambus_impacted_days()
        res = super().unlink()
        self._bambus_recompute_impacted(impacted)
        return res

    # Button flows (some versions write state internally; this makes it explicit)
    def action_validate(self, check_state=True):
        res = super().action_validate(check_state)
        self._bambus_recompute_impacted(self._bambus_impacted_days())
        return res

    def action_refuse(self):
        impacted = self._bambus_impacted_days()
        res = super().action_refuse()
        self._bambus_recompute_impacted(impacted)
        return res

    def action_draft(self):
        impacted = self._bambus_impacted_days()
        res = super().action_draft()
        self._bambus_recompute_impacted(impacted)
        return res
