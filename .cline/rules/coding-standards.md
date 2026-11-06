# Project Rules and Standards

- Prefer the smallest implementation that fully satisfies the request.
- Before adding code, check whether existing code already provides the functionality.
- Prefer existing functions, utilities, libraries, and abstractions over creating new ones.
- Do not introduce abstractions unless they provide clear reuse or materially simplify the code.
- Do not refactor unrelated code.
- Do not add speculative features.
- Do not add configuration unless the task requires it.
- Do not add comments that merely restate the code.
- Do not add error handling for hypothetical situations unless the surrounding
  codebase already follows that pattern or the failure is realistically possible.
- Prefer standard-library functionality when it is sufficient.
- Prefer a direct implementation over creating a helper used only once.
- When finishing a set of changes, commit them.
- Write documentation in clear, concise technical English, using ASD-STE100 principles where they
improve clarity: prefer short sentences, active voice, and consistent terms. Do not simplify away
technical meaning. Preserve defined terms, requirement strength, assumptions, conditions, hazards,
security details, and distinctions needed for verification or review. Treat this as a style guide,
not a claim of ASD-STE100 compliance.

## Important

"Minimal" means minimal implementation, not reduced correctness.

Do not remove or weaken:

- validation
- security
- error handling that is required
- accessibility
- tests necessary to establish correctness
- existing behavior

## Context

You are running from inside of a docker container. Any launched docker containers will be in a
docker-out-of-docker context where volumes mounted will reference the host, not your context.