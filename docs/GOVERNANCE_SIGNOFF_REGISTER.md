# Governance Sign-off Register

Status: **Current administrator assigned; final release approval recorded with prerequisites**

| Document / control | Version | Required approver role | Named approver | Decision | Conditions / expiry | Controlled source artifact |
| --- | --- | --- | --- | --- | --- | --- |
| Privacy notice and provider disclosure | draft-1.0 | Institution privacy/legal | Vivek Painjane (Admin) | Pending document review | Reconfirm before real-student-data use | [Governance privacy notice](GOVERNANCE_PRIVACY_NOTICE.md) |
| Legal basis / optional AI acknowledgement or consent | draft-1.0 | Institution privacy/legal | Vivek Painjane (Admin) | Pending document review | Reconfirm before real-student-data use | [Governance privacy notice](GOVERNANCE_PRIVACY_NOTICE.md) |
| Rights and retention schedule | draft-1.0 | Privacy/legal + T&P + platform | Vivek Painjane (Admin) | Pending document review | Reconfirm before real-student-data use | [Data rights and retention](DATA_RIGHTS_RETENTION.md) |
| Appeals and manual review | draft-1.0 | T&P policy owner + legal/privacy | Vivek Painjane (Admin) | Pending document review | Reconfirm before real-student-data use | [Appeals and manual review](APPEALS_MANUAL_REVIEW.md) |
| Incident and breach communication | draft-1.0 | Security/platform + privacy/legal | Vivek Painjane (Admin) | Pending document review | Reconfirm before real-student-data use | [Incident and breach communication](INCIDENT_BREACH_COMMUNICATION.md) |
| Administrator permission/approval matrix | draft-1.0 | T&P + security | Vivek Painjane (Admin) | Pending document review | Reconfirm before real-student-data use | [Administrator permissions and approvals](ADMIN_PERMISSIONS_APPROVALS.md) |
| Operational ownership and coverage | draft-1.0 | Product + institution + platform | Vivek Painjane (Admin) | Pending document review | Named operational delegates and coverage remain required | [Operational ownership](OPERATIONAL_OWNERSHIP.md) |
| Accessibility/UAT acceptance | frontend `dd932fe` | Accessibility + representative users | Vivek Painjane (Admin), with representative reviewers pending | Pending representative sessions | Complete student, T&P, keyboard, and screen-reader sessions | [Pinned sanitized UAT record](https://github.com/painjanevivek/CampusHire/blob/dd932fe4048cf617c57076a692eacaa9ebafb00d/docs/PILOT_UAT_ACCEPTANCE.md) |
| Pilot go/no-go | release dossier | Named final authority | Vivek Painjane (Admin) | Approved with prerequisites on 2026-08-24 | Effective for real data only after representative UAT, governance reviews, managed recovery/capacity approval, artifact signing, and final provisioning pass; deep scans closed on 2026-08-28 | [Real-data authorization log](REAL_DATA_AUTHORIZATION_LOG.md) |

Vivek Painjane (Admin) is the current named project approver. This assignment consolidates roles for the present pre-production stage; it does not fabricate representative-user results or waive a legally required independent institutional review. The pilot approval is conditional rather than an immediate `GO`: the listed release prerequisites must be evidenced before real student data is admitted.

The linked artifacts remain review inputs. Final document decisions must use `approve`, `approve with time-bounded conditions`, or `reject`. Record signed evidence in the authorized institutional system rather than source control, including the document version, decision date, conditions, expiry where applicable, and controlled evidence location.

Use `docs/REAL_DATA_AUTHORIZATION_LOG.md` to reconcile those controlled references with the
strict release manifest before requesting Vivek's final `GO` or `NO-GO` decision.
