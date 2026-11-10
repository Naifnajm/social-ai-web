# Licensed fonts (not in git)

The marketing page (`/[locale]/welcome`) uses **Forma DJR Arabic Text** for Arabic when these files are present:

| File | Used for |
| --- | --- |
| `FormaDJRArabicText-Bold.woff2` | headlines, buttons, labels (weight 600 and up) |
| `FormaDJRArabicText-Light.woff2` | paragraphs and body text (weight 500 and below) |

If a file is missing, the page falls back to Alexandria (headlines) and the system Arabic font (text).

The fonts are licensed by DJR (https://djr.com/license). A *testing* copy may only be used for internal
evaluation: do not commit it, share it or put it on a public site. Before going live, buy the web
licence for the expected monthly visitors and place the WOFF2 files here on the server before
`deploy.sh` builds the image.
