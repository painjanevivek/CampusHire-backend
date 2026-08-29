# Pilot Activation Control

The launch operator generates a sanitized health snapshot from the approved monitoring system and
runs this guard before admitting the institution and before each new onboarding window:

```text
python scripts/check_pilot_activation.py /controlled/path/pilot-health.json
```

The input contains metrics only; it must not contain participant, student, administrator, resume,
credential, or raw-log data. Required fields are `authorized_go`, consecutive threshold-window
count, CPU, memory, disk, object allocation, error rate, route-latency budget utilization, backup
age, certificate days remaining, database-pool use, and missed worker lease periods.

`PILOT_ONBOARDING_ALLOWED` permits only the chartered institution. Exit status `2` and
`PILOT_ONBOARDING_PAUSED` stop new onboarding; existing data rights, downloads, deletions, and
support access remain available. The operator records the reason, controlled health reference,
UTC time, owner, remediation, and independent retest in the launch record.

The guard immediately pauses for missing authorization, backup age of 30 hours or more,
certificate expiry within 14 days, database-pool use of 90% or more, or two missed worker lease
periods. It pauses after three consecutive measurement windows at CPU 70%, memory 75%, disk/object
allocation 70%, error rate 1%, or 80% of a route's latency budget.
