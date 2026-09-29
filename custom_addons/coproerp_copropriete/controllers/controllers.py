# from odoo import http


# class CoproerpCopropriete(http.Controller):
#     @http.route('/coproerp_copropriete/coproerp_copropriete', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/coproerp_copropriete/coproerp_copropriete/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('coproerp_copropriete.listing', {
#             'root': '/coproerp_copropriete/coproerp_copropriete',
#             'objects': http.request.env['coproerp_copropriete.coproerp_copropriete'].search([]),
#         })

#     @http.route('/coproerp_copropriete/coproerp_copropriete/objects/<model("coproerp_copropriete.coproerp_copropriete"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('coproerp_copropriete.object', {
#             'object': obj
#         })

