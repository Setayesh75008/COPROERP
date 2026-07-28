# from odoo import http


# class CoproerpCore(http.Controller):
#     @http.route('/coproerp_core/coproerp_core', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/coproerp_core/coproerp_core/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('coproerp_core.listing', {
#             'root': '/coproerp_core/coproerp_core',
#             'objects': http.request.env['coproerp_core.coproerp_core'].search([]),
#         })

#     @http.route('/coproerp_core/coproerp_core/objects/<model("coproerp_core.coproerp_core"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('coproerp_core.object', {
#             'object': obj
#         })

