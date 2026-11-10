# Onboarding and Data Portability

A new account is seeded rather than left empty. On first sign in, Unopsis creates a Personal
space, installs a small set of example notifications that demonstrate the priority score and
the digest, and opens the connector gallery. The example notifications are clearly marked as
samples and are deleted automatically once the user connects their first real service, or after
seven days, whichever comes first. This decision was made after early testers who signed in and
saw an empty inbox assumed the product was broken rather than simply unconfigured.

The recommended onboarding path is to connect one noisy service first rather than several at
once. Connecting a single chat or mail account immediately produces enough volume for the
priority score to become visible and for the user to feel the difference between immediate
delivery and digest delivery. Users who connect six services on their first day frequently
report feeling overwhelmed and then abandon the product, whereas users who connect one service
and adjust their threshold before adding a second are substantially more likely to still be
active after a month.

Every account may export its data at any time, on every plan including Free. Exports are
produced in both CSV and JSON and include notifications, connector configuration, rules, and
space membership. An export is generated asynchronously and a download link is emailed when it
is ready, which usually takes under two minutes but may take longer for accounts with large
histories. Download links expire after twenty four hours. Exports deliberately exclude OAuth
tokens, which cannot be exported in any form, because an exported token would be a credential
leak rather than a portability feature.

Importing is supported only for rules, not for notifications. A rules file previously exported
from Unopsis may be uploaded into another space or another account, which makes it practical to
replicate a carefully tuned configuration across spaces or to hand a working setup to a
teammate. Notification history is intentionally not importable, because an imported history
would carry timestamps and priority scores that were computed under a different configuration
and would therefore misrepresent what the system actually observed. Users who want their old
history available are advised to keep the exported CSV alongside their records rather than
attempting to load it back into the product.
