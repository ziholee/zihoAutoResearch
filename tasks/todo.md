# AutoResearch tool design

## Objective
Build a tool that imports external ML projects, uses an LLM to understand their objectives and execution paths, and iteratively improves models and training configurations through a graph-based experiment loop.

## Plan
- [x] Inspect repository and existing notes before documentation.
- [x] Document the agreed product definition and conceptual research loop.
- [x] Verify documentation consistency and prepare the documentation for delivery.
- [x] Clarify that the product imports projects across ML domains.
- [ ] Agree on the graph workflow and the boundary between LLM decisions and deterministic execution.
- [ ] Define the project adapter contract, task specification, and supported initial execution environments.
- [ ] Define evaluation integrity, experiment budgets, reproducibility, and acceptance criteria.
- [ ] Specify experiment state, artifact storage, checkpointing, and recovery.
- [ ] Agree on an implementation plan before building the tool.

## Review
- Repository inspection found only README.md before these planning notes.
- Product scope corrected based on user clarification; implementation has not started.
- README.md describes the product goal and current status; docs/product-direction.md preserves the conceptual graph, roles, evaluation principles, experiment memory, and open decisions.
- This documentation does not select an implementation stack or claim a working research loop.
- Documentation review checked the agreed product scope, conceptual graph, and explicit separation of open implementation decisions. Git staged whitespace validation passed; no executable code was changed.
- Delivery: commit these documents to main, push to origin, and verify the remote commit. The final delivery result is reported in the chat after the push.
