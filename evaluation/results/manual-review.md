# Evidence support review

Development-assistant review of actual local Ollama responses on October 19, 2026.
This is a sample review, not an independent human accuracy assessment.
The answer evaluation is still running; consult results.json for completed rows.

| Question | Observed result | Assessment |
| --- | --- | --- |
| q01 | Answer contains only “Aurora Hotel — family stay”. | Does not answer the requested facts. A matching quotation and model support review did not establish relevance or completeness. |
| q02 | Abstention although the source states minimum age 12. | False abstention. |
| q03 | Abstention although the source states 90 minutes. | False abstention. |
| q05 | River Lights Cruise cancellation is free until 12 hours before departure. | Matches the labelled source fact. |
| q11 | Harbor Walk departs from Pier 2. | Matches the labelled source fact. |
| q12 | Castle Adventure runs Saturday at 09:00. | Matches the labelled source fact. |

The current qwen3:1.7b configuration is not accepted for answer quality.
Passing API tests verifies validation and error paths, not factual model accuracy.
Generation and support-review quality need improvement before the answer feature
can be described as finished. Retrieval measurements cover all 30 questions in
each of six configurations; answer measurements must be read separately.
