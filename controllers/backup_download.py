import os
import base64
import hashlib
from cryptography.fernet import Fernet
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessDenied
from werkzeug.utils import secure_filename
import tempfile


def simple_fernet_key(password: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())


class BackupDownloadController(http.Controller):

    @http.route('/db_backup/download/<int:backup_id>/<string:filename>', type='http', auth='user')
    def download_backup_file(self, backup_id, filename, **kwargs):
        password = kwargs.get('password')
        backup = request.env['db.backup'].sudo().browse(backup_id)
        if not backup.exists():
            return request.not_found()

        file_path = os.path.join(backup.directory, backup.database, filename)

        if not os.path.isfile(file_path):
            return request.not_found()

        if not any(f.name == filename for f in backup.backup_file_ids):
            raise AccessDenied("You're not allowed to access this file.")

        file_ext = os.path.splitext(filename)[1]

        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()

            if file_ext == '.encrypted':
                if not password:
                    raise AccessDenied("Password is required to decrypt the file.")

                key = simple_fernet_key(password)
                fernet = Fernet(key)
                file_data = fernet.decrypt(file_data)
                download_name = filename.replace('.encrypted', '.dump')

            elif file_ext == '.zip':
                download_name = filename

            else:
                download_name = filename

            return request.make_response(
                file_data,
                headers=[
                    ('Content-Type', 'application/octet-stream'),
                    ('Content-Disposition', f'attachment; filename="{download_name}"'),
                ]
            )

        except Exception as e:
            return request.make_response(
                f"Decryption Failed: {str(e)}",
                headers=[('Content-Type', 'text/plain')],
                status=500
            )

    @http.route('/db_backup/download_direct/<int:file_id>', type='http', auth='user')
    def download_backup_direct(self, file_id, password=None, **kwargs):
        record = request.env['db.backup.file'].sudo().browse(file_id)
        if not record.exists() or not os.path.isfile(record.file_path):
            return request.not_found()

        file_path = record.file_path
        filename = os.path.basename(file_path)

        if file_path.endswith('.encrypted'):
            key = simple_fernet_key(password)
            fernet = Fernet(key)
            with open(file_path, "rb") as f:
                file_data = fernet.decrypt(f.read()) # Decrypt the file
            decrypted_file = filename.replace('.encrypted', '.dump')

            return request.make_response(
                    file_data,
                    headers=[
                        ('Content-Type', 'application/octet-stream'),
                        ('Content-Disposition', f'attachment; filename="{decrypted_file}"'),
                    ]
                )
        else:
            return request.make_response(
                open(file_path, 'rb').read(),
                headers=[
                    ('Content-Type', 'application/octet-stream'),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                ]
            )


class BackupDecryptorController(http.Controller):

    @http.route('/db_backup/decryptor', type='http', auth='public', website=True, csrf=False)
    def decryptor_page(self, **kwargs):
        return request.render('db_backup.decryptor_template', {})

    @http.route('/db_backup/decryptor/submit', type='http', auth='public', methods=['POST'], website=True, csrf=False)
    def decryptor_submit(self, **post):
        uploaded_file = post.get('file')
        password = post.get('password')

        if not uploaded_file or not password:
            return request.render('db_backup.decryptor_template', {
                'error': 'Missing file or password.'
            })

        try:
            temp_dir = tempfile.mkdtemp()
            filename = secure_filename(uploaded_file.filename)
            temp_path = os.path.join(temp_dir, filename)

            with open(temp_path, 'wb') as f:
                f.write(uploaded_file.read())

            key = simple_fernet_key(password)
            fernet = Fernet(key)

            with open(temp_path, 'rb') as f:
                encrypted_data = f.read()

            decrypted_data = fernet.decrypt(encrypted_data)

            decrypted_filename = filename.replace('.encrypted', '.dump')

            return request.make_response(
                decrypted_data,
                headers=[
                    ('Content-Type', 'application/octet-stream'),
                    ('Content-Disposition', f'attachment; filename="{decrypted_filename}"'),
                ]
            )

        except Exception as e:
            return request.render('db_backup.decryptor_template', {
                'error': f'Decryption failed: {str(e)}'
            })
