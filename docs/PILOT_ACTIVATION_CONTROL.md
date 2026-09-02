# Pilot Activation Control

The approved monitoring export and the release authority are separate inputs. A controlled operator
builds a signed, metrics-only snapshot, then runs the guard before admitting the institution and
before each new onboarding window:

```text
python scripts/build_pilot_health_snapshot.py \
  /controlled/path/health-metrics.json /controlled/path/pilot-health.json \
  --candidate-id <immutable-release-manifest-id> \
  --monitoring-source <approved-monitoring-export-reference> \
  --authorization-reference <human-go-decision-reference> \
  --authorized-go \
  --hmac-key-file /controlled/keys/pilot-snapshot-hmac

python scripts/check_pilot_activation.py /controlled/path/pilot-health.json \
  --hmac-key-file /controlled/keys/pilot-snapshot-hmac
```

The input contains metrics only; it must not contain participant, student, administrator, resume,
credential, or raw-log data. Required fields are `authorized_go`, consecutive threshold-window
count, CPU, memory, disk, object allocation, error rate, route-latency budget utilization, backup
age, certificate days remaining, database-pool use, and missed worker lease periods.

The snapshot also binds the schema version, exact candidate, generation time, monitoring source,
and authorization evidence reference. It is rejected when malformed, non-finite, unrealistic,
more than ten minutes old, more than one minute in the future, or signed with the wrong key. Keep
the HMAC key outside Git, release bundles, workload containers, and the production host when the
guard runs from an independent release-control workstation. The key controls integrity only: an
`authorization_reference` is not proof of human approval unless the named release authority can
verify it in the controlled evidence system.

`PILOT_ONBOARDING_ALLOWED` permits only the chartered institution. Exit status `2` and
`PILOT_ONBOARDING_PAUSED` stop new onboarding; existing data rights, downloads, deletions, and
support access remain available. The operator records the reason, controlled health reference,
UTC time, owner, remediation, and independent retest in the launch record.

The guard immediately pauses for missing authorization, backup age of 30 hours or more,
certificate expiry within 14 days, database-pool use of 90% or more, or two missed worker lease
periods. It pauses after three consecutive measurement windows at CPU 70%, memory 75%, disk/object
allocation 70%, error rate 1%, or 80% of a route's latency budget.
