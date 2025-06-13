from odoo import models, fields, api
from odoo.exceptions import UserError
import os
import logging

_logger = logging.getLogger(__name__)

class DeleteBackupFileWizard(models.TransientModel):
    _name = 'delete.backup.file.wizard'
    _description = 'Confirm Delete Backup File'

    backup_file_ids = fields.Many2many(
        'db.backup.file',
        'delete_backup_file_rel',  # <== define relation table
        'wizard_id',
        'file_id',
        string="Backup Files to Delete"
    )

    def action_confirm_delete(self):
        for file in self.backup_file_ids:
            try:
                if file.file_path and os.path.isfile(file.file_path):
                    os.remove(file.file_path)
                    _logger.info("Deleted file from disk: %s", file.file_path)
            except Exception as e:
                _logger.exception("Error deleting file: %s", e)
                raise UserError(f"Failed to delete file from disk: {e}")
        self.backup_file_ids.unlink()
        return {'type': 'ir.actions.act_window_close'}
