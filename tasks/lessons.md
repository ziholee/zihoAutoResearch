# Lessons

## 2026-10-02 — Product scope
- The product is a general-purpose AutoResearch tool that imports external ML projects. It is not an experiment system tied to a particular dataset or ML topic.
- The LLM should interpret the imported project and propose task-appropriate losses, optimizers, training settings, and model changes through a graph-based experiment loop.
- Separate product scope from initial validation examples. Do not narrow the product to one ML task merely to simplify the MVP.
- Describe optimization as finding better configurations within a budget; do not promise a global optimum or universal project compatibility.
- The optimization target is the complete executable pipeline: data processing, features, model, loss, optimizer, and training strategy together. Do not reduce the product to parameter recommendations.
- A data-quality retry loop is insufficient. Downstream model evaluation must inform upstream strategy changes through a separate performance-improvement loop.
