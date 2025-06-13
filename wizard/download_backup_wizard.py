from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.http import request
import os
import base64
import hashlib
from cryptography.fernet import Fernet

class DownloadBackupWizard(models.TransientModel):
    _name = 'download.backup.wizard'
    _description = 'Download Backup File Wizard'

    backup_file_id = fields.Many2one('db.backup.file', required=True)
    password = fields.Char(string='Password', required=True)

    def _simple_fernet_key(self, password: str) -> bytes:
        return base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())

    def action_download(self):
        self.ensure_one()
        backup_file = self.backup_file_id
        password = self.password
        file_path = backup_file.file_path

        if not os.path.isfile(file_path):
            raise UserError("Backup file not found.")

        if file_path.endswith('.dump'):
            # No password needed for plain dump
            return {
                'type': 'ir.actions.act_url',
                'url': f'/db_backup/download_direct/{backup_file.id}',
                'target': 'self',
            }

        if file_path.endswith('.encrypted'):
            # Validate Fernet decryption
            try:
                key = self._simple_fernet_key(password)
                fernet = Fernet(key)
                with open(file_path, "rb") as f:
                    fernet.decrypt(f.read())  # Check if decryption is successful
                # If decryption is successful, return the download action
                return {
                    'type': 'ir.actions.act_url',
                    'url': f'/db_backup/download_direct/{backup_file.id}?password={password}',
                    'target': 'self',
                }
            except Exception:
                raise UserError("Incorrect password or corrupted encrypted file.")

        elif file_path.endswith('.zip'):
            # Validate zip password
            try:
                import pyzipper
                with pyzipper.AESZipFile(file_path, 'r') as zf:
                    zf.setpassword(password.encode())
                    zf.testzip()  # test all files
                
                # No password needed for Zip file download
                return {
                    'type': 'ir.actions.act_url',
                    'url': f'/db_backup/download_direct/{backup_file.id}',
                    'target': 'self',
                }
            except Exception:
                raise UserError("Incorrect ZIP password or invalid file.")
