# Evidence vintages

Version 0.26 introduces immutable `EvidenceVintage` records. A vintage binds a
content-addressed raw artifact to source identity, canonical URI, source
publication time, local retrieval and first-observation clocks, archive time,
server Date metadata, original source timezone, validity interval, revision
lineage, archive proof, confidence, retention class, and provenance.

The six classifications are:

| Classification | Historical research eligibility |
|---|---|
| `observed_live_at_time` | Eligible from its genuine local observation time |
| `official_archived_vintage` | Eligible only with explicit official release/version proof |
| `third_party_archived_snapshot` | Eligible only with trusted timestamped snapshot proof |
| `retrospectively_available_current_copy` | Never sufficient by itself |
| `temporally_ambiguous` | Not eligible |
| `unusable_for_causal_replay` | Not eligible |

A page displaying an old publication date today is not proof that its current
content was visible then. Official archive classification requires both a
source release timestamp and source-specific proof such as an SEC accession or
official publication version. Third-party material must be operator-supplied
from an authorized/trusted archive with a defensible snapshot timestamp. The
system does not scrape unauthorized archives.

Raw payloads and response metadata are preserved before downstream parsing.
Changed content creates a new vintage linked by `revision_of`; initial,
corrected, amended, and superseded versions remain queryable. Duplicate bytes
at the same proof/timestamp are idempotent. Missing scheduled observations are
explicit gap records and never interpreted as “nothing was published.”

An archive proof can make a new version of a previously unusable replay case
eligible. It never mutates the old case, commitments, or results. The upgrade
decision lists every supporting vintage and missing URI and requires the next
case version.
