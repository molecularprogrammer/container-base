# Documentation Guidelines

- Write clear, concise technical English. Prefer short, active sentences and
  consistent terms. Preserve technical meaning, defined terms, requirement
  strength, assumptions, conditions, hazards, security details, and distinctions
  needed for review or verification. ASD-STE100 is a style reference, not a
  compliance claim.

## Requirements, design, and implementation

- **Requirements** state what the system must do: observable obligations,
  constraints, and acceptance conditions, without prescribing unapproved design.
- **Design** states how the system intends to meet requirements: boundaries,
  component responsibilities, allocations, interfaces, interactions, decisions,
  and rationale.
- **Implementation** plans how to realize and verify the design. Resolve open
  details into actionable work, prerequisites, outputs, and verification. Do
  not use implementation tasks to conceal unresolved design decisions.
- Link these layers with StrictDoc relations that express real allocation,
  implementation, verification, dependency, or ownership. Avoid UID lists in
  prose. Link to relevant source code when it aids review; keep links current and
  avoid broad or unrelated links.
- Treat source links and generated traceability views as navigation aids, not
  proof of correctness or satisfaction. Verification records identify the
  applicable baseline, method, result, and evidence.

## Design Decomposition

- Components are identifiable system elements: devices, applications, services,
  software subsystems, configuration artifacts, or data stores. Processes,
  workflows, procedures, and interactions are not components.
- The system architecture defines scope, deployment context, top-level components,
  external interfaces, boundaries, and rationale. Deployment locations (plant,
  cloud, datacenter) are context, not components. Top-level component designs
  match the architecture; do not substitute environment, organizational, or
  cross-cutting categories.
- Decompose recursively by component containment. Each component design names its
  direct subcomponents and explains their interactions. Create child documents
  only when separate design or traceability adds value; otherwise leave the
  component as a leaf. Branches need not have equal depth.
- Keep component, interface, and decision records with the system element or
  interaction they belong to. Do not create folders or catalogues by record type.
  Multiple files are acceptable within a component subtree; they do not change
  ownership.
- Each interaction has one authoritative owner: a parent design owns interactions
  among its direct children and with their external components. The architecture
  owns top-level interactions; a component design owns its internal interactions.
  Child designs reference parent-owned interfaces without repeating participants,
  flows, or contracts.
- An interface is a contract between components, defined at their lowest common
  parent and referenced by its endpoints. Record scope, boundaries, relevant
  safety, security, failure, and operational constraints, and rationale for
  consequential decisions at the level that owns them.
- Give every design record a unique, stable UID. Preserve identity and relations
  when documents move or the hierarchy changes.
