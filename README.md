# DND Flow

DND Flow is a self-hosted Discord bot with optional online and offline web dashboards for local/home use.

## License

This project is distributed under the `DND Flow Non-Commercial Home Use License`.

### What this means
- ✅ Personal, private, educational, and hobby use are allowed
- ✅ Self-hosting at home is allowed
- ✅ Modifying the project for your own non-commercial use is allowed
- ❌ Selling the project is not allowed
- ❌ Paid hosting or offering it as a revenue-generating service is not allowed without written permission
- ❌ Commercial redistribution is not allowed without written permission

See the full terms in [`LICENSE`](LICENSE).

## Setup

1. Run `setup_install.bat`
2. Fill in your local `.env` values
3. Start the component(s) you want:
   - `Discord_Bot\start_bot.bat`
   - `Online_Web_Server\start.bat`
   - `Offline_Backup_Web_Server\start.bat`

If you want HTTPS / reverse-proxy support for the online dashboard, install Caddy separately from the official releases. The repository does not bundle the large `caddy.exe` binary so GitHub uploads stay within file-size limits.

## Support and contact

If you are the maintainer, host, or someone working on this project and need to reach out:

- GitHub: https://github.com/Zalthorarjir
- Discord: `@zalthorarjir`

Please avoid posting secrets, tokens, private server data, or personal user information in public issues.

## Notes

This repository is intended as a home/self-hosted project distribution. Keep your secrets, tokens, logs, and runtime databases private and out of version control.

Project assembled and maintained by its publisher, with development assistance from GitHub Copilot.
