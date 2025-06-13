# THIS IS A CUSTOMIZED AUTO DATABASE MANAGEMENT MODULE FOR ODOO 17 | BY RND ROBERT ANDREW BARDOQUILLO

{
    'name': 'Database Management',
    'version': '1.7.3',
    'summary': 'PN Lotus Database Management (CRON Integrated)',
    'category': 'Tools',
    'author': "TBSI | RND Andrew B.",
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/db_backup_actions.xml',
        'views/actions.xml',
        'views/db_backup_view.xml',
        'views/res_config_settings.xml',
        'views/backup_decryptor_templates.xml',
        'views/download_backup_wizard_view.xml',
    ],
    'installable': True,
    'application': True,
}
