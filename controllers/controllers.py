# -*- coding: utf-8 -*-
# from odoo import http


# class OnboardingOffboarding(http.Controller):
#     @http.route('/onboarding_offboarding/onboarding_offboarding', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/onboarding_offboarding/onboarding_offboarding/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('onboarding_offboarding.listing', {
#             'root': '/onboarding_offboarding/onboarding_offboarding',
#             'objects': http.request.env['onboarding_offboarding.onboarding_offboarding'].search([]),
#         })

#     @http.route('/onboarding_offboarding/onboarding_offboarding/objects/<model("onboarding_offboarding.onboarding_offboarding"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('onboarding_offboarding.object', {
#             'object': obj
#         })
