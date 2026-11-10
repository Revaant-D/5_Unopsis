# Privacy, Security, and Data Retention

Retention is determined by plan. The Free plan retains notifications for seven days, the Pro
plan for ninety days, and the Team plan for three hundred and sixty five days. When a
notification passes its retention window it is deleted permanently rather than archived, and
deletion is not reversible. Pinned notifications are exempt from retention and are kept until
the user unpins or deletes them. Users may delete any notification at any time, and may delete
their entire account from account settings, which removes all notifications, connectors, and
billing records within thirty days.

Unopsis stores the minimum necessary content from each source. For most connectors this means
the title, the author, the timestamp, a short preview of the body, and a deep link back to the
original item. Unopsis does not store full email bodies, full issue descriptions, or
attachments. Attachment previews are generated at display time by requesting the item from the
source service using the user's own authorisation, and are limited to five megabytes. This
design means that revoking a connector immediately removes Unopsis's ability to read any new
content from that service, even for notifications already in the inbox.

Data is stored in one of two regions, United States or European Union, chosen at account
creation and not changeable afterwards without opening a support request and accepting a
migration window. All data is encrypted in transit using TLS and at rest using AES two fifty
six. OAuth tokens are encrypted with a separate key that is rotated every ninety days.
Unopsis does not sell data, does not share it with advertisers, and does not use customer
notification content to train machine learning models. Aggregate, non identifying usage
statistics such as connector counts are used to prioritise engineering work.

Single sign on through SAML is available on the Team plan and supports Okta, Google Workspace,
and Microsoft Entra. Team administrators may require single sign on for all members, which
disables password login for that organisation. Audit logging is also a Team feature and records
connector changes, rule changes, member additions and removals, and export events, with entries
retained for one year. Two factor authentication using a time based one time password is
available on every plan including Free, and the team recommends it for all accounts.
