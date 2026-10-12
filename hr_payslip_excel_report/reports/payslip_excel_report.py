from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request


class ExcelReportController(http.Controller):
    @http.route('/my_excel/download', type='http', auth='user')
    def download_excel(self, id=None, **kwargs):
        try:
            wizard_id = int(id)
        except (TypeError, ValueError):
            raise BadRequest('A valid payroll report ID is required.')
        wizard = request.env['payslip.excel.wizard'].browse(wizard_id).exists()
        if not wizard:
            raise NotFound()
        try:
            wizard.check_access('read')
            content = wizard._generate_xlsx()
        except AccessError as error:
            raise Forbidden(str(error)) from error
        except UserError as error:
            raise BadRequest(str(error)) from error
        start, end = wizard._period_dates()
        name = 'payroll-review' if wizard.report_type == 'review' else 'payslip-summary'
        return request.make_response(content, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(f'{name}-{start}-{end}.xlsx')),
            ('Cache-Control', 'no-store'),
        ])
