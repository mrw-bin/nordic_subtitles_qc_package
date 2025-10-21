# Copilot Topics (Outline)

## Start QC
- Triggers: "run qc", "qc this", "check subtitles", file upload
- Steps:
  1. If no profile in session, prompt: Netflix-SV | SVT-SE | NRK-NO | DR-DK | Yle-FI (fi/sv)
  2. Store file to SharePoint (configured in action or Power Automate) and obtain fileUrl
  3. Call action: `RunQC(fileUrl, profile, targetCPS?)`
  4. Render Adaptive Card with summary
  5. Offer: Fix issues → go to Fix Issues topic

## Fix Issues
- Collect: autoFixMode (none | safe-only | llm-rewrite-with-approval)
- Optional: selected rule IDs
- Call action: `Fix(fileUrl, profile, autoFixMode, selectedRules)`
- Return links: fixed file, diff, residual issues

## Change Profile
- Update session profile & defaults

## Download
- Return SharePoint links for the last run (original, normalized, report, fixed, diff)
