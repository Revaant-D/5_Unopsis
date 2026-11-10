# Filtering and the Priority Score

Every notification entering Unopsis is assigned a priority score between zero and one hundred.
The score is computed from four inputs: how directly the event addresses the user, how quickly
the user has historically responded to similar events, the source connector's configured
weight, and whether the event matches any of the user's keyword rules. A direct mention scores
higher than a channel broadcast, and a connector the user opens frequently scores higher than
one they routinely ignore. The score is recomputed when a rule changes but is never recomputed
retroactively for notifications already delivered.

The default priority threshold is forty. Notifications scoring at or above forty are delivered
immediately through the user's chosen channels, and notifications scoring below forty are held
for the next digest instead. Users may move the threshold anywhere between zero and one
hundred. Setting it to zero delivers everything immediately, which some users prefer during an
on call rotation, and setting it to one hundred effectively routes everything to digests. The
threshold is per space, not per account, so a user may run an aggressive threshold on a noisy
project and a permissive one on a quiet project.

Keyword rules let a user override the score directly. A rule consists of a pattern, a scope,
and an action. Patterns may be plain substrings or regular expressions. Scope limits the rule
to a connector, a space, or the whole account. Actions are boost, suppress, or pin. Boost adds
thirty points to the score, suppress subtracts forty, and pin forces immediate delivery
regardless of score and marks the notification so it survives the retention window. Rules are
evaluated in order of specificity, with connector scoped rules beating space scoped rules and
space scoped rules beating account scoped rules.

Quiet hours suppress delivery without suppressing collection. By default quiet hours run from
ten at night until seven in the morning in the user's time zone. During quiet hours Unopsis
continues to collect and score notifications but holds all delivery until quiet hours end, at
which point anything above the threshold is delivered as a single batch. Pinned notifications
are the only exception and are delivered during quiet hours. Digest windows are separate from
quiet hours and may be set to hourly, daily at eight in the morning, or weekly on Monday
morning.
