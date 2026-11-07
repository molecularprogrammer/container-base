# Project Manifesto & Engineering Tenets

This project avoids vendor lock-in and champions open, reproducible, and verifiable engineering.
It is governed by a dual-licensing model, strict engineering paradigms, and an explicit
commitment to pro-human innovation across molecular programming and advanced manufacturing.

---

## 1. Dual-Licensing Framework

We believe that open science requires open tooling for both bits and atoms:
* **Software & Documentation:** Licensed under the
  [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). You are free to use,
  modify, and distribute software and documentation with clear protections for patent and
  intellectual property contributions.
* **Hardware Design Materials:** Licensed under the
  [CERN Open Hardware Licence v2 - Permissive (CERN-OHL-P)](https://ohwr.org/cern_ohl_p_v2.txt).
  Schematics, PCB layouts, microfluidic designs, and physical hardware artifacts are open for
  modification, fabrication, and commercial application without restrictive copyleft
  requirements.

---

## 2. Core Engineering Movements

Our workflow is built on three overlapping, mutually reinforcing paradigms:

* **[Docs-like-Code](https://writethedocs.org) (Documentation as Code):** Requirements, system
  architecture, and operational guides live as human-readable plain text directly inside the
  repository. Every engineering decision undergoes standard Git Pull Requests, peer review, and
  continuous testing.
* **[Local-First Development](https://inkandswitch.com):** Project tooling can run entirely on
  local hardware or any hosted infrastructure. Contributors can move between tools and
  environments with minimal disruption, avoiding proprietary lock-in.
* **[Requirements as Code](https://github.io) / GitOps:** Git serves as the single source of
  truth. Every Git commit hash cryptographically binds natural language requirements,
  architecture specifications, implementation logic, simulation models, and verification tests
  to generate audit-ready, bi-directional traceability matrices.

---

## 3. Molecular Programming Context & Scope

Molecular programming—the engineering of molecules to form prescribed structures, carry out
chemical computations, and orchestrate complex nanoscale behaviors—is fundamentally a
**universal manufacturing and information technology**.

Beyond public health and therapeutics, this project acknowledges its impact across diverse
domains of human industry, including:
* **Computing & Data Storage:** High-density molecular data archives and nanoscale logical
  reaction networks.
* **Materials & Construction:** Programmed self-assembly of smart materials, hierarchical
  lattices, and responsive structures.
* **Energy & Environment:** Molecular catalysts for green energy conversion, carbon
  sequestration, and targeted environmental remediation.
* **Nutrition & Agriculture:** Precision molecular tools for sustainable food systems and
  cellular growth support.

---

## 4. Hardware & Software Security

Because molecular programming bridges digital code and physical execution, robust security is
mandatory across the entire stack:
* **Supply Chain Integrity:** All software dependencies, container images, and firmware binaries
  are pinned, cryptographically verified, and built via automated, auditable CI/CD pipelines.
* **Air-Gapped & Isolated Lab Control:** Physical instrument controllers, synthesis hardware, and
  liquid handlers are designed to operate securely within isolated local networks, eliminating
  unauthorized remote exposure.
* **Verifiable Toolchains:** Compilation, sequence design, and simulation outputs are
  deterministic, reproducible, and subject to rigorous automated test suites to prevent silent
  runtime failures in physical experiments.

---

## 5. Pro-Human Intent & Safety Practices

Technology must serve human flourishing, dignity, and safety. We design our systems with an
unwavering pro-human orientation:
* **Transparent Safety Practices:** We embrace rigorous screening, verification, and open-source
  threat modeling. Safety mechanisms are engineered directly into the software and design files
  rather than treated as an afterthought.
* **Biosafety & Biosecurity:** Biological samples and molecular-programming systems can pose risks
  to people, animals, and the environment, depending on their properties and use. Projects assess
  those risks across the lifecycle—including handling, containment, access, transport, use, and
  disposal—and apply appropriate safeguards, oversight, and incident response. This manifesto is a
  commitment to assess risk, not a claim that any particular system is safe or hazardous.
* **Open Science & Anti-Monopoly:** By keeping designs transparent and unencumbered by restrictive
  commercial silos, we ensure that the benefits of molecular manufacturing remain accessible to
  researchers, communities, and independent builders globally.
* **Human-in-the-Loop Governance:** Automated code generation, AI-assisted design tools, and
  robotic execution pipelines remain strictly under human oversight, review, and accountability.