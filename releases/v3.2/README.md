# Complete Melee Zone update

These packages contain all V3.1 support, private feedback, fortnightly analysis and calculator work plus the V3.2 moderator/primary-admin approval changes. They are complete updates, not a patch that requires an unpublished older ZIP.

- [Install/update archive](Melee-Zone-V3.2-update.tar.gz): extract into a separate staging directory; the top folder is `melee-zone-v3.2`.
- [Full repository package](Melee-Zone-V3.2-repository.zip): source, README, requirements, tests, templates, accepted moderator HTML/Word, installer/rollback and admin documentation.
- [SHA-256 checksums](SHA256SUMS.txt).
- [Backup-first Termius upgrade instructions](../../docs/UPGRADE_V3_2_FA.md).
- [Local validation evidence](../../docs/TEST_REPORT.md).

The archives contain 101 files and no production .env, SQLite/WAL, member export, log, backup or virtual environment. The source manifest validates 100 payload files; the manifest itself is the remaining archive entry. Release archives are deliberately outside the payload to avoid recursion.

202 tests passed locally with a private recovered backup, including separate suites and a clean Python 3.12 environment. Public CI intentionally skips that one private-backup-only test. The accepted 14-page Word and searchable HTML moderator handbook are unchanged.

Do not overwrite live files using git pull or extract directly over the running application. The installer preserves the existing .env/database, backs up, tests migration and handles code/service rollback. Repository publication alone does not install the update on a VPS. Actual Discord/VPS acceptance requires the live environment; it was not performed in the offline workspace.
