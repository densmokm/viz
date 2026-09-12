# NHS CIM text-to-action agent

An MCP server that turns Registration Authority correspondence — joiner emails,
leaver notifications, service desk tickets — into validated Care Identity
Management actions, and performs them against a pluggable backend.

A working prototype: the tool surface, the guardrails, the audit trail and a
local sandbox directory are real and runnable. The system of record is not.

---

## 1. What it is

Registration Authorities receive access requests as prose. Someone emails "Dr
Khan starts Monday in ED, she needs the usual clinical access", and an RA agent
reads it, decides what it means in terms of positions, job roles and activity
codes, and performs a sequence of operations in **Care Identity Management** —
the NHS England application that replaced the legacy Care Identity Service app
in June 2024, and where RAs create users, assign positions, unlock smartcards
and renew certificates.

That translation step — prose to a specific, correct sequence of identity
operations — is what this agent does. The interesting part is not the
translation; a language model does that well. The interesting part is
everything that has to be true before a translation is allowed to change who
can see a patient record.

## 2. Where the boundary sits

**There is no public write API for Care Identity Management.** CIM is a web
application for RA staff. Anything that writes to it in anger goes through one
of three routes:

| Route | Shape |
|---|---|
| RA bulk operation file | The agent produces the file; a human uploads it |
| Supervised browser automation | Drives the CIM UI as a named RA operator |
| A national API | If and when one is published |

All three are the same shape from the agent's side — take a validated action,
perform it, return a receipt — so the agent talks to a `CIMBackend` protocol
with four read methods and one write method, and knows nothing about which is
underneath. `SandboxBackend`, a local JSON directory, is the fourth
implementation and the only one in this repository.

This is the honest version of the boundary. An agent that claimed to integrate
with CIM today would be claiming something that does not exist.

## 3. Division of labour

The design question for any MCP server is which side of the protocol holds
which responsibility. Here:

```
  the host model                        this server
  ──────────────                        ───────────
  reads the email                       holds the acting operator's identity
  asks what codes exist       ─────▶    holds the RBAC catalogue
  asks who this person is     ─────▶    holds the directory
  proposes actions + evidence ─────▶    validates against policy
                              ◀─────    returns a plan + confirmation token
  shows the plan to a human
  applies with the token      ─────▶    performs, and writes the audit record
```

Language understanding sits in the model. Authority, reference data and
validation sit in the server. A model cannot talk its way past `policy.py`,
because the model is not the thing enforcing it.

### Tools

| Tool | Writes? | Purpose |
|---|---|---|
| `cim_context` | no | Acting operator, their ODS scope, backend, catalogue provenance |
| `cim_lookup_codes` | no | Job roles (R codes) and activities (B codes) |
| `cim_find_user` | no | Find a Care ID by UUID, name, email or organisation |
| `cim_plan_actions` | no | Validate the model's proposed actions → plan + token |
| `cim_plan_from_text` | no | Same, via the built-in rule extractor (cross-check) |
| `cim_get_plan` | no | Re-read a plan |
| `cim_apply_plan` | **yes** | Perform a plan; needs the token, and approvals |
| `cim_audit_tail` | no | Read the audit trail |

## 4. The safety model

Ten rules run over every action before it can be applied. Each one exists
because the failure it prevents is one an LLM reading an email would plausibly
commit.

| Rule | Severity | What it stops |
|---|---|---|
| `EVIDENCE_REQUIRED` | block | An action with no span of source text asking for it — the guard against invented access changes |
| `OUT_OF_SCOPE_ODS` | block | Acting outside the organisations the operator's RA covers |
| `SELF_ACTION` | block | An operator changing their own Care ID |
| `UNVERIFIED_IDENTITY` | block | Creating a Care ID with no completed identity check |
| `UNKNOWN_CODE` | block | An R or B code that is not in the catalogue |
| `PRIVILEGED_GRANT` | approve | RA roles and sensitive activities, without a named RA Manager who is not the planner |
| `OUTSIDE_BASELINE` | approve | Activities the national baseline does not carry for that job role |
| `UNRESOLVED_SUBJECT` / `AMBIGUOUS_SUBJECT` / `UNRESOLVED_REFERENCE` / `MISSING_PARAM` | clarify | "The same access as Dr Osei", "starting Friday", a name matching two Care IDs |
| `AMBIGUOUS_POSITION` / `NO_OPEN_POSITION` | clarify | An amendment where it is not clear which of a person's positions is meant |
| `RETROSPECTIVE_REVOCATION` | warn | Applied, but flagged: access stayed live past the stated leaving date |

Three further mechanisms sit outside the rule list:

**The confirmation token.** Planning returns a token derived from the plan's
content — the actions, their resolved targets, their statuses. `cim_apply_plan`
demands it. A plan that changed between being shown to a human and being applied
has a different token, so it is refused rather than silently applied.

**Idempotency.** Each action carries a key derived from the action type, the
subject *as written*, and the parameters. Keys that already applied are skipped.
Forwarding the same leaver email twice performs the revocation once.

**The audit trail.** Append-only JSON Lines, fsynced per record. Every entry
carries the source document hash, the evidence spans, the policy issues raised,
the operator, and the approver. Skipped and blocked actions are recorded too —
a refusal is a fact about the request, and losing it loses the reason nothing
happened.

## 5. Running it

No dependencies for anything but the MCP server module itself.

```bash
cd nhs-cim-agent

# plan every sample request, changing nothing
PYTHONPATH=src python3 -m cim_agent.cli demo

# plan one and apply it
PYTHONPATH=src python3 -m cim_agent.cli plan samples/01-joiner.txt --apply

# a privileged grant needs a named RA Manager
PYTHONPATH=src python3 -m cim_agent.cli plan samples/07-privileged.txt --apply \
    --approve 1=s.adeyemi

PYTHONPATH=src python3 -m cim_agent.cli audit
PYTHONPATH=src python3 -m cim_agent.cli reset      # restore the sandbox

python3 -m unittest discover -s tests -t tests     # 42 tests
```

The MCP server needs `pip install -r requirements.txt` (the `mcp` package):

```bash
PYTHONPATH=src python3 -m cim_agent.server
```

To wire it into an MCP host, point it at the module:

```json
{
  "mcpServers": {
    "nhs-cim": {
      "command": "python3",
      "args": ["-m", "cim_agent.server"],
      "cwd": "/path/to/nhs-cim-agent",
      "env": {
        "PYTHONPATH": "src",
        "CIM_OPERATOR": "j.parker"
      }
    }
  }
}
```

`CIM_OPERATOR` is who the agent acts as, and therefore whose ODS scope binds it.
`CIM_STATE_PATH`, `CIM_AUDIT_PATH` and `CIM_TODAY` are also read.

### What the samples exercise

| Sample | What it demonstrates |
|---|---|
| `01-joiner` | Facts pooled across sentences and line wraps; position waits on the registration |
| `02-leaver` | Leaving date taken from a later sentence; backdated revocation flagged |
| `03-lockout` | Subject carried from a header line to the sentence that asks |
| `04-mover` | End one position, open another, renew certificates — one email |
| `05-vague` | "The same access as Dr Osei" produces **no actions** and a question |
| `06-out-of-scope` | A well-formed request for another trust's RA, blocked |
| `07-privileged` | RA agent grant held for a named RA Manager |
| `08-mixed-batch` | Three people in one email, kept apart |

## 6. What is synthetic

Everything. No real Care IDs, UUIDs, smartcard serials, people or ODS codes —
the organisation codes are deliberately not live ones.

`data/rbac.json` is an **illustrative subset**, not a National RBAC Database
extract. Six codes are ones I could verify against NHS England documentation
(R8000 Clinical Practitioner Access Role; R5080 RA Manager; R5090 RA Agent;
B0267 RA ID checker; B1300 Sponsor; B0825 Amend patient demographics); the rest
carry `"verified": false` and are plausible placeholders. The baseline policy
mappings are illustrative throughout.

That distinction is enforced, not just documented: while `catalogue_source` is
`illustrative-subset`, the `ILLUSTRATIVE_CATALOGUE` rule is a warning against
the sandbox and a **block** against any non-sandbox backend. The prototype
cannot be pointed at a real system while it is reasoning about invented codes.

## 7. Limitations

Worth stating plainly, because each is a real ceiling rather than a rough edge:

- **The rule extractor is a fallback, not the product.** It handles the sample
  phrasings and will miss others. The intended path is the host model calling
  `cim_plan_actions`; the extractor exists so the prototype runs without a model
  and so there is a deterministic baseline to compare against.
- **One action per person per type per request.** A request that genuinely ends
  two different positions for one person collapses into one action. It surfaces
  as a single previewed change for a human to reject, not a silent
  half-application — but it is a ceiling.
- **Plans live in memory.** Restarting the server invalidates outstanding plan
  IDs, and the apply fails closed. Intentional, but it means no long-lived
  approval queue without adding storage.
- **`SandboxBackend` is not a model of CIM's real semantics.** It is enough to
  demonstrate the flow. Real position, certificate and account-closure
  behaviour will differ in ways that matter.
- **The RBAC catalogue is not real.** See above.

## 8. Layout

```
src/cim_agent/
  catalogue.py   RBAC reference data and baseline lookups
  backends.py    CIMBackend protocol + the sandbox directory
  model.py       actions, evidence spans, issues, plans, tokens
  extract.py     free text -> candidate actions (rule-based fallback)
  plan.py        resolution, previews, dependency linking
  policy.py      the guardrails
  apply.py       the only module that writes
  audit.py       append-only JSONL trail
  session.py     the façade the server and CLI share
  server.py      the MCP tool surface (needs `mcp`)
  cli.py         offline runner
data/            rbac.json, directory.json (seed; state lands in data/.state/)
samples/         eight realistic RA requests
tests/           42 tests, stdlib unittest
```

---

**Sources for the NHS domain detail:**
[Care Identity Management](https://digital.nhs.uk/services/care-identity-service/applications-and-services/care-identity-management) ·
[Care Identity Service](https://digital.nhs.uk/services/care-identity-service) ·
[National RBAC for developers](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/national-rbac-for-developers) ·
[RA managers, agents and ID checkers](https://digital.nhs.uk/services/identity-and-access-management/national-care-identity-service/care-identity-service-guidance-leaflets/guidance-for-registration-authority-managers-agents-and-id-checkers) ·
[Smartcards and access controls](https://www.england.nhs.uk/long-read/smartcards-and-access-controls/)
