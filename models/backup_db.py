import os
import platform
import odoo
import logging
import datetime
import base64
import hashlib
import pyzipper

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.service import db
from cryptography.fernet import Fernet

_logger = logging.getLogger(__name__)


class DbBackupFile(models.Model):
    _name = 'db.backup.file'
    _description = 'Database Backup File'

    name = fields.Char("Filename", required=True)
    file_path = fields.Char("Path", readonly=True)
    backup_id = fields.Many2one('db.backup', string="Backup", required=True)
    download_url = fields.Char("Download URL", compute="_compute_download_url")
    is_encrypted = fields.Boolean(compute='_compute_is_encrypted', store=False)

    def _compute_download_url(self):
        for rec in self:
            if rec.backup_id and rec.name:
                rec.download_url = f"/db_backup/download/{rec.backup_id.id}/{rec.name}"

    def download_plain_backup(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/db_backup/download/{self.backup_id.id}/{self.name}",
            'target': 'self',
        }
    
    @api.depends('name')
    def _compute_is_encrypted(self):
        for record in self:
            record.is_encrypted = record.name.endswith('.encrypted')

    def action_smart_download(self):
        self.ensure_one()
        if self.name.endswith('.encrypted'):
            return {
                'type': 'ir.actions.act_window',
                'name': 'Download Encrypted Backup',
                'res_model': 'download.backup.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_backup_file_id': self.id,
                    'default_backup_id': self.backup_id.id,
                },
            }
        else:
            return {
                'type': 'ir.actions.act_url',
                'url': f"/db_backup/download/{self.backup_id.id}/{self.name}",
                'target': 'self',
            }
        
    # DATA BACKUP DELETE FUNCTION
    def unlink(self):
        backup_ids_to_check = self.mapped('backup_id').ids
        result = super().unlink()

        # Delete backup config if it has no more files
        # UNCOMMENT THIS IF YOU WANT AUTO DELETE BACKUP CONFIG IF NO DATA BACKUP FILE STORED IN THAT CONFIG
        # for backup in self.env['db.backup'].browse(backup_ids_to_check):
        #     if not backup.backup_file_ids:
        #         _logger.info("Auto-deleting empty backup config: %s", backup.database)
        #         backup.unlink()

        return result
        
    def action_delete_backup_file(self):
        for record in self:
            try:
                # Delete the physical file from disk
                if record.file_path and os.path.isfile(record.file_path):
                    os.remove(record.file_path)
                    _logger.info("Deleted backup file from disk: %s", record.file_path)
            except Exception as e:
                _logger.exception("Failed to delete file from disk: %s", e)
                raise UserError(f"Could not delete the file from disk: {e}")

            # Delete the record from the database
            record.unlink()

    def open_confirm_delete_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delete.backup.file.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_backup_file_ids': [(6, 0, self.ids)]},
        }
    
    # MULTIPLE FILES DELETE FUNCTION
    def action_batch_confirm_delete(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delete.backup.file.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_backup_file_ids': [(6, 0, self.ids)]},
        }

    # DATA RETENTION SCHEDULE FUNCTION (CRON JOB)
    @api.model
    def cron_auto_delete_old_backups(self, days=7):
        threshold_date = fields.Datetime.now() - datetime.timedelta(days=days)
        old_files = self.search([('create_date', '<', threshold_date)])
        for file in old_files:
            try:
                if file.file_path and os.path.isfile(file.file_path):
                    os.remove(file.file_path)
                    _logger.info("Auto-deleted old file from disk: %s", file.file_path)
            except Exception as e:
                _logger.exception("Failed to delete old file: %s", e)
            file.unlink()


class DbBackup(models.Model):
    _name = 'db.backup'
    _description = 'Database Backup'
    _rec_name = 'database'
    _sql_constraints = [
        ('unique_database_backup', 'unique(database)', 'A backup configuration already exists for this database!')
    ]

    directory = fields.Char(
        string="File Directory",
        default=lambda self: self.get_default_backup_directory(),
        required=True
    )

    backup_format = fields.Selection([
        ('zip', 'Zip'),
        ('encrypted', 'Encrypted'),
        ('dump', 'Plain Dump')
    ], default='dump', required=True)

    is_auto_remove = fields.Boolean(default=False, string="Auto Remove After Backup")

    plain_backup_password = fields.Char(string="Backup Password (Zip/Encrypted)", help="Password for zip or encrypted format", required=True)

    backup_times_per_day = fields.Selection(
        selection=[(str(i), str(i)) for i in range(1, 13)],
        string="Backups Per Day",
        default='5',
        required=True,
        help="Number of backups per day (divided equally over 24h)"
    )

    backup_executions = fields.Integer(default=0, string="Backup Executions", help="Number of backup executions in a day")

    backup_file_ids = fields.One2many(
        'db.backup.file',
        'backup_id',
        string="Backup Files"
    )

    @api.model
    def _get_available_databases(self):
        db_list = odoo.service.db.list_dbs()
        return [(db, db) for db in db_list]
    
    database = fields.Selection(
        selection=_get_available_databases,
        string="Select Database",
        required=True,
        help="Select the database to back up"
    )

    def get_default_backup_directory(self):
        if platform.system() == 'Windows':
            odoo_root = os.path.dirname(os.path.abspath(__file__))
            while odoo_root and not os.path.isdir(os.path.join(odoo_root, 'server')):
                odoo_root = os.path.dirname(odoo_root)
            return os.path.join(odoo_root, 'server', 'Data')
        else:
            return '/home/people_navee/Data'

    def _simple_fernet_key(self, password: str) -> bytes:
        return base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())

    def action_backup(self):
        self._run_backup()

    def action_open_password_prompt(self):
        # Replace this with actual logic or JS prompt later
        raise UserError("Password prompt not implemented yet.")

    def _run_backup(self):
        for rec in self:
            try:
                db_subdir = os.path.join(rec.directory, rec.database)
                os.makedirs(db_subdir, exist_ok=True)

                now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                base_filename = f"{rec.database}_{now}"
                raw_path = os.path.join(db_subdir, f"{base_filename}.dump")

                if rec.backup_format == 'dump':
                    # Plain dump
                    with open(raw_path, "wb") as f:
                        db.dump_db(rec.database, f, 'dump')
                    file_path = raw_path

                elif rec.backup_format == 'encrypted':
                    # Dump first
                    with open(raw_path, "wb") as f:
                        db.dump_db(rec.database, f, 'dump')

                    # Encrypt
                    password = rec.plain_backup_password
                    if not password:
                        raise UserError("Encryption password is required for encrypted backup")

                    key = self._simple_fernet_key(password)
                    fernet = Fernet(key)

                    with open(raw_path, "rb") as f:
                        data = f.read()
                        encrypted_data = fernet.encrypt(data)

                    encrypted_path = os.path.join(db_subdir, f"{base_filename}.encrypted")
                    with open(encrypted_path, "wb") as f:
                        f.write(encrypted_data)

                    os.remove(raw_path)
                    file_path = encrypted_path

                elif rec.backup_format == 'zip':
                    # Create temp zip from db.dump_db(format='zip')
                    temp_zip_path = os.path.join(db_subdir, f"{base_filename}_raw.zip")
                    with open(temp_zip_path, "wb") as temp_zip:
                        db.dump_db(rec.database, temp_zip, 'zip')

                    # Wrap in password-protected zip
                    final_zip_path = os.path.join(db_subdir, f"{base_filename}.zip")
                    if rec.plain_backup_password:
                        with pyzipper.AESZipFile(final_zip_path, 'w', compression=pyzipper.ZIP_DEFLATED,
                                                 encryption=pyzipper.WZ_AES) as zf:
                            zf.setpassword(rec.plain_backup_password.encode())
                            zf.write(temp_zip_path, arcname=os.path.basename(temp_zip_path))
                        os.remove(temp_zip_path)
                        file_path = final_zip_path
                    else:
                        os.rename(temp_zip_path, final_zip_path)
                        file_path = final_zip_path

                else:
                    raise UserError("Invalid backup format selected.")

                _logger.info("Backup created: %s", file_path)

                self.env['db.backup.file'].create({
                    'name': os.path.basename(file_path),
                    'file_path': file_path,
                    'backup_id': rec.id,
                })
                # Increment the backup execution count
                rec.backup_executions += 1

                if rec.is_auto_remove:
                    os.remove(file_path)
                    _logger.info("Auto-removed backup file: %s", file_path)

            except Exception as e:
                _logger.exception("Error during backup for database %s: %s", rec.database, e)
                raise UserError(f"Backup failed: {e}")

    def remove_backup_database(self):
        for rec in self:
            if rec.is_auto_remove:
                try:
                    db_subdir = os.path.join(rec.directory, rec.database)
                    if os.path.isdir(db_subdir):
                        files = [f for f in os.listdir(db_subdir) if f.startswith(rec.database)]
                        for f in files:
                            os.remove(os.path.join(db_subdir, f))
                            _logger.info("Removed backup file: %s", f)
                except Exception as e:
                    _logger.exception("Failed to remove backup for %s: %s", rec.database, e)
                    raise UserError(f"Error removing backup: {e}")

    @api.model
    def schedule_backups(self):
        now = fields.Datetime.now()
        current_hour = now.hour
        today = fields.Date.today()

        for rec in self.search([]):
            if not rec.backup_times_per_day:
                continue

            # Reset executions if write_date is not today
            if rec.write_date and rec.write_date.date() != today:
                _logger.info("Resetting backup executions for record ID %s due to new day.", rec.id)
                rec.backup_executions = 0  # You must have this field defined on the model

            backup_executions = rec.backup_executions or 0
            backup_times_per_day = int(rec.backup_times_per_day) or 0

            if backup_times_per_day == 0:
                continue

            interval = 24 / backup_times_per_day

            allowed_hours = sorted(set([round(i * interval) for i in range(backup_times_per_day)]))

            _logger.info("Record ID: %s | Current Hour: %s | Allowed Hours: %s | Slots: %s | Interval: %.2f",
                        rec.id, current_hour, allowed_hours, backup_times_per_day, interval)

            if current_hour in allowed_hours:
                if backup_executions >= backup_times_per_day:
                    _logger.info("Backup execution limit reached for record ID %s.", rec.id)
                    continue
                else:
                    _logger.info("Backup per Day: %s | Backups Execution: %s", backup_times_per_day, backup_executions)
                    rec._run_backup()

    @api.depends('database', 'directory')
    def _compute_backup_files(self):
        for rec in self:
            file_list = []
            try:
                backup_dir = os.path.join(rec.directory, rec.database)
                if os.path.isdir(backup_dir):
                    for filename in os.listdir(backup_dir):
                        file_path = os.path.join(backup_dir, filename)
                        if os.path.isfile(file_path):
                            file_list.append((0, 0, {
                                'name': filename,
                                'file_path': file_path,
                                'backup_id': rec.id,
                            }))
            except Exception as e:
                _logger.exception("Error computing backup files for record ID %s: %s", rec.id, e)

            rec.backup_file_ids = file_list

    @api.model
    def create(self, vals):
        if 'database' in vals:
            existing = self.search([('database', '=', vals['database'])])
            if existing:
                raise ValidationError("A backup configuration already exists for this database.")
        return super().create(vals)

    def write(self, vals):
        if 'database' in vals:
            for rec in self:
                existing = self.search([
                    ('database', '=', vals['database']),
                    ('id', '!=', rec.id)
                ])
                if existing:
                    raise ValidationError("A backup configuration already exists for this database.")
        return super().write(vals)
