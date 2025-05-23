from odoo import models, fields, api
import base64
import io
import PyPDF2
import logging
from odoo.exceptions import UserError
from odoo import http
from odoo.http import request
from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment
from datetime import datetime
from dateutil.relativedelta import relativedelta
import requests
import os
import re
from dotenv import load_dotenv
load_dotenv()



_logger = logging.getLogger(__name__)

class OnboardingOffboarding(models.Model):
    _name = "onboarding.offboarding"
    _description = "Onboarding & Offboarding"

    name = fields.Char(string="Nom", required=True)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    birthday = fields.Date(string="Date de naissance")
    age = fields.Integer(string="Age", store=True)
    material_ids = fields.One2many('employee.material', 'employee_id', string="Materials")
    access_ids = fields.One2many('employee.access', 'employee_id', string="Access")

class HrJobSkill(models.Model):
    _name = 'hr.job.skill'
    _description = "Compétence Pondérée"

    name = fields.Char(string="Compétence", required=True)
    weight = fields.Integer(string="Poids", default=1)
    job_id = fields.Many2one('hr.job', string="Offre d'emploi", required=True, ondelete='cascade')

class HrJobExperience(models.Model):
    _name = 'hr.job.experience'
    _description = "Expérience Pondérée"

    name = fields.Char(string="Expérience", required=True)
    weight = fields.Integer(string="Poids", default=1)
    job_id = fields.Many2one('hr.job', string="Offre d'emploi", required=True, ondelete='cascade')

class HrJobKeyword(models.Model):
    _name = 'hr.job.keyword'
    _description = "Mot-clé Pondéré"

    name = fields.Char(string="Mot-clé", required=True)
    weight = fields.Integer(string="Poids", default=1)
    job_id = fields.Many2one('hr.job', string="Offre d'emploi", required=True, ondelete='cascade')

class HrJob(models.Model):
    _inherit = 'hr.job'

    experience_ids = fields.One2many('hr.job.experience','job_id', string="Expériences pondérées")
    keyword_ids = fields.One2many('hr.job.keyword','job_id', string="Mots-clés pondérés")
    skill_ids = fields.One2many('hr.job.skill','job_id', string="Compétences pondérées")

    def _get_keywords(self):
        """Extract job keywords from weighted fields and custom fields."""
        keywords = []

        # Use weighted fields from One2many relations for keyword_ids, skill_ids, experience_ids
        for keyword in self.keyword_ids:
            keywords.append((keyword.name.lower(), keyword.weight))
        for skill in self.skill_ids:
            keywords.append((skill.name.lower(), skill.weight))
        for experience in self.experience_ids:
            keywords.append((experience.name.lower(), experience.weight))

        # Removing duplicates while maintaining the keyword and its associated weight
        keywords = list(set(keywords))

        # Logging for reference
        _logger.info("Extracted keywords for job %s: %s", self.name, keywords)

        return keywords



class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    cv_file = fields.Binary(string="CV (PDF)")
    cv_filename = fields.Char(string="Nom du fichier CV")
    ats_score = fields.Float(string="Score ATS", store=True)
    score_detail = fields.Text(string='Score Details')


    def _process_cv_and_score(self):
        """Shared method to process CV and calculate ATS score."""
        _logger.info("Processing CV for applicant %s, job %s, filename %s", self.id, self.job_id.name if self.job_id else "None", self.cv_filename)
        if self.cv_file and self.job_id:
            try:
                cv_content = base64.b64decode(self.cv_file)
                _logger.info("CV file decoded, size: %s bytes", len(cv_content))
            except Exception as e:
                _logger.error("Failed to decode CV file for applicant %s: %s", self.id, str(e))
                self.ats_score = 0.0
                return
            cv_record = self.env['hr.candidate.cv'].sudo().search(
                [('name', '=', self.id), ('job_id', '=', self.job_id.id)],
                limit=1
            )
            if not cv_record:
                _logger.info("Creating new hr.candidate.cv for applicant %s", self.id)
                cv_record = self.env['hr.candidate.cv'].sudo().create({
                    'name': self.partner_name,
                    'job_id': self.job_id.id,
                    'cv_file': self.cv_file,
                    'cv_filename': self.cv_filename or "cv.pdf",
                    'departement': self.department_id.name if self.department_id else "Non spécifié",
                })
            else:
                _logger.info("Updating existing hr.candidate.cv %s", cv_record.id)
                cv_record.write({
                    'cv_file': self.cv_file,
                    'cv_filename': self.cv_filename or "cv.pdf",
                    'departement': self.department_id.name if self.department_id else "Non spécifié",
                })
            score = cv_record._calculate_ats_score()
            cv_record.write({'ats_score': score})
            self.write({'ats_score': score})
            _logger.info("ATS score set to %s for applicant %s and CV %s", score, self.id, cv_record.id)
        else:
            self.ats_score = 0.0
            _logger.warning("No CV or job for applicant %s (cv_file: %s, job_id: %s)",
                           self.id, bool(self.cv_file), self.job_id.id if self.job_id else "None")

    @api.model
    def create(self, vals):
        _logger.info("Creating hr.applicant with vals: %s", vals)
        applicant = super(HrApplicant, self).create(vals)
        applicant._process_cv_and_score()
        return applicant

    @api.onchange('cv_file', 'job_id')
    def _onchange_cv_file(self):
        _logger.info("Onchange triggered for cv_file or job_id on applicant %s", self.id)
        self._process_cv_and_score()

class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    applicant_id = fields.Many2one('hr.applicant', string='Candidat')

class CandidateCV(models.Model):
    _name = "hr.candidate.cv"
    _description = "CV des candidats"
    applicant_id = fields.Many2one('hr.applicant', string="Candidature")
    name = fields.Char( string="Nom du candidat")
    partner_id = fields.Many2one('res.partner', string="Partenaire (candidat)")
    job_id = fields.Many2one('hr.job', string="Poste visé", required=True, ondelete='cascade')
    cv_file = fields.Binary(string="CV (PDF)")
    cv_filename = fields.Char(string="CV du candidat")
    application_date = fields.Date(string="Date de postulation", default=fields.Date.today)
    departement = fields.Char(string="Département")
    survey_input_ids = fields.One2many(
        'survey.user_input', 'partner_id', string='Résultats du test'
    )
    scoring_percentage = fields.Float(
        string="Score Test (%)",
        related='survey_input_ids.scoring_percentage',
        store=True
    )
    extracted_text = fields.Text(string="Extracted CV Text")
    ats_score = fields.Float(string="Score ATS", store=True)
    resume_summary = fields.Text(string="Résumé du CV", readonly=True)

    def generate_cv_summary(self):
        api_url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        headers = {
            "Authorization": f"Bearer {os.getenv('HF_API_TOKEN')}"
        }
        _logger.error("Clé API Hugging Face okk.")
        for record in self:
            if record.extracted_text:


                try:
                    # Limiter à 1024 caractères pour éviter les erreurs de token
                    cv_text = record.extracted_text[:1024]
                    _logger.info("Texte extrait du CV : %s", cv_text)
                    # Prompt ciblé en français
                    prompt = (
                            "Résumez le CV suivant en quelques lignes. "
                            "Mentionnez les expériences clés, les compétences techniques, et les diplômes principaux. "
                            "Utilisez des phrases courtes et fluides. "
                            "Voici le texte extrait du CV à résumer :\n"
                            + record.extracted_text
                    )

                    data = {
                        "inputs": prompt,
                        "parameters": {
                            "temperature": 0.3,
                            "max_new_tokens": 200
                        }
                    }

                    response = requests.post(api_url, headers=headers, json=data)
                    _logger.info("Réponse API Hugging Face : %s", response.json())

                    if response.status_code == 200:
                        result = response.json()
                        summary = result[0]["generated_text"].split("CV:")[-1].strip()
                        record.resume_summary = summary
                    else:
                        _logger.error("Hugging Face Error: %s - %s", response.status_code, response.text)
                        record.resume_summary = f"[Error {response.status_code}]"

                except Exception as e:
                    _logger.exception("Exception during CV summary generation: %s", str(e))
                    record.resume_summary = "[Processing Error]"
    @api.model
    def create(self, vals):
        _logger.info("Creating hr.candidate.cv with vals: %s", vals)
        record = super(CandidateCV, self).create(vals)
        if record.cv_file:
            record.ats_score = record._calculate_ats_score()
        return record

    @api.onchange('cv_file')
    def _onchange_cv_file(self):
        _logger.info("CV file changed for hr.candidate.cv %s", self.id)
        if self.cv_file:
            self.ats_score = self._calculate_ats_score()
        else:
            self.ats_score = 0.0

    def _extract_text_from_pdf(self, binary_data):
        """Extract text from PDF file."""
        text = ""
        if binary_data:
            try:
                cv_content = base64.b64decode(binary_data)
                _logger.info("PDF binary data size: %s bytes", len(cv_content))
                pdf_file = io.BytesIO(cv_content)
                reader = PyPDF2.PdfReader(pdf_file)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                _logger.info("Extracted text sample: %s", text[:200])
            except Exception as e:
                _logger.error("Failed to extract text from PDF: %s", str(e))
                text = ""
        _logger.info("Extracted text length: %s", len(text))
        # Remplacer les espaces entre lettres (ex: 'b a c c a l a u r é a t')
        text = re.sub(r'\b([a-zA-Z])\s+([a-zA-Z])\b', r'\1\2', text)
        # Enlever les chiffres suivis d'espaces (par exemple, '20xx' ou '00000')
        text = re.sub(r'\d\s+', '', text)
        # Remplacer les mots coupés trop souvent
        text = re.sub(r'\d\s+', '', text)
        text = re.sub(r'\b[\w.-]+@[\w.-]+\.[a-z]{2,}\b', '', text)  # Enlever les emails
        text = re.sub(r'http[s]?://[^\s]+', '', text)  # Enlever les URLs
        text = re.sub(r'\d{10,}', '', text)  # Enlever les numéros de téléphone (longs)
        # Remplacer les mots coupés trop fréquemment (ex: 'pr é no mn om' => 'prénom nom')
        text = re.sub(r'\b([a-zA-Z]+)\s+([a-zA-Z]+)\b', r'\1\2', text)
        # Remplacer les séquences d'espaces multiples par un seul espace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text.lower()

    def _calculate_ats_score(self):
        """Calculate ATS score based on job keywords and CV text, with section-based weighting."""
        _logger.info("Calculating ATS score for CV %s, job %s", self.id, self.job_id.name)

        if not self.job_id or not self.cv_file:
            _logger.warning("Missing job_id or cv_file for CV %s", self.id)
            return 0.0

        keywords = self.job_id._get_keywords()
        text = self._extract_text_from_pdf(self.cv_file)
        self.extracted_text = text

        if not text or not keywords:
            _logger.warning("No text (%s chars) or no keywords (%s) for CV %s", len(text), len(keywords), self.id)
            return 0.0

        # Poids par section du CV (modifiable selon ton besoin)
        section_weights = {
            'experience': 2.0,
            'skills': 1.5,
            'education': 1.0,
            'others': 0.5
        }

        # Découper le texte du CV en sections par mots-clés
        sections = {
            'experience': '',
            'skills': '',
            'education': '',
            'others': ''
        }

        current_section = 'others'
        for line in text.split('\n'):
            line_lower = line.lower()
            if any(word in line_lower for word in ['expérience', 'experience']):
                current_section = 'experience'
            elif any(word in line_lower for word in ['compétence', 'skills']):
                current_section = 'skills'
            elif any(word in line_lower for word in ['formation', 'education', 'diplôme']):
                current_section = 'education'
            elif line.strip() == '':
                continue  # Ignore blank lines
            sections[current_section] += line_lower + ' '

        # Calcul du score avec pondération
        total_score = 0.0
        total_weight = 0.0

        for keyword, weight in keywords:
            for section, section_text in sections.items():
                if keyword in section_text:
                    score = weight * section_weights.get(section, 1.0)
                    _logger.info(f"Keyword '{keyword}' found in section '{section}' -> +{score}")
                    total_score += score
                    total_weight += section_weights.get(section, 1.0)

        # Normalisation (optionnelle)
        final_score = (total_score / total_weight) * 10 if total_weight > 0 else 0.0
        _logger.info("Final ATS score for CV %s: %s", self.id, final_score)
        return round(final_score, 2)

    def _get_section_text(self, text, section_name):
        """Extraire le texte d'une section spécifique du CV."""
        # Cette méthode est un placeholder pour illustrer. Vous devrez l'implémenter pour extraire du texte en fonction de la section.
        # Par exemple, rechercher des titres comme "Expérience" ou "Compétences" dans le texte et extraire le contenu sous ces titres.

        # Pour le moment, retournons le texte complet (à adapter selon votre logique de parsing)
        return text

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

class JobRequirement(models.Model):
    _name = "hr.job.requirement"
    _description = "Les exigences du poste"

    job_id = fields.Many2one('hr.job', string="Poste associé", required=True, ondelete='cascade')
    departement = fields.Char(string="Département", required=True)
    description = fields.Char(string="Description", required=True)
    user_id = fields.Many2one('res.users', 'Responsable RH', default=lambda self: self.env.user)

class InterviewSchedule(models.Model):
    _name = 'hr.interview.schedule'
    _description = 'Schedule of interviews'
    name = fields.Char(string="Titre de l'entretien", required=True)
    job_id = fields.Many2one('hr.job', string="Poste associé", required=True, ondelete='cascade')
    applicant_id = fields.Many2one('hr.applicant', string="Candidat", required=True)
    interview_date = fields.Datetime(string="Date de l'entretien", required=True)
    hr_id = fields.Many2one('hr.employee', string="RH", required=True)
    manager_id = fields.Many2one('hr.employee', string="Manager", required=True)
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('canceled', 'Canceled'),
    ], string="State", default='scheduled')
    manager_feedback = fields.Text(string="Feedback Manager")
    rh_feedback = fields.Text(string="Feedback RH")
    feedback_ids = fields.One2many('interview.feedback.wizard1', 'interview_id', string="Feedbacks Manager")

    def open_feedback_popup1(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Feedback',
            'res_model': 'interview.feedback.wizard1',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_interview_id': self.id,
            }
        }
    def open_feedback_popup2(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Feedback',
            'res_model': 'interview.feedback.wizard2',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_interview_id': self.id,
            }
        }

class InterviewFeedbackWizard1(models.Model):
    _name = 'interview.feedback.wizard1'
    _description = 'Feedback Entretien'
    interview_id = fields.Many2one('hr.interview.schedule', string='Entretien lié')
    manager_id = fields.Many2one('hr.interview.schedule', required=True)
    manager_feedback = fields.Text(string="Feedback Manager")
    priority = fields.Selection([
        ('0', 'Éliminé'),
        ('1', 'Norma'),
        ('2', 'Bon'),
        ('3', 'Très Bien'),
        ('4', 'Excellent')
    ], string='Note', default='0')

    def action_submit_feedback(self):
        if self.manager_feedback or self.rh_feedback:
            self.interview_id.write({
                'manager_feedback': self.manager_feedback,

            })


class InterviewFeedbackWizard2(models.Model):
    _name = 'interview.feedback.wizard2'
    _description = 'Feedback Entretien'
    interview_id = fields.Many2one('hr.interview.schedule', string='Entretien lié')
    rh_id = fields.Many2one('hr.interview.schedule', required=True)
    rh_feedback = fields.Text(string="Feedback RH")
    priority = fields.Selection([
        ('0', 'Éliminé'),
        ('1', 'Norma'),
        ('2', 'Bon'),
        ('3', 'Très Bien'),
        ('4', 'Excellent')
    ], string='Note', default='0')

    def action_submit_feedback(self):
        if self.manager_feedback or self.rh_feedback:
            self.interview_id.write({
                'rh_feedback': self.rh_feedback,

            })

class CalendarEventInherit(models.Model):
    _inherit = 'calendar.event'

    is_entretien = fields.Boolean(string="Entretien")
    is_entretien_text = fields.Char(string="Entretien", compute="_compute_is_entretien_text")
    applicant_id = fields.Many2one('hr.applicant', string="Candidat")

    @api.depends('is_entretien')
    def _compute_is_entretien_text(self):
        for record in self:
            record.is_entretien_text = "Oui" if record.is_entretien else "Non"

class HrInterview(models.Model):
    _name = 'hr.interview'
    _description = 'Entretien Candidat'

    candidate_id = fields.Many2one('hr.candidate.cv', string="Candidat", required=True, ondelete='cascade')
    date = fields.Datetime(string="Date de l'entretien", required=True)
    interviewer = fields.Many2one('res.users', string="Interviewer", default=lambda self: self.env.user)
    result = fields.Selection([
        ('passed', 'Réussi'),
        ('failed', 'Échoué'),
        ('pending', 'En attente')
    ], string="Résultat", default='pending')
    notes = fields.Text(string="Notes")
    feedback =fields.Text(string="Feedback")

class TrainingCourse(models.Model):
    _name = 'training.course'
    _description = 'Formation'

    name = fields.Char(string='Titre de la formation', required=True)
    description = fields.Text(string='Description')
    trainer_id = fields.Many2one('hr.employee', string='Formateur')
    session_ids = fields.One2many('training.session', 'course_id', string='Sessions')


class TrainingSession(models.Model):
    _name = 'training.session'
    _description = 'Session de formation'

    name = fields.Char(string='Nom de la session', required=True)
    course_id = fields.Many2one('training.course', string='Formation', required=True)
    start_date = fields.Datetime(string='Date de début')
    end_date = fields.Datetime(string='Date de fin')
    trainer_id = fields.Many2one('hr.employee', string='Formateur')
    participant_ids = fields.Many2many('hr.employee', string='Participants')
    notes = fields.Text(string='Notes')
    meet_link = fields.Char(string="Lien de la réunion (Google Meet, Zoom...)")
