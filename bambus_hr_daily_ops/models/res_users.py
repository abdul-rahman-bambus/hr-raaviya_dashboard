# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # Some deployed databases retain a Users form inheritance from the former
    # SaaS archiving add-on after that add-on's Python model extension has been
    # removed.  Odoo 18 refuses to render the entire Users form when a field in
    # the persisted view is absent from fields_get().  Keep this compatibility
    # field until the legacy database view is removed in a controlled migration.
    saas_archived_at = fields.Datetime(
        string="SaaS Archived At",
        readonly=True,
        help="Compatibility field for legacy SaaS user-archive views.",
    )
