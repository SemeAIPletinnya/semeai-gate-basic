# Deployment Modes

SemeAI Gate Basic is designed as a release-control adapter, not as a single
mandatory SaaS product. The deployment path should follow the customer's data
boundary.

## 1. Open Source

Use this when the team wants to inspect the contract, run local demos, or build
an integration proof of concept.

- runs locally from this repository;
- no external LLM API is required;
- no customer documents are sent to SemeAI;
- useful for technical validation and pilot preparation.

## 2. Self-Hosted Enterprise

Use this when the company cannot send documents, prompts, answers, or business
data outside its own infrastructure.

The gate can be deployed inside the customer's:

- VPC;
- private cloud;
- internal Kubernetes platform;
- data center;
- regulated network boundary.

In this mode, SemeAI does not need to see the customer's documents. The host
system sends the user message, AI answer, business data, and business rules to a
gate running inside the customer's own perimeter.

## 3. SaaS API

Use this when the team wants a fast pilot and its security policy allows scoped
request data to be sent to a hosted release-control endpoint.

The hosted path is useful for:

- early demos;
- small teams;
- lower-sensitivity workflows;
- fast integration tests;
- design-partner validation.

The SaaS path is not the only model and should not be used for data that the
customer is not allowed to send outside its infrastructure.

## Privacy Objection Answer

If a company says:

> We cannot send internal documents to an external API.

The correct answer is:

> Then do not use the SaaS path. Run SemeAI Gate self-hosted inside your own
> infrastructure. The release-control boundary still works, and SemeAI does not
> see those documents.

This is the normal enterprise pattern for AI infrastructure: smaller teams can
start with a hosted service, while banks, medical teams, governments, and large
companies often require private deployment.

## Invariants

- Generation is not release authority.
- The host LLM answer is a candidate, not a released answer.
- Public actions remain `SHOW`, `REVIEW`, and `BLOCK`.
- Internal canonical decisions remain `PROCEED`, `NEEDS_REVIEW`, and `SILENCE`.
- `BLOCK` maps to `SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
- Deployment mode does not change gate semantics.
