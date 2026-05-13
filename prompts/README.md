# Prompt Contracts

Minimal skeleton mode uses three front-half prompts:

- `A2_model_ir.txt`: converts ProblemIR and structured MechLib context into JSON ModelIR. It separates facts, coordinates, local definitions, model instances, target, and forbidden assumptions.
- `controlled_sketch.txt`: converts ModelIR plus evidence bindings into a minimal proof-obligation sketch. It keeps only verified law/constraint equations in `proof_steps`, stores unbound law instances in `blocked_law_steps`, and allows at most one final `algebra_obligation`.
- `B_generate_minimal_skeleton.txt`: converts ModelIR, controlled sketch, evidence bindings, and audit data into JSON theorem skeleton candidates. It preserves hypothesis provenance, verified declarations, gap laws, and proof obligations.

Legacy mode continues to use `B_generate_statements.txt` and `B_revise_statements.txt`.
