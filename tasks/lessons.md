# Lessons

## 2026-10-03 — Keep the research workflow lightweight
- Define the project instructions, evidence, and one experiment loop before designing execution infrastructure. Existing data, commands, local validation, and competition scores should be reused.
- Do not equate portability with building OS-specific execution backends or adding containers. Add integration code only for a demonstrated gap in the actual project.
- Reusable instructions must contain the critical operational rules themselves: preserve the selected baseline on hold, retain candidate evidence, and verify an interrupted job before repeating it.
- Separate validity corrections from performance experiments. A lower score after fixing leakage is not a reason to restore invalid code.

## 2026-10-02 — Product scope
- The product is a general-purpose AutoResearch tool that imports external ML projects. It is not an experiment system tied to a particular dataset or ML topic.
- The LLM should interpret the imported project and propose task-appropriate losses, optimizers, training settings, and model changes through a graph-based experiment loop.
- Separate product scope from initial validation examples. Do not narrow the product to one ML task merely to simplify the MVP.
- Describe optimization as finding better configurations within a budget; do not promise a global optimum or universal project compatibility.
- The optimization target is the complete executable pipeline: data processing, features, model, loss, optimizer, and training strategy together. Do not reduce the product to parameter recommendations.
- A data-quality retry loop is insufficient. Downstream model evaluation must inform upstream strategy changes through a separate performance-improvement loop.

## 2026-10-02 — Workflow review
- A termination request is not proof that external work has stopped. Define cleanup, unknown-job handling, and the conditions for reporting completion.
- State tables must name successor states for uncertainty and deferral; distinguish initial baseline registration from replacement of an existing best result.
- When separating evaluation from research, define the evidence returned to the agent and the handoff to final testing, not just the separation principle.
