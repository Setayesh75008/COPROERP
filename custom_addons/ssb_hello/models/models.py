# from odoo import models, fields, api


# class ssb_hello(models.Model):
#     _name = 'ssb_hello.ssb_hello'
#     _description = 'ssb_hello.ssb_hello'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

