# from odoo import http


# class SsbHello(http.Controller):
#     @http.route('/ssb_hello/ssb_hello', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/ssb_hello/ssb_hello/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('ssb_hello.listing', {
#             'root': '/ssb_hello/ssb_hello',
#             'objects': http.request.env['ssb_hello.ssb_hello'].search([]),
#         })

#     @http.route('/ssb_hello/ssb_hello/objects/<model("ssb_hello.ssb_hello"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('ssb_hello.object', {
#             'object': obj
#         })

