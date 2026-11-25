# srs-crm-installer

Pemasang awam untuk SRS Advert CRM di Opalstack. Tiada rahsia dalam repo ini.

- `install.py` — dijalankan oleh Opalstack (`installer_url`) semasa app dicipta: composer, deploy key SSH, kata laluan DB rawak, `.env`, cron deploy + scheduler, notis kod claim admin.
- `deploy.sh` — cron setiap 2 minit: tarik `main` dari repo peribadi, `composer install`, `migrate`, cache.
