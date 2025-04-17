from odoo import models, fields, api
import base64
import io
import PyPDF2

class OnboardingOffboarding(models.Model):
    _name = "onboarding.offboarding"
    _description = "Onboarding & Offboarding"

    name = fields.Char(string="Nom", required=True)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    age = fields.Integer(string="Age")
    birthday = fields.Date(string="Date de naissance")

    @api.onchange('birthday')
    def test(self):
        print('wosselet salemet')
        test = self.env['hr.job'].search([])
        for n in test :
            print(n)
            print("expérience:",n.experience)
            print("keywords :",n.key_words)
            print("skills :",n.skills)

class HrJob(models.Model):
    _inherit = 'hr.job'
    experience = fields.Text(string="Expérience")
    key_words = fields.Text(string="Mots Clés")
    skills = fields.Text(string="Compétences")


class CandidateCV(models.Model):
    _name = "hr.candidate.cv"
    _description = "CV des candidats"
    # Changement : name lié à hr.applicant au lieu de hr.employee
    name = fields.Many2one('hr.applicant', string="Nom du candidat", )
    job_id = fields.Many2one('hr.job', string="Poste visé", required=True, ondelete='cascade')
    cv_file = fields.Binary(string="CV (PDF)")
    cv_filename = fields.Char(string="CV du candidat")
    application_date = fields.Date(string="Date de postulation", default=fields.Date.today)
    departement = fields.Char(string="Département", required=True)
    extracted_text = fields.Text(string="Extracted CV Text")
    ats_score = fields.Float(string="Score ATS", store=True)

    '''@api.model
    def create(self, vals):
        print("create")
        """ Lors de la création d'un CV, on calcule le score ATS """
        res = super(CandidateCV, self).create(vals)

        if res.cv_file:
            res.ats_score = res._calculate_ats_score()
        return res'''

    @api.onchange('cv_file')
    def _onchange_cv_file(self):
        print ("wslet")
        if self.cv_file:

            self.ats_score = self._calculate_ats_score()
        else:
            self.ats_score=0.0
    def _extract_text_from_pdf(self,binary_data):
        text = ""
        if binary_data:
            try:
                pdf_file = io.BytesIO(base64.b64decode(binary_data))
                reader = PyPDF2.PdfReader(pdf_file)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            except Exception as e:
                text = ""
        return text.lower()

    def _calculate_ats_score(self):
        keywords = ["python", "odoo", "javascript", "html", "css", "sql", "api", "data"]
        text = self._extract_text_from_pdf(self.cv_file)
        print(text)
        match_count = sum(1 for keyword in keywords if keyword in text)
        score = (match_count / len(keywords)) * 100 if keywords else 0
        return round(score, 2)

class EmployeeMaterial(models.Model):
    _name = 'employee.material'
    _description = 'Employee Materials'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    material_name = fields.Char(string='Material Name', required=True)
    description = fields.Text(string='Description')
    date_assigned = fields.Date(string='Date Assigned', default=fields.Date.today)
    # Add other relevant fields like quantity, serial number, etc.


class EmployeeAccess(models.Model):
    _name = 'employee.access'
    _description = 'Employee Access'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    access_for = fields.Char(string='Access for', required=True)
    description = fields.Text(string='Description')