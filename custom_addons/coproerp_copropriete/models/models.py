# from odoo import models, fields, api


# class coproerp_copropriete(models.Model):
#     _name = 'coproerp_copropriete.coproerp_copropriete'
#     _description = 'coproerp_copropriete.coproerp_copropriete'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

