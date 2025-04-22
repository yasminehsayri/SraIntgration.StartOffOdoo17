from odoo import models, fields, api
import base64
import io
import PyPDF2
import logging
from odoo import http
from odoo.http import request
from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment
from datetime import datetime
from dateutil.relativedelta import relativedelta
import mimetypes

_logger = logging.getLogger(__name__)

class OnboardingOffboarding(models.Model):
    _name = "onboarding.offboarding"
    _description = "Onboarding & Offboarding"

    name = fields.Char(string="Nom", required=True)
    employee_id = fields.Many2one('hr.employee', string="Employé", required=True)
    type = fields.Selection([('onboarding', 'Onboarding'), ('offboarding', 'Offboarding')], string="Type", required=True)
    start_date = fields.Date(string="Date de début", default=fields.Date.today)
    state = fields.Selection([('draft', 'Brouillon'), ('in_progress', 'En cours'), ('done', 'Terminé')], string="État", default='draft')

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    birthday = fields.Date(string="Date de naissance")
    age = fields.Integer(string="Age", compute="_compute_age", store=True)

    @api.depends('birthday')
    def _compute_age(self):
        for record in self:
            if record.birthday:
                record.age = relativedelta(datetime.now().date(), record.birthday).years
            else:
                record.age = 0

class HrJob(models.Model):
    _inherit = 'hr.job'

    experience = fields.Text(string="Expérience")
    key_words = fields.Text(string="Mots Clés")
    skills = fields.Text(string="Compétences")

    def _get_keywords(self):
        """Centralized method to extract job keywords."""
        job_keywords = self.key_words or ""
        job_experience = self.experience or ""
        job_skills = self.skills or ""
        combined_criteria = f"{job_keywords} {job_experience} {job_skills}".lower()
        return list(set(combined_criteria.replace(",", " ").split()))

class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    cv_file = fields.Binary(string="CV (PDF)")
    cv_filename = fields.Char(string="Nom du fichier CV")
    ats_score = fields.Float(string="Score ATS", store=True)

    def _validate_cv_file(self, cv_content, filename):
        """Validate CV file for size and type."""
        if not cv_content:
            return False
        if len(cv_content) > 10 * 1024 * 1024:  # 10 MB limit
            _logger.warning("File size exceeds 10 MB: %s", filename)
            return False
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type != 'application/pdf':
            _logger.warning("Invalid file type: %s", filename)
            return False
        return True

    def _process_cv_and_score(self):
        if self.cv_file and self.job_id:
            if not self._validate_cv_file(base64.b64decode(self.cv_file), self.cv_filename):
                self.ats_score = 0.0
                return
            # S'assurer que l'enregistrement hr.applicant est enregistré
            if not self.id:
                _logger.warning("hr.applicant not saved yet, cannot create hr.candidate.cv")
                self.ats_score = 0.0
                return
            # Créer l'enregistrement hr.candidate.cv
            cv_record = self.env['hr.candidate.cv'].create({
                'name': self.id,  # self.id est l'ID de hr.applicant
                'job_id': self.job_id.id,
                'cv_file': self.cv_file,
                'cv_filename': self.cv_filename or "cv.pdf",
                'departement': self.department_id.name if self.department_id else "Non spécifié",
            })
            score = cv_record._calculate_ats_score()
            _logger.info("Calculated ATS score: %s for applicant %s", score, self.id)
            cv_record.ats_score = score
            self.ats_score = score
        else:
            _logger.warning("No cv_file or job_id provided, setting ATS score to 0")
            self.ats_score = 0.0

    @api.model
    def create(self, vals):
        applicant = super(HrApplicant, self).create(vals)
        applicant._process_cv_and_score()
        return applicant

    @api.onchange('cv_file', 'job_id')
    def _onchange_cv_file(self):
        self._process_cv_and_score()

class WebsiteHrRecruitmentCustom(WebsiteHrRecruitment):
    @http.route(['/jobs/apply/<model("hr.job"):job>'], type='http', auth="public", website=True, sitemap=True)
    def jobs_apply(self, job, **kwargs):
        _logger.info("Custom jobs_apply called for job: %s", job.name)
        result = super(WebsiteHrRecruitmentCustom, self).jobs_apply(job, **kwargs)

        if request.httprequest.method == 'POST':
            cv_file = request.httprequest.files.get('cv_file') or request.httprequest.files.get('ufile')
            if cv_file:
                _logger.info("CV file received: %s", cv_file.filename)
                try:
                    if not cv_file.filename.lower().endswith('.pdf'):
                        _logger.warning("Invalid file type uploaded: %s", cv_file.filename)
                        return request.redirect('/jobs/apply/%s?error=invalid_file' % job.id)

                    cv_content = cv_file.read()
                    cv_filename = cv_file.filename

                    # Rechercher la candidature par email ou autres critères uniques
                    email = request.params.get('email')
                    applicant = request.env['hr.applicant'].sudo().search(
                        [('job_id', '=', job.id), ('email_from', '=', email)],
                        order='id desc', limit=1
                    )
                    if applicant:
                        _logger.info("Updating applicant %s with CV: %s", applicant.id, cv_filename)
                        applicant.write({
                            'cv_file': base64.b64encode(cv_content),
                            'cv_filename': cv_filename,
                        })
                        applicant._process_cv_and_score()
                    else:
                        _logger.warning("No applicant found for job %s with email %s", job.id, email)
                        return request.redirect('/jobs/apply/%s?error=no_applicant' % job.id)
                except Exception as e:
                    _logger.error("Error processing CV file: %s", str(e))
                    return request.redirect('/jobs/apply/%s?error=file_processing' % job.id)
            else:
                _logger.warning("No CV file found in form data")
        return result

class CandidateCV(models.Model):
    _name = "hr.candidate.cv"
    _description = "CV des candidats"

    name = fields.Many2one('hr.applicant', string="Nom du candidat")
    job_id = fields.Many2one('hr.job', string="Poste visé", required=True, ondelete='cascade')
    cv_file = fields.Binary(string="CV (PDF)")
    cv_filename = fields.Char(string="CV du candidat")
    application_date = fields.Date(string="Date de postulation", default=fields.Date.today)
    departement = fields.Char(string="Département", required=True)
    extracted_text = fields.Text(string="Extracted CV Text")
    ats_score = fields.Float(string="Score ATS", store=True)

    @api.model
    def create(self, vals):
        _logger.info("Creating hr.candidate.cv with vals: %s", vals)
        record = super(CandidateCV, self).create(vals)
        if record.cv_file:
            record.ats_score = record._calculate_ats_score()
        return record

    @api.onchange('cv_file')
    def _onchange_cv_file(self):
        _logger.info("CV file changed for hr.candidate.cv")
        if self.cv_file:
            self.ats_score = self._calculate_ats_score()
        else:
            self.ats_score = 0.0

    def _extract_text_from_pdf(self, binary_data):
        """Extract text from PDF file."""
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
                _logger.error("Failed to extract text from PDF: %s", str(e))
                text = ""
        _logger.info("Extracted text length: %s", len(text))
        return text.lower()

    def _calculate_ats_score(self):
        """Calculate ATS score based on job keywords and CV text."""
        if not self.job_id or not self.cv_file:
            _logger.warning("Missing job_id or cv_file for ATS score calculation")
            return 0.0

        keywords = self.job_id._get_keywords()
        text = self._extract_text_from_pdf(self.cv_file)
        self.extracted_text = text  # Store extracted text

        if not text or not keywords:
            _logger.warning("No text extracted or no keywords available")
            return 0.0

        _logger.info("Keywords: %s", keywords)
        match_count = sum(1 for keyword in keywords if keyword in text)
        score = (match_count / len(keywords)) * 100 if keywords else 0
        _logger.info("ATS score calculated: %s", score)
        return round(score, 2)

class EmployeeMaterial(models.Model):
    _name = 'employee.material'
    _description = 'Employee Materials'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    material_name = fields.Char(string='Material Name', required=True)
    description = fields.Text(string='Description')
    date_assigned = fields.Date(string='Date Assigned', default=fields.Date.today)
    serial_number = fields.Char(string="Numéro de série")

class EmployeeAccess(models.Model):
    _name = 'employee.access'
    _description = 'Employee Access'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    access_for = fields.Char(string='Access for', required=True)
    description = fields.Text(string='Description')
    start_date = fields.Date(string="Date de début", default=fields.Date.today)
    end_date = fields.Date(string="Date de fin")