# Lane 1 results (lane1-v1.1)

## Core, config `spec` — blocking metrics FAIL

| metric | pass | fail |
|---|---|---|
| agent_text_contamination | 1 | 0 |
| contradiction_correctness | 1 | 0 |
| cross_org_leakage | 1 | 0 |
| cross_person_leakage | 2 | 0 |
| deletion_resurrection | 9 | 0 |
| hallucinated_memory | 5 | 1 |
| merge_undo_attribution | 4 | 0 |
| provenance_correctness | 1 | 0 |
| recall | 8 | 1 |
| recovery_correctness | 0 | 1 |
| stale_use | 4 | 0 |
| temporal_correctness | 6 | 0 |
| update_correctness | 5 | 0 |

Recall per language (scripted proposals, so this measures gate acceptance, not model extraction): en 1.00, hi 1.00, hinglish 1.00, te 0.67

Failures: residence_te_unverified/recall, inference_paraphrase_same_script/hallucinated_memory, q17_recovery_same_subject/recovery_correctness

## Core, config `f_only` — blocking metrics PASS

| metric | pass | fail |
|---|---|---|
| agent_text_contamination | 1 | 0 |
| contradiction_correctness | 1 | 0 |
| cross_org_leakage | 1 | 0 |
| cross_person_leakage | 2 | 0 |
| deletion_resurrection | 9 | 0 |
| hallucinated_memory | 6 | 0 |
| merge_undo_attribution | 4 | 0 |
| provenance_correctness | 1 | 0 |
| recall | 8 | 1 |
| recovery_correctness | 1 | 0 |
| stale_use | 4 | 0 |
| temporal_correctness | 6 | 0 |
| update_correctness | 5 | 0 |

Recall per language (scripted proposals, so this measures gate acceptance, not model extraction): en 1.00, hi 1.00, hinglish 1.00, te 0.67

Failures: residence_te_unverified/recall

## Core, config `reviewed` — blocking metrics PASS

| metric | pass | fail |
|---|---|---|
| agent_text_contamination | 1 | 0 |
| contradiction_correctness | 1 | 0 |
| cross_org_leakage | 1 | 0 |
| cross_person_leakage | 2 | 0 |
| deletion_resurrection | 9 | 0 |
| hallucinated_memory | 6 | 0 |
| merge_undo_attribution | 4 | 0 |
| provenance_correctness | 1 | 0 |
| recall | 9 | 0 |
| recovery_correctness | 1 | 0 |
| stale_use | 4 | 0 |
| temporal_correctness | 6 | 0 |
| update_correctness | 5 | 0 |

Recall per language (scripted proposals, so this measures gate acceptance, not model extraction): en 1.00, hi 1.00, hinglish 1.00, te 1.00

Failures: none

## Legacy baseline (ported write semantics, scripted outputs)

| failure class | failing cases |
|---|---|
| concurrency | 1/1 |
| contamination | 1/1 |
| deletion | 1/1 |
| hallucination | 2/2 |
| stale | 1/1 |
| temporal | 1/1 |
| truncation | 2/2 |
| wipe | 2/2 |
